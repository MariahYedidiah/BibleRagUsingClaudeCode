"""Build the verse store and the vector indexes.

    data/processed/verses/*.jsonl
      -> data/processed/verses.parquet        canonical table: USFM book codes, text_norm, text_search
      -> data/verses.db                       SQLite verse store + FTS5 lexical index
      -> data/processed/embeddings/<model>/   cached embeddings, resumable
      -> data/vector_db                       Chroma: verses_all, filter by metadata for one language

    uv run python scripts/build_index.py                 # everything
    uv run python scripts/build_index.py --skip-vectors  # Parquet + SQLite only (fast)
    uv run python scripts/build_index.py --limit 300     # smoke-test the vector path on 300 verses

Embedding is CPU-bound and can take hours. It writes one cache file per SHARD verses, so
stopping it (Ctrl+C) and running again continues where it stopped.

canon_ref is each verse's English (KJV) reference, mapped from native numbering by
src/bible_rag/versification.py; `alignment` says how exact that mapping is. The SQLite store
also gets the OpenBible cross-references. Sources and licenses: docs/data-sources.md.
"""

import argparse
import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

import bible_rag
from bible_rag import crossrefs, versification
from bible_rag.books import BOOK_NAMES, OSIS_TO_USFM, lxx_book, testament
from bible_rag.config import (CHROMA_DIR, COLLECTION, DATA, EMB_ROOT, JSONL_DIR, MODEL,
                              PARQUET, SQLITE, load_model)
from bible_rag.text import fold, normalize

VERSE_MAP = DATA / "raw" / "oshb" / "wlc" / "VerseMap.xml"
TVTMS = DATA / "raw" / "stepbible" / "TVTMS.txt"
CROSS_REFS = DATA / "raw" / "openbible" / "cross_references.txt"

EMBED_BATCH = 16   # verses per forward pass; lower it if you run out of RAM
SHARD = 2048       # verses per cached embedding file (the unit of resume)

# One multilingual collection. With a single embedding model, per-language collections would
# hold the same vectors as a `where={"language": ...}` filter on this one, at twice the disk.
# Add entries here (name -> language) only if a language gets its own model.
COLLECTIONS = {COLLECTION: None}
# Chroma's defaults (16 neighbors, ef 100) left ~2% of verses unreachable by their own vector:
# a self-query of 300 random verses found itself only 98% of the time.
HNSW = {"space": "cosine", "max_neighbors": 32, "ef_construction": 200, "ef_search": 200}
VERSIFICATION = {"web": "kjv", "sblgnt": "kjv", "oshb_wlc": "wlc", "lxx_swete": "lxx"}
COLUMNS = ["verse_uid", "source", "language", "testament", "book_id", "book_name", "chapter",
           "verse", "edition", "source_ref", "canon_ref", "alignment", "versification",
           "text_display", "text_norm", "text_search"]
META_COLUMNS = ["source", "language", "testament", "book_id", "chapter", "verse", "edition",
                "canon_ref", "alignment", "versification"]

SCHEMA = """
CREATE TABLE verses (
    id            INTEGER PRIMARY KEY,
    verse_uid     TEXT NOT NULL UNIQUE,
    source        TEXT NOT NULL,
    language      TEXT NOT NULL,
    testament     TEXT NOT NULL,
    book_id       TEXT NOT NULL,
    book_name     TEXT NOT NULL,
    chapter       INTEGER NOT NULL,
    verse         INTEGER NOT NULL,
    edition       TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    canon_ref     TEXT NOT NULL,
    alignment     TEXT NOT NULL,
    versification TEXT NOT NULL,
    text_display  TEXT NOT NULL,
    text_norm     TEXT NOT NULL,
    text_search   TEXT NOT NULL
);
CREATE INDEX verses_canon ON verses (canon_ref, language);
CREATE INDEX verses_book ON verses (book_id, chapter, verse);
CREATE VIRTUAL TABLE verses_fts USING fts5(
    text_search, content='verses', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
"""


def canonical_book(row):
    """(USFM book code, chapter, edition) for a raw JSONL row from any source."""
    if row.source == "oshb_wlc":
        return OSIS_TO_USFM[row.source_ref.split(".")[0]], row.chapter, ""
    if row.source == "lxx_swete":
        return lxx_book(row.source_ref.split(".")[0], row.chapter)
    return row.book_id, row.chapter, ""


