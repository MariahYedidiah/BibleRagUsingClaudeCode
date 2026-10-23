"""Phase 1: verse store, hybrid fusion, service and CLI.

Vector search is faked here so the tests run without loading bge-m3. The real vector path is
covered by test_vector_store.py once the Chroma index is built.
"""

import json

import pytest
from fastapi.testclient import TestClient

from bible_rag import cli
from bible_rag.retrieval import Retriever, detect_language, rrf
from bible_rag.server import create_app
from bible_rag.store import VerseStore, match_expression, where_clause
from bible_rag.vectors import chroma_where


class FakeVectors:
    """Returns preset hits per query (the fake embedding is the query's index)."""

    def __init__(self, *rankings):
        self.rankings = rankings
        self.calls = []

    def search(self, embedding, filters=None, k=20):
        self.calls.append(filters)
        ranking = self.rankings[int(embedding[0])]
        return [{"verse_uid": uid, "rank": i, "score": round(0.9 - i / 100, 4)}
                for i, uid in enumerate(ranking[:k], 1)]

    def count(self):
        return 3


def fake_embed(texts):
    return [[float(i)] for i in range(len(texts))]


@pytest.fixture(scope="module")
def store(db):  # `db` skips the module when verses.db is missing
    return VerseStore()


# --- fusion and query building ----------------------------------------------------------

def test_rrf_rewards_agreement_between_lists():
    fused = dict(rrf([["a", "b", "c"], ["b", "d"]]))
    assert max(fused, key=fused.get) == "b"  # 2nd + 1st beats 1st alone
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_counts_a_repeated_uid_once_per_list():
    assert dict(rrf([["a", "a", "b"]])) == pytest.approx({"a": 1 / 61, "b": 1 / 62})


def test_match_expression_drops_stopwords_and_quotes_terms():
    assert match_expression("What is the love of God?") == '"love" OR "god"'


def test_match_expression_neutralises_fts_syntax():
    expr = match_expression('love* NEAR(god) OR "x" title:lord')
    assert expr == '"love" OR "near" OR "god" OR "x" OR "title" OR "lord"'


def test_match_expression_phrase_and_empty():
    assert match_expression("Jesus wept", phrase=True) == '"jesus wept"'
    assert match_expression("?!") is None


def test_match_expression_folds_greek_and_hebrew():
    assert match_expression("ὁ λόγος") == '"ο" OR "λογοσ"'
    assert match_expression("בְּרֵאשִׁית") == '"בראשית"'


def test_unknown_filter_is_rejected():
    with pytest.raises(ValueError):
        where_clause({"colour": "red"})
    with pytest.raises(ValueError):
        chroma_where({"colour": "red"})


def test_chroma_where():
    assert chroma_where(None) is None
    assert chroma_where({"language": "he", "book_id": None}) == {"language": "he"}
    assert chroma_where({"language": ["he", "grc"], "testament": "OT"}) == {
        "$and": [{"language": {"$in": ["he", "grc"]}}, {"testament": "OT"}]}


def test_detect_language():
    assert detect_language("בראשית") == "he"
    assert detect_language("ἐν ἀρχῇ") == "grc"
    assert detect_language("in the beginning") == "en"


# --- verse store ------------------------------------------------------------------------

def test_lexical_respects_filters(store):
    assert store.lexical("Jesus wept", {"language": "en"})[0]["verse_uid"] == "web:JHN.11.35"
    assert store.lexical("Jesus wept", {"language": "grc"}) == []


def test_context_stays_inside_the_chapter(store):
    verses = [r["verse"] for r in store.context("web:JHN.11.35", 2, 2)]
    assert verses == [33, 34, 35, 36, 37]
    first = store.context("web:JHN.2.1", 2, 2)
    assert [r["verse"] for r in first] == [1, 2, 3] and {r["chapter"] for r in first} == {2}


def test_context_keeps_lxx_editions_apart(store):
    rows = store.context("lxx_swete:57.1.2", 1, 1)  # Daniel, Theodotion
    assert rows and {r["edition"] for r in rows} == {"th"}


def test_by_ref_with_source_filter(store):
    rows = store.by_ref("GEN.1.1", {"source": ["oshb_wlc", "web"]})
    assert {r["source"] for r in rows} == {"oshb_wlc", "web"}


# --- hybrid retriever -------------------------------------------------------------------

