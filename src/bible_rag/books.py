"""Book codes. Every source is normalized to 3-letter USFM codes."""

OT = ["GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
      "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
      "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
      "HAG", "ZEC", "MAL"]
NT = ["MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL",
      "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN",
      "3JN", "JUD", "REV"]

BOOK_NAMES = {
    "GEN": "Genesis", "EXO": "Exodus", "LEV": "Leviticus", "NUM": "Numbers",
    "DEU": "Deuteronomy", "JOS": "Joshua", "JDG": "Judges", "RUT": "Ruth",
    "1SA": "1 Samuel", "2SA": "2 Samuel", "1KI": "1 Kings", "2KI": "2 Kings",
    "1CH": "1 Chronicles", "2CH": "2 Chronicles", "EZR": "Ezra", "NEH": "Nehemiah",
    "EST": "Esther", "JOB": "Job", "PSA": "Psalms", "PRO": "Proverbs",
    "ECC": "Ecclesiastes", "SNG": "Song of Solomon", "ISA": "Isaiah",
    "JER": "Jeremiah", "LAM": "Lamentations", "EZK": "Ezekiel", "DAN": "Daniel",
    "HOS": "Hosea", "JOL": "Joel", "AMO": "Amos", "OBA": "Obadiah", "JON": "Jonah",
    "MIC": "Micah", "NAM": "Nahum", "HAB": "Habakkuk", "ZEP": "Zephaniah",
    "HAG": "Haggai", "ZEC": "Zechariah", "MAL": "Malachi", "MAT": "Matthew",
    "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts", "ROM": "Romans",
    "1CO": "1 Corinthians", "2CO": "2 Corinthians", "GAL": "Galatians",
    "EPH": "Ephesians", "PHP": "Philippians", "COL": "Colossians",
    "1TH": "1 Thessalonians", "2TH": "2 Thessalonians", "1TI": "1 Timothy",
    "2TI": "2 Timothy", "TIT": "Titus", "PHM": "Philemon", "HEB": "Hebrews",
    "JAS": "James", "1PE": "1 Peter", "2PE": "2 Peter", "1JN": "1 John",
    "2JN": "2 John", "3JN": "3 John", "JUD": "Jude", "REV": "Revelation",
    # Deuterocanon / LXX-only books
    "1ES": "1 Esdras", "JDT": "Judith", "TOB": "Tobit", "1MA": "1 Maccabees",
    "2MA": "2 Maccabees", "3MA": "3 Maccabees", "4MA": "4 Maccabees", "ODA": "Odes",
    "WIS": "Wisdom of Solomon", "SIR": "Sirach", "PSS": "Psalms of Solomon",
    "BAR": "Baruch", "LJE": "Letter of Jeremiah", "SUS": "Susanna", "BEL": "Bel and the Dragon",
}

# OSHB (OSIS) book codes, as they appear in source_ref, e.g. "1Chr.1.1".
OSIS_TO_USFM = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU", "Josh": "JOS",
    "Judg": "JDG", "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA", "1Kgs": "1KI", "2Kgs": "2KI",
    "1Chr": "1CH", "2Chr": "2CH", "Ezra": "EZR", "Neh": "NEH", "Esth": "EST", "Job": "JOB",
    "Ps": "PSA", "Prov": "PRO", "Eccl": "ECC", "Song": "SNG", "Isa": "ISA", "Jer": "JER",
    "Lam": "LAM", "Ezek": "EZK", "Dan": "DAN", "Hos": "HOS", "Joel": "JOL", "Amos": "AMO",
    "Obad": "OBA", "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB", "Zeph": "ZEP",
    "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
}

# Swete LXX files, keyed by the number prefix of the file name (also the first part of
# source_ref). Value: (USFM code, edition). Edition separates the Old Greek ("og") and
# Theodotion ("th") versions of Daniel, Susanna and Bel.
LXX_FILES = {
    "01": ("GEN", ""), "02": ("EXO", ""), "03": ("LEV", ""), "04": ("NUM", ""),
    "05": ("DEU", ""), "06": ("JOS", ""), "08": ("JDG", ""), "10": ("RUT", ""),
    "11": ("1SA", ""), "12": ("2SA", ""), "13": ("1KI", ""), "14": ("2KI", ""),  # 1-4 Kingdoms
    "15": ("1CH", ""), "16": ("2CH", ""),                                        # Paralipomenon
    "17": ("1ES", ""), "18": ("EZR", ""),  # Esdras B = Ezra + Nehemiah, split in lxx_book()
    "19": ("EST", ""), "20": ("JDT", ""), "21": ("TOB", ""),
    "23": ("1MA", ""), "24": ("2MA", ""), "25": ("3MA", ""), "26": ("4MA", ""),
    "27": ("PSA", ""), "28": ("ODA", ""), "29": ("PRO", ""), "31": ("SNG", ""),
    "32": ("JOB", ""), "33": ("WIS", ""), "34": ("SIR", ""), "35": ("PSS", ""),
    "36": ("HOS", ""), "37": ("AMO", ""), "38": ("MIC", ""), "39": ("JOL", ""),
    "40": ("OBA", ""), "41": ("JON", ""), "42": ("NAM", ""), "43": ("HAB", ""),
    "44": ("ZEP", ""), "45": ("HAG", ""), "46": ("ZEC", ""), "47": ("MAL", ""),
    "48": ("ISA", ""), "49": ("JER", ""), "50": ("BAR", ""), "51": ("LAM", ""),
    "52": ("LJE", ""), "53": ("EZK", ""),
    "54": ("SUS", "og"), "55": ("SUS", "th"), "56": ("DAN", "og"), "57": ("DAN", "th"),
    "58": ("BEL", "og"), "59": ("BEL", "th"),
}


def lxx_book(prefix, chapter):
    """Map a Swete file prefix and chapter to (USFM code, chapter, edition)."""
    book, edition = LXX_FILES[prefix]
    if prefix == "18" and chapter > 10:  # 2 Esdras 11-23 is Nehemiah 1-13
        return "NEH", chapter - 10, edition
    return book, chapter, edition


def testament(book_id):
    if book_id in OT:
        return "OT"
    if book_id in NT:
        return "NT"
    return "DC"
