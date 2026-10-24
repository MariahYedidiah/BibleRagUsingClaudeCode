# Project: Multilingual Bible RAG Using Native Claude Code Agents (revised)

Build a multilingual Bible RAG system using a **hierarchical multi-agent architecture built from Claude Code's native custom subagents and skills**.

Claude's agent capabilities handle reasoning, delegation, orchestration, query analysis, translation and synthesis. Do not replace this with a LangGraph agent system or Python functions that pretend to be agents. This supersedes the LangGraph design and the "Pipeline A vs B" comparison in `plan.md`; update `plan.md` accordingly.

Python is used for deterministic work: retrieval, database access, indexing, parsing, verse alignment, validation and evaluation. That code must be reusable and tested.

Use Claude Code's own model access for all reasoning and translation. Do not add a paid LLM API dependency unless I approve it.

---

## 0. Starting point and constraints (read first)

Before building anything, inspect the repo and confirm this state:

- **Corpora:** OSHB/WLC (Hebrew OT), Swete LXX (Greek OT), SBLGNT (Greek NT), **WEB** (World English Bible, the only English version). Do not add KJV or YLT.
- **Verse store:** `data/verses.db`, a SQLite `verses` table plus `verses_fts` (FTS5), built by `scripts/build_index.py`. It contains `canon_ref`, `source`, `language`, `testament`, `edition`, `versification`, `text_display`, `text_norm` and `text_search`.
- **Vector store:** `data/vector_db`, one Chroma collection `verses_all` embedded with `BAAI/bge-m3` (dense vectors only, cosine distance). Filter by `language` / `source` metadata. Do **not** create per-language collections unless a language gets its own model.
- **Normalization:** `bible_rag.text.normalize()` before embedding a query, and `fold()` before an FTS5 `MATCH`, exactly as at index time.
- **Known gap:** `canon_ref` normalizes book codes only. Rows with `versification` = `wlc` or `lxx` still use native verse numbers.
- **Machine:** CPU only, 16 GB RAM, usually only 2–5 GB of it free. Loading bge-m3 needs about 1.7 GB in bfloat16. **Never load the model once per agent call.**

Do not discard existing data or working components. Extend `scripts/build_index.py` and `src/bible_rag/` rather than replacing them.

---

## 1. Phased implementation

Build and test in this order. Each phase ends with passing tests, a short note in `CLAUDE.md`, and a commit. Do not start a phase until the previous one passes.

1. **Retrieval service and command-line interface (CLI)** (§4)
2. **Validator** (§9)
3. **Versification and cross-reference data** (§7, §8)
4. **Translation skills** (§3)
5. **Specialist agents** (§11)
6. **Leader and synthesis agents, demo mode** (§11, §12)
7. **Golden-query evaluation** (§13)

Before phase 1, write a short plan listing missing dependencies and downloads with their licenses. Wait for my approval before downloading anything or adding dependencies.

---

## 2. English version

- The English corpus is the **World English Bible (WEB)**, a public-domain modern translation, stored as source `web`.
- Label every English passage "WEB". Never call it KJV or YLT, and never quote KJV/YLT wording from memory.
- Where WEB's wording matters to the answer (e.g. it differs from the original-language text), say so; don't hide it.
- Keep the source a setting, so another version could be added later through the same extract → Parquet → SQLite → embed pipeline without changing agent code.

---

## 3. Translation skills

Create four skills under `.claude/skills/`: `english-to-hebrew`, `hebrew-to-english`, `english-to-greek`, `greek-to-english`. Each has its own instructions, invocation conditions, input/output JSON schema and error handling.

**Purposes are different. State them in each skill:**

- `hebrew-to-english` and `greek-to-english` translate **retrieved passages** for display. Input: `{canon_ref, source, text_display}`. Output: `{canon_ref, source, translation, translator: "claude:<model>", method: "machine", notes}`. `greek-to-english` must be told whether the text is **LXX** or **NT** Greek.
- `english-to-hebrew` and `english-to-greek` translate the **user's query** into search terms for lexical retrieval over the original-language corpora. Output: a list of candidate terms or lemmas, folded with `fold()`. Their output is **never** displayed as scripture or as a translation of scripture.

