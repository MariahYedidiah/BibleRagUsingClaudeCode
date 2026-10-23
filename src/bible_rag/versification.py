"""Map each source's native verse numbers to the English (KJV) standard used by `canon_ref`.

WEB already follows KJV numbering. The others are mapped from published data (see
docs/data-sources.md):

- Hebrew (OSHB/WLC): VerseMap.xml, shipped with OSHB for exactly this text.
- Greek NT (SBLGNT): the SBLGNT/KJV differences listed in STEPBible TVTMS.
- Greek OT (Swete LXX): STEPBible TVTMS. Each TVTMS row says "in tradition X, verse A is
  standard verse B", with tests ("Psa.22:6=Last", "Psa.9:30=Exist") that identify which
  tradition a Bible follows in that section. The tests are evaluated against Swete's actual
  verses, because Swete mixes traditions (Greek Psalms, but English-style Malachi and Joel).

Each verse gets (canon_ref, alignment):
  mapped    the verse corresponds one-to-one to the standard verse
  partial   it covers part of a standard verse, or more than one
  unmapped  no reliable correspondence; canon_ref keeps the native number
Psalm titles have no English verse number; they get verse 0 (e.g. PSA.3.0).
"""

import re
import xml.etree.ElementTree as ET
from collections import defaultdict

from bible_rag.books import OSIS_TO_USFM

# SBLGNT -> KJV, from the "Differences between KJV and other English versions" table in
# TVTMS. WEB follows KJV at all of these.
SBLGNT_MAP = {
    "ACT.19.40": ("ACT.19.40", "partial"),  # KJV splits it into 40-41
    "2CO.13.12": ("2CO.13.12", "partial"),  # KJV 12-13
    "2CO.13.13": ("2CO.13.14", "mapped"),
    "PHP.1.16": ("PHP.1.17", "mapped"),     # verse order swapped
    "PHP.1.17": ("PHP.1.16", "mapped"),
    "3JN.1.14": ("3JN.1.14", "partial"),    # KJV 14 = SBLGNT 14-15
    "3JN.1.15": ("3JN.1.14", "partial"),
    "REV.12.18": ("REV.13.1", "partial"),   # KJV 13:1a
    "REV.13.1": ("REV.13.1", "partial"),    # KJV 13:1b
}

# TVTMS traditions that describe Greek OT Bibles.
GREEK_TRADITIONS = ("Greek", "Grk", "BrentonMerged", "AllBibles")
FULL_ACTIONS = {"Keep verse", "Renumber verse", "Renumber title", "Psalm title"}
TVTMS_REF = re.compile(r"^([1-4A-Za-z][A-Za-z0-9]{2})\.(\d+):(\d+|Title)(![a-z0-9]+)?$")
TEST_STATE = re.compile(r"^([1-4A-Za-z][A-Za-z0-9]{2})\.(\d+):(\w+(?:\.\d+)?)=(Exist|NotExist|Last)$")
TEST_COMPARE = re.compile(r"^([1-4A-Za-z][A-Za-z0-9]{2})\.(\d+):(\d+)([<>])"
                          r"([1-4A-Za-z][A-Za-z0-9]{2})\.(\d+):(\d+)$")


def ref(book, chapter, verse):
    return f"{book}.{chapter}.{verse}"


# --- Hebrew -----------------------------------------------------------------------------

def load_verse_map(path):
    """{OSIS wlc ref: (OSIS kjv ref, "full" | "partial")} from OSHB's VerseMap.xml."""
    root = ET.parse(path).getroot()
    return {el.get("wlc"): (el.get("kjv"), el.get("type"))
            for el in root.iter() if el.tag.endswith("verse") and el.get("wlc")}


def osis_to_canon(osis):
    book, chapter, verse = osis.split(".")
    return ref(OSIS_TO_USFM[book], chapter, verse)


