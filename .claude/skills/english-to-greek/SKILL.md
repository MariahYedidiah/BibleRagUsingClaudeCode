---
name: english-to-greek
description: Turn an English question or topic into Koine Greek search terms for lexical (BM25) retrieval over the Septuagint (Swete LXX) and/or the Greek New Testament (SBLGNT). Every term is checked against the corpus. Output is search input only and is never shown as scripture or as a translation.
when_to_use: A Septuagint or Greek New Testament specialist, or the leader, needs vectorless retrieval over lxx_swete or sblgnt for an English query. Not for translating retrieved verses (use greek-to-english).
argument-hint: "\"<English query or topic>\" --corpus lxx_swete|sblgnt|lxx_swete+sblgnt [--out runs/<id>/greek_terms.json]"
allowed-tools: Bash(uv run bible-rag *) Read Write
---

# English → Greek (search terms)

Produce **Koine Greek search terms** for the user's English query, so keyword (BM25) search can find Septuagint and/or New Testament verses. This is **query translation for retrieval only**: the terms are never displayed as scripture, never quoted as a translation, and never inserted into an answer.

Input: $ARGUMENTS

## How the Greek index works (why the forms matter)

- The search index stores each Greek word **lower-cased, without accents or breathings, with final ς folded to σ**: ἀγάπης is indexed as `αγαπησ`. Accented or unaccented input both work.
- A term matches **only whole words**, so `ἀγάπη` doesn't match `ἀγάπης` or `ἀγαπᾷ`. Greek is highly inflected, so you need the **inflected forms** that actually occur, not just the dictionary form.

## Steps

1. **Choose the corpus.** Use `--corpus` if given. Otherwise: Old Testament topics → `lxx_swete`, New Testament topics → `sblgnt`, unclear or both → `lxx_swete+sblgnt`.
2. **Pick the concepts.** Take the 2–6 content concepts that carry the query's meaning. Ignore function words. For a polarized query, include the concepts of its neutral reformulation too.
3. **Propose Koine Greek forms** for each concept, using the vocabulary of the Septuagint and NT rather than modern Greek:
   - nouns: nominative, genitive, dative, accusative, singular and plural where common (`ἔλεος`, `ἐλέους`, `ἐλέει`; `ἀγάπη`, `ἀγάπης`, `ἀγάπην`);
   - verbs: the frequent forms (present, aorist, future, participles) of the key verbs (`ἐλεέω`: `ἐλέησον`, `ἠλέησεν`, `ἐλεῶν`);
   - for the LXX, the Greek words the Septuagint uses for the Hebrew concept (חסד → `ἔλεος`; רחמים → `οἰκτιρμοί`).
   Propose about 4–12 forms per concept.
4. **Check every form against the corpus:**
   ```bash
   uv run bible-rag terms --corpus lxx_swete ἔλεος ἐλέους ἐλέησον οἰκτιρμοί οἰκτιρμῶν θλῖψις θλίψει
   ```
   **Keep only forms with a count above 0**, and record each count exactly as `hits`. Drop the rest silently.
5. **Avoid noise.** Leave out extremely common words (καί, ὁ/ἡ/τό and their forms, θεός, κύριος, αὐτός, ἐν, εἰς, ὅτι) unless the query is specifically about them. Prefer terms with 3–1,500 hits.
6. **Build `lexical_queries`**: 1–4 space-separated strings, each covering one facet, e.g. `"ἔλεος ἐλέους ἐλέησον οἰκτιρμοί"` and `"θλῖψις θλίψει θλίψεως"`.
7. **Write the JSON** to the `--out` path, or to `runs/skills/greek-terms.json` if no path was given, then check it:
   ```bash
   uv run bible-rag check terms <path>
   ```
   If `valid` is false, fix the reported terms (usually: drop terms with 0 hits) and check again **once**. Return the path and the `lexical_queries`.

## Output

```json
{
  "query": "How does God show compassion to people who suffer?",
  "language": "grc",
  "corpus": "lxx_swete",
  "terms": [
    {"term": "ἔλεος", "gloss": "mercy (nom./acc.)", "hits": 120},
    {"term": "οἰκτιρμοί", "gloss": "compassions (LXX for רחמים)", "hits": 9},
    {"term": "θλίψει", "gloss": "in affliction (dat.)", "hits": 40}
  ],
  "lexical_queries": ["ἔλεος οἰκτιρμοί", "θλίψει"],
  "method": "machine",
  "translator": "claude:<model id>",
  "display": false,
  "notes": []
}
```

The `hits` numbers above are illustrative; always use the counts that `bible-rag terms` returns for the chosen corpus. `display` is always `false` and `language` is always `"grc"`. `corpus` is `"lxx_swete"`, `"sblgnt"` or `"lxx_swete+sblgnt"`, and must be the corpus the counts came from.

## Errors

```json
{"error": "no_terms_found", "message": "none of the proposed Greek forms occur in the corpus", "input": "<query>"}
```

| `error` | When |
|---|---|
| `empty_input` | No query was given |
| `wrong_language` | The query is already in Greek: return its words as terms after checking them, or report this |
| `no_terms_found` | After checking, no proposed form has any hits. Report it; never invent forms |
| `check_failed` | The output still fails `bible-rag check terms` after one fix |

If the tools are unavailable, report the command's error verbatim and return no terms. Lexical retrieval for Greek then falls back to vector search only.