All skills must:

- Never alter or replace the original text. It is passed through unchanged.
- Label output as machine-generated, distinct from the WEB translation.
- Flag uncertainty: textual variants, idioms, ambiguous grammar. Do not smooth it over.
- On bad input (empty text, wrong language), return `{"error": ...}` instead of guessing.

---

## 4. Hybrid retrieval: vector and vectorless

### Retrieval service

Agents must not query Chroma or SQLite directly, and must not load the embedding model themselves.

- Add a small **local retrieval service** (FastAPI is already a dependency). It loads bge-m3 **once** and keeps it in memory.
- Wrap it in a **CLI** that agents call through Bash and that returns JSON, e.g. `uv run bible-rag search --q "..." --lang he --k 10`, `uv run bible-rag verse JHN.3.16 --sources sblgnt,kjv`, `uv run bible-rag xref JHN.1.23`.
- If the service is not running, the CLI fails with a clear message saying how to start it. It must not silently load the model in-process.
- Concurrent agent calls go through the one service. Only one copy of the model is ever loaded.

### Vector retrieval

Semantic search on `verses_all` with a `where` filter on `language` / `source` / `testament`.

### Vectorless retrieval

FTS5 BM25 over `text_search`, plus:

- exact reference lookup by `canon_ref`;
- metadata filters;
- **Strong's numbers and morphology only where they actually exist.** OSHB's raw XML has per-word `lemma` and `morph`, but `extract_verses.py` currently discards them, so add a `tokens` table. SBLGNT has none; MorphGNT would be needed, so ask first. Swete has none.

Hebrew and Greek lexical queries use terms from `english-to-hebrew` / `english-to-greek`, folded with `fold()`.

### Pipeline (per corpus)

Vector results + vectorless results → merge on `verse_uid` → deduplicate → rank fusion with **reciprocal rank fusion (RRF)** → optional rerank → select.

- **Reranker:** optional and off by default. A cross-encoder such as `bge-reranker-v2-m3` needs about 2 GB more RAM, which this machine usually lacks. If enabled, it runs inside the retrieval service, never per call.
- Every result keeps `verse_uid`, `canon_ref`, `source`, `edition`, `versification`, its vector rank and score, and its lexical rank and score.
- Document in `CLAUDE.md` where each store lives and how each kind of retrieval works.

---

## 5. Query analysis (leader)

The leader performs and records in `analysis.json`:

1. query understanding;
2. sentiment and polarity;
3. topic and intent;
4. explicit scripture references;
5. OT/NT determination where possible;
6. retrieval strategy.

Sentiment is a signal only. It never decides the answer or the retrieval path on its own.

**Negative or polarized queries.** Do not rely on a literal antonym. Generate:

1. the original query;
2. a neutral reformulation;
3. a contrasting or positive formulation;
4. a literal antonym only if it is useful.

Run hybrid retrieval for each useful variant, then merge, deduplicate and rerank across variants. Compare the evidence. Do not assume the contrasting query represents the correct Biblical view.

Example — "Why doesn't God care about human suffering?":

- the original;
- "How does the Bible describe God's response to human suffering?";
- "Which passages describe God's compassion toward people who suffer?"

---

## 6. Old Testament and New Testament workflows

### Old Testament

Run three specialists **in parallel**:

- **English agent:** WEB, vector + vectorless.
- **Hebrew agent:** OSHB/WLC, vector + vectorless. Include surrounding context where useful. Invoke `hebrew-to-english` on the selected verses.
- **Septuagint agent:** Swete LXX, vector + vectorless. Invoke `greek-to-english` with the LXX flag. Always label the text "Septuagint Greek", never "Greek NT". For Daniel, Susanna and Bel, report the edition (`og` / `th`).

### New Testament

Run in parallel:

- **English agent:** WEB, vector + vectorless.
- **Greek NT agent:** SBLGNT, vector + vectorless. Invoke `greek-to-english` with the NT flag.

### Presentation order

**OT:**