def map_hebrew(rows, verse_map):
    """rows: [(verse_uid, source_ref)] -> {verse_uid: (canon_ref, alignment)}."""
    claimed = {kjv for kjv, _ in verse_map.values()}
    # VerseMap doesn't separate psalm titles: for a two-verse title it maps both the second
    # title verse and the first real verse to KJV verse 1 (Ps 51:2 and 51:3 -> 51:1).
    # Of several Hebrew psalm verses mapped to one KJV verse, all but the last are title.
    by_target = defaultdict(list)
    for wlc, (kjv, _) in verse_map.items():
        if wlc.startswith("Ps."):
            by_target[kjv].append(wlc)
    title_part = {w for ws in by_target.values() if len(ws) > 1
                  for w in sorted(ws, key=lambda w: int(w.split(".")[2]))[:-1]}
    out = {}
    for uid, source_ref in rows:
        if source_ref in title_part:
            _, chapter, _ = source_ref.split(".")
            out[uid] = (ref("PSA", chapter, 0), "mapped")
            continue
        if source_ref in verse_map:
            kjv, kind = verse_map[source_ref]
            part = "!" in kjv  # "1Kgs.22.43!b": part of a KJV verse
            out[uid] = (osis_to_canon(kjv.split("!")[0]),
                        "mapped" if kind == "full" and not part else "partial")
            continue
        canon = osis_to_canon(source_ref)
        if source_ref in claimed:  # its English number belongs to a different Hebrew verse
            book, chapter, _ = canon.split(".")
            if book == "PSA":  # a psalm title, numbered as verse 1 (or 1-2) in Hebrew
                out[uid] = (ref(book, chapter, 0), "mapped")
            else:
                out[uid] = (canon, "unmapped")
        else:
            out[uid] = (canon, "mapped")
    return out


# --- Greek OT (TVTMS) -------------------------------------------------------------------

def load_tvtms(path):
    """Rows of TVTMS's expanded section that apply to Greek OT traditions."""
    rows, inside = [], False
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.startswith("#DataStart(Expanded)"):
                inside = True
                continue
            if line.startswith("#DataEnd(Expanded)"):
                break
            cols = line.rstrip("\r\n").split("\t")
            if not inside or len(cols) < 9 or cols[0] == "SourceType":
                continue
            traditions = [t.strip() for t in cols[0].split("+")]
            if not any(t.startswith(GREEK_TRADITIONS) for t in traditions):
                continue
            source = TVTMS_REF.match(cols[1].strip())
            if not source:
                continue  # ranges and sub-verse splits our whole-verse data can't use
            rows.append({
                "traditions": traditions,
                "book": source.group(1).upper(),
                "chapter": int(source.group(2)),
                "verse": source.group(3),
                "part": source.group(4) or "",
                "standard": cols[2].strip(),
                "action": cols[3].strip().rstrip("*"),
                "tests": [t.strip() for t in cols[8].split("&") if t.strip()],
            })
    return rows


class Chapters:
    """Verse numbers and word counts of one source book, for evaluating TVTMS tests."""

    def __init__(self, verses):
        """verses: {(book, chapter, verse): word_count}"""
        self.words = verses
        self.last = defaultdict(int)
        self.has_v0 = set()
        for book, chapter, verse in verses:
            if verse == 0:
                self.has_v0.add((book, chapter))
            else:
                self.last[(book, chapter)] = max(self.last[(book, chapter)], verse)

    def test(self, atom):
        """True/False for one TVTMS test, None if it can't be evaluated."""
        m = TEST_STATE.match(atom)
        if m:
            book, chapter, verse, state = m.group(1).upper(), int(m.group(2)), m.group(3), m.group(4)
            if verse == "TextBeforeV1":
                exists = (book, chapter) in self.has_v0
                return exists if state == "Exist" else (not exists if state == "NotExist" else None)
            if not verse.isdigit():  # sub-verse ("31.2") or title: whole-verse data has none
                return state == "NotExist"
            key = (book, chapter, int(verse))
            if state == "Last":
                return self.last.get((book, chapter)) == int(verse)
            return (key in self.words) == (state == "Exist")
        m = TEST_COMPARE.match(atom)
        if m:
            a = self.words.get((m.group(1).upper(), int(m.group(2)), int(m.group(3))))
            b = self.words.get((m.group(5).upper(), int(m.group(6)), int(m.group(7))))
            if a is None or b is None:
                return False
            return a < b if m.group(4) == "<" else a > b
        return None

    def passes(self, tests, relaxed=False):
        """All tests hold. `relaxed` skips the tests that only pick between verse-division
        variants (word-count comparisons, whether a title is numbered separately); they often
        fit no variant of Swete exactly, while the chapter-level tests still identify it."""
        return all(self.test(t) for t in tests
                   if not (relaxed and (TEST_COMPARE.match(t) or "TextBeforeV1" in t)))


