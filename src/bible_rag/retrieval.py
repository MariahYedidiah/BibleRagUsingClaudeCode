"""Hybrid retrieval: vector + lexical search for every query variant, fused by rank.

    queries ──────┬─ normalize + embed ─> vector search (Chroma) ─┐
                  └─ fold ──────────────> BM25 search (SQLite) ───┼─> RRF ─> dedupe ─> top k
    lexical_queries ─ fold ─────────────> BM25 search (SQLite) ───┘        ─> records from SQLite

Scores from different lists can't be compared (cosine vs BM25), so lists are merged by rank
with reciprocal rank fusion. Every result keeps which query and method found it, at what rank
and score, so agents and the validator can see why it was retrieved.
"""

import re

from bible_rag.text import normalize

RRF_K = 60  # standard constant (Cormack et al., 2009); damps the weight of the very top ranks
MODES = ("hybrid", "vector", "lexical")


def detect_language(text):
    if re.search("[֐-׿]", text):
        return "he"
    if re.search("[Ͱ-Ͽἀ-῿]", text):
        return "grc"
    return "en"


def rrf(rankings, k=RRF_K):
    """Fuse ranked lists of verse_uids: score = sum over lists of 1 / (k + rank).

    Returns [(verse_uid, score)], best first. A uid repeated within one list counts once.
    """
    scores = {}
    for ranking in rankings:
        for rank, uid in enumerate(dict.fromkeys(ranking), 1):
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


def signals(lists, fused):
    """Raw retrieval evidence. Confidence levels are calibrated from these on golden queries."""
    vector = [hits for _, method, hits in lists if method == "vector" and hits]
    lexical = [hits for _, method, hits in lists if method == "lexical" and hits]
    best = max(vector, key=lambda hits: hits[0]["score"], default=[])
    top = fused[0][0] if fused else None
    vector_top10 = {h["verse_uid"] for hits in vector for h in hits[:10]}
    lexical_top10 = {h["verse_uid"] for hits in lexical for h in hits[:10]}
    return {
        "top_vector_score": best[0]["score"] if best else None,
        "vector_margin": round(best[0]["score"] - best[1]["score"], 4) if len(best) > 1 else None,
        "vector_lexical_overlap_top10": len(vector_top10 & lexical_top10),
        "lists": len(lists),
        "lists_with_hits": len(vector) + len(lexical),
        "lists_containing_top_result": sum(
            1 for _, _, hits in lists if any(h["verse_uid"] == top for h in hits)),
    }


class Retriever:
    def __init__(self, store, vectors=None, embed=None):
        """`embed` maps a list of texts to a list of normalized vectors."""
        self.store = store
        self.vectors = vectors
        self.embed = embed

    def search(self, queries, filters=None, k=10, lexical_queries=(), mode="hybrid",
               candidates=30, context=0):
        """Hybrid search. `queries` are natural-language variants (vector + lexical);
        `lexical_queries` are lexical only, e.g. Hebrew or Greek terms from a translation skill.
        """
        queries = [q.strip() for q in ([queries] if isinstance(queries, str) else queries) if q.strip()]
        lexical_queries = [q.strip() for q in lexical_queries if q.strip()]
        filters = {key: value for key, value in (filters or {}).items() if value is not None}
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        if not queries and not lexical_queries:
            raise ValueError("no query given")
        if mode != "lexical" and queries and (self.vectors is None or self.embed is None):
            raise ValueError("vector search is unavailable here; use the retrieval service")

        lists = []  # (query, method, hits)
        if mode != "lexical" and queries:
            vecs = self.embed([normalize(q, detect_language(q)) for q in queries])
            for query, vec in zip(queries, vecs):
                lists.append((query, "vector", self.vectors.search(vec, filters, candidates)))
        if mode != "vector":
            for query in dict.fromkeys(queries + lexical_queries):
                lists.append((query, "lexical", self.store.lexical(query, filters, candidates)))

        fused = rrf([h["verse_uid"] for h in hits] for _, _, hits in lists)[:k]
        records = self.store.get([uid for uid, _ in fused])
        hits_by_uid = {}
        for query, method, hits in lists:
            for h in hits:
                hits_by_uid.setdefault(h["verse_uid"], []).append(
                    {"query": query, "method": method, "rank": h["rank"], "score": h["score"]})

        results, missing = [], []
        for uid, score in fused:
            record = records.get(uid)
            if record is None:  # in Chroma but not in SQLite: the two indexes are out of sync
                missing.append(uid)
                continue
            hits = hits_by_uid[uid]
            result = {"rank": len(results) + 1, "rrf": round(score, 5), **record,
                      "found_by": sorted({h["method"] for h in hits}), "hits": hits}
            if context:
                result["context"] = [
                    {"verse_uid": r["verse_uid"], "verse": r["verse"], "text_display": r["text_display"]}
                    for r in self.store.context(uid, context, context)]
            results.append(result)

        return {"queries": queries, "lexical_queries": lexical_queries, "filters": filters,
                "mode": mode, "results": results, "missing": missing,
                "signals": signals(lists, fused)}
