"""Phase 7: retrieval evaluation, confidence calibration, and the committed golden-query runs."""

import json

import pytest

from bible_rag import evaluate, runs
from bible_rag.store import VerseStore


@pytest.fixture(scope="module")
def store(db):
    return VerseStore()


@pytest.fixture()
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS", tmp_path)
    return tmp_path


# --- retrieval evaluation ---------------------------------------------------------------

def fake_search(ranked):
    """A /search stand-in that returns `ranked[source]` as canon_refs, best first."""
    def search(request):
        refs = ranked.get(request["filters"]["source"], [])
        return {"results": [{"canon_ref": r} for r in refs],
                "signals": {"top_vector_score": 0.7 if refs else None, "vector_margin": 0.01}}
    return search


def test_retrieval_ranks_and_recall(store):
    cases = [{"query": "q", "expected": ["GEN.1.1"], "testament": "OT", "kind": "quote"}]
    out = evaluate.retrieval(cases, fake_search({"web": ["GEN.1.1"], "oshb_wlc": ["GEN.2.4", "GEN.1.1"],
                                                 "lxx_swete": []}), store, modes=("vector",))
    assert {r["corpus"]: r["rank"] for r in out["rows"]} == {"web": 1, "oshb_wlc": 2, "lxx_swete": None}
    s = out["summary"]
    assert s["web/vector"]["recall@1"] == 1.0 and s["oshb_wlc/vector"]["mrr"] == 0.5
    assert s["lxx_swete/vector"]["misses"] == ["q"]


def test_retrieval_skips_corpora_without_the_verse(store):
    # Swete has no Ecclesiastes, so an Ecclesiastes case isn't scored against lxx_swete
    cases = [{"query": "a time for everything", "expected": ["ECC.3.1"], "testament": "OT", "kind": "quote"}]
    out = evaluate.retrieval(cases, fake_search({}), store, modes=("vector",))
    assert {r["corpus"] for r in out["rows"]} == {"web", "oshb_wlc"}


def test_off_topic_cases_only_record_signals(store):
    cases = [{"query": "cookies", "testament": "both", "kind": "off_topic"}]
    out = evaluate.retrieval(cases, fake_search({"web": ["GEN.1.1"]}), store, modes=("vector",))
    assert len(out["rows"]) == 4 and set(out["summary"]) == {"off_topic"}


def test_golden_and_retrieval_case_files_are_consistent(store):
    golden = evaluate.load_cases("golden_queries.json")["queries"]
    assert [g["name"] for g in golden] == ["ot_creation", "nt_word", "polarized_suffering",
                                           "nt_ot_voice", "low_evidence"]
    for g in golden:
        for ref in g.get("expect_refs", {}):
            assert store.by_ref(ref), ref
    for case in evaluate.load_cases("retrieval_cases.json")["cases"]:
        for ref in case.get("expected", []):
            assert store.by_ref(ref, {"source": "web"}), ref


# --- confidence calibration -------------------------------------------------------------

def specialist(run_id, source, scores, service="up", found_by=("vector",)):
    agent = runs.AGENT_FOR[source]
    passages = [{"canon_ref": f"PSA.{i + 1}.1", "verse_uid": f"{source}:x{i}", "source": source,
                 "found_by": list(found_by),
                 "hits": [{"query": "q", "method": "vector", "rank": 1, "score": s}]}
                for i, s in enumerate(scores)]
    runs.save({"agent": agent, "service": service, "passages": passages},
              runs.run_dir(run_id) / f"{agent}.json")


def test_passages_at_off_topic_similarity_cap_confidence(tmp_runs):
    runs.new_run("q", "weak")
    specialist("weak", "web", [0.55, 0.52])          # below the WEB floor (0.60)
    specialist("weak", "oshb_wlc", [0.50])            # below the Hebrew floor (0.53)
    c = runs.confidence("weak")
    assert c["level"] == "low" and c["signals"]["above_vector_floor"] == 0
    assert "off-topic" in c["basis"]


def test_one_passage_above_its_floor_lifts_the_cap(tmp_runs):
    runs.new_run("q", "ok")
    specialist("ok", "web", [0.55, 0.72])
    c = runs.confidence("ok")
    assert c["signals"]["above_vector_floor"] == 1 and "off-topic" not in c["basis"]


def test_floor_is_not_applied_without_vector_search(tmp_runs):
    runs.new_run("q", "lexical")
    specialist("lexical", "web", [], service="down")
    runs.save({"agent": "english-retrieval-agent", "service": "down",
               "passages": [{"canon_ref": "PSA.1.1", "verse_uid": "web:PSA.1.1", "source": "web",
                             "found_by": ["lexical"], "hits": []}]},
              runs.run_dir("lexical") / "english-retrieval-agent.json")
    assert "off-topic" not in runs.confidence("lexical")["basis"]


# --- committed golden runs --------------------------------------------------------------

GOLDEN = {g["name"]: g for g in evaluate.load_cases("golden_queries.json")["queries"]}
COMMITTED = sorted(p.name for p in runs.RUNS.glob("golden-*") if (p / "answer.json").exists())


@pytest.mark.parametrize("run_id", COMMITTED)
def test_committed_golden_run_still_passes(store, run_id):
    name = run_id.removeprefix("golden-").replace("-", "_")
    golden = next(g for key, g in GOLDEN.items() if name.startswith(key) or key.startswith(name))
    result = evaluate.check_run(run_id, golden, store)
    assert result["passed"], json.dumps([c for c in result["checks"] if not c["passed"]], indent=1)