def test_hybrid_fuses_vector_and_lexical(store):
    vectors = FakeVectors(["web:GEN.1.1", "web:JHN.11.35"])
    out = Retriever(store, vectors, fake_embed).search("Jesus wept", {"language": "en"}, k=5)
    top = out["results"][0]
    assert top["verse_uid"] == "web:JHN.11.35"
    assert top["found_by"] == ["lexical", "vector"]
    assert top["text_display"].startswith("Jesus wept")
    assert {h["method"] for h in top["hits"]} == {"lexical", "vector"}
    assert "web:GEN.1.1" in [r["verse_uid"] for r in out["results"]]  # vector-only hit kept
    assert vectors.calls == [{"language": "en"}]
    assert out["signals"]["vector_lexical_overlap_top10"] >= 1


def test_results_are_deduplicated_and_ranked(store):
    vectors = FakeVectors(["web:JHN.11.35", "web:JHN.11.35", "web:GEN.1.1"])
    out = Retriever(store, vectors, fake_embed).search("Jesus wept", k=10)
    uids = [r["verse_uid"] for r in out["results"]]
    assert len(uids) == len(set(uids))
    assert [r["rank"] for r in out["results"]] == list(range(1, len(uids) + 1))
    assert len(uids) <= 10


def test_every_query_variant_is_searched(store):
    vectors = FakeVectors(["web:JHN.11.35"], ["web:GEN.1.1"])
    out = Retriever(store, vectors, fake_embed).search(
        ["Jesus wept", "Jesus cried at the tomb"], {"language": "en"})
    assert len(vectors.calls) == 2
    assert out["signals"]["lists"] == 4  # 2 vector + 2 lexical
    assert {"web:JHN.11.35", "web:GEN.1.1"} <= {r["verse_uid"] for r in out["results"]}


def test_lexical_queries_reach_hebrew(store):
    out = Retriever(store).search([], {"language": "he"}, lexical_queries=["ואהבת לרעך כמוך"],
                                  mode="lexical")
    assert out["results"][0]["verse_uid"] == "oshb_wlc:Lev.19.18"


def test_ids_missing_from_sqlite_are_reported_not_returned(store):
    out = Retriever(store, FakeVectors(["web:NOPE.1.1"]), fake_embed).search("zzz", mode="vector")
    assert out["results"] == [] and out["missing"] == ["web:NOPE.1.1"]


def test_context_is_attached(store):
    out = Retriever(store).search("Jesus wept", {"language": "en"}, k=1, mode="lexical", context=1)
    assert [c["verse"] for c in out["results"][0]["context"]] == [34, 35, 36]


def test_vector_modes_need_vectors(store):
    with pytest.raises(ValueError, match="unavailable"):
        Retriever(store).search("Jesus wept")
    with pytest.raises(ValueError, match="no query"):
        Retriever(store).search([], mode="lexical")


# --- service ----------------------------------------------------------------------------

@pytest.fixture()
def client(store):
    app = create_app(Retriever(store, FakeVectors(["web:JHN.11.35"]), fake_embed))
    with TestClient(app) as c:
        yield c


def test_service_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["verses"] > 90_000 and body["vectors"] == 3


def test_service_search(client):
    resp = client.post("/search", json={"queries": ["Jesus wept"], "filters": {"language": "en"}})
    assert resp.status_code == 200
    assert resp.json()["results"][0]["verse_uid"] == "web:JHN.11.35"


def test_service_rejects_bad_requests(client):
    assert client.post("/search", json={"queries": ["x"], "filters": {"colour": "red"}}).status_code == 400
    assert client.post("/search", json={"queries": ["x"], "mode": "fuzzy"}).status_code == 422
    assert client.post("/search", json={"queries": ["x"], "k": 0}).status_code == 422


def test_service_verse(client):
    body = client.get("/verse/jhn.1.1", params={"source": "sblgnt"}).json()
    assert [v["verse_uid"] for v in body["verses"]] == ["sblgnt:JHN.1.1"]
    assert client.get("/verse/XYZ.1.1").status_code == 404


# --- CLI --------------------------------------------------------------------------------

def run_cli(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(list(argv))
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def test_cli_verse(capsys, store):
    code, out = run_cli(capsys, "verse", "gen.1.1", "--source", "web")
    assert code == 0 and out["verses"][0]["text_display"].startswith("In the beginning")


def test_cli_lexical_search_without_service(capsys, store):
    code, out = run_cli(capsys, "search", "Jesus wept", "--mode", "lexical", "--lang", "en", "--k", "1")
    assert code == 0 and out["results"][0]["verse_uid"] == "web:JHN.11.35"


def test_cli_reports_service_down(capsys):
    code, out = run_cli(capsys, "search", "Jesus wept", "--port", "1")
    assert code == 2 and "bible-rag serve" in out["error"]


def test_cli_reports_bad_input(capsys, store):
    code, out = run_cli(capsys, "verse", "XYZ.1.1")
    assert code == 1 and "no verse" in out["error"]
