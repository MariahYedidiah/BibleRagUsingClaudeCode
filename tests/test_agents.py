"""Phase 5: specialist agent definitions, `bible-rag pack`, and the result checks."""

import json
import re
from pathlib import Path

import pytest

from bible_rag import results
from bible_rag.retrieval import Retriever
from bible_rag.store import VerseStore
from bible_rag.validator import validate_specialist, validate_xrefs

AGENTS = Path(__file__).resolve().parents[1] / ".claude" / "agents"
SPECIALISTS = {
    "english-retrieval-agent": ("web", []),
    "hebrew-specialist-agent": ("oshb_wlc", ["english-to-hebrew", "hebrew-to-english"]),
    "septuagint-specialist-agent": ("lxx_swete", ["english-to-greek", "greek-to-english"]),
    "greek-new-testament-agent": ("sblgnt", ["english-to-greek", "greek-to-english"]),
}


@pytest.fixture(scope="module")
def store(db):
    store = VerseStore()
    if not store.con.execute("SELECT 1 FROM sqlite_master WHERE name = 'cross_refs'").fetchone():
        pytest.skip("verses.db predates phase 3")
    return store


def definition(name):
    body = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", body, re.S)
    assert m, f"{name}: missing frontmatter"
    head = m.group(1)
    fields = dict(re.findall(r"^([\w-]+):\s*(.*)$", head, re.M))
    skills = re.findall(r"^\s+-\s+(\S+)$", head, re.M)
    return fields, skills, body


# --- definitions ------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(SPECIALISTS))
def test_specialist_definition(name):
    corpus, expected_skills = SPECIALISTS[name]
    fields, skills, body = definition(name)
    assert fields["name"] == name
    assert fields["model"] in {"haiku", "sonnet"}
    assert {"Bash", "Read", "Write"} <= {t.strip() for t in fields["tools"].split(",")}
    assert sorted(skills) == sorted(expected_skills)
    assert f"--agent {name}" in body and f"runs/<run_id>/{name}.json" in body
    assert f"--source {corpus}" in body                 # searches only its own corpus
    assert "bible-rag health" in body and "--mode lexical" in body  # service-down fallback
    assert "## Never" in body and "Reply with **only**" in body


def test_cross_reference_definition():
    fields, skills, body = definition("cross-reference-agent")
    assert fields["name"] == "cross-reference-agent" and skills == []
    assert "bible-rag pack xrefs" in body and "never upgrade" in body.lower()


def test_project_settings_allow_the_cli():
    settings = json.loads((AGENTS.parent / "settings.json").read_text(encoding="utf-8"))
    assert "Bash(uv run bible-rag *)" in settings["permissions"]["allow"]


# --- pack specialist --------------------------------------------------------------------

@pytest.fixture()
def search_file(tmp_path, store):
    out = Retriever(store).search([], {"source": "oshb_wlc"}, k=8, mode="lexical",
                                  lexical_queries=["רחמיו רחמיך ירחם רחום וחנון"])
    path = tmp_path / "search.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return path


def pack(store, search_file, keep, **kw):
    return results.pack_specialist("hebrew-specialist-agent", "t", "oshb_wlc", [search_file],
                                   {"keep": keep}, store, **kw)


def codes(result):
    return [e["code"] for e in result["errors"]]


def test_pack_copies_text_and_evidence(store, search_file):
    r = pack(store, search_file, [{"verse_uid": "oshb_wlc:Ps.103.8", "relevance": "compassion"}],
             context=1)
    p = r["passages"][0]
    assert p["text"] == store.get(["oshb_wlc:Ps.103.8"])["oshb_wlc:Ps.103.8"]["text_display"]
    assert p["found_by"] == ["lexical"] and p["hits"] and p["rrf"]
    assert [c["verse"] for c in p["context"]] == [7, 8, 9]
    assert r["service"] == "down"  # lexical-only search
    result = validate_specialist(r, store)
    assert result["valid"] and {w["code"] for w in result["warnings"]} == {"untranslated", "lexical_only"}


def test_pack_resolves_references(store, search_file):
    r = pack(store, search_file, [{"canon_ref": "isa.40.3", "relevance": "verified OT target"}])
    p = r["passages"][0]
    assert p["verse_uid"] == "oshb_wlc:Isa.40.3" and p["found_by"] == ["reference"]


