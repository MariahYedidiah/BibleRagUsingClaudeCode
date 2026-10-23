"""Paths and model settings shared by the build script, the retrieval service and the CLI."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
JSONL_DIR = DATA / "processed" / "verses"
PARQUET = DATA / "processed" / "verses.parquet"
SQLITE = DATA / "verses.db"
EMB_ROOT = DATA / "processed" / "embeddings"
CHROMA_DIR = DATA / "vector_db"
COLLECTION = "verses_all"

MODEL = "BAAI/bge-m3"
DTYPE = "bfloat16"  # halves model RAM (~1.1 GB); fp32 needs ~4 GB and swapped on this machine
MAX_SEQ_LEN = 256   # verses are short; bge-m3's default of 8192 only wastes memory

SERVICE_HOST = os.environ.get("BIBLE_RAG_HOST", "127.0.0.1")
SERVICE_PORT = int(os.environ.get("BIBLE_RAG_PORT", "8765"))

# Keep the ~2.3 GB model download off C:, which is nearly full on this machine.
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer  # heavy import, only needed here

    model = SentenceTransformer(MODEL, model_kwargs={"dtype": getattr(torch, DTYPE)})
    model.max_seq_length = MAX_SEQ_LEN
    return model
