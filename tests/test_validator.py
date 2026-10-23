"""Phase 2: schemas and the anti-fabrication validator."""

import copy
import json
import sqlite3

import pytest

from bible_rag import cli
from bible_rag.config import SQLITE
from bible_rag.store import VerseStore
from bible_rag.validator import XREF_MIN_VOTES, validate

GREEK = "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος."
WEB = "In the beginning was the Word, and the Word was with God, and the Word was God."


@pytest.fixture(scope="module")
def store(db):  # `db` skips the module when verses.db is missing
    return VerseStore()


@pytest.fixture()
def answer():
    return {
        "question": "What was in the beginning?",
        "answer": "John 1:1 says the Word was in the beginning.",
        "passages": [{
            "canon_ref": "JHN.1.1",
            "display_ref": "John 1:1",
            "testament": "NT",
            "alignment": "mapped",
            "texts": [
                {"kind": "original", "source": "sblgnt", "language": "grc", "text": GREEK,
                 "verse_uid": "sblgnt:JHN.1.1"},
                {"kind": "machine_translation", "source": "sblgnt", "language": "en",
                 "text": "In the beginning was the Word...", "translates": "sblgnt:JHN.1.1",
                 "translator": "claude:test"},
                {"kind": "established_translation", "source": "web", "language": "en", "text": WEB,
                 "verse_uid": "web:JHN.1.1"},
            ],
            "cross_refs": [{"to": "GEN.1.1", "relation": "thematic"}],
        }],
        "confidence": {"level": "high", "basis": "vector and lexical agree"},
    }


def codes(result):
    return [e["code"] for e in result["errors"]]


def texts(answer):
    return answer["passages"][0]["texts"]


def test_valid_answer_passes(store, answer):
    result = validate(answer, store)
    assert result == {"valid": True, "errors": [], "warnings": []}


def test_whitespace_differences_are_tolerated(store, answer):
    texts(answer)[2]["text"] = "  " + WEB.replace(" ", "  ") + "\n"
    assert validate(answer, store)["valid"]


def test_fabricated_text_is_caught(store, answer):
    texts(answer)[2]["text"] = WEB.replace("Word was God", "Word was a god")
    assert codes(validate(answer, store)) == ["text_mismatch"]


def test_excerpt_must_be_part_of_the_verse(store, answer):
    texts(answer)[2].update(text="the Word was with God", excerpt=True)
    assert validate(answer, store)["valid"]
    texts(answer)[2]["text"] = "the Word was with Moses"
    assert codes(validate(answer, store)) == ["text_mismatch"]


def test_invented_verse_and_reference_are_caught(store, answer):
    bad = copy.deepcopy(answer)
    texts(bad)[2]["verse_uid"] = "web:JHN.1.99"
    assert "unknown_verse" in codes(validate(bad, store))
    answer["passages"][0].update(canon_ref="JHN.99.1", display_ref="John 99:1")
    assert "unknown_reference" in codes(validate(answer, store))


def test_wrong_source_label_is_caught(store, answer):
    texts(answer)[2]["source"] = "sblgnt"  # WEB text passed off as SBLGNT
    assert "wrong_source" in codes(validate(answer, store))


def test_unlabelled_machine_translation_is_rejected(store, answer):
    del texts(answer)[1]["translator"]
    result = validate(answer, store)
    assert not result["valid"] and codes(result) == ["schema"]


def test_machine_translation_cannot_pose_as_stored_text(store, answer):
    texts(answer)[1]["verse_uid"] = "sblgnt:JHN.1.1"
    assert codes(validate(answer, store)) == ["schema"]


def test_quoted_text_must_cite_a_verse(store, answer):
    del texts(answer)[2]["verse_uid"]
    assert codes(validate(answer, store)) == ["schema"]


def test_orphan_translation_is_caught(store, answer):
    texts(answer)[1]["translates"] = "sblgnt:JHN.3.16"  # not quoted in this passage
    assert codes(validate(answer, store)) == ["orphan_translation"]