1. English — WEB
2. Hebrew — OSHB/WLC
3. Hebrew → English (machine)
4. Septuagint Greek — Swete LXX
5. Greek → English (machine)

**NT:**

1. Greek NT — SBLGNT
2. Greek → English (machine)
3. English — WEB

Hebrew, Septuagint, NT Greek, WEB and machine translations are never treated as interchangeable.

---

## 7. NT → OT cross-references

**Data:** use a named, licensed dataset, e.g. OpenBible.info cross-references (CC-BY, with vote counts). Load it into a `cross_refs` table: `from_canon_ref`, `to_canon_ref`, `votes`, `dataset`. Ask before downloading. Record the dataset and threshold with every relationship.

Classify every NT → OT relationship as one of:

1. **verified:** present in the dataset with votes ≥ a documented threshold, and/or a recognized quotation (introductory formula such as "it is written", or high lexical overlap with the LXX verified by the validator);
2. **possible allusion:** in the dataset below the threshold, or partial lexical overlap;
3. **thematic similarity:** found only by semantic search.

Never create a cross-reference just because two passages share a theme.

- For **verified** references, run the full OT workflow automatically.
- Allusions and thematic similarities are shown separately with their uncertainty label. They are not expanded unless I ask.

**Presentation per NT passage:**

1. NT Greek
2. NT Greek → English
3. NT English
4. OT Hebrew
5. OT Hebrew → English
6. OT Septuagint
7. OT Septuagint → English
8. OT English

Each part is labeled with its reference, source and translation status.

---

## 8. Canonical alignment

**Prerequisite phase:**

- Apply `data/raw/oshb/wlc/VerseMap.xml` (WLC ↔ KJV versification).
- Find a licensed LXX ↔ KJV versification mapping and ask before using it.

Afterwards, `canon_ref` means the same verse in every source, and each row keeps its native `source_ref`.

Where a mapping is missing or partial, the result says so: `alignment: "unmapped" | "partial" | "mapped"`. Never present a wrong verse as aligned.

