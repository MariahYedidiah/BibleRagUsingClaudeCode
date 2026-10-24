"""One question = one run folder under runs/<run_id>/. Everything an agent produces lands there:

    analysis.json                    leader's query analysis
    trace.json                       who was delegated what, in parallel or in sequence (demo mode)
    <agent>.json                     specialist / cross-reference results (sub-folders for later
                                     rounds, e.g. xref/ for verified OT references, r2/ for a retry)
    confidence.json                  computed from the specialist results
    synthesis.json                   synthesis agent's prose and passage picks
    answer.json / answer.md          assembled, validated, rendered answer
"""

import json
import re
from datetime import datetime
from pathlib import Path

from bible_rag.books import testament as testament_of
from bible_rag.config import ROOT
from bible_rag.schemas import SPECIALIST_CORPUS

RUNS = ROOT / "runs"
ALIGN_ORDER = {"mapped": 0, "partial": 1, "unmapped": 2}
LANG = {"web": "en", "oshb_wlc": "he", "lxx_swete": "grc", "sblgnt": "grc"}
CORPUS_NAME = {"web": "English: WEB", "oshb_wlc": "Hebrew: OSHB/WLC",
               "lxx_swete": "Septuagint Greek: Swete LXX", "sblgnt": "New Testament Greek: SBLGNT"}
# Presentation order of the corpora for each testament (docs/agent-system-prompt.md §6).
ORDER = {"OT": ["web", "oshb_wlc", "lxx_swete"], "DC": ["lxx_swete", "web"],
         "NT": ["sblgnt", "web"]}
AGENT_FOR = {corpus: agent for agent, corpus in SPECIALIST_CORPUS.items()}
# Top cosine that off-topic questions reach in each corpus, rounded up (`bible-rag eval retrieval`,
# 2026-10-24: off-topic max web 0.544, oshb 0.514, lxx 0.512, sblgnt 0.492; the lowest correct
# top hit was 0.655, 0.518, 0.538 and 0.642). A kept passage whose best vector score is below
# its corpus's floor looks no better than what an off-topic question retrieves.
VECTOR_FLOOR = {"web": 0.60, "oshb_wlc": 0.53, "lxx_swete": 0.53, "sblgnt": 0.55}


def run_dir(run_id):
    return RUNS / run_id


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# --- run folder and trace ---------------------------------------------------------------

def new_run(question, run_id=None):
    if not run_id:
        slug = "-".join(re.findall(r"[a-z0-9]+", question.lower())[:5]) or "question"
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    d = run_dir(run_id)
    if (d / "trace.json").exists():
        raise ValueError(f"run {run_id} already exists")
    save({"run_id": run_id, "question": question, "started": now(), "events": []}, d / "trace.json")
    return {"run_id": run_id, "dir": str(d)}


def now():
    return datetime.now().isoformat(timespec="seconds")


def trace(run_id, event, agent, group=None, detail=None, path=None, status=None):
    """Append one event. `group` ties together delegations sent in parallel."""
    f = run_dir(run_id) / "trace.json"
    t = load(f)
    entry = {"t": now(), "event": event, "agent": agent}
    entry.update({k: v for k, v in (("group", group), ("detail", detail), ("path", path),
                                     ("status", status)) if v is not None})
    t["events"].append(entry)
    save(t, f)
    return entry


def show(run_id):
    """Human-readable trace and file list for demo mode."""
    d = run_dir(run_id)
    t = load(d / "trace.json")
    lines = [f"# Run {run_id}", "", f"Question: {t['question']}", "", "## Trace", ""]
    groups = {}
    for e in t["events"]:
        if e.get("group"):
            groups.setdefault(e["group"], set()).add(e["agent"])
    for e in t["events"]:
        par = ""
        if e.get("group") and len(groups[e["group"]]) > 1:
            par = f" [parallel group {e['group']}: {len(groups[e['group']])} agents]"
        extra = " ".join(f"{k}={e[k]}" for k in ("status", "path") if k in e)
        lines.append(f"- {e['t'][11:]}  {e['event']:<9} {e['agent']}{par}  {e.get('detail', '')} {extra}".rstrip())
    lines += ["", "## Files", ""]
    lines += [f"- {p.relative_to(d).as_posix()}" for p in sorted(d.rglob("*.json"))]
    return "\n".join(lines)