def test_pack_rejects_unknown_references(store, search_file):
    with pytest.raises(ValueError):
        pack(store, search_file, [{"canon_ref": "ISA.99.1", "relevance": "x"}])


def test_pack_attaches_translations(tmp_path, store, search_file):
    uid = "oshb_wlc:Ps.103.8"
    t = {"canon_ref": "PSA.103.8", "verse_uid": uid, "source": "oshb_wlc",
         "corpus_label": "Hebrew (OSHB/WLC)", "original": store.get([uid])[uid]["text_display"],
         "translation": "The LORD is compassionate and gracious.", "method": "machine",
         "translator": "claude:test", "_web_text": "ignored"}
    path = tmp_path / "t.json"
    path.write_text(json.dumps([t], ensure_ascii=False), encoding="utf-8")
    r = pack(store, search_file, [{"verse_uid": uid, "relevance": "compassion"}], translations=path)
    assert r["passages"][0]["translation"]["translation"].startswith("The LORD")
    assert "untranslated" not in [w["code"] for w in validate_specialist(r, store)["warnings"]]


def test_check_catches_tampering(store, search_file):
    r = pack(store, search_file, [{"verse_uid": "oshb_wlc:Ps.103.8", "relevance": "compassion"}])
    r["passages"][0]["text"] = "רחום וחנון יהוה"  # shortened "quote"
    assert codes(validate_specialist(r, store)) == ["text_mismatch"]


def test_check_catches_other_corpus(store, search_file):
    r = pack(store, search_file, [{"verse_uid": "oshb_wlc:Ps.103.8", "relevance": "compassion"}])
    web = store.get(["web:PSA.103.8"])["web:PSA.103.8"]
    r["passages"][0].update(verse_uid="web:PSA.103.8", source="web", language="en", text=web["text_display"])
    assert "wrong_corpus" in codes(validate_specialist(r, store))
    r = pack(store, search_file, [])
    r["corpus"] = "web"
    assert codes(validate_specialist(r, store)) == ["wrong_corpus"]


def test_check_requires_a_relevance_reason(store, search_file):
    r = pack(store, search_file, [{"verse_uid": "oshb_wlc:Ps.103.8"}])
    assert codes(validate_specialist(r, store)) == ["schema"]


def test_empty_result_must_explain(store, search_file):
    r = pack(store, search_file, [])
    assert [w["code"] for w in validate_specialist(r, store)["warnings"]] == ["empty", "lexical_only"]


# --- pack xrefs -------------------------------------------------------------------------

def test_pack_xrefs_finds_the_quotation(store):
    r = results.pack_xrefs("t", ["mrk.1.3", "JHN.1.23"], store, limit=10)
    assert r["verified_targets"] == ["ISA.40.3"]
    assert validate_xrefs(r, store) == {"valid": True, "errors": [], "warnings": []}


def test_downgrade_needs_a_note_and_upgrades_are_refused(store):
    adjust = {"downgrade": [{"from": "MRK.1.3", "to": "ISA.40.3", "relation": "thematic",
                             "note": "test downgrade"}]}
    r = results.pack_xrefs("t", ["MRK.1.3"], store, limit=10, adjust=adjust)
    assert r["verified_targets"] == [] and validate_xrefs(r, store)["valid"]

    r["entries"][0]["links"][0]["note"] = None
    assert "unexplained_downgrade" in codes(validate_xrefs(r, store))

    weak = next(l for e in results.pack_xrefs("t", ["MRK.1.3"], store, testament="NT")["entries"]
                for l in e["links"] if l["relation"] == "possible_allusion")
    with pytest.raises(ValueError):
        results.pack_xrefs("t", ["MRK.1.3"], store, testament="NT", adjust={"downgrade": [
            {"from": "MRK.1.3", "to": weak["to"], "relation": "verified", "note": "upgrade"}]})


def test_check_rejects_invented_links_and_votes(store):
    r = results.pack_xrefs("t", ["MRK.1.3"], store, limit=10)
    r["entries"][0]["links"].append({"to": "GEN.1.1", "votes": 99, "relation": "verified",
                                     "dataset": "openbible"})
    assert "unknown_cross_ref" in codes(validate_xrefs(r, store))
    r = results.pack_xrefs("t", ["MRK.1.3"], store, limit=10)
    r["entries"][0]["links"][0]["votes"] += 50
    r["verified_targets"] = []
    assert {"votes", "verified_targets"} <= set(codes(validate_xrefs(r, store)))