def test_misaligned_verse(store, answer):
    texts(answer)[2].update(verse_uid="web:JHN.1.2",
                            text="The same was in the beginning with God.")
    assert codes(validate(answer, store)) == ["misaligned"]
    answer["passages"][0]["alignment"] = "partial"
    result = validate(answer, store)
    assert result["valid"] and [w["code"] for w in result["warnings"]] == ["unaligned"]


def test_display_ref_mismatch_warns(store, answer):
    answer["passages"][0]["display_ref"] = "John 3:16"
    result = validate(answer, store)
    assert result["valid"] and result["warnings"][0]["code"] == "display_ref"


def test_unknown_fields_are_rejected(store, answer):
    answer["passages"][0]["vibes"] = "good"
    assert codes(validate(answer, store)) == ["schema"]


def small_store(tmp_path, xrefs=None):
    """A small copy of the verse store, with a cross_refs table only if `xrefs` is given."""
    path = tmp_path / "verses.db"
    con = sqlite3.connect(path)
    con.execute("ATTACH ? AS real", (str(SQLITE),))
    con.execute("CREATE TABLE verses AS SELECT * FROM real.verses "
                "WHERE canon_ref IN ('JHN.1.1', 'GEN.1.1', 'ISA.40.3')")
    if xrefs is not None:
        con.execute("CREATE TABLE cross_refs (from_canon_ref, to_canon_ref, votes, dataset)")
        con.executemany("INSERT INTO cross_refs VALUES (?, ?, ?, 'openbible')", xrefs)
    con.commit()
    con.close()
    return VerseStore(path)


def test_verified_cross_ref_needs_data(tmp_path, db, answer):
    store = small_store(tmp_path)  # no cross_refs table
    answer["passages"][0]["cross_refs"] = [{"to": "GEN.1.1", "relation": "verified"}]
    assert codes(validate(answer, store)) == ["schema"]  # no dataset named
    answer["passages"][0]["cross_refs"][0]["dataset"] = "openbible"
    assert codes(validate(answer, store)) == ["unverifiable"]


@pytest.fixture()
def store_with_xrefs(tmp_path, db):
    return small_store(tmp_path, [("JHN.1.1", "GEN.1.1", XREF_MIN_VOTES + 5),
                                  ("JHN.1.1", "ISA.40.3", 1)])


def test_real_quotation_is_verified(store, answer):
    if not store.con.execute("SELECT 1 FROM sqlite_master WHERE name = 'cross_refs'").fetchone():
        pytest.skip("verses.db has no cross_refs yet")
    passage = answer["passages"][0]
    passage.update(canon_ref="JHN.1.23", display_ref="John 1:23", texts=[
        {"kind": "established_translation", "source": "web", "language": "en", "verse_uid": "web:JHN.1.23",
         "text": store.get(["web:JHN.1.23"])["web:JHN.1.23"]["text_display"]}],
        cross_refs=[{"to": "ISA.40.3", "relation": "verified", "dataset": "openbible"},
                    {"to": "ISA.40.4", "relation": "verified", "dataset": "openbible"}])  # inside range
    assert validate(answer, store)["valid"]


@pytest.mark.parametrize("to, expected", [
    ("GEN.1.1", []), ("ISA.40.3", ["weak_cross_ref"]), ("PSA.1.1", ["unknown_cross_ref"])])
def test_verified_cross_refs_are_checked(store_with_xrefs, answer, to, expected):
    answer["passages"][0]["cross_refs"] = [{"to": to, "relation": "verified", "dataset": "openbible"}]
    assert codes(validate(answer, store_with_xrefs)) == expected


def test_cli_validate(tmp_path, capsys, store, answer):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as ok:
        cli.main(["validate", str(path)])
    assert ok.value.code == 0 and json.loads(capsys.readouterr().out)["valid"]

    texts(answer)[0]["text"] = "fabricated"
    path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as bad:
        cli.main(["validate", str(path)])
    assert bad.value.code == 1 and json.loads(capsys.readouterr().out)["errors"][0]["code"] == "text_mismatch"


def test_cli_validate_bad_json(tmp_path, capsys, store):
    path = tmp_path / "answer.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["validate", str(path)])
    assert exit_info.value.code == 1 and json.loads(capsys.readouterr().out)["errors"][0]["code"] == "json"
