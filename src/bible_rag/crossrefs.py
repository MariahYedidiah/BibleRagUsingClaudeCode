"""OpenBible.info cross-references (CC BY 4.0), loaded into the verse store.

Source rows look like "Mark.1.3<TAB>Isa.40.3-Isa.40.5<TAB>512". References use English (KJV)
numbering, so they map straight onto `canon_ref`. A target range inside one chapter is
expanded into one row per verse, so a link to Isa 40:3-5 also matches ISA.40.4. A range that
crosses chapters keeps only its first verse, with the range recorded in `to_range`.
"""

import re

from bible_rag.books import OSIS_NT_TO_USFM, OSIS_TO_USFM

DATASET = "openbible"
# Relation classes by community votes. Calibrated on 12 well-known NT quotations of the OT
# (Mark 1:3 -> Isa 40:3, Matt 4:4 -> Deut 8:3, Rom 1:17 -> Hab 2:4, ...): all have >= 32
# votes. About 2,500 of 55,771 NT->OT links reach VERIFIED_MIN_VOTES.
VERIFIED_MIN_VOTES = 25
ALLUSION_MIN_VOTES = 5   # below this a link is too weak to show as more than thematic


def relation(votes):
    if votes >= VERIFIED_MIN_VOTES:
        return "verified"
    return "possible_allusion" if votes >= ALLUSION_MIN_VOTES else "thematic"
OSIS = {**OSIS_TO_USFM, **OSIS_NT_TO_USFM}
OSIS_REF = re.compile(r"^(\w+)\.(\d+)\.(\d+)$")

SCHEMA = """
CREATE TABLE cross_refs (
    from_canon_ref TEXT NOT NULL,
    to_canon_ref   TEXT NOT NULL,
    votes          INTEGER NOT NULL,
    dataset        TEXT NOT NULL,
    to_range       TEXT            -- the original target when it was a range
);
CREATE INDEX cross_refs_from ON cross_refs (from_canon_ref, votes);
CREATE INDEX cross_refs_to ON cross_refs (to_canon_ref);
"""


def to_canon(osis):
    m = OSIS_REF.match(osis)
    if not m or m.group(1) not in OSIS:
        return None
    return OSIS[m.group(1)], int(m.group(2)), int(m.group(3))


def parse(path):
    """Yield (from_canon_ref, to_canon_ref, votes, to_range) rows."""
    with open(path, encoding="utf-8-sig") as f:
        next(f)  # header
        for line in f:
            cols = line.rstrip("\r\n").split("\t")
            if len(cols) < 3:
                continue
            start, _, end = cols[1].partition("-")
            src, first = to_canon(cols[0]), to_canon(start)
            if src is None or first is None:
                continue
            votes = int(cols[2])
            from_ref = "{}.{}.{}".format(*src)
            last = to_canon(end) if end else first
            if last and last[:2] == first[:2] and last[2] >= first[2]:
                for verse in range(first[2], last[2] + 1):
                    yield from_ref, f"{first[0]}.{first[1]}.{verse}", votes, cols[1] if end else None
            else:
                yield from_ref, "{}.{}.{}".format(*first), votes, cols[1]


def load(con, path):
    """Create and fill the cross_refs table. Returns the number of rows."""
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO cross_refs VALUES (?, ?, ?, ?, ?)",
                    ((f, t, v, DATASET, r) for f, t, v, r in parse(path)))
    return con.execute("SELECT count(*) FROM cross_refs").fetchone()[0]
