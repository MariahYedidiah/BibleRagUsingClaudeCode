---
name: english-to-hebrew
description: Turn an English question or topic into Biblical Hebrew search terms for lexical (BM25) retrieval over the Hebrew Old Testament (OSHB). Every term is checked against the corpus. Output is search input only and is never shown as scripture or as a translation.
when_to_use: A Hebrew specialist or the leader needs vectorless retrieval over oshb_wlc for an English query (vector search handles English directly, keyword search needs Hebrew words). Not for translating retrieved verses (use hebrew-to-english).
argument-hint: "\"<English query or topic>\" [--out runs/<id>/hebrew_terms.json]"
allowed-tools: Bash(uv run bible-rag *) Read Write
---

# English → Hebrew (search terms)

Produce **Hebrew search terms** for the user's English query, so keyword (BM25) search can find Hebrew Old Testament verses. This is **query translation for retrieval only**: the terms are never displayed as scripture, never quoted as a translation, and never inserted into an answer.

Input: $ARGUMENTS

## How the Hebrew index works (why the forms matter)

- The search index stores each Hebrew word **without vowel points or accents**, **with its prefixes and suffixes attached**: וָ/יָֽפֶת is indexed as `ויפת`, בְּ/רֵאשִׁית as `בראשית`.
- A term matches **only whole words**, so `חסד` does not match `חסדו` ("his steadfast love"). You need the **inflected surface forms** that actually occur, not just the dictionary form.
- Pointed or unpointed input both work; points are stripped. Final letters (ך ם ן ף ץ) must be correct.

## Steps

1. **Pick the concepts.** Take the 2–6 content concepts that carry the query's meaning (e.g. "God's compassion for the suffering": compassion/mercy, steadfast love, affliction/suffering, cry out/hear). Ignore function words. For a polarized query, include the concepts of its neutral reformulation too.
2. **Propose Biblical Hebrew forms** for each concept, using the vocabulary of the Hebrew Bible rather than modern Hebrew:
   - the bare form (`חסד`, `רחמים`, `עני`);
   - frequent prefixed forms: ו "and", ה "the", ב "in", ל "to", כ "as", מ "from" (`וחסד`, `בחסדך`);
   - frequent suffixed forms: ו "his", ך "your", י "my", ם "their" (`חסדו`, `חסדך`, `חסדי`);
   - for verbs, the common stems and tenses (`רחם`, `ירחם`, `ירחמנו`).
   Propose about 4–10 forms per concept.
3. **Check every form against the corpus:**
   ```bash
   uv run bible-rag terms --corpus oshb_wlc חסד חסדו חסדך בחסדך רחמים רחמיו עני
   ```
   **Keep only forms with a count above 0**, and record each count exactly as `hits`. Drop the rest silently. A term that occurs in no verse is useless and must not be passed on.
4. **Watch for homographs.** Without vowel points, different words can be spelled the same: `בצרה` is "in distress" but also the city Bozrah. Prefer forms whose consonants are unambiguous, and say in `notes` when a kept term is ambiguous, so the specialist can discard false hits.
5. **Avoid noise.** Leave out extremely common words (יהוה, אלהים, כי, את, אשר, על, כל) unless the query is specifically about them; they match thousands of verses. Prefer terms with 3–1,500 hits.
6. **Build `lexical_queries`**: 1–4 space-separated strings, each covering one facet of the query, e.g. `"חסד חסדו חסדך רחמים רחמיו"` and `"עני עניי צרה צעקה"`. Search ORs the words within a string, and each string becomes its own ranked list.
7. **Write the JSON** to the `--out` path, or to `runs/skills/hebrew-terms.json` if no path was given, then check it:
   ```bash
   uv run bible-rag check terms <path>
   ```
   If `valid` is false, fix the reported terms (usually: drop terms with 0 hits) and check again **once**. Return the path and the `lexical_queries`.

## Output

```json
{
  "query": "How does God show compassion to people who suffer?",
  "language": "he",
  "corpus": "oshb_wlc",
  "terms": [
    {"term": "רחמים", "gloss": "compassion, mercy (plural noun)", "hits": 4},
    {"term": "חסדו", "gloss": "his steadfast love", "hits": 61},
    {"term": "עני", "gloss": "poor, afflicted", "hits": 30}
  ],
  "lexical_queries": ["רחמים חסדו", "עני"],
  "method": "machine",
  "translator": "claude:<model id>",
  "display": false,
  "notes": ["חסד covers 'steadfast love / lovingkindness'; included because God's compassion is usually expressed with it"]
}
```

The `hits` numbers above are illustrative; always use the counts that `bible-rag terms` returns. `display` is always `false`. `language` is `"he"` and `corpus` is `"oshb_wlc"`.

## Errors

```json
{"error": "no_terms_found", "message": "none of the proposed Hebrew forms occur in the corpus", "input": "<query>"}
```

| `error` | When |
|---|---|
| `empty_input` | No query was given |
| `wrong_language` | The query is already in Hebrew: return its words as terms after checking them, or report this |
| `no_terms_found` | After checking, no proposed form has any hits. Report it; never invent forms |
| `check_failed` | The output still fails `bible-rag check terms` after one fix |

If the tools are unavailable, report the command's error verbatim and return no terms. Lexical retrieval for Hebrew then falls back to vector search only.