The Hebrew and LXX texts can genuinely differ (Jeremiah's order and length, Psalm numbering, additions in Esther and Daniel). Report such differences; do not hide them.

### Structured handoff

Agents exchange JSON only, never unlabelled text. Each passage record looks like:

```json
{
  "canon_ref": "JHN.1.1",
  "display_ref": "John 1:1",
  "testament": "NT",
  "alignment": "mapped",
  "texts": [
    {"source": "sblgnt", "language": "grc", "kind": "original", "text": "...", "verse_uid": "sblgnt:JHN.1.1"},
    {"source": "web", "language": "en", "kind": "established_translation", "text": "...", "verse_uid": "web:JHN.1.1"},
    {"source": "sblgnt", "language": "en", "kind": "machine_translation", "translator": "claude:<model>", "text": "..."}
  ],
  "retrieval": {"vector": [{"rank": 1, "score": 0.71}], "vectorless": [{"rank": 3, "bm25": -8.2}], "fused_rank": 1},
  "cross_refs": [{"to": "ISA.40.3", "class": "verified", "dataset": "openbible", "votes": 512}]
}
```

Missing data is explicit (`null` plus a reason), never filled in. Define the schemas in `src/bible_rag/schemas.py`, and have every agent output validated against them.

---

## 9. Validator and anti-fabrication

Instructions alone cannot enforce "no fabrication". Add `uv run bible-rag validate runs/<id>/answer.json`, which checks that:

- every `original` and `established_translation` text exactly matches `verses.db` for its `verse_uid`;
- every reference exists;
- every cross-reference marked `verified` exists in `cross_refs` above the threshold;
- every `machine_translation` is labeled with its translator;
- no section is missing its source label.

If validation fails, the leader sends the specific errors back to the responsible agent once. If it fails again, the answer reports what could not be verified instead of shipping it.

---

## 10. Retrieval confidence and fallbacks

Estimate confidence from **measurable signals**, never an LLM-invented number:

- top vector cosine score, and its margin over the next result;
- vector/lexical agreement (the same `verse_uid` in both top-k lists);
- cross-lingual agreement (the same `canon_ref` retrieved in two or more languages);
- agreement across query variants.

Combine them into documented levels (`high` / `medium` / `low`) with thresholds tuned on the golden queries. Do not present them as calibrated probabilities.

**If confidence is low:**

1. expand or reformulate the query;
2. run hybrid retrieval again;
3. merge, deduplicate and rerank;
4. reassess.

Allow at most 2 rounds. If confidence is still low, say that no sufficiently relevant evidence was found, and ask a clarifying question where that would help.

---

## 11. Agent architecture

**Agents** in `.claude/agents/` (frontmatter `name`, `description`, `tools`, `model`, `skills`):

| Agent | Role | Suggested model |
|---|---|---|
| `leader-agent` | Analysis, strategy, delegation, validation loop | opus |
| `english-retrieval-agent` | English hybrid retrieval | haiku or sonnet |
| `hebrew-specialist-agent` | Hebrew retrieval; preloads `hebrew-to-english` and `english-to-hebrew` | sonnet |
| `septuagint-specialist-agent` | LXX retrieval; preloads `greek-to-english` and `english-to-greek` | sonnet |
| `greek-new-testament-agent` | SBLGNT retrieval; preloads `greek-to-english` and `english-to-greek` | sonnet |
| `cross-reference-agent` | NT → OT classification from `cross_refs` and the validator | sonnet |
| `synthesis-agent` | Final answer from validated JSON only | opus |

**Orchestration:**

- **Canonical entry point:** `claude --agent leader-agent`, or `"agent": "leader-agent"` in `.claude/settings.json`. The leader then runs as the main thread, so delegation is visible in the session.
- Restrict the leader to its specialists with `tools: Agent(english-retrieval-agent, hebrew-specialist-agent, ...), Read, Write, Bash`.
- Also provide a `/bible-ask` skill as an alternative entry point.
- Run independent specialists in parallel (the English, Hebrew and LXX agents). Run dependent steps in sequence: cross-references after NT retrieval, synthesis after validation.
- Specialists do retrieval through the CLI only (`tools: Bash, Read, Write`, plus the Skill tool for translation). They must not edit project files.
- Each agent writes its result to `runs/<query-id>/<agent>.json` and returns the path plus a short summary. The leader reads the files; JSON is not passed through chat text.
- Defining an agent does not make it run. The orchestration must be exercised by the golden-query tests (§13).

---

## 12. Final answer and demo mode

The synthesis agent writes `runs/<id>/answer.json` (validated) and `runs/<id>/answer.md`. The answer:

1. answers the question from retrieved evidence only;
2. separates WEB English, Hebrew, Septuagint Greek and NT Greek;
3. gives the source and reference for every passage;
4. marks machine translations as such;
5. separates verified cross-references from allusions and thematic similarities;
6. preserves meaningful differences between Hebrew, LXX, NT Greek and WEB;
7. states the confidence level and what it is based on;
8. reads well enough for a research demo.

**Demo mode** (`--demo`, or a line in the prompt) also writes `runs/<id>/trace.json`, recording:

- which agent was delegated what;
- parallel or sequential;
- start and end times;
- which skills were invoked;
- the retrieval queries and their variants;
- validator results.

Add `uv run bible-rag show-run <id>` to print a run's trace.

---

## 13. Tests

**Deterministic (pytest, no LLM):**

- retrieval service and CLI;
- RRF merge and deduplication;
- versification mapping (e.g. Mal 4:1 ↔ WLC Mal 3:19, Psalm titles);
- cross-reference classification;
- schema validation;
- the validator: it must catch a fabricated verse, a wrong reference and an unlabeled machine translation.

**Golden-query evaluations** (run inside Claude Code; results vary between runs, so check properties rather than exact text):

- **OT:** "What does Genesis say about creation?" — expects GEN.1.1 from the English, Hebrew and LXX corpora.
- **NT:** "In the beginning was the Word" — expects JHN.1.1 from SBLGNT and WEB.
- **Polarized:** "Why doesn't God care about human suffering?" — expects 3 or more query variants in the trace, and evidence from more than one variant.
- **NT → OT:** "Who is the voice crying in the wilderness?" — expects a verified link from MRK.1.3 / JHN.1.23 to ISA.40.3, with Hebrew, LXX and WEB for Isaiah.
- **Low evidence:** a query with no Biblical basis — expects a fallback round, then an "insufficient evidence" answer instead of an invented one.

Each evaluation checks:

- the expected `canon_ref`s are present;
- the validator passes;
- every section has its label;
- machine translations are flagged;
- the trace shows the expected agents, with parallel delegation where required.

---

## 14. Repeatability

Provide:

- `CLAUDE.md`: architecture, how to start the retrieval service, the canonical invocation, and the workflow from query to answer;
- agent and skill definitions;
- schemas;
- tests;
- `runs/` in `.gitignore`, except one committed example run per golden query.

Clearly separate what works offline from what needs Claude Code access. Offline: data, indexes, the CLI, the validator, pytest. Needs Claude Code: the agents, the skills, the evaluations.

---

## 15. Hooks: enforcing the source checks

The checks against the sources (`bible-rag check ...`, `pack`, `run answer`, `check answer --run`) are only as strong as the agents' willingness to run them and act on the result. Use Claude Code hooks (`.claude/settings.json`, scripts in `scripts/hooks/`) where a hook **blocks** something the instructions forbid but nothing currently prevents. Don't add hooks that repeat a check a deterministic command already runs in the same step (e.g. re-validating right after `pack`, which validates itself): those are vestigial.

Every hook calls the same Python functions as the CLI (no second implementation), reads its input as JSON on stdin, and blocks with exit code 2 plus the errors on stderr, so the agent sees why and can fix it.

| Hook | Event / matcher | Blocks | Why it isn't vestigial |
|---|---|---|---|
| **Results come from the store** | `PreToolUse` on `Write\|Edit` | writing `runs/**/<agent>.json`, `cross-reference-agent.json`, `answer.json`, `answer.md` or `confidence.json` directly | These files must be produced by `pack`, `run answer` and `run confidence`, which copy scripture from the store. Today an agent could hand-write one and bypass every check. |
| **No scripture in agent-written files** | `PreToolUse` on `Write\|Edit` of `runs/**/*_selection.json`, `xref_adjust.json`, `synthesis.json` | content containing a stored verse's text (≥ 8 consecutive words of any verse in the target corpus, Hebrew/Greek compared after `fold()`) | The selection and synthesis files are specified to contain no scripture; the only thing stopping an agent from quoting from memory today is its instructions. |
| **Specialist can't stop on a failed check** | `SubagentStop` for the four retrieval specialists and the cross-reference agent | stopping while its result file is missing or `check specialist` / `check xrefs` fails | The leader trusts the two-line reply. The hook makes "check passed" a fact, and the agent gets the errors back instead of the leader finding out later. |
| **Kept verses were retrieved** | inside the same `SubagentStop` check | a kept passage that is in no saved search and not one of the delegation's `references` | Picking a verse from memory and packing it is not retrieval. (`pack specialist --references` already enforces this; the hook makes sure the flag can't be skipped by packing without it.) |
| **The leader can't finish without validation** | `Stop` for the leader session | ending a turn after `answer.md` was written but `check answer runs/<id>/answer.json --run <id>` was not run, or failed | §9 says never skip the final check; nothing enforces it today. |
| **The trace records itself** | `SubagentStart` / `SubagentStop` (and `PostToolUse` on `Skill`) | nothing; appends to `runs/<id>/trace.json` | §12 asks for start and end times and skill invocations. The leader logs delegations by hand, which it can forget or get wrong, and skill calls aren't logged at all. |

Rules for the hooks themselves:

- They find the run from the file path or the delegation message (`run_id: ...`). With no run in scope, they allow the action.
- They must be fast (no model loading, no service calls) and deterministic; they read `data/verses.db` only.
- Test each with pytest by feeding it the JSON a hook receives: an allowed case and a blocked case.
- Document them in `CLAUDE.md` next to the agents they constrain.
