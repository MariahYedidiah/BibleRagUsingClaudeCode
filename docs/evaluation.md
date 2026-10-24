# Evaluation (phase 7)

Two kinds of evaluation, both reproducible from the repository:

| | What it measures | Command | Needs |
|---|---|---|---|
| **Retrieval benchmark** | recall of the right verse per corpus, and the similarity scores of on- vs off-topic questions | `uv run bible-rag eval retrieval --out eval/results/retrieval.json` | the retrieval service |
| **Golden queries** | the whole agent workflow on the five queries of `docs/agent-system-prompt.md` §13 | run the query with the leader, then `uv run bible-rag eval run <run_id> --golden <name>` | Claude Code (the agents); the check itself is offline |

Inputs: `eval/retrieval_cases.json` (41 English queries with the verses that answer them, plus 6 off-topic ones) and `eval/golden_queries.json` (the five golden queries with the properties each run must have). Results: `eval/results/`. Example runs: `runs/golden-*` (see `runs/README.md`). `tests/test_evaluation.py` re-checks every committed golden run offline.

## Retrieval benchmark

Each case is searched in every corpus of its testament (OT: WEB, Hebrew, LXX; NT: WEB, SBLGNT), filtered to that corpus, with English queries only. The rank is that of the first expected verse; a corpus without the verse is skipped (Swete has no Ecclesiastes). Results of 2026-10-24, after the WEB markup fix and the HNSW change below (k = 10):

| Corpus | n | recall@1 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|---|
| WEB, vector | 41 | 0.85 | 0.98 | 0.98 | 0.89 |
| WEB, hybrid | 41 | 0.85 | 0.98 | 0.98 | 0.91 |
| Swete LXX | 24 | 0.50 | 0.67 | 0.83 | 0.59 |
| SBLGNT | 16 | 0.38 | 0.69 | 0.69 | 0.50 |
| Hebrew (OSHB, pointed) | 25 | 0.16 | 0.36 | 0.44 | 0.25 |

- For Hebrew and Greek, hybrid equals vector here: English words never match Hebrew or Greek text. In a real run the specialists add Hebrew/Greek search terms from the `english-to-*` skills, so their recall is higher than this table.
- WEB misses: vector-only misses the paraphrase "Love the people around you as much as you love yourself" (Lev 19:18 ranks ~45; the verse is mostly about vengeance, and Matt 22:39, which quotes it, ranks 3); hybrid finds it at rank 1. Hybrid misses "Jesus cried when his friend died" (John 11:35, "Jesus wept."), which vector alone finds: BM25 matches on "cried", "died" and "friend" in longer verses push it out of the fused top 10.

### Hebrew: vowel points

bge-m3 splits pointed Hebrew into single letters and marks (77.5 tokens per verse vs 25.9 unpointed). `experiments/hebrew_pointing.py` compares both on the same pool: the 36 Hebrew verses the OT cases expect plus 4,000 random others, same 25 English queries (`eval/results/hebrew_pointing.json`):

| Hebrew embedded | recall@1 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|
| pointed (current index) | 0.36 | 0.56 | 0.60 | 0.44 |
| unpointed | **0.76** | **0.84** | **0.88** | **0.79** |

The numbers are higher than in the table above because the pool is 4,036 verses, not all 23,213. Switching would mean re-embedding the Hebrew verses from `fold(text_norm)`; display text, lexical search and translations would not change. The project keeps pointed embeddings until the owner decides otherwise (CLAUDE.md, "Known data issues").

### Index quality

Querying the collection with a verse's own stored vector should return that verse. With Chroma's default HNSW settings (16 neighbors, ef 100) that failed for ~2% of verses (e.g. SBLGNT John 3:16 returned Hebrew Gen 1:25 at distance 0.38): those verses were badly connected in the graph and hard to reach for any query. `build_index.py` now uses 32 neighbors and ef 200; on 1,000 random verses every miss left is a verse whose text is identical to another's (distance 0), so effective self-recall is 100%. This change alone raised Hebrew recall@10 from 0.32 to 0.44.

## Confidence calibration

`runs.confidence` combines measured agreement into levels (documented in its docstring). The benchmark adds one calibrated rule: the top cosine that **off-topic** questions reach in each corpus.

| Corpus | off-topic max | lowest correct top hit | floor (`runs.VECTOR_FLOOR`) |
|---|---|---|---|
| WEB | 0.552 | 0.655 | 0.60 |
| Hebrew | 0.514 | 0.518 | 0.53 |
| LXX | 0.512 | 0.538 | 0.53 |
| SBLGNT | 0.492 | 0.642 | 0.55 |

If vector search was up and **no** kept passage reaches its corpus's floor (requested references excepted), the level is capped at `low`: the agents kept something, but nothing scores better than what an off-topic question retrieves. WEB separates cleanly; for Hebrew and LXX the gap is small (6 off-topic queries), so the floor is a cap on a whole run, never a filter on single passages. The other thresholds (≥ 2 cross-lingual references and ≥ 1 passage found by both methods for `high`) held on all five golden runs: the four answerable queries came out `high`, the off-topic one `insufficient`. Levels are not probabilities.

## Golden queries

| Golden query | Run | Checks | Confidence | Notes |
|---|---|---|---|---|
| OT: "What does Genesis say about creation?" | `golden-ot-creation` | 26/26 | high | GEN.1.1 kept by WEB, Hebrew and LXX; LXX differences kept (Gen 2:2 "sixth day") |
| NT: "In the beginning was the Word" | `golden-nt-word` | 28/28 | high | JHN.1.1 from SBLGNT and WEB; verified OT background GEN.1.1, PRO.8.22, ISA.40.5 |
| Polarized: "Why doesn't God care about human suffering?" | `golden-polarized-suffering` | 27/27 | high | 4 query variants, evidence from several; laments and response passages both shown |
| NT→OT: "Who is the voice crying in the wilderness?" | `golden-nt-ot-voice` | 26/26 | high | verified MRK.1.3 / JHN.1.23 → ISA.40.3 with Hebrew, LXX and WEB |
| Low evidence: "What does the Bible say about configuring a Kubernetes cluster?" | `golden-low-evidence` | 14/14 | insufficient | retry round r2, nothing kept, no passages, clarifying question |

Each check covers what §13 asks: expected references kept (and shown), validator passes, every section labeled, machine translations flagged, expected agents in the trace with the parallel groups required.

## Findings fixed during phase 7

- **WEB markup**: 2,079 WEB verses carried USFM word markup (`Selah|strong="H5542"`) from words nested in character styles (`\bk \+w ...\+w*`). Fixed in `extract_verses.clean_usfm`; the 2,074 changed verses were re-embedded; `tests/test_verse_store.py` guards it.
- **Retrieved-only rule**: a specialist could keep a verse no search had returned (picked from memory) and `pack` labeled it `found_by: reference`. `pack specialist` now rejects a kept verse that is in no saved search and not among the delegation's `--references`.
- **HNSW settings** (above) and a pandas 3 bug in `build_index.embed` that turned a fully cached run into "0 cached" with NaN text.
- **Swete has no Ecclesiastes** (upstream gap: the converter's book list skips book 30), so Ecclesiastes questions have no LXX evidence.
