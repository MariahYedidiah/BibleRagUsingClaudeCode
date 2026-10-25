# Run folders

Every question gets a folder here (`bible-rag run new`). Only the golden-query example runs
(`golden-*`, one per query in `eval/golden_queries.json`) are committed; everything else is ignored.

Check an example run against its golden query, offline:

```powershell
uv run bible-rag eval run golden-ot-creation --golden ot_creation
uv run bible-rag run show golden-ot-creation        # the delegation trace
```

`tests/test_evaluation.py` runs these checks for every committed `golden-*` run.

Notes on the committed runs (made 2026-10-24):

- They were produced by the agents through the leader workflow, so the prose, relevance notes and
  machine translations are model output and would differ on a re-run; the checks test properties.
- `golden-ot-creation`, `golden-nt-word`, `golden-polarized-suffering` and `golden-low-evidence` ran
  before a fix to the WEB parser, when 2,079 WEB verses still carried USFM word markup
  (`|strong="H5542"`). Their saved search outputs (`*_search.json`), one agent note and the
  `_web_text` helper of a draft translation still show it. Only one kept passage was affected
  (WEB Luke 18:7 in `golden-polarized-suffering`); that result was re-packed from the corrected store
  with `bible-rag pack specialist` and the answer re-assembled with `bible-rag run answer`.
- `golden-nt-word`'s first Greek NT result kept two verses that no search had returned. `pack` now
  rejects that, so the specialist was re-delegated; the trace shows the failed result and the retry.
