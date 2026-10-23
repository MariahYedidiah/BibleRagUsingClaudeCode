"""Unit tests for normalization and book-code mapping. No built data needed."""

import pandas as pd

import build_index
from bible_rag.books import BOOK_NAMES, LXX_FILES, NT, OSIS_TO_USFM, OT, lxx_book
from bible_rag import books
from bible_rag.text import fold, normalize


def test_hebrew_normalize_drops_cantillation_separators_and_paragraph_marks():
    raw = "נֹ֥חַ שֵׁ֖ם חָ֥ם וָ/יָֽפֶת׃ ס"
    assert normalize(raw, "he") == "נֹחַ שֵׁם חָם וָיָפֶת"


def test_hebrew_normalize_keeps_vowel_points():
    assert normalize("בְּרֵאשִׁ֖ית", "he") == "בְּרֵאשִׁית"


def test_hebrew_maqaf_becomes_space():
    assert normalize("אֶת־הָאָרֶץ", "he") == "אֶת הָאָרֶץ"


def test_fold_strips_all_points_for_search():
    assert fold("נֹחַ שֵׁם") == "נח שם"


def test_fold_makes_greek_accent_and_case_insensitive():
    assert fold("ΕΝ ΑΡΧΗ") == fold("ἐν ἀρχῇ") == "εν αρχη"
    assert fold("λόγος") == "λογοσ"  # final sigma folds to σ, so queries match either form


def test_non_hebrew_text_is_only_whitespace_normalized():
    assert normalize("  In the   beginning ", "en") == "In the beginning"
    assert normalize("καὶ  ὁ", "grc") == "καὶ ὁ"


def test_every_osis_code_maps_to_an_ot_book():
    assert sorted(OSIS_TO_USFM.values()) == sorted(OT)


def test_lxx_codes_are_known_usfm_books():
    assert all(code in BOOK_NAMES for code, _ in LXX_FILES.values())


def test_lxx_2_esdras_splits_into_ezra_and_nehemiah():
    assert lxx_book("18", 10) == ("EZR", 10, "")
    assert lxx_book("18", 11) == ("NEH", 1, "")
    assert lxx_book("18", 23) == ("NEH", 13, "")


def test_lxx_daniel_editions():
    assert lxx_book("56", 1) == ("DAN", 1, "og")
    assert lxx_book("57", 1) == ("DAN", 1, "th")


def test_testament():
    assert books.testament("GEN") == "OT"
    assert books.testament("REV") == "NT"
    assert books.testament("SIR") == "DC"
    assert len(set(OT) & set(NT)) == 0


def test_cache_key_changes_when_text_changes():
    a = pd.DataFrame({"verse_uid": ["web:GEN.1.1"], "text_norm": ["In the beginning"]})
    b = a.assign(text_norm=["In the beginning,"])
    assert build_index.cache_key(a)[0] != build_index.cache_key(b)[0]
    assert build_index.cache_key(a)[0] == build_index.cache_key(a.copy())[0]
