---
name: hebrew-to-english
description: Translate retrieved Hebrew Old Testament verses (OSHB/WLC) into English for display, as a clearly labeled machine translation shown next to the untouched Hebrew. Use for verses from source oshb_wlc that a retrieval step returned.
when_to_use: A Hebrew specialist or the leader has a canon_ref or verse_uid from the oshb_wlc corpus and needs an English rendering of that exact verse. Not for translating the user's question (use english-to-hebrew) and not for Greek (use greek-to-english).
argument-hint: "<canon_ref or verse_uid> [more refs...] [--out runs/<id>/hebrew_translation.json]"
allowed-tools: Bash(uv run bible-rag *) Read Write
---

# Hebrew → English (passage translation)

Translate verses of the **Hebrew Old Testament (OSHB, based on the Westminster Leningrad Codex)** into English. The output is a **machine translation**. It is always shown next to the original Hebrew and is never presented as an established Bible translation.

Input: $ARGUMENTS

## Rules that are never broken

1. **The Hebrew is never changed.** Copy `text_display` from the tool output into `original` exactly, character for character. Never retype it, normalize it, or "fix" it.
2. **Only translate what the store returns.** If a reference isn't found, return an error. Never translate a verse from memory.
3. **Never pass off WEB or another published translation as your translation.** WEB is a comparison reference only. Translate the Hebrew yourself; don't copy WEB's wording and call it yours.
4. **Always label the output** `"method": "machine"` with `"translator": "claude:<your model id>"`.

## Steps

1. **Parse the input.** It holds one or more references, either `canon_ref` (`PSA.23.1`, English numbering) or `verse_uid` (`oshb_wlc:Ps.23.1`, native Hebrew numbering), plus an optional `--out` path.
2. **Create the draft.** It copies the Hebrew verbatim, fills in the references and labels, and adds the WEB text as `_web_text` for comparison:
   ```bash
   uv run bible-rag draft translation PSA.23.1 [more refs] --source oshb_wlc > runs/<id>/hebrew_translation.json
   ```
   Several refs give a JSON list. A ref missing from the Hebrew corpus becomes an `unknown_reference` error item; keep it. If the meaning depends on the surrounding verses, read them with `uv run bible-rag verse PSA.23.1 --source oshb_wlc --context 1`. Translate only the requested verses.
   **Edit only** `translation`, `translator`, `literal_notes`, `uncertainties` and `differences_from_web`. Never touch `original`, `canon_ref`, `verse_uid`, `source` or `corpus_label`. The `_`-prefixed fields are ignored by the check and can stay.
3. **Read the Hebrew correctly:**
   - `/` marks morpheme boundaries (prefix + word, word + suffix). It is not punctuation and is not translated.
   - Accent marks (cantillation) carry no meaning for translation.
   - `׃` (sof pasuq) ends the verse. A standalone `ס` or `פ` is a paragraph marker, not a word.
   - This text is the **written (ketiv) text**. Marginal readings (qere) were removed. If the verse has a well-known qere that changes the meaning, say so in `uncertainties`.
   - Render the divine name יהוה as "the LORD" (small capitals in print) and mention it in `literal_notes` the first time.
4. **Translate.** Aim for faithful, readable English that stays close to the Hebrew structure, not a paraphrase. Keep proper names in their usual English forms.
5. **Compare with WEB** (`_web_text`; `web_reference` is already set). In `differences_from_web`, list meaningful differences between your rendering and WEB's: word choice that changes the sense, tense or aspect, an added or missing phrase. Don't list mere style differences.
6. **Record uncertainty honestly** in `uncertainties`:
   - ambiguous grammar or vocabulary (give the alternative rendering);
   - idioms whose literal sense differs from their meaning;
   - textual issues (ketiv/qere);
   - **alignment**: if the verse's `alignment` is not `mapped`, say "verse numbering alignment is <partial|unmapped>: …";
   - a psalm title (`canon_ref` ending in `.0`) has no verse number in English Bibles: say so.
7. **Save the edited draft** at the `--out` path, or at `runs/skills/hebrew-<canon_ref>.json` if no path was given.
8. **Check it:**
   ```bash
   uv run bible-rag check translation <path>
   ```
   If `valid` is false, fix the reported fields and check again **once**. If it still fails, replace that item with a `check_failed` error object. Return the path and a one-line summary.

## Output (one verse)

```json
{
  "canon_ref": "PSA.23.1",
  "verse_uid": "oshb_wlc:Ps.23.1",
  "source": "oshb_wlc",
  "corpus_label": "Hebrew (OSHB/WLC)",
  "original": "<text_display, verbatim>",
  "translation": "A psalm of David. The LORD is my shepherd; I lack nothing.",
  "method": "machine",
  "translator": "claude:<model id>",
  "literal_notes": ["יְהוָה (YHWH) rendered 'the LORD'", "רֹעִי: 'my shepherd' (participle 'one who shepherds me')"],
  "uncertainties": [],
  "web_reference": "web:PSA.23.1",
  "differences_from_web": ["WEB omits the title 'A psalm of David', which English Bibles print above verse 1"]
}
```

`corpus_label` is always exactly `"Hebrew (OSHB/WLC)"`. `literal_notes`, `uncertainties` and `differences_from_web` may be empty lists.

## Errors

Return an error object in place of a translation; never guess:

```json
{"error": "unknown_reference", "message": "PSA.151.1 is not in the Hebrew corpus", "input": "PSA.151.1"}
```

| `error` | When |
|---|---|
| `empty_input` | No reference was given |
| `unknown_reference` | `bible-rag verse` finds no `oshb_wlc` row (e.g. a deuterocanonical or NT reference) |
| `wrong_language` | The reference is Greek-only (LXX/NT); point to `greek-to-english` |
| `check_failed` | The output still fails `bible-rag check translation` after one fix |

If the retrieval tools are unavailable (the command itself fails), report that error message verbatim. Do not translate from memory.
