"""Phase 7 evaluation: retrieval recall per corpus, and property checks on golden-query runs.

    bible-rag eval retrieval [--k 10] [--out FILE]   recall and signals per corpus (needs the service)
    bible-rag eval run RUN --golden NAME             check a finished run against a golden query

Golden runs vary between executions, so `check_run` checks properties (expected references,
labels, flags, trace shape), never exact text.
"""

import json
import re
from pathlib import Path
from statistics import median

from bible_rag import runs
from bible_rag.validator import validate

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval"
CORPORA = {"OT": ["web", "oshb_wlc", "lxx_swete"], "NT": ["web", "sblgnt"],
           "both": ["web", "oshb_wlc", "lxx_swete", "sblgnt"]}
SECTION_LABELS = {"web": "English: WEB", "oshb_wlc": "Hebrew: OSHB/WLC",
                  "lxx_swete": "Septuagint Greek: Swete LXX", "sblgnt": "New Testament Greek: SBLGNT"}
MT_LABEL = re.compile(r"^\*\*.+ → English \(machine translation, claude:[\w.:-]+\)\*\*$", re.M)


def load_cases(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


# --- retrieval --------------------------------------------------------------------------

def retrieval(cases, search, store, k=10, modes=("vector", "hybrid")):
    """Rank of the first expected verse in each corpus of the case's testament.

    `search(request) -> response` is the service's /search (injected so tests can fake it).
    A corpus that has none of the expected verses (Swete has no Ecclesiastes) is skipped.
    """
    rows = []
    for case in cases:
        expected = set(case.get("expected", []))
        for corpus in CORPORA[case["testament"]]:
            if expected and not any(store.by_ref(ref, {"source": corpus}) for ref in expected):
                continue
            for mode in modes:
                filters = {"source": corpus}
                if case["testament"] != "both":
                    filters["testament"] = case["testament"]
                out = search({"queries": [case["query"]], "filters": filters, "k": k,
                              "candidates": max(30, k), "mode": mode})
                refs = [r["canon_ref"] for r in out["results"]]
                rank = next((i for i, ref in enumerate(refs, 1) if ref in expected), None)
                rows.append({"query": case["query"], "kind": case["kind"], "corpus": corpus,
                             "mode": mode, "rank": rank, "top": refs[0] if refs else None,
                             "top_vector_score": out["signals"]["top_vector_score"],
                             "vector_margin": out["signals"]["vector_margin"]})
    return {"k": k, "summary": summarize(rows, k), "rows": rows}


def summarize(rows, k):
    out = {}
    for row in rows:
        group = "off_topic" if row["kind"] == "off_topic" else f'{row["corpus"]}/{row["mode"]}'
        out.setdefault(group, []).append(row)
    summary = {}
    for group, items in sorted(out.items()):
        scores = [r["top_vector_score"] for r in items if r["top_vector_score"] is not None]
        entry = {"n": len(items), "top_vector_score_median": round(median(scores), 4) if scores else None,
                 "top_vector_score_min": min(scores, default=None),
                 "top_vector_score_max": max(scores, default=None)}
        if group != "off_topic":
            ranks = [r["rank"] for r in items]
            entry.update({
                "recall@1": round(sum(1 for r in ranks if r == 1) / len(ranks), 3),
                "recall@5": round(sum(1 for r in ranks if r and r <= 5) / len(ranks), 3),
                f"recall@{k}": round(sum(1 for r in ranks if r) / len(ranks), 3),
                "mrr": round(sum(1 / r for r in ranks if r) / len(ranks), 3),
                "misses": [r["query"] for r in items if not r["rank"]]})
        summary[group] = entry
    return summary


# --- golden-query runs ------------------------------------------------------------------

def check_run(run_id, golden, store):
    """Property checks for a finished run. Returns {"golden", "run_id", "passed", "checks": [...]}."""
    d = runs.run_dir(run_id)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    answer = runs.load(d / "answer.json") if (d / "answer.json").exists() else None
    md = (d / "answer.md").read_text(encoding="utf-8") if (d / "answer.md").exists() else ""
    trace = runs.load(d / "trace.json")["events"]
    analysis = runs.load(d / "analysis.json") if (d / "analysis.json").exists() else {}
    results = runs.specialist_results(run_id)

    check("answer exists", answer is not None)
    if answer is None:
        return {"golden": golden["name"], "run_id": run_id, "passed": False, "checks": checks}
    v = validate(answer, store, run_id)
    check("validator passes", v["valid"], "; ".join(e["message"] for e in v["errors"]))

    kept = {}
    for _, r in results:
        for p in r["passages"]:
            kept.setdefault(p["canon_ref"], set()).add(p["source"])
    for ref, sources in golden.get("expect_refs", {}).items():
        got = kept.get(ref, set())
        check(f"{ref} kept from {', '.join(sources)}", set(sources) <= got,
              f"kept from {', '.join(sorted(got)) or 'nothing'}")
        check(f"{ref} shown in the answer", any(p["canon_ref"] == ref for p in answer["passages"]))

    shown = answer["passages"]
    for p in shown:
        for t in p["texts"]:
            if t["kind"] != "machine_translation":
                label = SECTION_LABELS[t["source"]]
                check(f'{p["canon_ref"]}: {t["source"]} section labeled',
                      f'**{label} ({t["verse_uid"]})**' in md, label)
    mt = sum(1 for p in shown for t in p["texts"] if t["kind"] == "machine_translation")
    check("machine translations flagged", len(MT_LABEL.findall(md)) == mt and
          all(t.get("translator") for p in shown for t in p["texts"] if t["kind"] == "machine_translation"),
          f"{mt} machine translations, {len(MT_LABEL.findall(md))} labeled")

    for link in golden.get("expect_links", []):
        found = [l for r in runs.xref_results(run_id) for e in r["entries"] if e["from_ref"] in link["from"]
                 for l in e["links"] if l["to"] == link["to"] and l["relation"] == link["relation"]]
        check(f'{link["relation"]} link {"/".join(link["from"])} → {link["to"]}', found)

    delegated = [e for e in trace if e["event"] == "delegate"]
    agents = {e["agent"] for e in delegated}
    for agent in golden.get("expect_agents", []):
        check(f"{agent} delegated", agent in agents)
    for group, size in golden.get("expect_parallel", {}).items():
        n = len({e["agent"] for e in delegated if e.get("group") == group})
        check(f"parallel group {group} has ≥ {size} agents", n >= size, f"{n} agents")

    if "min_variants" in golden:
        n = len(analysis.get("queries", []))
        check(f'≥ {golden["min_variants"]} query variants', n >= golden["min_variants"], f"{n} variants")
    if "min_variants_with_evidence" in golden:
        used = {h["query"] for _, r in results for p in r["passages"] for h in p.get("hits", [])
                if h["query"] in analysis.get("queries", [])}
        check(f'kept evidence from ≥ {golden["min_variants_with_evidence"]} variants',
              len(used) >= golden["min_variants_with_evidence"], f"{len(used)} variants")

    level = answer["confidence"]["level"]
    if "expect_confidence" in golden:
        check(f'confidence in {golden["expect_confidence"]}', level in golden["expect_confidence"], level)
    if golden.get("expect_retry"):
        check("fallback round recorded", any(e["event"] == "retry" for e in trace)
              and (d / "r2").is_dir())
    if golden.get("expect_insufficient"):
        check("no passages shown", not answer["passages"], f'{len(answer["passages"])} shown')
        check("asks a clarifying question", bool(answer.get("clarifying_question")))

    return {"golden": golden["name"], "run_id": run_id, "passed": all(c["passed"] for c in checks),
            "checks": checks}
