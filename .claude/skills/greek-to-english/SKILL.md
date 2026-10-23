---
name: greek-to-english
description: Translate retrieved Greek verses into English for display, as a clearly labeled machine translation shown next to the untouched Greek. Handles both Septuagint Greek (Swete LXX, source lxx_swete) and New Testament Greek (SBLGNT, source sblgnt) and keeps them distinct.
when_to_use: A Septuagint or Greek New Testament specialist, or the leader, has a canon_ref or verse_uid from lxx_swete or sblgnt and needs an English rendering of that exact verse. Not for translating the user's question (use english-to-greek) and not for Hebrew (use hebrew-to-english).
argument-hint: "<canon_ref or verse_uid> [more refs...] --corpus lxx|nt [--out runs/<id>/greek_translation.json]"
allowed-tools: Bash(uv run bible-rag *) Read Write
---

# Greek → English (passage translation)

Translate verses of **Septuagint Greek (Swete's LXX)** or **New Testament Greek (SBLGNT)** into English. The output is a **machine translation**. It is always shown next to the original Greek and is never presented as an established Bible translation.

Input: $ARGUMENTS

## Rules that are never broken

1. **The Greek is never changed.** Copy `text_display` into `original` exactly, character for character, including SBLGNT's ⸂ ⸃ ⟦ ⟧ signs. Never retype or normalize it.
2. **Only translate what the store returns.** If a reference isn't found, return an error. Never translate a verse from memory.
3. **Keep the two Greek corpora distinct.** Septuagint Greek is a translation of Hebrew scripture made centuries before the NT. Label it `"Septuagint Greek (Swete LXX)"` and never call it New Testament Greek. SBLGNT is `"New Testament Greek (SBLGNT)"`.
4. **Translate the Greek as it stands.** For LXX verses, don't harmonize toward the Hebrew or WEB (WEB translates the Hebrew). Where the LXX says something different, translate the difference and report it.
5. **Always label the output** `"method": "machine"` with `"translator": "claude:<your model id>"`.

## Steps

1. **Parse the input.** It holds references as `canon_ref` (`PSA.23.1`, `JHN.1.1`, English numbering) or `verse_uid` (`lxx_swete:27.22.1`, `sblgnt:JHN.1.1`, native numbering), `--corpus lxx` or `--corpus nt` (infer it from the `verse_uid` or testament if missing), and an optional `--out` path.
2. **Create the draft.** It copies the Greek verbatim, fills in the references and labels, and adds the WEB text as `_web_text` for comparison:
   ```bash
   uv run bible-rag draft translation PSA.23.1 --source lxx_swete > runs/<id>/greek_translation.json   # Septuagint
   uv run bible-rag draft translation JHN.1.1 --source sblgnt > runs/<id>/greek_translation.json       # New Testament
   ```
   - Several refs give a JSON list. A ref missing from the corpus becomes an `unknown_reference` error item; keep it.
   - **LXX Daniel, Susanna and Bel** come in two editions (`_edition` `og` = Old Greek, `th` = Theodotion), and the draft has one item per edition. Pass `--edition og|th` for one of them. If neither was requested, translate both and name the edition in `literal_notes`.
   - The LXX native reference can differ from the English one (Swete Ps 22:1 is English Ps 23:1). The draft already has the right `canon_ref`; never change it.
   - If the meaning depends on the surrounding verses, read them with `uv run bible-rag verse <ref> --source <source> --context 1`. Translate only the requested verses.
   - **Edit only** `translation`, `translator`, `literal_notes`, `uncertainties` and `differences_from_web`. Never touch `original`, `canon_ref`, `verse_uid`, `source` or `corpus_label`.
3. **Read the Greek correctly:**
   - SBLGNT ⸂ … ⸃ marks a phrase with a significant textual variant, and ⟦ … ⟧ marks text generally judged to be a later addition. Translate the text inside them, and add a note to `uncertainties` ("variant unit: …", "bracketed as a later addition").
   - LXX: a few verses still contain OCR damage inside words (Latin letters inside a Greek word, e.g. "Μrπτον"). Translate the evident word ("Αἴγυπτον" → Egypt) and record the damaged form in `uncertainties`. Never copy a "corrected" form into `original`.
4. **Translate.** Aim for faithful, readable English that stays close to the Greek: keep tense, voice and participles visible where it matters, without paraphrasing. Render κύριος used for the divine name as "the Lord". Keep proper names in their usual English forms.
5. **Compare with WEB** (`_web_text`; `web_reference` is already set). In `differences_from_web`, list meaningful differences in sense. **For LXX verses these are expected and important**: they show where the Septuagint differs from the Hebrew text that WEB translates (e.g. Isa 7:14 LXX παρθένος "virgin" against Hebrew עַלְמָה "young woman"). Don't list style differences.
6. **Record uncertainty honestly** in `uncertainties`: ambiguous grammar, textual variants (SBLGNT signs), OCR damage, and **alignment** when the verse's `alignment` is not `mapped` ("verse numbering alignment is partial: …").
7. **Save the edited draft** at the `--out` path, or at `runs/skills/greek-<canon_ref>.json` if no path was given.
8. **Check it:**
   ```bash
   uv run bible-rag check translation <path>
   ```
   If `valid` is false, fix the reported fields and check again **once**. If it still fails, replace that item with a `check_failed` error object. Return the path and a one-line summary.

## Output (one verse)

```json
{
  "canon_ref": "PSA.23.1",
  "verse_uid": "lxx_swete:27.22.1",
  "source": "lxx_swete",
  "corpus_label": "Septuagint Greek (Swete LXX)",
  "original": "<text_display, verbatim>",
  "translation": "The Lord shepherds me, and I shall lack nothing.",
  "method": "machine",
  "translator": "claude:<model id>",
  "literal_notes": ["ποιμαίνει: present tense, 'shepherds / tends'", "Swete numbers this Psalm 22:1 (Greek numbering)"],
  "uncertainties": [],
  "web_reference": "web:PSA.23.1",
  "differences_from_web": ["LXX has a verb ('shepherds me') where the Hebrew has a noun ('my shepherd')"]
}
```

`corpus_label` is exactly `"Septuagint Greek (Swete LXX)"` for `lxx_swete` and `"New Testament Greek (SBLGNT)"` for `sblgnt`.

## Errors

Return an error object in place of a translation; never guess:

```json
{"error": "unknown_reference", "message": "JHN.22.1 is not in SBLGNT", "input": "JHN.22.1"}
```

| `error` | When |
|---|---|
| `empty_input` | No reference was given |
| `unknown_reference` | No row from the requested Greek corpus (e.g. an OT book missing from the LXX, or a verse that doesn't exist) |
| `wrong_language` | The reference exists only in Hebrew or English; point to `hebrew-to-english` |
| `check_failed` | The output still fails `bible-rag check translation` after one fix |

If the retrieval tools are unavailable (the command itself fails), report that error message verbatim. Do not translate from memory.
