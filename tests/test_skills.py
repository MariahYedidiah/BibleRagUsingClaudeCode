"""Phase 4: translation skill definitions and the checks their outputs must pass."""

import copy
import json
import re
from pathlib import Path

import pytest

from bible_rag import cli
from bible_rag.store import VerseStore
from bible_rag.validator import validate_query_terms, validate_translation

SKILLS = Path(__file__).resolve().parents[1] / ".claude" / "skills"
NAMES = ["hebrew-to-english", "greek-to-english", "english-to-hebrew", "english-to-greek"]


@pytest.fixture(scope="module")
def store(db):
    return VerseStore()


def text(store, uid):
    return store.get([uid])[uid]["text_display"]


@pytest.fixture()
def hebrew(store):
    return {
        "canon_ref": "PSA.23.1", "verse_uid": "oshb_wlc:Ps.23.1", "source": "oshb_wlc",
        "corpus_label": "Hebrew (OSHB/WLC)", "original": text(store, "oshb_wlc:Ps.23.1"),
        "translation": "A psalm of David. The LORD is my shepherd; I lack nothing.",
        "method": "machine", "translator": "claude:test",
        "web_reference": "web:PSA.23.1",
    }


@pytest.fixture()
def lxx(store):
    return {
        "canon_ref": "PSA.23.1", "verse_uid": "lxx_swete:27.22.1", "source": "lxx_swete",
        "corpus_label": "Septuagint Greek (Swete LXX)", "original": text(store, "lxx_swete:27.22.1"),
        "translation": "The Lord shepherds me, and I shall lack nothing.",
        "method": "machine", "translator": "claude:test", "web_reference": "web:PSA.23.1",
    }


def codes(result):
    return [e["code"] for e in result["errors"]]


# --- skill files ------------------------------------------------------------------------

def frontmatter(name):
    body = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", body, re.S)
    assert m, f"{name}: missing frontmatter"
    fields = dict(re.findall(r"^([\w-]+):\s*(.*)$", m.group(1), re.M))
    return fields, body


@pytest.mark.parametrize("name", NAMES)
def test_skill_definition(name):
    fields, body = frontmatter(name)
    assert fields["name"] == name
    assert 50 < len(fields["description"]) + len(fields.get("when_to_use", "")) < 1536
    assert "Bash(uv run bible-rag *)" in fields["allowed-tools"]
    kind = "translation" if name.endswith("-to-english") else "terms"
    assert f"bible-rag check {kind}" in body          # every skill checks its own output
    assert "$ARGUMENTS" in body
    assert "## Errors" in body and '"error"' in body


def test_passage_skills_start_from_a_verbatim_draft():
    for name in ("hebrew-to-english", "greek-to-english"):
        _, body = frontmatter(name)
        assert "bible-rag draft translation" in body and "Never touch `original`" in body


def test_draft_copies_the_original_verbatim(capsys, store):
    code, out = run_cli(capsys, "draft", "translation", "GEN.32.1", "PSA.151.1", "--source", "oshb_wlc")
    assert code == 0
    assert out[0]["verse_uid"] == "oshb_wlc:Gen.32.2"  # English 32:1 is Hebrew 32:2
    assert out[0]["original"] == text(store, "oshb_wlc:Gen.32.2")
    assert out[1]["error"] == "unknown_reference"
    filled = {**out[0], "translation": "And Jacob went on his way.", "translator": "claude:test"}
    assert validate_translation(filled, store)["valid"]  # `_` helper fields are ignored


def test_query_skills_never_display_terms():
    for name in ("english-to-hebrew", "english-to-greek"):
        _, body = frontmatter(name)
        assert '"display": false' in body and "never" in body.lower()


# --- passage translation checks ---------------------------------------------------------

def test_valid_translations_pass(store, hebrew, lxx):
    assert validate_translation(hebrew, store) == {"valid": True, "errors": [], "warnings": []}
    assert validate_translation(lxx, store)["valid"]


def test_retyped_original_is_caught(store, hebrew):
    hebrew["original"] = hebrew["original"].replace("/", "")  # "cleaned up" Hebrew
    assert codes(validate_translation(hebrew, store)) == ["text_mismatch"]


def test_septuagint_cannot_be_labeled_new_testament(store, lxx):
    lxx["corpus_label"] = "New Testament Greek (SBLGNT)"
    assert codes(validate_translation(lxx, store)) == ["wrong_label"]


def test_native_lxx_reference_is_caught(store, lxx):
    lxx["canon_ref"] = "PSA.22.1"  # Swete's own number, not the English one
    assert codes(validate_translation(lxx, store)) == ["misaligned"]


def test_untranslated_output_is_caught(store, hebrew):
    hebrew["translation"] = hebrew["original"]
    assert codes(validate_translation(hebrew, store)) == ["not_translated"]


