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
```

## Retrieval (phase 1)

- **Vectorless:** SQLite FTS5, BM25 over `text_search` (`store.py`). Query text goes through `fold()` and every term is quoted, so user input can't inject FTS5 syntax. English stopwords are dropped; non-phrase queries are OR'ed.
- **Vector:** Chroma `verses_all`, cosine similarity on bge-m3 (`vectors.py`). Queries go through `normalize()` before embedding.
- **Hybrid** (`retrieval.py`): for each query variant, vector + BM25 lists; `--lexical` adds BM25-only lists (Hebrew/Greek terms). All lists are fused with reciprocal rank fusion (k=60), deduplicated by `verse_uid`, and the text comes from SQLite. Each result lists which query/method found it at what rank and score, plus raw `signals` (top cosine, margin, vector/lexical overlap) for later confidence levels. No reranker yet.
- **Service** (`server.py`, FastAPI): agents must go through it for vector search so only one model copy is loaded. Lexical search and `verse` lookups read SQLite directly. The CLI exits 2 with a start-the-service message if it is down, 1 on bad input.
- Shared paths and model settings live in `src/bible_rag/config.py`; `scripts/build_index.py` imports them.

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

## Known data issues

Book codes are fixed in the Parquet/SQLite layer (`src/bible_rag/books.py`), so `canon_ref` joins across sources at the book level. The JSONL files still carry the raw codes below. **Versification is not mapped yet**: rows with `versification` = `wlc` or `lxx` use native verse numbers.

Raw JSONL issues (handled by `books.py`, not by `extract_verses.py`):

- **Hebrew (OSHB)** uses OSIS book codes uppercased (`EXOD`, `1SAM`, `PS`, `SONG`), not the USFM codes used elsewhere (`EXO`, `1SA`, `PSA`, `SNG`). `book_name` is the raw OSIS code (e.g. `1Chr`), because the `BOOKS` lookup misses.
- **LXX** maps only part of its books through `LXX_BOOKS`. The rest fall back to `LXX_<file prefix>` (e.g. Kingdoms, Chronicles, Joel, Jonah, the deuterocanon). `book_name` is the Latin file name (e.g. `Numeri`), and `source_ref` uses the file prefix (`01.1.1`), not the book code.
- **LXX versification** differs from the Masoretic text (Psalms numbering, Jeremiah order, etc.), so an identical reference can still mean a different verse.
- WEB and SBLGNT use clean USFM codes and are the reference scheme.

Next: apply `data/raw/oshb/wlc/VerseMap.xml` and an LXX mapping to make `canon_ref` truly canonical.

Use `bible_rag.text.normalize()` before embedding a query and `fold()` before an FTS5 `MATCH`, the same as at index time.

## Planned stack

These dependencies are declared but not used yet: LangChain / LangGraph, sentence-transformers / langchain-huggingface (embeddings), Chroma / FAISS / pgvector (vector store), Groq / OpenAI / Ollama (LLM), FastAPI + LangServe or Streamlit (interface). Some deps (`arxiv`, `wikipedia`, `pypdf`, `pymupdf`, `bs4`) look like tutorial leftovers and are likely unneeded. Confirm with the user before relying on or removing them.

## Conventions

- Put new application code under `src/bible_rag/`. The top-level scripts are one-off data prep.
- Read raw sources with `utf-8-sig`, because some have BOMs. Write JSONL with `ensure_ascii=False` so Hebrew and Greek stay readable.
- Pipeline order: `data/raw` → `extract_verses.py` → `data/processed/verses/*.jsonl` → (to build) embeddings/index → retrieval → LLM. Regenerate the JSONL after any change to the parsers. The script overwrites the JSONL files and warns if any dataset comes out empty.
- `.env` is not in `.gitignore` yet. Add it before creating one for API keys.
