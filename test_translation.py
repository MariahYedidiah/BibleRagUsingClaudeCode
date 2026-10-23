"""
test_translation.py

Verifies local offline translation functionality for Hebrew and Greek.
"""

import unicodedata
import argostranslate.translate
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def strip_accents(text: str) -> str:
    """Normalizes polytonic Greek text to monotonic Greek."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def test_argos():
    print("\n--- Testing Argos Translate ---")
    hebrew_text = "שָׁלוֹם"
    greek_text = "ειρήνη"

    try:
        translated_he = argostranslate.translate.translate(
            hebrew_text, "he", "en"
        )
        print(f"Hebrew ('{hebrew_text}') -> English: {translated_he}")
    except Exception as e:
        print(f"Argos Hebrew error: {e}")

    try:
        translated_el = argostranslate.translate.translate(
            greek_text, "el", "en"
        )
        print(f"Greek ('{greek_text}') -> English: {translated_el}")
    except Exception as e:
        print(f"Argos Greek error: {e}")


def test_opus():
    print("\n--- Testing Helsinki-NLP OPUS-MT ---")

    # 1. Hebrew Test
    hebrew_text = "בראשית ברא אלהים"
    try:
        model_name = "Helsinki-NLP/opus-mt-tc-big-he-en"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

        # Prepend target language prefix required by tc-big models
        prompt = f">>en<< {hebrew_text}"
        inputs = tokenizer(prompt, return_tensors="pt")
        outputs = model.generate(
            **inputs, max_length=64, num_beams=4, no_repeat_ngram_size=3
        )
        result = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print(f"Hebrew ('{hebrew_text}') -> English: {result}")
    except Exception as e:
        print(f"OPUS-MT Hebrew error: {e}")

    # 2. Greek Test
    raw_greek = "Ἐν ἀρχῇ ἦν ὁ λόγος"
    normalized_greek = strip_accents(raw_greek)

    try:
        model_name = "Helsinki-NLP/opus-mt-tc-big-el-en"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

        # Prepend target language prefix required by tc-big models
        prompt = f">>en<< {normalized_greek}"
        inputs = tokenizer(prompt, return_tensors="pt")
        outputs = model.generate(
            **inputs, max_length=64, num_beams=4, no_repeat_ngram_size=3
        )
        result = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print(f"Greek Raw: '{raw_greek}'")
        print(f"Greek Normalized: '{normalized_greek}'")
        print(f"Greek -> English: {result}")
    except Exception as e:
        print(f"OPUS-MT Greek error: {e}")


if __name__ == "__main__":
    test_argos()
    test_opus()