# --- collecting results -----------------------------------------------------------------

def specialist_results(run_id):
    """All specialist results of a run, in every round folder: [(path, result)]."""
    d = run_dir(run_id)
    out = []
    for agent in SPECIALIST_CORPUS:
        out += [(p, load(p)) for p in sorted(d.rglob(f"{agent}.json"))]
    return out


def xref_results(run_id):
    return [load(p) for p in sorted(run_dir(run_id).rglob("cross-reference-agent.json"))]


# --- confidence -------------------------------------------------------------------------

def confidence(run_id):
    """Confidence from measurable agreement, never from an LLM's own estimate.

    insufficient  no specialist kept any passage
    high          >= 2 references kept in two or more languages, and >= 1 passage found by
                  both vector and lexical search
    medium        >= 1 reference kept in two or more languages, or >= 2 passages found by both
    low           anything else, or (with vector search up) no kept passage reaches its
                  corpus's VECTOR_FLOOR and none is a requested reference
    Calibrated on the golden queries and `bible-rag eval retrieval` (docs/evaluation.md).
    """
    langs, both, kept, down, top, strong, variants = {}, 0, 0, False, None, 0, {}
    for _, r in specialist_results(run_id):
        down |= r["service"] == "down"
        for p in r["passages"]:
            kept += 1
            vector = [h["score"] for h in p.get("hits", []) if h["method"] == "vector"]
            if p["found_by"] == ["reference"] or max(vector, default=0.0) >= VECTOR_FLOOR[p["source"]]:
                strong += 1
            if vector:
                top = max(top or 0.0, *vector)
            for h in p.get("hits", []):
                variants.setdefault(p["verse_uid"], set()).add(h["query"])
            if p["canon_ref"].endswith(".0"):
                continue
            langs.setdefault(p["canon_ref"], set()).add(LANG[p["source"]])
            if {"vector", "lexical"} <= set(p["found_by"]):
                both += 1
    cross = sorted(ref for ref, ls in langs.items() if len(ls) >= 2)
    weak = not down and kept and not strong
    if kept == 0:
        level = "insufficient"
    elif weak:
        level = "low"
    elif len(cross) >= 2 and both >= 1:
        level = "high"
    elif cross or both >= 2:
        level = "medium"
    else:
        level = "low"
    signals = {"passages_kept": kept, "cross_lingual_refs": cross, "found_by_both_methods": both,
               "above_vector_floor": strong, "found_by_two_or_more_queries":
               sum(1 for qs in variants.values() if len(qs) >= 2),
               "top_vector_score": top, "vector_search_available": not down}
    basis = (f"{kept} passages kept; {len(cross)} references found in two or more languages; "
             f"{both} passages found by both vector and lexical search"
             + ("; no kept passage scores above what off-topic questions retrieve" if weak else "")
             + ("; vector search was unavailable (lexical only)" if down else ""))
    return {"level": level, "basis": basis, "signals": signals}


# --- answer assembly --------------------------------------------------------------------

