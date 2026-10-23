"""Phase 3: versification mapping, data cleanup and cross-references."""

import collections
import json
import re

import pytest

from bible_rag import crossrefs, versification as vz
from bible_rag.config import JSONL_DIR
from bible_rag.store import VerseStore


# --- TVTMS test evaluation (synthetic data) ---------------------------------------------

@pytest.fixture()
def chapters():
    # Psalm 9 with 30 verses and a title as verse 0; Psalm 10 with 5 verses.
    verses = {("PSA", 9, v): 10 for v in range(0, 31)}
    verses.update({("PSA", 10, v): v for v in range(1, 6)})  # word count = verse number
    return vz.Chapters(verses)


@pytest.mark.parametrize("atom, expected", [
    ("Psa.9:30=Exist", True),
    ("Psa.9:31=Exist", False),
    ("Psa.9:31=NotExist", True),
    ("PSA.9:30=Last", True),
    ("Psa.10:4=Last", False),
    ("Psa.9:TextBeforeV1=Exist", True),
    ("Psa.10:TextBeforeV1=NotExist", True),
    ("Psa.10:2.1=Exist", False),      # sub-verses never exist in whole-verse data
    ("Psa.10:2.1=NotExist", True),
    ("Psa.10:2<Psa.10:3", True),      # word counts 2 < 3
    ("Psa.10:4>Psa.10:5", False),
    ("Psa.10:4>Psa.10:9", False),     # missing verse
    ("nonsense", None),
])
def test_tvtms_test_atoms(chapters, atom, expected):
    assert chapters.test(atom) is expected


def test_relaxed_skips_only_variant_tests(chapters):
    tests = ["Psa.9:30=Exist", "Psa.10:4>Psa.10:5", "Psa.10:TextBeforeV1=Exist"]
    assert not chapters.passes(tests)
    assert chapters.passes(tests, relaxed=True)
    assert not chapters.passes(["Psa.9:31=Exist"], relaxed=True)  # chapter-level tests still count


def test_parse_standard():
    assert vz.parse_standard("Psa.23:1") == ("PSA.23.1", True)
    assert vz.parse_standard("Psa.23:Title") == ("PSA.23.0", True)
    assert vz.parse_standard("Gen.2:25-3:1") == ("GEN.2.25", False)
    assert vz.parse_standard("Absent") is None


def test_map_hebrew_synthetic():
    verse_map = {"Ps.3.2": ("Ps.3.1", "full"), "Gen.32.1": ("Gen.31.55", "full"),
                 "Exod.8.1": ("Exod.8.5", "partial"), "Exod.8.2": ("Exod.7.30", "full")}
    rows = [("a", "Ps.3.1"), ("b", "Ps.3.2"), ("c", "Gen.32.1"), ("d", "Exod.8.1"),
            ("e", "Exod.7.30"), ("f", "Gen.1.1")]
    out = vz.map_hebrew(rows, verse_map)
    assert out == {"a": ("PSA.3.0", "mapped"), "b": ("PSA.3.1", "mapped"),
                   "c": ("GEN.31.55", "mapped"), "d": ("EXO.8.5", "partial"),
                   "e": ("EXO.7.30", "unmapped"), "f": ("GEN.1.1", "mapped")}


def test_map_hebrew_two_verse_title_and_part_verse():
    verse_map = {"Ps.51.2": ("Ps.51.1", "full"), "Ps.51.3": ("Ps.51.1", "full"),
                 "Ps.51.4": ("Ps.51.2", "full"), "1Kgs.22.44": ("1Kgs.22.43!b", "partial")}
    rows = [("t1", "Ps.51.1"), ("t2", "Ps.51.2"), ("v1", "Ps.51.3"), ("v2", "Ps.51.4"),
            ("k", "1Kgs.22.44")]
    out = vz.map_hebrew(rows, verse_map)
    assert out["t1"] == out["t2"] == ("PSA.51.0", "mapped")
    assert out["v1"] == ("PSA.51.1", "mapped") and out["v2"] == ("PSA.51.2", "mapped")
    assert out["k"] == ("1KI.22.43", "partial")


