from pathlib import Path

raw = Path(r"D:\bible-rag\data\raw")
files = [
    raw / "oshb" / "wlc" / "Gen.xml",
    raw / "web" / "WEB" / "02-GENengwebp.usfm",
    raw / "lxx-swete" / "data" / "01.Genesis.txt",
    raw / "sblgnt-tei" / "usfm" / "01MATSBL.sfm",
]

for path in files:
    print(f"\n{'=' * 70}\n{path}")
    if not path.exists():
        print("MISSING")
        continue
    with path.open("r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if i >= 12:
                break
            print(repr(line.rstrip("\r\n")))
