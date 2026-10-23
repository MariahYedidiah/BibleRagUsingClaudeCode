"""Phase 6: leader and synthesis definitions, query analysis, runs, confidence, answer assembly."""

import json
import re
from pathlib import Path

import pytest

from bible_rag import results, runs
from bible_rag.retrieval import Retriever
from bible_rag.store import VerseStore
from bible_rag.validator import validate, validate_analysis

CLAUDE_DIR = Path(__file__).resolve().parents[1] / ".claude"
TEAM = ["english-retrieval-agent", "hebrew-specialist-agent", "septuagint-specialist-agent",
        "greek-new-testament-agent", "cross-reference-agent", "synthesis-agent"]


@pytest.fixture(scope="module")
def store(db):
    store = VerseStore()
    if not store.con.execute("SELECT 1 FROM sqlite_master WHERE name = 'cross_refs'").fetchone():
        pytest.skip("verses.db predates phase 3")
    return store


@pytest.fixture()
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS", tmp_path)
    return tmp_path


def codes(result):
    return [e["code"] for e in result["errors"]]


# --- definitions ------------------------------------------------------------------------

def frontmatter(path):
    head = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S).group(1)
    return dict(re.findall(r"^([\w-]+):\s*(.*)$", head, re.M)), path.read_text(encoding="utf-8")


def test_leader_can_only_delegate_to_the_team():
    fields, body = frontmatter(CLAUDE_DIR / "agents" / "leader-agent.md")
    allowed = re.match(r"Agent\(([^)]*)\)", fields["tools"]).group(1)
    assert sorted(a.strip() for a in allowed.split(",")) == sorted(TEAM)
    for step in ("run new", "check analysis", "run confidence", "retry once", "--group r1",
                 "check answer runs/<run_id>/answer.json --run", "parallel"):
        assert step in body
    assert "Never" in body and "answer from memory" in body


def test_synthesis_definition():
    fields, body = frontmatter(CLAUDE_DIR / "agents" / "synthesis-agent.md")
    assert fields["name"] == "synthesis-agent" and "Agent" not in fields["tools"]
    assert "bible-rag run answer" in body and "[PSA.103.8]" in body


def test_bible_ask_command_runs_the_leader_workflow():
    fields, body = frontmatter(CLAUDE_DIR / "skills" / "bible-ask" / "SKILL.md")
    assert fields["disable-model-invocation"] == "true"
    assert ".claude/agents/leader-agent.md" in body and "$ARGUMENTS" in body


# --- query analysis ---------------------------------------------------------------------

@pytest.fixture()
def analysis():
    q = "Why doesn't God care about human suffering?"
    return {"run_id": "t", "question": q, "understanding": "Asks whether God is indifferent to suffering.",
            "intent": "explain", "topics": ["suffering", "God's compassion"], "sentiment": "negative",
            "polarity": "polarized", "explicit_refs": [], "testament": "both", "workflows": ["OT", "NT"],
            "queries": [q, "How does the Bible describe God's response to human suffering?",
                        "Which passages describe God's compassion toward people who suffer?"],
            "variant_kinds": ["original", "neutral", "contrasting"]}


def test_valid_analysis(store, analysis):
    assert validate_analysis(analysis, store) == {"valid": True, "errors": [], "warnings": []}


def test_polarized_question_needs_neutral_and_contrasting(store, analysis):
    analysis["queries"] = analysis["queries"][:1] + ["Why does God care about human suffering?"]
    analysis["variant_kinds"] = ["original", "antonym"]
    assert set(codes(validate_analysis(analysis, store))) == {"polarized", "antonym_only"}


def test_original_question_comes_first_unchanged(store, analysis):
    analysis["queries"][0] = "God and suffering"
    assert codes(validate_analysis(analysis, store)) == ["variants"]


def test_explicit_refs_must_exist(store, analysis):
    analysis["explicit_refs"] = ["JHN.3.16", "John 3:16", "JHN.30.1"]
    assert codes(validate_analysis(analysis, store)) == ["unknown_reference", "unknown_reference"]


def test_sentiment_is_a_closed_label(store, analysis):
    analysis["sentiment"] = "angry"
    assert codes(validate_analysis(analysis, store)) == ["schema"]


# --- runs and trace ---------------------------------------------------------------------

def test_new_run_and_trace(tmp_runs):
    r = runs.new_run("What is love?", "demo")
    with pytest.raises(ValueError):
        runs.new_run("again", "demo")
    for agent in ("english-retrieval-agent", "hebrew-specialist-agent"):
        runs.trace("demo", "delegate", agent, group="r1")
    runs.trace("demo", "delegate", "synthesis-agent", group="synth")
    shown = runs.show("demo")
    assert "parallel group r1: 2 agents" in shown and "synthesis-agent" in shown
    assert "parallel group synth" not in shown  # a single delegation is sequential
    assert Path(r["dir"]).name == "demo"


# --- building a run ---------------------------------------------------------------------

def lexical_result(store, tmp_path, agent, corpus, lexical, keep, run_id, translate=False):
    out = Retriever(store).search([], {"source": corpus}, k=10, mode="lexical", lexical_queries=lexical)
    search = tmp_path / f"{agent}-search.json"
    search.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    translations = None
    if translate:
        items = []
        for uid in keep:
            row = store.get([uid])[uid]
            items.append({"canon_ref": row["canon_ref"], "verse_uid": uid, "source": corpus,
                          "corpus_label": {"oshb_wlc": "Hebrew (OSHB/WLC)",
                                           "lxx_swete": "Septuagint Greek (Swete LXX)",
                                           "sblgnt": "New Testament Greek (SBLGNT)"}[corpus],
                          "original": row["text_display"], "translation": f"(test rendering of {uid})",
                          "method": "machine", "translator": "claude:test"})
        translations = tmp_path / f"{agent}-translations.json"
        translations.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    r = results.pack_specialist(agent, run_id, corpus, [search],
                                {"keep": [{"verse_uid": u, "relevance": "test"} for u in keep]},
                                store, translations)
    runs.save(r, runs.run_dir(run_id) / f"{agent}.json")
    return r


