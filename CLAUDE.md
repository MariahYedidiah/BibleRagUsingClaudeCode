# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**bible-rag** is a retrieval-augmented generation (RAG) system over the Bible in Hebrew, Greek and English. The goal: embed verses, retrieve the relevant ones for a question, and answer with an LLM grounded in those verses.

**Status:** data ingestion, indexing and hybrid retrieval (phase 1) are done. `scripts/build_index.py` builds the canonical Parquet table, a SQLite verse store with an FTS5 index, and a Chroma collection embedded with `BAAI/bge-m3`. The `bible-rag` CLI and a local retrieval service do hybrid search over both. The agent system is specified in `docs/agent-system-prompt.md` and is being built phase by phase; agents, skills and the validator don't exist yet.

## Environment

- Python 3.14, managed with **uv** (`pyproject.toml` + `uv.lock`). Use `uv add <pkg>` to add dependencies, not pip.
- `requirements.txt` is a legacy, hand-kept list that partly duplicates `pyproject.toml`. Treat `pyproject.toml` as the source of truth.
- Windows machine. Scripts use absolute `D:\bible-rag\...` paths.

```powershell
uv sync                          # install deps
uv run python inspect_sources.py # preview the raw format of each source
uv run python extract_verses.py  # rebuild data/processed/verses/*.jsonl
uv run python scripts/build_index.py                # Parquet + SQLite/FTS5 + embeddings + Chroma
uv run python scripts/build_index.py --skip-vectors # Parquet + SQLite only (seconds)
uv run pytest                    # tests/ (vector tests skip until data/vector_db exists)

uv run bible-rag serve           # retrieval service on 127.0.0.1:8765; loads bge-m3 once (~1.7 GB RAM)
uv run bible-rag health
uv run bible-rag search "God's compassion for the suffering" "variant 2" --lang he,grc --testament OT --k 10
uv run bible-rag search --lexical "ואהבת לרעך כמוך" --lang he --mode lexical   # no service needed
uv run bible-rag verse JHN.3.16 --source sblgnt,web --context 2                 # no service needed
uv run bible-rag xref MRK.1.3 --testament OT                                    # cross-references, no service
```

## Retrieval (phase 1)

- **Vectorless:** SQLite FTS5, BM25 over `text_search` (`store.py`). Query text goes through `fold()` and every term is quoted, so user input can't inject FTS5 syntax. English stopwords are dropped; non-phrase queries are OR'ed.
- **Vector:** Chroma `verses_all`, cosine similarity on bge-m3 (`vectors.py`). Queries go through `normalize()` before embedding.
- **Hybrid** (`retrieval.py`): for each query variant, vector + BM25 lists; `--lexical` adds BM25-only lists (Hebrew/Greek terms). All lists are fused with reciprocal rank fusion (k=60), deduplicated by `verse_uid`, and the text comes from SQLite. Each result lists which query/method found it at what rank and score, plus raw `signals` (top cosine, margin, vector/lexical overlap) for later confidence levels. No reranker yet.
- **Service** (`server.py`, FastAPI): agents must go through it for vector search so only one model copy is loaded. Lexical search and `verse` lookups read SQLite directly. The CLI exits 2 with a start-the-service message if it is down, 1 on bad input.
- Shared paths and model settings live in `src/bible_rag/config.py`; `scripts/build_index.py` imports them.

## Validation (phase 2)

- `schemas.py` (pydantic, `extra="forbid"`): `Answer` → `Passage` → `TextEntry` / `CrossRef`. A `TextEntry` is `original` or `established_translation` (must cite `verse_uid`) or `machine_translation` (must have `translator` and `translates`, never a `verse_uid`). A `verified` cross-reference must name its dataset. Missing data goes in `missing` with a reason.
- `validator.py` / `uv run bible-rag validate answer.json`: every quoted text must equal the stored verse (NFC + whitespace-insensitive; `excerpt: true` allows a contiguous part), source/language labels must match the store, references must exist, a `mapped` passage can't quote a verse with another `canon_ref`, machine translations must translate a verse quoted in the same passage, and `verified` cross-references must be in the `cross_refs` table with ≥ `XREF_MIN_VOTES`. Until that table exists (phase 3), any `verified` cross-reference fails.
- Exit 0 = valid, 1 = invalid. Errors fail the answer; warnings (display_ref mismatch, unaligned partial passage) don't.
- `uv run pytest` would also run `tests/test_vector_store.py`, which loads bge-m3. While another process holds the model, use `--ignore=tests/test_vector_store.py`.

Embedding all ~91k verses takes ~5-6 h on this CPU. It is resumable: cached shards in `data/processed/embeddings/` are reused. The model loads in bfloat16 because fp32 (~4 GB) swapped on this 16 GB machine, and `HF_HOME` points at `.cache/huggingface` to keep the 2.3 GB model off C:. No linter is configured.

## Data layout

```
data/raw/                  # upstream sources (git clones / zip) — don't edit
  oshb/wlc/*.xml           # Hebrew OT, OSIS XML (Open Scriptures Hebrew Bible / WLC)
  lxx-swete/data/*.txt     # Greek OT (Swete LXX), one word per line: "<n>.<ch>.<v> word"
  sblgnt-tei/usfm/*.sfm    # Greek NT (SBLGNT), USFM
  web/WEB/*.usfm           # English (World English Bible), USFM, unzipped from engwebp_usfm.zip
data/processed/verses/     # output of extract_verses.py, one JSON object per verse
  hebrew_oshb.jsonl  greek_lxx.jsonl  greek_sblgnt.jsonl  english_web.jsonl
data/processed/verses.parquet   # canonical table (build_index.py): USFM book_id, canon_ref, text_norm, text_search
data/processed/embeddings/      # cached bge-m3 vectors, one Parquet shard per 2,048 verses
data/verses.db                  # SQLite verse store + FTS5 (verses_fts over text_search)
data/vector_db/                 # Chroma, one collection `verses_all`; filter by `language` metadata
```

