"""Chroma vector store: semantic search over the bge-m3 embeddings (vector retrieval)."""

from bible_rag.config import CHROMA_DIR, COLLECTION
from bible_rag.store import FILTERS


def chroma_where(filters):
    """Chroma `where` for {field: value | [values]} filters, or None for no filter."""
    clauses = []
    for key, value in (filters or {}).items():
        if key not in FILTERS:
            raise ValueError(f"unknown filter {key!r}; allowed: {', '.join(FILTERS)}")
        if value is None:
            continue
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        clauses.append({key: values[0]} if len(values) == 1 else {key: {"$in": values}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class VectorStore:
    def __init__(self, path=CHROMA_DIR, name=COLLECTION):
        import chromadb

        self.collection = chromadb.PersistentClient(path=str(path)).get_collection(name)

    def count(self):
        return self.collection.count()

    def search(self, embedding, filters=None, k=20):
        """[{"verse_uid", "rank", "score"}], best first. Score is cosine similarity."""
        res = self.collection.query(query_embeddings=[embedding], n_results=k,
                                    where=chroma_where(filters), include=["distances"])
        return [{"verse_uid": uid, "rank": i, "score": round(1 - dist, 4)}
                for i, (uid, dist) in enumerate(zip(res["ids"][0], res["distances"][0]), 1)]