def align(df):
    """(canon_ref, alignment) per row, from each source's versification mapping."""
    out = {}
    heb = df[df["source"] == "oshb_wlc"]
    out.update(versification.map_hebrew(zip(heb["verse_uid"], heb["source_ref"]),
                                        versification.load_verse_map(VERSE_MAP)))
    tvtms = versification.load_tvtms(TVTMS)
    lxx = df[df["source"] == "lxx_swete"]
    for _, edition in lxx.groupby("edition"):
        out.update(versification.map_lxx(
            list(zip(edition["verse_uid"], edition["book_id"], edition["chapter"], edition["verse"],
                     edition["text_display"].str.split().str.len())), tvtms))
    native = df["book_id"] + "." + df["chapter"].astype(str) + "." + df["verse"].astype(str)
    for uid, source, ref in zip(df["verse_uid"], df["source"], native):
        if uid not in out:  # WEB follows KJV; SBLGNT differs at a handful of verses
            out[uid] = versification.SBLGNT_MAP.get(ref, (ref, "mapped")) if source == "sblgnt" \
                else (ref, "mapped")
    return [out[uid][0] for uid in df["verse_uid"]], [out[uid][1] for uid in df["verse_uid"]]


def build_parquet():
    sources = sorted(JSONL_DIR.glob("*.jsonl"))
    if not sources:
        raise SystemExit(f"No JSONL in {JSONL_DIR}. Run extract_verses.py first.")
    # Rebuild when the data, the mapping tables, or the code that shapes the table changed.
    inputs = sources + [VERSE_MAP, TVTMS, __file__] + list(Path(bible_rag.__file__).parent.glob("*.py"))
    if PARQUET.exists() and PARQUET.stat().st_mtime > max(Path(p).stat().st_mtime for p in inputs):
        print(f"1. Parquet is up to date: {PARQUET}")
        return pd.read_parquet(PARQUET)

    print("1. Building canonical Parquet from JSONL...")
    raw = pd.concat([pd.read_json(p, lines=True, encoding="utf-8", dtype=False) for p in sources],
                    ignore_index=True)
    books = [canonical_book(r) for r in raw.itertuples(index=False)]
    df = pd.DataFrame({
        "verse_uid": raw["source"] + ":" + raw["source_ref"],
        "source": raw["source"],
        "language": raw["language"],
        "book_id": [b for b, _, _ in books],
        "chapter": [c for _, c, _ in books],
        "verse": raw["verse"],
        "edition": [e for _, _, e in books],
        "source_ref": raw["source_ref"],
        "text_display": raw["text"],
    })
    df["testament"] = df["book_id"].map(testament)
    df["book_name"] = df["book_id"].map(lambda b: BOOK_NAMES.get(b, b))
    df["canon_ref"], df["alignment"] = align(df)
    df["versification"] = df["source"].map(VERSIFICATION)
    df["text_norm"] = [normalize(t, lang) for t, lang in zip(df["text_display"], df["language"])]
    df["text_search"] = df["text_norm"].map(fold)
    df = df[df["text_norm"] != ""][COLUMNS].reset_index(drop=True)

    dupes = df.loc[df["verse_uid"].duplicated(), "verse_uid"]
    if not dupes.empty:
        raise SystemExit(f"Duplicate verse_uid values, fix the parser first: {dupes.head().tolist()}")

    PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET, index=False)
    print(f"   {len(df):,} verses -> {PARQUET}")
    print(df.groupby(["source", "testament"]).size().to_string())
    print(df.groupby(["source", "alignment"]).size().unstack(fill_value=0).to_string())
    return df


def build_sqlite(df):
    print("2. Building SQLite verse store + FTS5 index...")
    # Build into a temp file and swap it in, so a crash never leaves a half-built database.
    tmp = SQLITE.with_name(SQLITE.name + ".tmp")
    tmp.unlink(missing_ok=True)
    insert = (f"INSERT INTO verses ({', '.join(COLUMNS)}) "
              f"VALUES ({', '.join(':' + c for c in COLUMNS)})")
    con = sqlite3.connect(tmp)
    try:
        with con:
            con.executescript(SCHEMA)
            con.executemany(insert, df[COLUMNS].to_dict("records"))
            con.execute("INSERT INTO verses_fts(verses_fts) VALUES ('rebuild')")
            n_xrefs = crossrefs.load(con, CROSS_REFS)
    finally:
        con.close()
    tmp.replace(SQLITE)
    print(f"   {len(df):,} verses, {n_xrefs:,} cross-references -> {SQLITE}")


