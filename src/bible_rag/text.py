"""Text normalization. Use the same functions at index time and at query time."""

import re
import unicodedata

# Cantillation accents, meteg, paseq, sof pasuq and the upper/lower dots. Vowel points stay.
_HEB_MARKS = re.compile("[֑-ֽ֯׀׃-ׅ]")
# Standalone setumah (ס) / petuchah (פ): paragraph markers, not words.
_HEB_PARAGRAPH = re.compile(r"(?<!\S)[ספ](?!\S)")
# SBLGNT editorial signs: ⸂ ⸃ mark variant units, ⟦ ⟧ later additions. Kept for display.
_GRC_SIGNS = re.compile("[⸂⸃⟦⟧]")
_SPACES = re.compile(r"\s+")


def normalize(text, language):
    """The text that gets embedded."""
    text = unicodedata.normalize("NFC", text)
    if language == "grc":
        text = _GRC_SIGNS.sub("", text)
    if language == "he":
        text = text.replace("/", "").replace("־", " ")  # morpheme separators, maqaf
        text = _HEB_MARKS.sub("", text)
        text = _HEB_PARAGRAPH.sub("", text)
    return _SPACES.sub(" ", text).strip()


def fold(text):
    """Lexical-search form: no vowel points or accents, case-folded (ς -> σ).

    Index rows with fold(normalize(text, lang)) and run FTS queries through fold() too,
    so "αρχη" matches "ἀρχῇ" and unpointed Hebrew matches pointed text.
    """
    text = text.replace("/", "").replace("־", " ")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text).casefold()).strip()
