import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index  # noqa: E402


@pytest.fixture(scope="session")
def verses():
    if not build_index.PARQUET.exists():
        pytest.skip("verses.parquet not built; run scripts/build_index.py")
    return pd.read_parquet(build_index.PARQUET)


@pytest.fixture(scope="session")
def db():
    if not build_index.SQLITE.exists():
        pytest.skip("verses.db not built; run scripts/build_index.py")
    con = sqlite3.connect(build_index.SQLITE)
    yield con
    con.close()


@pytest.fixture(scope="session")
def collection():
    chromadb = pytest.importorskip("chromadb")
    if not build_index.CHROMA_DIR.exists():
        pytest.skip("vector_db not built; run scripts/build_index.py")
    client = chromadb.PersistentClient(path=str(build_index.CHROMA_DIR))
    return client.get_collection("verses_all")


@pytest.fixture(scope="session")
def model():
    return build_index.load_model()
