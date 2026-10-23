"""
download_opusmt_models.py

Pre-downloads and caches Helsinki-NLP OPUS-MT transformers models locally for:
- Hebrew (he) <-> English (en)
- Greek (el) <-> English (en)
"""

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def cache_opus_models():
    # Corrected model names matching Hugging Face repository identifiers
    opus_models = [
        "Helsinki-NLP/opus-mt-tc-big-he-en",  # Hebrew to English (tc-big format)
        "Helsinki-NLP/opus-mt-en-he",  # English to Hebrew
        "Helsinki-NLP/opus-mt-tc-big-el-en",  # Greek to English (tc-big format)
        "Helsinki-NLP/opus-mt-en-el",  # English to Greek
    ]

    print("Pre-downloading and caching Helsinki-NLP OPUS-MT models...\n")

    for model_name in opus_models:
        print(f"Caching model: {model_name}")
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
            print(f"✅ Successfully cached {model_name}\n")
        except Exception as e:
            print(f"❌ Failed to download {model_name}: {e}\n")

    print("==========================================")
    print("Helsinki-NLP OPUS-MT model caching complete!")
    print("==========================================")


if __name__ == "__main__":
    cache_opus_models()