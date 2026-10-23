"""SQLite verse store: exact lookup, surrounding context and BM25 lexical (vectorless) search.

This is the source of truth for verse text. Vector search only returns verse_uids; the text
shown to users always comes from here.
"""

import re
import sqlite3
import threading
from pathlib import Path

from bible_rag.config import SQLITE
from bible_rag.text import fold

FILTERS = ("language", "source", "testament", "book_id", "edition")
VERSE_FIELDS = ("verse_uid", "source", "language", "testament", "book_id", "book_name", "chapter",
                "verse", "edition", "source_ref", "canon_ref", "alignment", "versification",
                "text_display")
# Dropped from lexical queries so "the"/"of" don't dominate an OR match. Hebrew and Greek
# queries come from the translation skills as content words, so they need no list.
EN_STOPWORDS = frozenset("""
    a an and are as at be been but by can could did do does for from had has have he her him his
    how i if in into is it its me my no not of on or our s she shall should so than that the their
    them then there these they this those to us was we were what when where which who whom why will
    with would you your
""".split())


def where_clause(filters, alias="v"):
    """SQL conditions and parameters for {field: value | [values]} filters."""
    parts, params = [], []
    for key, value in (filters or {}).items():
        if key not in FILTERS:
            raise ValueError(f"unknown filter {key!r}; allowed: {', '.join(FILTERS)}")
        if value is None:
            continue
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        parts.append(f"{alias}.{key} IN ({', '.join('?' * len(values))})")
        params.extend(values)
    return parts, params


def match_expression(text, phrase=False):
    """FTS5 MATCH string for free text, or None if nothing searchable is left.

    Every term is folded the same way as the index and quoted, so user text can't inject FTS5
    syntax (OR, NEAR, *, column filters). A phrase needs the words adjacent and in order;
    otherwise any term may match and BM25 ranks verses with more and rarer terms higher.
    """
    terms = re.findall(r"\w+", fold(text))
    if not terms:
        return None
    if phrase:
        return '"' + " ".join(terms) + '"'
    content = [t for t in terms if t not in EN_STOPWORDS] or terms
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(content))


class VerseStore:
    def __init__(self, path=SQLITE):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run scripts/build_index.py")
        self.uri = path.resolve().as_uri() + "?mode=ro"
        self._local = threading.local()  # one read-only connection per thread (FastAPI threadpool)

    @property
    def con(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.uri, uri=True)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def count(self):
        return self.con.execute("SELECT count(*) FROM verses").fetchone()[0]

    def get(self, verse_uids):
        """{verse_uid: record} for the given uids. Unknown uids are left out."""
        if not verse_uids:
            return {}
        sql = (f"SELECT {', '.join(VERSE_FIELDS)} FROM verses "
               f"WHERE verse_uid IN ({', '.join('?' * len(verse_uids))})")
        return {r["verse_uid"]: dict(r) for r in self.con.execute(sql, list(verse_uids))}

    def by_ref(self, canon_ref, filters=None):
        """Every source's text for one canonical reference, e.g. "JHN.3.16"."""
        parts, params = where_clause(filters)
        sql = (f"SELECT {', '.join('v.' + f for f in VERSE_FIELDS)} FROM verses v "
               f"WHERE {' AND '.join(['v.canon_ref = ?'] + parts)} ORDER BY v.id")
        return [dict(r) for r in self.con.execute(sql, [canon_ref] + params)]

    def context(self, verse_uid, before=2, after=2):
        """The verse and its neighbours in the same source, book, chapter and edition."""
        row = self.con.execute(
            "SELECT source, book_id, chapter, verse, edition FROM verses WHERE verse_uid = ?",
            (verse_uid,)).fetchone()
        if row is None:
            return []
        sql = (f"SELECT {', '.join(VERSE_FIELDS)} FROM verses WHERE source = ? AND book_id = ? "
               "AND chapter = ? AND edition = ? AND verse BETWEEN ? AND ? ORDER BY verse")
        params = (row["source"], row["book_id"], row["chapter"], row["edition"],
                  row["verse"] - before, row["verse"] + after)
        return [dict(r) for r in self.con.execute(sql, params)]

    def cross_refs(self, canon_ref, min_votes=None, testament=None, limit=50):
        """Links from one verse, strongest first, each labeled with its relation class."""
        from bible_rag.books import testament as testament_of
        from bible_rag.crossrefs import ALLUSION_MIN_VOTES, relation

        # A range target was stored once per verse; report it once, at its first verse.
        rows = self.con.execute(
            "SELECT min(id) AS first, to_range, votes, dataset FROM ("
            "  SELECT rowid AS id, coalesce(to_range, to_canon_ref) AS to_range, votes, dataset"
            "  FROM cross_refs WHERE from_canon_ref = ? AND votes >= ?) "
            "GROUP BY to_range, dataset ORDER BY votes DESC, first",
            (canon_ref, ALLUSION_MIN_VOTES if min_votes is None else min_votes)).fetchall()
        out = []
        for r in rows:
            to = self.con.execute("SELECT to_canon_ref FROM cross_refs WHERE rowid = ?",
                                  (r["first"],)).fetchone()[0]
            if testament and testament_of(to.split(".")[0]) != testament:
                continue
            out.append({"to": to, "votes": r["votes"], "relation": relation(r["votes"]),
                        "dataset": r["dataset"],
                        "to_range": r["to_range"] if r["to_range"] != to else None})
            if len(out) == limit:
                break
        return out

    def lexical(self, query, filters=None, k=20, phrase=False):
        """BM25 search: [{"verse_uid", "rank", "score"}], best first. Lower bm25 is better."""
        match = match_expression(query, phrase)
        if match is None:
            return []
        parts, params = where_clause(filters)
        sql = ("SELECT v.verse_uid, bm25(verses_fts) AS score FROM verses_fts "
               "JOIN verses v ON v.id = verses_fts.rowid "
               f"WHERE {' AND '.join(['verses_fts MATCH ?'] + parts)} ORDER BY score LIMIT ?")
        rows = self.con.execute(sql, [match] + params + [k]).fetchall()
        return [{"verse_uid": r["verse_uid"], "rank": i, "score": round(r["score"], 4)}
                for i, r in enumerate(rows, 1)]
