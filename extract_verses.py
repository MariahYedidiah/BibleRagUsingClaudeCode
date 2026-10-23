from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = Path(r"D:\bible-rag\data\raw")
OUT = Path(r"D:\bible-rag\data\processed\verses")
OUT.mkdir(parents=True, exist_ok=True)

BOOKS = {
    "GEN":"Genesis","EXO":"Exodus","LEV":"Leviticus","NUM":"Numbers",
    "DEU":"Deuteronomy","JOS":"Joshua","JDG":"Judges","RUT":"Ruth",
    "1SA":"1 Samuel","2SA":"2 Samuel","1KI":"1 Kings","2KI":"2 Kings",
    "1CH":"1 Chronicles","2CH":"2 Chronicles","EZR":"Ezra","NEH":"Nehemiah",
    "EST":"Esther","JOB":"Job","PSA":"Psalms","PRO":"Proverbs",
    "ECC":"Ecclesiastes","SNG":"Song of Solomon","ISA":"Isaiah",
    "JER":"Jeremiah","LAM":"Lamentations","EZK":"Ezekiel","DAN":"Daniel",
    "HOS":"Hosea","JOL":"Joel","AMO":"Amos","OBA":"Obadiah","JON":"Jonah",
    "MIC":"Micah","NAM":"Nahum","HAB":"Habakkuk","ZEP":"Zephaniah",
    "HAG":"Haggai","ZEC":"Zechariah","MAL":"Malachi","MAT":"Matthew",
    "MRK":"Mark","LUK":"Luke","JHN":"John","ACT":"Acts","ROM":"Romans",
    "1CO":"1 Corinthians","2CO":"2 Corinthians","GAL":"Galatians",
    "EPH":"Ephesians","PHP":"Philippians","COL":"Colossians",
    "1TH":"1 Thessalonians","2TH":"2 Thessalonians","1TI":"1 Timothy",
    "2TI":"2 Timothy","TIT":"Titus","PHM":"Philemon","HEB":"Hebrews",
    "JAS":"James","1PE":"1 Peter","2PE":"2 Peter","1JN":"1 John",
    "2JN":"2 John","3JN":"3 John","JUD":"Jude","REV":"Revelation",
}
LXX_BOOKS = {
    "Genesis":"GEN","Exodus":"EXO","Leviticus":"LEV","Numeri":"NUM",
    "Deuteronomium":"DEU","Josue":"JOS","Judices":"JDG","Ruth":"RUT",
    "Psalmi":"PSA","Psalms":"PSA","Proverbia":"PRO","Iob":"JOB",
    "Isaias":"ISA","Ieremias":"JER","Ezechiel":"EZK","Daniel":"DAN",
    "Osee":"HOS","Ioel":"JOL","Amos":"AMO","Abdias":"OBA","Ionas":"JON",
    "Michaeas":"MIC","Nahum":"NAM","Habacuc":"HAB","Sophonia":"ZEP",
    "Aggaeus":"HAG","Zacharias":"ZEC","Malachias":"MAL",
}

def write_jsonl(filename, records):
    path = OUT / filename
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{filename}: {len(records):,} records")

def parse_osis(path):
    # Parse each verse independently, including nested text.
    root = ET.parse(path).getroot()
    verses = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "verse":
            continue
        ref = el.attrib.get("osisID", "")
        m = re.match(r"^([A-Za-z0-9]+)\.(\d+)\.(\d+)$", ref)
        if not m:
            continue
        book, chapter, verse = m.groups()
        text = "".join(el.itertext())
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            verses.append({
                "source":"oshb_wlc", "language":"he",
                "book_id":book.upper(),
                "book_name":BOOKS.get(book.upper(), book),
                "chapter":int(chapter), "verse":int(verse),
                "source_ref":ref, "text":text
            })
    return verses

def clean_usfm(text):
    text = re.sub(r"\\f\b.*?\\f\*", " ", text)
    text = re.sub(r"\\x\b.*?\\x\*", " ", text)
    text = re.sub(r"\\w\s+([^|\\]+)\|.*?\\w\*", r"\1", text)
    text = re.sub(r"\\\+?[A-Za-z][A-Za-z0-9-]*\*?", " ", text)
    text = re.sub(r"[{}~]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def parse_usfm(path, source, language):
    records = []
    chapter = None
    verse = None
    book_id = None
    parts = []

    def flush():
        nonlocal parts
        if book_id and chapter is not None and verse is not None:
            text = clean_usfm(" ".join(parts))
            if text:
                records.append({
                    "source":source, "language":language,
                    "book_id":book_id,
                    "book_name":BOOKS.get(book_id, book_id),
                    "chapter":chapter, "verse":verse,
                    "source_ref":f"{book_id}.{chapter}.{verse}",
                    "text":text
                })
        parts = []

    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = re.match(r"\\id\s+([A-Za-z0-9]{3})\b", line)
            if m:
                flush()
                book_id = m.group(1).upper()
                chapter = verse = None
                continue
            m = re.match(r"\\c\s+(\d+)", line)
            if m:
                flush()
                chapter, verse = int(m.group(1)), None
                continue
            m = re.match(r"\\v\s+(\d+)\s*(.*)", line)
            if m and chapter is not None:
                flush()
                verse = int(m.group(1))
                parts.append(m.group(2))
                continue
            if re.match(r"\\(?:s\d*|ms\d*|mt\d*|h|toc\d*|rem)\b", line):
                continue
            if verse is not None:
                parts.append(line)
    flush()
    return records

def parse_lxx():
    records = []
    for path in sorted((ROOT / "lxx-swete" / "data").glob("*.txt")):
        book_name = path.stem.split(".", 1)[-1]
        prefix = path.stem.split(".", 1)[0]
        book_id = LXX_BOOKS.get(book_name, f"LXX_{prefix}")
        grouped = defaultdict(list)
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*\d+\.(\d+)\.(\d+)\s+(.+?)\s*$", line)
                if m:
                    chapter, verse, word = m.groups()
                    grouped[(int(chapter), int(verse))].append(word)
        for (chapter, verse), words in sorted(grouped.items()):
            records.append({
                "source":"lxx_swete", "language":"grc",
                "book_id":book_id, "book_name":book_name,
                "chapter":chapter, "verse":verse,
                "source_ref":f"{prefix}.{chapter}.{verse}",
                "text":" ".join(words)
            })
    return records

def main():
    hebrew = []
    for p in sorted((ROOT / "oshb" / "wlc").rglob("*.xml")):
        hebrew.extend(parse_osis(p))

    web = []
    for p in sorted((ROOT / "web" / "WEB").glob("*.usfm")):
        web.extend(parse_usfm(p, "web", "en"))

    lxx = parse_lxx()

    sblgnt = []
    for p in sorted((ROOT / "sblgnt-tei" / "usfm").glob("*.sfm")):
        sblgnt.extend(parse_usfm(p, "sblgnt", "grc"))

    datasets = [
        ("hebrew_oshb.jsonl", hebrew),
        ("english_web.jsonl", web),
        ("greek_lxx.jsonl", lxx),
        ("greek_sblgnt.jsonl", sblgnt),
    ]
    print("\nExtraction results:")
    for filename, records in datasets:
        write_jsonl(filename, records)
    print(f"\nOutput: {OUT}")
    if any(not rows for _, rows in datasets):
        print("WARNING: One or more datasets are empty. Do not proceed yet.")
    else:
        print("All four datasets contain records. Validate before indexing.")

if __name__ == "__main__":
    main()