def test_map_lxx_synthetic():
    rows = [{"traditions": ["Greek"], "book": "PSA", "chapter": 22, "verse": "1", "part": "",
             "standard": "Psa.23:1", "action": "Renumber verse", "tests": ["Psa.22:2=Last"]},
            {"traditions": ["Greek"], "book": "PSA", "chapter": 22, "verse": "2", "part": "",
             "standard": "Psa.23:2", "action": "Renumber verse", "tests": ["Psa.22:2=Last"]}]
    verses = [("t", "PSA", 22, 0, 3), ("a", "PSA", 22, 1, 5), ("b", "PSA", 22, 2, 5),
              ("x", "PSA", 23, 1, 4)]
    out = vz.map_lxx(verses, rows)
    assert out["a"] == ("PSA.23.1", "mapped") and out["b"] == ("PSA.23.2", "mapped")
    assert out["t"] == ("PSA.23.0", "partial")   # title follows its psalm
    assert out["x"] == ("PSA.23.1", "unmapped")  # kept its number only by default, now taken


# --- real data --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def store(db):
    store = VerseStore()
    if "alignment" not in {r[1] for r in store.con.execute("PRAGMA table_info(verses)")}:
        pytest.skip("verses.db predates phase 3; rebuild with scripts/build_index.py")
    return store


@pytest.mark.parametrize("uid, canon_ref, alignment", [
    ("oshb_wlc:Gen.32.1", "GEN.31.55", "mapped"),
    ("oshb_wlc:Mal.3.19", "MAL.4.1", "mapped"),
    ("oshb_wlc:Joel.3.1", "JOL.2.28", "mapped"),
    ("oshb_wlc:Ps.3.1", "PSA.3.0", "mapped"),     # psalm title
    ("oshb_wlc:Ps.3.2", "PSA.3.1", "mapped"),
    ("lxx_swete:27.22.0", "PSA.23.0", "mapped"),  # Swete title, was mislabeled 22.32
    ("lxx_swete:27.22.1", "PSA.23.1", "mapped"),
    ("lxx_swete:27.9.22", "PSA.10.1", "mapped"),  # LXX Ps 9 = Heb/Eng Ps 9-10
    ("lxx_swete:27.113.9", "PSA.115.1", "mapped"),
    ("lxx_swete:49.38.31", "JER.31.31", "mapped"),  # new covenant: LXX Jer 38 = Eng Jer 31
    ("lxx_swete:18.11.1", "NEH.1.1", "mapped"),   # 2 Esdras 11 = Nehemiah 1
    ("lxx_swete:27.88.48", "PSA.89.47", "mapped"),  # source typo 88.84 fixed
    ("sblgnt:PHP.1.16", "PHP.1.17", "mapped"),
    ("sblgnt:3JN.1.15", "3JN.1.14", "partial"),
    ("web:PSA.23.1", "PSA.23.1", "mapped"),
])
def test_known_alignments(store, uid, canon_ref, alignment):
    row = store.get([uid])[uid]
    assert (row["canon_ref"], row["alignment"]) == (canon_ref, alignment)


def test_psalm_23_in_three_languages(store):
    rows = {r["source"]: r["text_display"] for r in store.by_ref("PSA.23.1")}
    assert set(rows) == {"oshb_wlc", "lxx_swete", "web"}
    assert "רֹ֝עִ֗/י" in rows["oshb_wlc"] and "ποιμαίνει" in rows["lxx_swete"]


def test_no_two_mapped_verses_share_a_reference(store):
    rows = store.con.execute(
        "SELECT source, edition, canon_ref, count(*) FROM verses WHERE alignment = 'mapped' "
        "AND canon_ref NOT LIKE '%.0' GROUP BY source, edition, canon_ref HAVING count(*) > 1"
    ).fetchall()
    assert [tuple(r) for r in rows] == []


