"""Checks on the Chroma collection. The retrieval tests load bge-m3 (~2.3 GB RAM)."""

import pytest

import build_index


def test_collection_has_every_verse(collection, verses):
    assert collection.count() == len(verses)


def test_collection_uses_cosine_and_records_model(collection):
    assert collection.configuration["hnsw"]["space"] == "cosine"
    assert collection.metadata["embedding_model"] == build_index.MODEL


def test_stored_record_shape(collection):
    got = collection.get(ids=["web:GEN.1.1"], include=["embeddings", "metadatas", "documents"])
    assert len(got["embeddings"][0]) == 1024
    meta = got["metadatas"][0]
    assert set(build_index.META_COLUMNS) <= set(meta)
    assert meta["canon_ref"] == "GEN.1.1" and meta["language"] == "en"
    assert got["documents"][0].startswith("In the beginning")


def test_stored_vector_finds_itself(collection):
    vec = collection.get(ids=["sblgnt:JHN.3.16"], include=["embeddings"])["embeddings"][0]
    hit = collection.query(query_embeddings=[vec], n_results=1)
    assert hit["ids"][0][0] == "sblgnt:JHN.3.16"


def search(collection, model, text, language=None, k=10):
    vec = model.encode([text], normalize_embeddings=True)
    where = {"language": language} if language else None
    return collection.query(query_embeddings=vec, n_results=k, where=where)["ids"][0]


@pytest.mark.parametrize("query, language, expected_uid", [
    ("In the beginning God created the heavens and the earth", "en", "web:GEN.1.1"),
    ("The Lord is my shepherd, I shall not want", "en", "web:PSA.23.1"),
    ("For God so loved the world that he gave his only Son", "en", "web:JHN.3.16"),
])
def test_english_semantic_search(collection, model, query, language, expected_uid):
    assert expected_uid in search(collection, model, query, language)


# Paraphrased questions: wording differs from the verse, so only semantic search can match.
@pytest.mark.parametrize("query, expected_uid", [
    pytest.param("Love the people around you as much as you love yourself", "web:LEV.19.18",
                 marks=pytest.mark.xfail(reason="known vector-only miss (rank ~45): the verse is mostly "
                                                "about vengeance; hybrid search finds it, see docs/evaluation.md")),
    ("Jesus cried when his friend died", "web:JHN.11.35"),
    ("Should I be anxious about tomorrow?", "web:MAT.6.34"),
    ("Everything has its own time and season", "web:ECC.3.1"),
])
def test_paraphrase_search(collection, model, query, expected_uid):
    assert expected_uid in search(collection, model, query, "en", k=20)


def test_language_filter_returns_only_that_language(collection, model):
    vec = model.encode(["God's love"], normalize_embeddings=True)
    for language in ("he", "grc", "en"):
        metas = collection.query(query_embeddings=vec, n_results=10, where={"language": language})["metadatas"][0]
        assert metas and all(m["language"] == language for m in metas)


def test_testament_and_source_filter(collection, model):
    vec = model.encode(["the resurrection of the dead"], normalize_embeddings=True)
    where = {"$and": [{"testament": "NT"}, {"source": "sblgnt"}]}
    metas = collection.query(query_embeddings=vec, n_results=10, where=where)["metadatas"][0]
    assert metas and all(m["testament"] == "NT" and m["source"] == "sblgnt" for m in metas)


def test_get_verse_in_every_language(collection):
    got = collection.get(where={"canon_ref": "GEN.1.1"}, include=["metadatas"])
    assert {m["source"] for m in got["metadatas"]} == {"oshb_wlc", "lxx_swete", "web"}


# Cross-lingual recall: an English question should find the original-language verse.
# These are the real test of whether bge-m3 understands Koine Greek and Biblical Hebrew.
@pytest.mark.parametrize("query, language, expected_uid", [
    ("For God so loved the world that he gave his only Son", "grc", "sblgnt:JHN.3.16"),
    ("In the beginning was the Word, and the Word was with God", "grc", "sblgnt:JHN.1.1"),
    ("In the beginning God created the heavens and the earth", "he", "oshb_wlc:Gen.1.1"),
    ("Hear, O Israel: the Lord our God, the Lord is one", "he", "oshb_wlc:Deut.6.4"),
])
def test_cross_lingual_search(collection, model, query, language, expected_uid):
    assert expected_uid in search(collection, model, query, language)
