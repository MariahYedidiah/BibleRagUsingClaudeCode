"""Assemble agent results from the verse store, so agents never copy scripture text themselves.

An agent decides *which* verses are relevant and why, in a small selection file without any
scripture text:

    {"keep": [{"verse_uid": "oshb_wlc:Ps.103.8", "relevance": "God is compassionate and gracious"},
              {"canon_ref": "ISA.40.3", "relevance": "verified OT reference of MRK.1.3"}],
     "discard": [{"verse_uid": "oshb_wlc:Amos.1.12", "reason": "בצרה here is the city Bozrah"}],
     "notes": ["..."], "missing": [{"field": "...", "reason": "..."}]}

`pack_specialist` then copies every text verbatim from the store and attaches the retrieval
evidence and the translations; `pack_xrefs` builds the cross-reference result from the
cross_refs table.
"""

import json
from pathlib import Path

from bible_rag.crossrefs import relation as relation_for_votes

RELATION_ORDER = {"thematic": 0, "possible_allusion": 1, "verified": 2}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pack_specialist(agent, run_id, corpus, search_files, selection, store, translations=None,
                    context=0, references=()):
    """SpecialistResult dict. Raises ValueError for selections the store can't resolve.

    A kept verse must be in one of the saved searches or be one of the delegation's
    `references`; anything else would be a verse chosen from memory, not retrieved.
    """
    references = {r.upper() for r in references}
    searches = [load_json(p) for p in search_files]
    hits, rrf = {}, {}
    queries, lexical_queries, signals, service = [], [], [], "down"
    for s in searches:
        queries += [q for q in s.get("queries", []) if q not in queries]
        lexical_queries += [q for q in s.get("lexical_queries", []) if q not in lexical_queries]
        signals.append(s.get("signals", {}))
        if s.get("mode") in ("hybrid", "vector"):
            service = "up"
        for r in s.get("results", []):
            hits.setdefault(r["verse_uid"], []).extend(r.get("hits", []))
            rrf[r["verse_uid"]] = max(rrf.get(r["verse_uid"], 0.0), r.get("rrf", 0.0))

    by_uid = {}
    if translations:
        items = load_json(translations)
        for t in items if isinstance(items, list) else [items]:
            if "error" not in t:
                by_uid[t["verse_uid"]] = {k: v for k, v in t.items() if not k.startswith("_")}

    passages, seen = [], set()
    for item in selection.get("keep", []):
        if item.get("verse_uid"):
            rows = list(store.get([item["verse_uid"]]).values())
        elif item.get("canon_ref"):
            rows = store.by_ref(item["canon_ref"].upper(), {"source": corpus})
        else:
            raise ValueError(f"keep item needs verse_uid or canon_ref: {item}")
        if not rows:
            raise ValueError(f"not in the verse store: {item.get('verse_uid') or item.get('canon_ref')}")
        for row in rows:
            uid = row["verse_uid"]
            if uid in seen:
                continue
            seen.add(uid)
            if uid not in hits and row["canon_ref"] not in references:
                raise ValueError(f"{uid} is not in any saved search and not one of the requested "
                                 f"references ({', '.join(sorted(references)) or 'none'}); keep only "
                                 f"retrieved verses, or search for it first")
            found = sorted({h["method"] for h in hits.get(uid, [])}) or ["reference"]
            passage = {
                "rank": len(passages) + 1, "canon_ref": row["canon_ref"], "verse_uid": uid,
                "source": row["source"], "language": row["language"], "testament": row["testament"],
                "edition": row["edition"], "alignment": row["alignment"], "text": row["text_display"],
                "found_by": found, "hits": hits.get(uid, []), "rrf": rrf.get(uid),
                "relevance": item.get("relevance", ""),
            }
            if context:
                passage["context"] = [
                    {"verse_uid": c["verse_uid"], "verse": c["verse"], "text_display": c["text_display"]}
                    for c in store.context(uid, context, context)]
            if uid in by_uid:
                passage["translation"] = by_uid[uid]
            passages.append(passage)

    return {
        "agent": agent, "run_id": run_id, "corpus": corpus, "queries": queries,
        "lexical_queries": lexical_queries, "service": service, "signals": signals,
        "passages": passages, "discarded": selection.get("discard", []),
        "missing": selection.get("missing", []), "notes": selection.get("notes", []),
    }


def pack_xrefs(run_id, refs, store, testament="OT", min_votes=None, limit=20, adjust=None):
    """CrossRefResult dict. `adjust` may only downgrade a link's relation, with a note."""
    adjustments = {(a["from"], a["to"]): a for a in (adjust or {}).get("downgrade", [])}
    entries, verified = [], []
    for ref in refs:
        ref = ref.upper()
        links = []
        for link in store.cross_refs(ref, min_votes, testament, limit):
            a = adjustments.get((ref, link["to"]))
            if a:
                if RELATION_ORDER[a["relation"]] > RELATION_ORDER[link["relation"]]:
                    raise ValueError(f"{ref} -> {link['to']}: relations can only be downgraded")
                link = {**link, "relation": a["relation"], "note": a.get("note")}
            links.append(link)
            if link["relation"] == "verified" and link["to"] not in verified:
                verified.append(link["to"])
        entries.append({"from_ref": ref, "links": links})
    return {"agent": "cross-reference-agent", "run_id": run_id, "entries": entries,
            "verified_targets": verified, "notes": (adjust or {}).get("notes", [])}


def write(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