@pytest.fixture()
def ot_run(tmp_runs, tmp_path, store):
    runs.new_run("How does God show compassion?", "ot")
    lexical_result(store, tmp_path, "hebrew-specialist-agent", "oshb_wlc", ["רחום וחנון"],
                   ["oshb_wlc:Ps.103.8", "oshb_wlc:Exod.34.6"], "ot", translate=True)
    lexical_result(store, tmp_path, "english-retrieval-agent", "web", ["compassionate and gracious"],
                   ["web:PSA.103.8", "web:EXO.34.6"], "ot")
    return "ot"


def synthesis(run_id, refs, text=None):
    return {"run_id": run_id, "passages": [{"canon_ref": r, "note": "test"} for r in refs],
            "answer": text or " and ".join(f"[{r}]" for r in refs) + " describe God as compassionate."}


def test_confidence_levels(tmp_runs, tmp_path, store, ot_run):
    c = runs.confidence(ot_run)
    assert c["signals"]["cross_lingual_refs"] == ["EXO.34.6", "PSA.103.8"]
    assert c["signals"]["vector_search_available"] is False
    assert c["level"] == "medium"  # agreement across languages, but no vector evidence
    runs.new_run("empty", "empty")
    assert runs.confidence("empty")["level"] == "insufficient"


def test_answer_assembles_and_validates(store, ot_run):
    answer = runs.pack_answer(ot_run, synthesis(ot_run, ["PSA.103.8", "EXO.34.6"]), store)
    assert validate(answer, store, ot_run) == {"valid": True, "errors": [], "warnings": []}
    p = answer["passages"][0]
    assert [(t["kind"], t["source"]) for t in p["texts"]] == [
        ("established_translation", "web"), ("original", "oshb_wlc"), ("machine_translation", "oshb_wlc")]
    assert [m["field"] for m in p["missing"]] == ["lxx_swete"]  # not retrieved: explicit, not invented
    assert p["texts"][1]["text"] == store.get(["oshb_wlc:Ps.103.8"])["oshb_wlc:Ps.103.8"]["text_display"]


def test_uncited_and_unretrieved_references_are_rejected(store, ot_run):
    answer = runs.pack_answer(ot_run, synthesis(ot_run, ["PSA.103.8"], "See [PSA.103.8] and [JHN.3.16]."), store)
    assert codes(validate(answer, store, ot_run)) == ["uncited_reference"]
    with pytest.raises(ValueError):
        runs.pack_answer(ot_run, synthesis(ot_run, ["JHN.3.16"]), store)


def test_confidence_cannot_be_overruled(store, ot_run):
    answer = runs.pack_answer(ot_run, synthesis(ot_run, ["PSA.103.8"]), store)
    answer["confidence"]["level"] = "high"
    assert codes(validate(answer, store, ot_run)) == ["confidence"]


def test_render_ot_order_and_labels(store, ot_run):
    md = runs.render(runs.pack_answer(ot_run, synthesis(ot_run, ["PSA.103.8"]), store))
    labels = re.findall(r"^\*\*(.+?)\*\*$", md, re.M)
    assert labels[0].startswith("English: WEB") and labels[1].startswith("Hebrew: OSHB/WLC")
    assert labels[2].startswith("Hebrew → English (machine translation")
    assert "lxx_swete: not retrieved by septuagint-specialist-agent" in md
    assert "Evidence confidence: medium" in md


def test_nt_to_ot_rendering(tmp_runs, tmp_path, store):
    runs.new_run("Who is the voice in the wilderness?", "nt")
    lexical_result(store, tmp_path, "greek-new-testament-agent", "sblgnt", ["φωνὴ βοῶντος ἐν τῇ ἐρήμῳ"],
                   ["sblgnt:MRK.1.3"], "nt", translate=True)
    lexical_result(store, tmp_path, "english-retrieval-agent", "web", ["voice of one crying in the wilderness"],
                   ["web:MRK.1.3"], "nt")
    runs.save(results.pack_xrefs("nt", ["MRK.1.3"], store, limit=10), runs.run_dir("nt") / "cross-reference-agent.json")
    lexical_result(store, tmp_path, "hebrew-specialist-agent", "oshb_wlc", ["קול קורא במדבר"],
                   ["oshb_wlc:Isa.40.3"], "nt/xref", translate=True)
    answer = runs.pack_answer("nt", synthesis("nt", ["MRK.1.3", "ISA.40.3"]), store)
    assert answer["passages"][1]["referenced_by"] == ["MRK.1.3"]
    assert any(l["to"] == "ISA.40.3" and l["relation"] == "verified" for l in answer["passages"][0]["cross_refs"])
    assert validate(answer, store, "nt")["valid"]
    md = runs.render(answer)
    nt_greek = md.index("New Testament Greek: SBLGNT")
    ot_section = md.index("Old Testament reference of Mark 1:3: Isaiah 40:3 (verified")
    assert nt_greek < md.index("English: WEB (web:MRK.1.3)") < ot_section < md.index("Hebrew: OSHB/WLC")