def parse_standard(text):
    """TVTMS standard ref -> (canon_ref, exact) or None. "Psa.23:Title" -> PSA.23.0."""
    m = re.match(r"^([1-4A-Za-z][A-Za-z0-9]{2})\.(\d+):(\d+|Title)", text)
    if not m:
        return None
    verse = 0 if m.group(3) == "Title" else int(m.group(3))
    exact = bool(TVTMS_REF.match(text)) and "!" not in text
    return ref(m.group(1).upper(), int(m.group(2)), verse), exact


def specificity(row):
    """Prefer the row with the most tests, then the plain "Greek" tradition."""
    return (len(row["tests"]), "Greek" in row["traditions"])


def map_lxx(verses, tvtms_rows):
    """verses: [(verse_uid, book_id, chapter, verse, word_count)] for ONE edition of Swete.

    Returns {verse_uid: (canon_ref, alignment)}.
    """
    chapters = Chapters({(b, c, v): n for _, b, c, v, n in verses})
    books = {b for _, b, _, _, _ in verses}
    strict, relaxed = defaultdict(list), defaultdict(list)  # (book, chapter, verse) -> rows
    for row in tvtms_rows:
        if row["book"] not in books:
            continue
        key = (row["book"], row["chapter"], 0 if row["verse"] == "Title" else int(row["verse"]))
        if chapters.passes(row["tests"]):
            strict[key].append(row)
        elif chapters.passes(row["tests"], relaxed=True):
            relaxed[key].append(row)

    out, defaulted = {}, set()
    for uid, book, chapter, verse, _ in verses:
        key = (book, chapter, verse)
        rows, approximate = strict.get(key), False
        if not rows and key in relaxed:
            rows, approximate = relaxed[key], True
        if not rows:
            out[uid] = (ref(book, chapter, verse), "mapped")  # outside every TVTMS section
            defaulted.add(uid)
            continue
        whole = [r for r in rows if not r["part"]]
        best = max(whole or rows, key=specificity)
        parsed = parse_standard(best["standard"])
        if parsed is None:  # "Absent", empty: no standard verse for this one
            out[uid] = (ref(book, chapter, verse), "unmapped")
            continue
        canon, exact = parsed
        full = exact and not approximate and not best["part"] and best["action"] in FULL_ACTIONS \
            and not (whole and len({r["standard"] for r in whole}) > 1)
        out[uid] = (canon, "mapped" if full else "partial")

    # A title (verse 0) that no TVTMS row covers belongs to the psalm it heads: give it the
    # chapter that verse 1 was mapped to.
    first = {(b, c): uid for uid, b, c, v, _ in verses if v == 1}
    for uid, book, chapter, verse, _ in verses:
        if verse == 0 and (book, chapter, 0) not in strict and (book, chapter, 0) not in relaxed \
                and (book, chapter) in first:
            v1_book, v1_chapter, _ = out[first[(book, chapter)]][0].split(".")
            if (v1_book, v1_chapter) != (book, str(chapter)):
                out[uid] = (ref(v1_book, v1_chapter, 0), "partial")
                defaulted.discard(uid)

    # A verse that kept its own number only because no TVTMS row matched, while another verse
    # was mapped onto that number, is not aligned: say so instead of guessing.
    taken = defaultdict(list)
    for uid, (canon, _) in out.items():
        if not canon.endswith(".0"):
            taken[canon].append(uid)
    for uids in taken.values():
        if len(uids) > 1 and any(u not in defaulted for u in uids):
            for uid in uids:
                if uid in defaulted:
                    out[uid] = (out[uid][0], "unmapped")
    return out