Record schema (same for all four files):

```json
{"source": "web", "language": "en", "book_id": "GEN", "book_name": "Genesis",
 "chapter": 1, "verse": 1, "source_ref": "GEN.1.1", "text": "..."}
```

`source` values: `oshb_wlc`, `lxx_swete`, `sblgnt`, `web`. `language` values: `he`, `grc`, `en`.

Licenses, download URLs and the purpose of every dataset (including the OpenBible cross-references and STEPBible TVTMS versification data in `data/raw/openbible/` and `data/raw/stepbible/`) are in `docs/data-sources.md`. Swete's LXX is CC BY-SA, so anything derived from it must stay CC BY-SA if distributed.

## Canonical alignment (phase 3)

`canon_ref` is every verse's English (KJV-numbered) reference, so the same `canon_ref` means the same verse in every source. `alignment` says how exact that is: `mapped` (one-to-one), `partial` (part of, or more than, the standard verse), `unmapped` (no reliable match; native number kept). `chapter`/`verse`/`source_ref` keep the native numbering. Psalm titles have no English verse and get verse 0 (`PSA.3.0`).

- **Hebrew:** OSHB's `VerseMap.xml` (`versification.map_hebrew`). VerseMap doesn't separate two-verse psalm titles (it maps Ps 51:2 and 51:3 both to 51:1); the earlier verse is treated as title.
- **LXX:** STEPBible TVTMS (`versification.map_lxx`). Each TVTMS row's tests ("Psa.22:6=Last") are evaluated against Swete's actual verses, because Swete mixes traditions (Greek Psalms, English-style Malachi/Joel). If no row passes strictly, a relaxed pass ignores the variant-only tests and marks the result `partial`. A verse that keeps its own number only because nothing matched, when another verse was mapped onto that number, is `unmapped` (5 verses: LXX Jer 30:1-5).
- **SBLGNT:** 9 verses differ from KJV numbering (`SBLGNT_MAP`). WEB follows KJV.
- Result: lxx 28,713 mapped / 358 partial / 5 unmapped; oshb 23,209 / 1 / 3; sblgnt 7,921 / 6 / 0. No two `mapped` verses of one source share a `canon_ref`; ~99% of LXX and Hebrew OT references exist in WEB.
- **Cross-references** (`crossrefs.py`, `cross_refs` table): OpenBible.info, ranges within a chapter expanded per verse. Relation by votes: `verified` ≥ 25, `possible_allusion` ≥ 5, else `thematic` (calibrated on 12 known NT quotations, all ≥ 32). `uv run bible-rag xref MRK.1.3 --testament OT`.

## Known data issues

- **Fixed in `extract_verses.py`:** OSHB `<note>` text (English editorial notes, "KJV:Ps.23.1" markers, qere readings) leaked into 2,000+ Hebrew verses; notes are now skipped, so text is the written (ketiv) text. Swete psalm/ode titles carried stale verse numbers (Ps 22's title was "22.32") and are now verse 0. Swete digitization artifacts (alternate verse numbers "(52)", glued digits/superscripts, Roman numerals, Latin look-alike letters, stray sigla) are cleaned by `clean_lxx`. Typo Ps 88.84 → 88.48 (`LXX_VERSE_FIXES`).
- **Not fixed:** ~100 LXX verses have OCR errors inside Greek words ("Μrπτον" for Αἴγυπτον); guessing corrections would be riskier than leaving them. Swete Song 7 and Job 16 each have one verse labeled with the wrong chapter. SBLGNT keeps its ⸂ ⸃ ⟦ ⟧ signs in `text_display`; `normalize()` drops them for embedding and search.
- The JSONL files still carry raw book codes (OSIS for Hebrew, `LXX_<prefix>` for some LXX books); `books.py` normalizes them in the Parquet/SQLite layer.

Use `bible_rag.text.normalize()` before embedding a query and `fold()` before an FTS5 `MATCH`, the same as at index time.

## Planned stack

These dependencies are declared but not used yet: LangChain / LangGraph, sentence-transformers / langchain-huggingface (embeddings), Chroma / FAISS / pgvector (vector store), Groq / OpenAI / Ollama (LLM), FastAPI + LangServe or Streamlit (interface). Some deps (`arxiv`, `wikipedia`, `pypdf`, `pymupdf`, `bs4`) look like tutorial leftovers and are likely unneeded. Confirm with the user before relying on or removing them.

## Conventions

- Put new application code under `src/bible_rag/`. The top-level scripts are one-off data prep.
- Read raw sources with `utf-8-sig`, because some have BOMs. Write JSONL with `ensure_ascii=False` so Hebrew and Greek stay readable.
- Pipeline order: `data/raw` → `extract_verses.py` → `data/processed/verses/*.jsonl` → (to build) embeddings/index → retrieval → LLM. Regenerate the JSONL after any change to the parsers. The script overwrites the JSONL files and warns if any dataset comes out empty.
- `.env` is not in `.gitignore` yet. Add it before creating one for API keys.
