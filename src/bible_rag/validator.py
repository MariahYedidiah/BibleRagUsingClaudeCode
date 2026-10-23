"""Anti-fabrication checks for an Answer, against the verse store.

    bible-rag validate runs/<id>/answer.json

Instructions can't guarantee an agent never invents scripture, so every quoted text, reference
and cross-reference is checked against the data. Errors make the answer invalid; warnings are
shown but don't.
"""

import re
import unicodedata

from pydantic import ValidationError

from bible_rag.books import BOOK_NAMES
from bible_rag.schemas import Answer

XREF_MIN_VOTES = 10  # "verified" threshold; tune once the cross-reference data is loaded
_SPACES = re.compile(r"\s+")


def same_text(a):
    return _SPACES.sub(" ", unicodedata.normalize("NFC", a)).strip()


def display_ref(canon_ref):
    book, chapter, verse = canon_ref.split(".")
    return f"{BOOK_NAMES.get(book, book)} {chapter}:{verse}"


def validate(data, store):
    """{"valid", "errors", "warnings"}; each issue has a JSON path, a code and a message."""
    errors, warnings = [], []

    def error(path, code, message):
        errors.append({"path": path, "code": code, "message": message})

    def warn(path, code, message):
        warnings.append({"path": path, "code": code, "message": message})

    try:
        answer = Answer.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            error(".".join(str(p) for p in err["loc"]) or "$", "schema", err["msg"])
        return {"valid": False, "errors": errors, "warnings": warnings}

    con = store.con
    has_xrefs = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cross_refs'").fetchone()
    rows = store.get([t.verse_uid for p in answer.passages for t in p.texts if t.verse_uid])

    for i, passage in enumerate(answer.passages):
        at = f"passages[{i}]"
        if not con.execute("SELECT 1 FROM verses WHERE canon_ref = ?", (passage.canon_ref,)).fetchone():
            error(at, "unknown_reference", f"{passage.canon_ref} is not in the verse store")
        if passage.display_ref != display_ref(passage.canon_ref):
            warn(at, "display_ref", f"{passage.display_ref!r} doesn't match {passage.canon_ref} "
                                    f"(expected {display_ref(passage.canon_ref)!r})")

        quoted = {t.verse_uid for t in passage.texts if t.verse_uid}
        for j, entry in enumerate(passage.texts):
            path = f"{at}.texts[{j}]"
            if entry.kind == "machine_translation":
                if entry.translates not in quoted:
                    error(path, "orphan_translation",
                          f"translates {entry.translates!r}, which isn't quoted in this passage")
                continue
            row = rows.get(entry.verse_uid)
            if row is None:
                error(path, "unknown_verse", f"{entry.verse_uid} is not in the verse store")
                continue
            for field in ("source", "language"):
                if getattr(entry, field) != row[field]:
                    error(path, f"wrong_{field}", f"says {getattr(entry, field)!r}, "
                                                  f"store has {row[field]!r} for {entry.verse_uid}")
            stored, given = same_text(row["text_display"]), same_text(entry.text)
            if entry.excerpt:
                if given not in stored:
                    error(path, "text_mismatch", f"excerpt is not part of {entry.verse_uid}")
            elif given != stored:
                error(path, "text_mismatch", f"text differs from {entry.verse_uid} in the verse store")
            if row["canon_ref"] != passage.canon_ref:
                if passage.alignment == "mapped":
                    error(path, "misaligned", f"{entry.verse_uid} is {row['canon_ref']}, "
                                              f"not {passage.canon_ref}, but alignment is 'mapped'")
                else:
                    warn(path, "unaligned", f"{entry.verse_uid} is {row['canon_ref']} "
                                            f"(alignment {passage.alignment})")

        for j, xref in enumerate(passage.cross_refs):
            path = f"{at}.cross_refs[{j}]"
            if xref.relation != "verified":
                continue
            if not has_xrefs:
                error(path, "unverifiable", "no cross_refs table loaded; label it "
                                            "possible_allusion or thematic instead")
                continue
            hit = con.execute(
                "SELECT votes FROM cross_refs WHERE from_canon_ref = ? AND to_canon_ref = ? "
                "AND dataset = ?", (passage.canon_ref, xref.to, xref.dataset)).fetchone()
            if hit is None:
                error(path, "unknown_cross_ref",
                      f"{passage.canon_ref} -> {xref.to} is not in {xref.dataset}")
            elif hit[0] < XREF_MIN_VOTES:
                error(path, "weak_cross_ref", f"{hit[0]} votes < {XREF_MIN_VOTES}; not 'verified'")

    if answer.confidence.level == "insufficient" and answer.passages and not answer.clarifying_question:
        warn("confidence", "insufficient", "insufficient evidence but no clarifying question")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
