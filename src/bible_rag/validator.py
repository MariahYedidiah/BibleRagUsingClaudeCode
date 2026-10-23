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
from bible_rag.crossrefs import VERIFIED_MIN_VOTES as XREF_MIN_VOTES
from bible_rag.schemas import Answer, PassageTranslation, QueryTerms, SkillError

CORPUS_LABELS = {"oshb_wlc": "Hebrew (OSHB/WLC)", "lxx_swete": "Septuagint Greek (Swete LXX)",
                 "sblgnt": "New Testament Greek (SBLGNT)"}
CORPUS_SOURCES = {"oshb_wlc": ["oshb_wlc"], "lxx_swete": ["lxx_swete"], "sblgnt": ["sblgnt"],
                  "lxx_swete+sblgnt": ["lxx_swete", "sblgnt"]}
_SPACES = re.compile(r"\s+")


def same_text(a):
    return _SPACES.sub(" ", unicodedata.normalize("NFC", a)).strip()


def display_ref(canon_ref):
    book, chapter, verse = canon_ref.split(".")
    return f"{BOOK_NAMES.get(book, book)} {chapter}:{verse}"


def _result(errors, warnings):
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _schema_errors(e):
    return [{"path": ".".join(str(p) for p in err["loc"]) or "$", "code": "schema",
             "message": err["msg"]} for err in e.errors()]


def validate_translation(data, store):
    """Check a passage-translation skill output (one object or a list) against the verse store."""
    if isinstance(data, list):
        errors, warnings = [], []
        for i, item in enumerate(data):
            result = validate_translation(item, store)
            errors += [{**e, "path": f"[{i}].{e['path']}"} for e in result["errors"]]
            warnings += [{**w, "path": f"[{i}].{w['path']}"} for w in result["warnings"]]
        return _result(errors, warnings)
    if "error" in data:
        try:
            SkillError.model_validate(data)
            return _result([], [{"path": "$", "code": "skill_error", "message": data["message"]}])
        except ValidationError as e:
            return _result(_schema_errors(e), [])
    data = {k: v for k, v in data.items() if not k.startswith("_")}  # `draft` helper fields
    try:
        t = PassageTranslation.model_validate(data)
    except ValidationError as e:
        return _result(_schema_errors(e), [])
    errors, warnings = [], []
    row = store.get([t.verse_uid]).get(t.verse_uid)
    if row is None:
        return _result([{"path": "verse_uid", "code": "unknown_verse",
                         "message": f"{t.verse_uid} is not in the verse store"}], [])
    if row["source"] != t.source:
        errors.append({"path": "source", "code": "wrong_source",
                       "message": f"{t.verse_uid} is {row['source']}, not {t.source}"})
    if t.corpus_label != CORPUS_LABELS[row["source"]]:
        errors.append({"path": "corpus_label", "code": "wrong_label",
                       "message": f"should be {CORPUS_LABELS[row['source']]!r}"})
    if row["canon_ref"] != t.canon_ref:
        errors.append({"path": "canon_ref", "code": "misaligned",
                       "message": f"{t.verse_uid} is {row['canon_ref']}, not {t.canon_ref}"})
    if same_text(t.original) != same_text(row["text_display"]):
        errors.append({"path": "original", "code": "text_mismatch",
                       "message": "original must be copied verbatim from the verse store"})
    if t.web_reference:
        web = store.get([t.web_reference]).get(t.web_reference)
        if web is None or web["source"] != "web":
            errors.append({"path": "web_reference", "code": "unknown_verse",
                           "message": f"{t.web_reference} is not a WEB verse"})
    if same_text(t.translation) == same_text(row["text_display"]):
        errors.append({"path": "translation", "code": "not_translated",
                       "message": "translation is identical to the original"})
    if row["alignment"] != "mapped" and not any("align" in u.lower() or "number" in u.lower()
                                                for u in t.uncertainties):
        warnings.append({"path": "uncertainties", "code": "alignment",
                         "message": f"alignment is {row['alignment']}; mention it in uncertainties"})
    return _result(errors, warnings)


def validate_query_terms(data, store):
    """Check a query-term skill output: every term must really occur in the target corpus."""
    if "error" in data:
        try:
            SkillError.model_validate(data)
            return _result([], [{"path": "$", "code": "skill_error", "message": data["message"]}])
        except ValidationError as e:
            return _result(_schema_errors(e), [])
    try:
        q = QueryTerms.model_validate(data)
    except ValidationError as e:
        return _result(_schema_errors(e), [])
    errors, warnings = [], []
    counts = store.term_counts([t.term for t in q.terms], CORPUS_SOURCES[q.corpus])
    for i, term in enumerate(q.terms):
        actual = counts[term.term]
        if actual == 0:
            errors.append({"path": f"terms[{i}]", "code": "term_not_in_corpus",
                           "message": f"{term.term!r} occurs in no {q.corpus} verse; drop it"})
        elif actual != term.hits:
            warnings.append({"path": f"terms[{i}].hits", "code": "hits",
                             "message": f"{term.term!r} occurs in {actual} verses, not {term.hits}"})
    expected = "he" if q.corpus == "oshb_wlc" else "grc"
    if q.language != expected:
        errors.append({"path": "language", "code": "wrong_language",
                       "message": f"{q.corpus} is {expected}"})
    return _result(errors, warnings)


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
