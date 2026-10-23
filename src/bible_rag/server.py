"""Local retrieval service. Loads bge-m3 once so agents never load their own copy.

    uv run bible-rag serve        # http://127.0.0.1:8765, docs at /docs
"""

import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from bible_rag.config import MODEL

Filter = str | list[str] | None


class SearchRequest(BaseModel):
    queries: list[str] = []
    lexical_queries: list[str] = []
    filters: dict[str, Filter] = {}
    k: int = Field(10, ge=1, le=100)
    candidates: int = Field(30, ge=1, le=200)
    mode: Literal["hybrid", "vector", "lexical"] = "hybrid"
    context: int = Field(0, ge=0, le=5)


def build_retriever():
    from bible_rag.config import load_model
    from bible_rag.retrieval import Retriever
    from bible_rag.store import VerseStore
    from bible_rag.vectors import VectorStore

    model = load_model()
    lock = threading.Lock()  # one encode at a time; parallel encodes only fight over the CPU

    def embed(texts):
        with lock:
            return model.encode(texts, normalize_embeddings=True).tolist()

    return Retriever(VerseStore(), VectorStore(), embed)


def create_app(retriever=None):
    """`retriever` is injected in tests; the real one is built at startup."""

    @asynccontextmanager
    async def lifespan(app):
        app.state.retriever = retriever or build_retriever()
        yield

    app = FastAPI(title="bible-rag retrieval", lifespan=lifespan)

    @app.get("/health")
    def health():
        r = app.state.retriever
        return {"status": "ok", "model": MODEL, "verses": r.store.count(),
                "vectors": r.vectors.count() if r.vectors else None}

    @app.post("/search")
    def search(req: SearchRequest):
        try:
            return app.state.retriever.search(**req.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/verse/{canon_ref}")
    def verse(canon_ref: str, source: str | None = None, context: int = 0):
        filters = {"source": source.split(",")} if source else None
        try:
            rows = app.state.retriever.store.by_ref(canon_ref.upper(), filters)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not rows:
            raise HTTPException(404, f"no verse {canon_ref}")
        if context:
            for row in rows:
                row["context"] = app.state.retriever.store.context(row["verse_uid"], context, context)
        return {"canon_ref": canon_ref.upper(), "verses": rows}

    return app