@pytest.mark.parametrize("source", ["oshb_wlc", "lxx_swete"])
def test_ot_references_line_up_with_web(store, source):
    found, total = store.con.execute(
        "SELECT sum(canon_ref IN (SELECT canon_ref FROM verses WHERE source = 'web')), count(*) "
        "FROM verses WHERE source = ? AND testament = 'OT' AND canon_ref NOT LIKE '%.0'",
        (source,)).fetchone()
    assert found / total > 0.985


def test_hebrew_has_no_leaked_notes(store):
    n = store.con.execute("SELECT count(*) FROM verses WHERE source = 'oshb_wlc' "
                          "AND (text_display GLOB '*[A-Za-z]*')").fetchone()[0]
    assert n == 0


def test_lxx_digitization_artifacts_removed(store):
    n = store.con.execute("SELECT count(*) FROM verses WHERE source = 'lxx_swete' "
                          "AND (text_display GLOB '*([0-9]*' OR text_display GLOB '*[0-9]*')").fetchone()[0]
    assert n == 0
    assert store.get(["lxx_swete:01.9.1"])["lxx_swete:01.9.1"]["text_display"].startswith("καὶ εἶπεν")


def test_sblgnt_signs_kept_for_display_but_not_embedded(store):
    row = store.con.execute("SELECT text_display, text_norm FROM verses "
                            "WHERE verse_uid = 'sblgnt:PHP.1.16'").fetchone()
    assert "⸂" in row[0] and "⸂" not in row[1]


def test_jsonl_titles_are_verse_zero():
    titles = [json.loads(l) for l in open(JSONL_DIR / "greek_lxx.jsonl", encoding="utf-8")
              if '"verse": 0' in l]
    psalms = [t for t in titles if t["book_name"] == "Psalmi"]
    assert len(psalms) >= 50 and all(re.search("ψαλμ|ᾠδ|ὕμν|εἰς τὸ τέλος", t["text"], re.I)
                                     or len(t["text"].split()) < 25 for t in psalms)


# --- cross-references -------------------------------------------------------------------

def test_cross_refs_loaded(store):
    assert store.con.execute("SELECT count(*) FROM cross_refs").fetchone()[0] > 500_000


@pytest.mark.parametrize("votes, relation", [(100, "verified"), (25, "verified"),
                                             (24, "possible_allusion"), (5, "possible_allusion"),
                                             (4, "thematic"), (-3, "thematic")])
def test_relation_thresholds(votes, relation):
    assert crossrefs.relation(votes) == relation


def test_range_is_reported_once(store):
    links = store.cross_refs("MRK.1.3", testament="OT")
    isaiah = [l for l in links if l["to"].startswith("ISA.40.")]
    assert len(isaiah) == 1
    assert isaiah[0] == {"to": "ISA.40.3", "votes": isaiah[0]["votes"], "relation": "verified",
                         "dataset": "openbible", "to_range": "Isa.40.3-Isa.40.5"}


def test_testament_filter(store):
    from bible_rag.books import testament

    links = store.cross_refs("MAT.1.23", testament="OT")
    assert links and all(testament(l["to"].split(".")[0]) == "OT" for l in links)
    assert any(l["to"] == "ISA.7.14" and l["relation"] == "verified" for l in links)


def test_parse_expands_ranges_within_a_chapter(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("From Verse\tTo Verse\tVotes\n"
                    "Mark.1.3\tIsa.40.3-Isa.40.5\t32\n"
                    "Matt.1.1\tGen.5.32-Gen.6.2\t7\n"
                    "Bogus.1.1\tGen.1.1\t3\n", encoding="utf-8")
    rows = list(crossrefs.parse(path))
    assert [r[1] for r in rows[:3]] == ["ISA.40.3", "ISA.40.4", "ISA.40.5"]
    assert rows[3] == ("MAT.1.1", "GEN.5.32", 7, "Gen.5.32-Gen.6.2")  # cross-chapter: first verse
    assert len(rows) == 4  # unknown book skipped