@pytest.mark.parametrize("field, value", [("method", "human"), ("translator", "gpt"),
                                          ("corpus_label", "Hebrew")])
def test_labels_are_enforced_by_schema(store, hebrew, field, value):
    hebrew[field] = value
    assert codes(validate_translation(hebrew, store)) == ["schema"]


def test_web_reference_must_be_web(store, hebrew):
    hebrew["web_reference"] = "sblgnt:JHN.1.1"
    assert codes(validate_translation(hebrew, store)) == ["unknown_verse"]


def test_list_output_reports_item_paths(store, hebrew, lxx):
    bad = copy.deepcopy(lxx)
    bad["original"] = "made up"
    result = validate_translation([hebrew, bad], store)
    assert [(e["path"], e["code"]) for e in result["errors"]] == [("[1].original", "text_mismatch")]


def test_partial_alignment_must_be_mentioned(store):
    uid = "sblgnt:3JN.1.15"
    item = {"canon_ref": "3JN.1.14", "verse_uid": uid, "source": "sblgnt",
            "corpus_label": "New Testament Greek (SBLGNT)", "original": text(store, uid),
            "translation": "Peace to you. The friends greet you. Greet the friends by name.",
            "method": "machine", "translator": "claude:test"}
    assert [w["code"] for w in validate_translation(item, store)["warnings"]] == ["alignment"]
    item["uncertainties"] = ["verse numbering alignment is partial: English Bibles put this in v.14"]
    assert validate_translation(item, store) == {"valid": True, "errors": [], "warnings": []}


def test_skill_error_object_is_accepted(store):
    result = validate_translation({"error": "unknown_reference", "message": "no such verse",
                                   "input": "PSA.151.1"}, store)
    assert result["valid"] and result["warnings"][0]["code"] == "skill_error"
    assert codes(validate_translation({"error": "oops", "message": "", "input": ""}, store)) == ["schema"]


# --- query term checks ------------------------------------------------------------------

@pytest.fixture()
def terms(store):
    counts = store.term_counts(["חסדו", "רחמים"], ["oshb_wlc"])
    return {"query": "God's compassion", "language": "he", "corpus": "oshb_wlc",
            "terms": [{"term": t, "gloss": "x", "hits": n} for t, n in counts.items()],
            "lexical_queries": ["חסדו רחמים"], "translator": "claude:test"}


def test_valid_terms_pass(store, terms):
    assert validate_query_terms(terms, store) == {"valid": True, "errors": [], "warnings": []}


def test_term_missing_from_corpus_is_an_error(store, terms):
    terms["terms"].append({"term": "רחמנות", "gloss": "modern Hebrew 'pity'", "hits": 3})
    assert codes(validate_query_terms(terms, store)) == ["term_not_in_corpus"]


def test_wrong_hit_count_is_a_warning(store, terms):
    terms["terms"][0]["hits"] += 1
    result = validate_query_terms(terms, store)
    assert result["valid"] and result["warnings"][0]["code"] == "hits"


def test_terms_are_never_for_display(store, terms):
    terms["display"] = True
    assert codes(validate_query_terms(terms, store)) == ["schema"]


def test_greek_terms_count_in_the_named_corpus(store):
    counts = store.term_counts(["ἀγάπη"], ["sblgnt"])
    q = {"query": "love", "language": "grc", "corpus": "sblgnt", "translator": "claude:test",
         "terms": [{"term": "ἀγάπη", "gloss": "love", "hits": counts["ἀγάπη"]}],
         "lexical_queries": ["ἀγάπη"]}
    assert validate_query_terms(q, store)["valid"]
    q["language"] = "he"
    assert codes(validate_query_terms(q, store)) == ["wrong_language"]


def test_accents_and_points_do_not_matter(store):
    accented, plain = store.term_counts(["ἔλεος", "ελεοσ"], ["lxx_swete"]).values()
    assert accented == plain > 0
    pointed, plain = store.term_counts(["חַסְדּוֹ", "חסדו"], ["oshb_wlc"]).values()
    assert pointed == plain > 0


# --- CLI --------------------------------------------------------------------------------

def run_cli(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(list(argv))
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def test_cli_terms(capsys, store):
    code, out = run_cli(capsys, "terms", "--corpus", "oshb_wlc", "חסדו", "xyz")
    assert code == 0 and out["counts"]["חסדו"] > 0 and out["missing"] == ["xyz"]


def test_cli_check(tmp_path, capsys, store, hebrew):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(hebrew, ensure_ascii=False), encoding="utf-8")
    code, out = run_cli(capsys, "check", "translation", str(path))
    assert code == 0 and out["valid"]
    hebrew["original"] = "x"
    path.write_text(json.dumps(hebrew, ensure_ascii=False), encoding="utf-8")
    code, out = run_cli(capsys, "check", "translation", str(path))
    assert code == 1 and out["errors"][0]["code"] == "text_mismatch"
