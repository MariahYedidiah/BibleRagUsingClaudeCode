"""Checks on the built Parquet table and the SQLite / FTS5 verse store."""

import json
import re

import pytest

import build_index
from bible_rag.books import BOOK_NAMES
from bible_rag.text import fold

SOURCES = {"oshb_wlc": "he", "lxx_swete": "grc", "sblgnt": "grc", "web": "en"}


def jsonl_counts():
    counts = {}
    for path in build_index.JSONL_DIR.glob("*.jsonl"):
        with path.open(encoding="utf-8") as f:
            for line in f:
                source = json.loads(line)["source"]
                counts[source] = counts.get(source, 0) + 1
    return counts


def test_parquet_has_every_jsonl_verse(verses):
    assert verses.groupby("source").size().to_dict() == jsonl_counts()


def test_parquet_schema_and_no_nulls(verses):
    assert list(verses.columns) == build_index.COLUMNS
    assert not verses.isna().any().any()
    assert (verses["text_norm"].str.strip() != "").all()


def test_verse_uid_unique(verses):
    assert verses["verse_uid"].is_unique


def test_source_language_pairs(verses):
    pairs = verses.groupby("source")["language"].unique().to_dict()
    assert {s: list(l) for s, l in pairs.items()} == {s: [l] for s, l in SOURCES.items()}


def test_all_book_ids_are_usfm(verses):
    assert set(verses["book_id"]) <= set(BOOK_NAMES)
    assert not verses["book_id"].str.startswith("LXX_").any()


def test_canon_ref_format(verses):
    assert verses["canon_ref"].str.fullmatch(r"[1-4A-Z][A-Z0-9]{2}\.\d+\.\d+").all()


def test_hebrew_text_norm_is_clean(verses):
    he = verses[verses["language"] == "he"]["text_norm"]
    assert not he.str.contains("/").any()
    assert not he.str.contains("[֑-֯]").any()


def test_sqlite_matches_parquet(db, verses):
    assert db.execute("select count(*) from verses").fetchone()[0] == len(verses)
    assert db.execute("select count(distinct verse_uid) from verses").fetchone()[0] == len(verses)


def test_fts_index_in_sync(db):
    n_verses = db.execute("select count(*) from verses").fetchone()[0]
    n_fts = db.execute("select count(*) from verses_fts").fetchone()[0]
    assert n_fts == n_verses
    db.execute("insert into verses_fts(verses_fts) values ('integrity-check')")


@pytest.mark.parametrize("canon_ref, sources", [
    ("GEN.1.1", {"oshb_wlc", "lxx_swete", "web"}),
    ("JHN.1.1", {"sblgnt", "web"}),
    ("NEH.1.1", {"oshb_wlc", "lxx_swete", "web"}),
])
def test_cross_source_join_on_canon_ref(db, canon_ref, sources):
    found = {r[0] for r in db.execute("select source from verses where canon_ref = ?", (canon_ref,))}
    assert found == sources


@pytest.mark.parametrize("query, expected_uid", [
    ("ἐν ἀρχῇ ἦν ὁ λόγος", "sblgnt:JHN.1.1"),
    ("εν αρχη ην ο λογος", "sblgnt:JHN.1.1"),       # unaccented query, same hit
    ("בראשית ברא אלהים", "oshb_wlc:Gen.1.1"),      # unpointed Hebrew
    ("God so loved the world", "web:JHN.3.16"),
])
def test_fts_finds_verse(db, query, expected_uid):
    match = " ".join(f'"{t}"' for t in fold(query).split())
    uids = [r[0] for r in db.execute(
        "select v.verse_uid from verses_fts f join verses v on v.id = f.rowid "
        "where verses_fts match ? order by bm25(verses_fts) limit 10", (match,))]
    assert expected_uid in uids


@pytest.mark.parametrize("query, expected_uid", [
    ("ἀγαπήσεις τὸν πλησίον σου ὡς σεαυτόν", "sblgnt:MAT.22.39"),  # love your neighbour, Greek NT
    ("ואהבת לרעך כמוך", "oshb_wlc:Lev.19.18"),                    # same command, Hebrew
    ("Jesus wept", "web:JHN.11.35"),
])
def test_fts_finds_quoted_phrase(db, query, expected_uid):
    match = '"' + fold(query) + '"'  # FTS5 phrase query: words adjacent and in order
    uids = [r[0] for r in db.execute(
        "select v.verse_uid from verses_fts f join verses v on v.id = f.rowid "
        "where verses_fts match ? limit 50", (match,))]
    assert expected_uid in uids


def test_fts_returns_nothing_for_nonsense(db):
    assert db.execute("select count(*) from verses_fts where verses_fts match ?", ('"xqzv blorpt"',)).fetchone()[0] == 0


def test_lookup_by_reference(db):
    row = db.execute("select text_display from verses where source='web' and canon_ref='JHN.11.35'").fetchone()
    assert row and re.search(r"Jesus wept", row[0])
