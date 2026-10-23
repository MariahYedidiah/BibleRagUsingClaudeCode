# Data sources

Every dataset the project uses: what it is, why it's here, where it lives and its license.
Raw files are in `data/raw/` (not committed). Re-download them from the URLs below.

## Biblical texts

| Source | `source` value | Language | Contents | License | Location |
|---|---|---|---|---|---|
| Open Scriptures Hebrew Bible (OSHB), based on the Westminster Leningrad Codex | `oshb_wlc` | Hebrew | Hebrew OT, plus per-word lemma (Strong's-based) and morphology | WLC text: public domain. OSHB lemma/morphology: CC BY 4.0 (credit "Open Scriptures Hebrew Bible") | `data/raw/oshb/` — github.com/openscriptures/morphhb |
| Swete, *The Old Testament in Greek According to the Septuagint* | `lxx_swete` | Greek | Greek OT (LXX) plus deuterocanon | **CC BY-SA 4.0** (see note) | `data/raw/lxx-swete/` |
| SBL Greek New Testament (SBLGNT) | `sblgnt` | Greek | Greek NT | CC BY 4.0 | `data/raw/sblgnt-tei/` |
| World English Bible (WEB) | `web` | English | The only English version in the project | Public domain ("World English Bible" is a trademark of eBible.org) | `data/raw/web/` — ebible.org |

**Share-alike note:** Swete is CC BY-SA. Anything derived from it (the LXX rows in `verses.parquet`, `verses.db` and the embeddings) must be shared under CC BY-SA 4.0 if it is ever distributed. Today it isn't: `data/` is git-ignored.

## Supporting data

### 1. OpenBible.info cross-references

- **What it is:** a community-built list of which verses refer to which, about 345,000 verse-to-verse links. "Mark 1:3 → Isaiah 40:3" is one link. Each link has a **vote count** for how many people agree it's real. The data comes mainly from the public-domain *Treasury of Scripture Knowledge*, scored by OpenBible.info users.
- **What it's for:** the NT→OT workflow. When an agent finds a NT verse, it looks up which OT passages that verse points to. The validator only accepts a link as **"verified"** if it is in this dataset with enough votes (`XREF_MIN_VOTES` in `src/bible_rag/validator.py`). Without it, every cross-reference would be the model's guess, which is exactly the fabrication the spec forbids.
- **Format:** `cross_references.txt`, tab-separated: `From Verse`, `To Verse`, `Votes`. References use OSIS-style book names (`Gen.1.1`, `Ps.23.1`, `Matt.5.3`). About 88k targets are ranges (`Isa.40.3-Isa.40.5`). 1,228 links have negative votes, meaning users rejected them.
- **License:** CC BY 4.0. Credit "OpenBible.info".
- **Source:** https://www.openbible.info/labs/cross-references/, file https://a.openbible.info/data/cross-references.zip (downloaded 2026-10-24, file dated 2026-10-19).
- **Location:** `data/raw/openbible/`.

### 2. LXX ↔ English verse-number mapping (STEPBible TVTMS)

- **What it is:** a table saying which Greek Old Testament verse corresponds to which English verse. They don't always line up. Most Psalms are numbered one lower in the LXX (LXX Psalm 22 = English Psalm 23), Jeremiah's chapters are in a different order, and Malachi 4 is part of chapter 3 in some traditions.
- **What it's for:** without it, "PSA.23.1" in the LXX rows is actually a different psalm than "PSA.23.1" in WEB. With the mapping, the Hebrew, Greek and English versions of the same verse share one `canon_ref`. Cross-language search, side-by-side display and the validator's alignment check all depend on that.
- **The dataset:** *TVTMS — Translators Versification Traditions with Methodology for Standardisation*, from STEPBible / Tyndale House Cambridge. It maps Hebrew, Greek, Latin and other numbering traditions to the English (KJV) standard. Each row comes with **tests** that tell which tradition a given Bible follows, e.g. "if Gen 32 ends at verse 33, this Bible uses Hebrew numbering". That matters because Swete mixes traditions: its Psalms use Greek numbering, but its Malachi and Joel use English chapter divisions.
- **Also covers the NT:** SBLGNT differs from KJV numbering at Acts 19:40–41, 2 Cor 13:12–14, Phil 1:16–17, 3 John 1:14–15 and Rev 12:18–13:1. TVTMS lists those too.
- **License:** CC BY 4.0. Credit "STEP Bible" with a link to www.STEPBible.org. Changes must be noted for later users. STEPBible asks that the data itself not be redistributed: point people to github.com/STEPBible/STEPBible-Data instead.
- **Source:** https://github.com/STEPBible/STEPBible-Data, folder `Versification/`, file "TVTMS - Translators Versification Traditions with Methodology for Standardisation for Eng+Heb+Lat+Grk+Others - STEPBible.org CC BY.txt" (downloaded 2026-10-24).
- **Location:** `data/raw/stepbible/TVTMS.txt`.

### 3. OSHB VerseMap (Hebrew ↔ English)

- **What it is:** `VerseMap.xml`, shipped with OSHB. It lists the 1,978 verses where WLC and KJV numbering differ (1,971 full matches, 7 partial), e.g. Hebrew Gen 32:1 = English Gen 31:55, Hebrew Mal 3:19 = English Mal 4:1.
- **What it's for:** the Hebrew side of the canonical alignment. It is used instead of TVTMS for Hebrew because it was written for exactly this text.
- **Psalm titles:** Hebrew numbers most psalm titles as verse 1, so Hebrew Ps 3:2 = English Ps 3:1. The title itself has no English verse. Titles get verse **0** in `canon_ref` (e.g. `PSA.3.0`), so they never collide with the real verse 1.
- **License:** part of OSHB (CC BY 4.0). **Location:** `data/raw/oshb/wlc/VerseMap.xml`.

## Changes we make to the source data

CC BY and CC BY-SA require noting changes. `extract_verses.py` and `src/bible_rag/` change the texts as follows; the raw files in `data/raw/` are never edited.

- **OSHB:** `<note>` elements are dropped (English editorial notes, KJV numbering markers, marginal qere readings). Morpheme separators `/` and cantillation marks are removed from the embedded/search text, not from the displayed text.
- **Swete LXX:** psalm/ode titles that carried a stale verse number become verse 0; Ps 88.84 is corrected to 88.48; digitization artifacts are removed (parenthesized alternate verse numbers, digits and superscripts glued to words, Roman numerals, stray Latin sigla) and Latin look-alike letters inside Greek words are replaced by the Greek letters. About 100 verses with OCR errors inside words are left as they are.
- **SBLGNT:** ⸂ ⸃ ⟦ ⟧ editorial signs are kept for display and removed from the embedded/search text.
- **Verse numbering:** each verse gets an English (KJV-numbered) `canon_ref` from VerseMap.xml (Hebrew), TVTMS (LXX) and the TVTMS SBLGNT table; native numbers are kept in `source_ref`. TVTMS data itself is not modified, only evaluated.
- **OpenBible:** target ranges within a chapter are stored once per verse; votes are unchanged.

## Model

| Model | Use | License | Location |
|---|---|---|---|
| `BAAI/bge-m3` | Multilingual embeddings for vector search, loaded in bfloat16 | MIT | `.cache/huggingface/` (not committed) |

## Attribution text

For any published output (a demo, a report, a shared dataset):

> Hebrew text: Westminster Leningrad Codex (public domain), with morphology from the Open Scriptures Hebrew Bible (CC BY 4.0). Greek OT: Swete's Septuagint (CC BY-SA 4.0). Greek NT: SBL Greek New Testament (CC BY 4.0). English: World English Bible (public domain). Cross-references: OpenBible.info (CC BY 4.0). Versification data: STEP Bible, www.STEPBible.org (CC BY 4.0).