def pack_answer(run_id, synthesis, store):
    """Answer dict from the synthesis draft and the verified specialist results."""
    from bible_rag.validator import display_ref

    d = run_dir(run_id)
    analysis = load(d / "analysis.json") if (d / "analysis.json").exists() else {}
    question = analysis.get("question") or load(d / "trace.json")["question"]

    kept = {}  # canon_ref -> {source: passage}
    for _, r in specialist_results(run_id):
        for p in r["passages"]:
            kept.setdefault(p["canon_ref"], {}).setdefault(p["source"], p)
    links, referenced_by = {}, {}
    for x in xref_results(run_id):
        for entry in x["entries"]:
            links.setdefault(entry["from_ref"], []).extend(entry["links"])
            for link in entry["links"]:
                if link["relation"] == "verified":
                    referenced_by.setdefault(link["to"], []).append(entry["from_ref"])

    passages = []
    for pick in synthesis["passages"]:
        ref = pick["canon_ref"]
        if ref not in kept:
            raise ValueError(f"{ref} was not retrieved by any specialist; it can't be shown")
        testament = testament_of(ref.split(".")[0])
        texts, missing, retrieval, worst = [], [], {}, "mapped"
        for source in ORDER[testament]:
            p = kept[ref].get(source)
            if p is None:
                missing.append({"field": source, "reason": f"not retrieved by {AGENT_FOR[source]}"})
                continue
            row = store.get([p["verse_uid"]])[p["verse_uid"]]
            kind = "established_translation" if source == "web" else "original"
            texts.append({"kind": kind, "source": source, "language": row["language"],
                          "text": row["text_display"], "verse_uid": row["verse_uid"]})
            t = p.get("translation")
            if t:
                notes = t.get("uncertainties", []) + t.get("differences_from_web", [])
                texts.append({"kind": "machine_translation", "source": source, "language": "en",
                              "text": t["translation"], "translates": row["verse_uid"],
                              "translator": t["translator"], "notes": "; ".join(notes) or None})
            elif source != "web":
                missing.append({"field": f"{source} translation", "reason": "no machine translation produced"})
            retrieval[source] = {"found_by": p["found_by"], "rrf": p.get("rrf"), "relevance": p["relevance"]}
            if ALIGN_ORDER[row["alignment"]] > ALIGN_ORDER[worst]:
                worst = row["alignment"]
        passages.append({
            "canon_ref": ref, "display_ref": display_ref(ref), "testament": testament,
            "alignment": worst, "texts": texts, "retrieval": retrieval,
            "cross_refs": [{"to": l["to"], "relation": l["relation"], "dataset": l["dataset"],
                            "votes": l["votes"], "note": l.get("note")} for l in links.get(ref, [])],
            "referenced_by": sorted(set(referenced_by.get(ref, []))),
            "note": pick["note"], "missing": missing,
        })

    return {"question": question, "answer": synthesis["answer"], "passages": passages,
            "confidence": confidence(run_id), "clarifying_question": synthesis.get("clarifying_question"),
            "run_id": run_id}


# --- rendering --------------------------------------------------------------------------

def render(answer):
    """answer.md: the prose, then every passage in the spec's section order, every text labeled."""
    c = answer["confidence"]
    out = [f"# {answer['question']}", "", answer["answer"], "",
           f"**Evidence confidence: {c['level']}**: {c['basis']}.", ""]
    if answer.get("clarifying_question"):
        out += [f"> **Clarifying question:** {answer['clarifying_question']}", ""]
    by_ref = {p["canon_ref"]: p for p in answer["passages"]}
    shown = set()
    primary = [p for p in answer["passages"] if not p["referenced_by"]] + \
              [p for p in answer["passages"] if p["referenced_by"] and not
               any(r in by_ref for r in p["referenced_by"])]
    for p in primary:
        out += render_passage(p, level=2)
        shown.add(p["canon_ref"])
        verified = [l for l in p["cross_refs"] if l["relation"] == "verified"]
        for link in verified:
            target = by_ref.get(link["to"])
            if target and link["to"] not in shown:
                out += [f"#### Old Testament reference of {p['display_ref']}: {target['display_ref']} "
                        f"(verified, {link['votes']} votes, {link['dataset']})", ""]
                out += render_passage(target, level=4, heading=False)
                shown.add(link["to"])
        others = [l for l in p["cross_refs"] if l["relation"] != "verified"]
        if others:
            out += ["*Other links (unverified):* " + "; ".join(
                f"{l['to']} ({l['relation'].replace('_', ' ')}, {l['votes']} votes)" for l in others), ""]
    out += ["---", "", "*Machine translations are generated by Claude and labeled as such; WEB is the "
            "World English Bible (public domain). Sources and licenses: docs/data-sources.md.*"]
    return "\n".join(out)


def render_passage(p, level=2, heading=True):
    out = []
    if heading:
        out += [f"{'#' * level} {p['display_ref']} ({p['canon_ref']})", ""]
    if p.get("note"):
        out += [f"*{p['note']}*", ""]
    if p["alignment"] != "mapped":
        out += [f"*Verse numbering alignment: {p['alignment']}.*", ""]
    for t in p["texts"]:
        if t["kind"] == "machine_translation":
            label = f"{CORPUS_NAME[t['source']].split(':')[0]} → English (machine translation, {t['translator']})"
        else:
            label = CORPUS_NAME[t["source"]] + f" ({t['verse_uid']})"
        out += [f"**{label}**", "", f"> {t['text']}", ""]
        if t.get("notes"):
            out += [f"<sub>Notes: {t['notes']}</sub>", ""]
    for m in p.get("missing", []):
        out += [f"*{m['field']}: {m['reason']}.*", ""]
    return out