def cache_key(df):
    """verse_uid plus a hash of text_norm, so edited text gets re-embedded."""
    digest = df["text_norm"].map(lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()[:16])
    return df["verse_uid"] + "|" + digest


def embed(df):
    """Embed text_norm into cache shards, skipping verses that are already cached."""
    cache = EMB_ROOT / MODEL.replace("/", "__")
    cache.mkdir(parents=True, exist_ok=True)
    shards = sorted(cache.glob("part-*.parquet"))
    done = set()
    for path in shards:
        done.update(pq.read_table(path, columns=["key"]).column("key").to_pylist())

    keys = cache_key(df)
    todo = df[~keys.isin(done)].assign(key=keys)
    print(f"3. Embedding with {MODEL}: {len(df) - len(todo):,} cached, {len(todo):,} to go")
    if todo.empty:
        return cache

    model = load_model()

    next_part = max((int(p.stem.split("-")[1]) for p in shards), default=-1) + 1
    for start in tqdm(range(0, len(todo), SHARD), desc="   shards", unit="shard"):
        part = todo.iloc[start:start + SHARD]
        vecs = model.encode(part["text_norm"].tolist(), batch_size=EMBED_BATCH,
                            normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)
        table = pa.table({
            "key": part["key"].tolist(),
            "embedding": pa.FixedSizeListArray.from_arrays(pa.array(vecs.ravel()), vecs.shape[1]),
        })
        path = cache / f"part-{next_part:05d}.parquet"
        tmp = path.with_suffix(".tmp")
        pq.write_table(table, tmp)
        tmp.replace(path)
        next_part += 1
    return cache


def build_chroma(df, cache):
    import chromadb

    print("4. Loading cached embeddings into Chroma...")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    existing = {getattr(c, "name", c) for c in client.list_collections()}
    collections = {}
    for name, language in COLLECTIONS.items():
        # Recreate from the cache every time: no stale ids, no leftover distance setting.
        if name in existing:
            client.delete_collection(name)
        collections[name] = (language, client.create_collection(
            name,
            configuration={"hnsw": HNSW},
            metadata={"embedding_model": MODEL},
            embedding_function=None,
        ))

    rows = df.assign(key=cache_key(df)).set_index("key")
    batch = client.get_max_batch_size()
    loaded = set()
    for path in tqdm(sorted(cache.glob("part-*.parquet")), desc="   shards", unit="shard"):
        table = pq.read_table(path)
        keys = table.column("key").to_pylist()
        vecs = table.column("embedding").combine_chunks().flatten().to_numpy().reshape(len(keys), -1)
        keep = [i for i, k in enumerate(keys) if k in rows.index and k not in loaded]
        if not keep:
            continue
        part = rows.loc[[keys[i] for i in keep]]
        vecs = vecs[keep]
        loaded.update(part.index)
        for language, collection in collections.values():
            mask = np.ones(len(part), bool) if language is None else (part["language"] == language).to_numpy()
            add(collection, part[mask], vecs[mask], batch)

    for name, (_, collection) in collections.items():
        print(f"   {name}: {collection.count():,} verses")
    if len(loaded) < len(df):
        print(f"   WARNING: {len(df) - len(loaded):,} verses have no cached embedding.")


def add(collection, part, vecs, batch):
    metadatas = part[META_COLUMNS].to_dict("records")
    for i in range(0, len(part), batch):
        collection.add(
            ids=part["verse_uid"].iloc[i:i + batch].tolist(),
            embeddings=vecs[i:i + batch],
            documents=part["text_display"].iloc[i:i + batch].tolist(),
            metadatas=metadatas[i:i + batch],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-vectors", action="store_true", help="build Parquet and SQLite only")
    parser.add_argument("--limit", type=int, help="embed and index only a random sample of N verses")
    args = parser.parse_args()

    df = build_parquet()
    build_sqlite(df)
    if args.skip_vectors:
        return
    if args.limit:
        df = df.sample(n=min(args.limit, len(df)), random_state=0)
    cache = embed(df)
    build_chroma(df, cache)


if __name__ == "__main__":
    main()
