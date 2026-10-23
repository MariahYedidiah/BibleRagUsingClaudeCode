# Experiments

Not part of the pipeline. Kept for reference only.

- `download_opusmt_models.py`, `download_argostranslate_models.py`, `try_mt_translation.py`:
  offline machine translation (Helsinki-NLP OPUS-MT, Argos Translate) for Hebrew/Greek <-> English.
  They are trained on **modern** Hebrew and Greek and give poor output on Biblical text, so the
  translation skills use Claude instead. Possible later use: a baseline when measuring whether
  Claude-generated Hebrew/Greek search terms improve lexical recall.
- `argostranslate` was removed from the dependencies; reinstall it (`uv add argostranslate`)
  before running the Argos scripts. OPUS-MT only needs `transformers`, which is still installed.
  Note: `>>en<<` prefixes are only for multi-target OPUS-MT models; `he-en` / `el-en` don't use them.
