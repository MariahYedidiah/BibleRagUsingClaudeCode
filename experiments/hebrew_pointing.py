"""Does bge-m3 retrieve Hebrew better from pointed or unpointed text?

Pointed Hebrew (with vowel points, as indexed) tokenizes into single letters and marks; unpointed
text gets whole-word tokens. This compares both on the same pool of verses: every Hebrew verse
expected by an OT case in eval/retrieval_cases.json plus a fixed random sample of the others.
Pointed vectors come from the embedding cache; unpointed ones are embedded here (a few minutes).

    uv run python experiments/hebrew_pointing.py [--pool 4000]

Needs the model, so run it while the retrieval service is stopped (two copies don't fit in RAM).
Writes eval/results/hebrew_pointing.json.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index  # noqa: E402
from bible_rag.text import fold, normalize  # noqa: E402


def ranks(query_vecs, pool_vecs, pool_refs, cases):
    scores = query_vecs @ pool_vecs.T
    out = []
    for case, row in zip(cases, scores):
        order = np.argsort(-row)
        refs = [pool_refs[i] for i in order[:50]]
        expected = set(case.get("expected", []))
        rank = next((i for i, ref in enumerate(refs, 1) if ref in expected), None)
        out.append({"query": case["query"], "kind": case["kind"], "rank": rank,
                    "top_score": round(float(row[order[0]]), 4)})
    return out


def summary(rows):
    on = [r for r in rows if r["kind"] != "off_topic"]
    off = [r for r in rows if r["kind"] == "off_topic"]
    n = len(on)
    return {"n": n,
            "recall@1": round(sum(r["rank"] == 1 for r in on) / n, 3),
            "recall@5": round(sum(bool(r["rank"]) and r["rank"] <= 5 for r in on) / n, 3),
            "recall@10": round(sum(bool(r["rank"]) and r["rank"] <= 10 for r in on) / n, 3),
            "mrr": round(sum(1 / r["rank"] for r in on if r["rank"]) / n, 3),
            "correct_top_score_min": min((r["top_score"] for r in on if r["rank"] == 1), default=None),
            "off_topic_top_score_max": max((r["top_score"] for r in off), default=None)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", type=int, default=4000, help="random non-target verses in the pool")
    args = ap.parse_args()

    cases = json.loads((ROOT / "eval" / "retrieval_cases.json").read_text(encoding="utf-8"))["cases"]
    cases = [c for c in cases if c["testament"] in ("OT", "both")]
    expected = {ref for c in cases for ref in c.get("expected", [])}

    df = pd.read_parquet(build_index.PARQUET, columns=["verse_uid", "source", "canon_ref", "text_norm"])
    he = df[df["source"] == "oshb_wlc"].reset_index(drop=True)
    targets = he[he["canon_ref"].isin(expected)]
    others = he[~he["canon_ref"].isin(expected)].sample(args.pool, random_state=0)
    pool = pd.concat([targets, others]).reset_index(drop=True)
    print(f"pool: {len(pool):,} Hebrew verses ({len(targets)} targets)")

    cache = build_index.EMB_ROOT / build_index.MODEL.replace("/", "__")
    keys = dict(zip(build_index.cache_key(pool), range(len(pool))))
    pointed = np.zeros((len(pool), 1024), dtype=np.float32)
    found = 0
    for path in sorted(cache.glob("part-*.parquet")):
        t = pq.read_table(path).to_pydict()
        for key, vec in zip(t["key"], t["embedding"]):
            if key in keys:
                pointed[keys[key]] = vec
                found += 1
    if found != len(pool):
        sys.exit(f"only {found} of {len(pool)} pointed vectors are cached; run build_index.py first")

    model = build_index.load_model()
    unpointed = model.encode([fold(t) for t in pool["text_norm"]], batch_size=32,
                             normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=True)
    queries = model.encode([normalize(c["query"], "en") for c in cases], normalize_embeddings=True,
                           convert_to_numpy=True)

    refs = pool["canon_ref"].tolist()
    result = {}
    for name, vecs in (("pointed", pointed), ("unpointed", unpointed)):
        rows = ranks(queries, vecs, refs, cases)
        result[name] = {"summary": summary(rows), "rows": rows}
    out = ROOT / "eval" / "results" / "hebrew_pointing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pool": len(pool), **result}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in result.items()}, indent=1))


if __name__ == "__main__":
    main()
