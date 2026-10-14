# Evaluation protocol

What the scorer does, what it assumes about your run, and what a result does and does not mean.
The README is enough to run the benchmark; read this before you publish or compare numbers.

## 1. Inputs

| Collection | Unit | Where the list comes from |
|---|---|---|
| Financial | one page of a multi-page PDF | `data/corpus/run_manifest.csv` (210 rows: `pdf`, `page`) |
| olmOCR | one single-page PDF | `pdf` field of `data/olmocr_bench/bench_data/*.jsonl` (120 files) |
| Perturbation | one image | `data/perturbed/manifest.csv` (210 rows) |
| ParseBench | one file (PDF or image) | `pdf` field of `data/parsebench/subset/*.jsonl` (500 files) |

`python -m eval inputs` writes all of them, with the expected prediction path, to `inputs.csv`.

- **Financial: parse only the listed page.** Do not send the whole PDF and split the output afterwards
  unless that is how your product works; if it is, say so in `notes`.
- **Choose one input mode and declare it** in `run_card.yaml`:
  - `image`: render the page to RGB at a declared DPI (300 is the reference) and send the image.
  - `pdf`: send an extracted single-page PDF. A PDF keeps its text layer and a rendered image does not,
    so a PDF-input run can score higher for reasons unrelated to OCR. Never compare an image run with a PDF run.
- **Never send the model GT**: anything under `data/assertions/`, `gt/`, the `*.jsonl` files or `metadata/`.
- Keep the model's raw output, version, settings and failures **outside this repository**.

## 2. Running a model (`python -m eval run`)

For an OpenAI-compatible endpoint the kit produces the predictions itself (`eval/run.py`):

- **Rendering:** PDF pages are rendered with PyMuPDF at the run card's `dpi` (300 reference) to PNG; image inputs
  (perturbation, some ParseBench files) are sent unchanged. One request per input, image first, then the prompt.
- **Prompt:** a neutral default ("Convert this document page to Markdown…", see `eval/run.py`) unless the run card
  sets `endpoint.prompt`. The prompt changes results: its hash is recorded, and two models compared with
  different prompts must say so.
- **Parameters:** `temperature` 0, `max_tokens` 16384 unless overridden; `extra_body` is merged into the request.
- **Success** = HTTP 200 and `finish_reason: "stop"`. Errors, timeouts and `finish_reason: "length"` (truncation)
  write no prediction and are scored as failures. HTTP 408/409/425/429/5xx and network errors are retried
  (`retries`, default 2, exponential backoff).
- **Audit trail:** `predictions/<model>/_raw/<same path>.json` holds every attempt: UTC time, latency, status,
  response headers (cookies and auth removed), full response body, usage, served model. The image and the key
  are never written. `_raw/_runs.jsonl` logs each invocation with its effective settings.
- **Resume:** inputs with a prediction are skipped, so re-running continues an interrupted run and retries failures.
- **Concurrency** is capped at 16. If the endpoint queues silently instead of returning 429, latency numbers
  depend on concurrency: report them together.

## 3. Predictions

- One Markdown file per input at the path given by `inputs.csv`. UTF-8.
- If the model call failed, **write nothing** for that input. A missing file is scored as a failure
  on every test of that input (outcome `missing`). Do not write an empty file to hide a failure:
  an empty file is a real (empty) answer and fails on its own.
- A ```` ``` ```` / ```` ```markdown ```` fence is removed before scoring **only if it wraps the whole output**
  (opens at the very start and closes at the very end). Fences inside the output are content. Nothing else is changed.

## 4. Scoring

### Financial assertions (`eval/financial.py`)

| Field | Meaning |
|---|---|
| `type` | `page_integrity` (480), `amount` (562), `unit_currency` (111), `amount_label` (76) |
| `rule` | `exactly_once`, `exactly_n` (with `n`), `at_least_once`, `label_proximity` (with `label`, `max_gap`) |
| `forbid` | variants that must **not** appear (e.g. the amount without thousands separators) |
| `status` | only `auto`, `auto_textlayer`, `confirmed` are scored; `draft` / `rejected` never are |

- All whitespace is removed from both the prediction and the target before matching. Models merge the PDF's hard
  line breaks; anchors come from physical text-layer lines. Consequence: spacing and line breaks are not checked.
- `exactly_n`: the expected count comes from the PDF text layer (the same amount often appears in two period columns).
- `label_proximity`: amount and row label must be within `max_gap` characters after whitespace removal.
  This is text proximity, **not** proof that the amount is in the right table cell.
- Not every selected page has an assertion (205 of 210 do). All 210 pages are still inputs; coverage is reported separately.
- Assertions are targeted checks, not complete reference transcriptions. A pass rate here is not a character accuracy.

GT provenance: 137 assertions were reviewed by a person (`confirmed`; the earlier value is in `original_status` /
`original_target`); the other 1,092 were derived automatically and not all individually reviewed.
See `metadata/finance_gt_provenance.csv`.

### olmOCR-Bench subset (`eval/olmocr.py`)

Upstream test classes from `allenai/olmocr` @ `ab294c6a`, unmodified (`eval/vendor/`). Types: present/absent
text (222), table (187), math (105), reading order (90). A checker exception is `not_scored`, not a model failure.

### Perturbation (`eval/financial.py`)

Each image reuses the financial assertions of the page it was made from (`doc_id` + `page`).
The useful number is the **drop vs. the clean page** for the same model, which the report computes when the
financial collection was scored in the same run.

### ParseBench subset (`eval/parsebench.py`)

The official ParseBench evaluator (`run-llama/ParseBench` @ `3295d7f`, vendored in `eval/vendor/parsebench_src`)
does all scoring. Each prediction is wrapped as an official `ParseOutput` (the markdown, as one page) and evaluated
one dimension at a time. A file's score is the dimension's headline metric, the column the official leaderboard averages:

| Dimension | Metric | Files |
|---|---|---|
| Tables | `grits_trm_composite` | 130 |
| Charts | `rule_pass_rate` | 100 |
| Content Faithfulness | `content_faithfulness` | 150 (text) |
| Semantic Formatting | `semantic_formatting` | 150 (text; the evaluator scores 133) |
| Visual Grounding | `layout_element_rule_pass_rate` | 120: **N/A** for markdown, it needs element bounding boxes |

- A missing prediction is scored as an empty document (the official evaluator would drop it from the denominator).
- Page header/footer fields are empty in a markdown submission. Rules that read them from structured page data fall
  back to the markdown, as they do for any provider without that data.
- Means per dimension and stratum with a percentile bootstrap 95% interval (2,000 resamples, fixed seed).
- Install: `python -m pip install -r eval/requirements-parsebench.txt`. Never install `parse-bench` from PyPI:
  its 1.0.4 is a different build from `3295d7f`.

## 5. Math tests

Math tests render LaTeX with KaTeX in a headless Chromium and compare the renderings. They are skipped by default.
To score them, every team must use the **same browser build**, or renderings, and therefore pass/fail, can differ:

1. `python -m pip install -r eval/requirements-math.txt` (Playwright 1.63.0).
2. Provide Chromium build **1243** (`chromium_headless_shell-1243`). Either:
   - `python -m playwright install chromium` if your network or mirror allows it
     (`PLAYWRIGHT_DOWNLOAD_HOST` can point to an internal mirror), or
   - unpack the approved browser archive into `.playwright-browsers/` (git-ignored).
3. Point Playwright at it: `set PLAYWRIGHT_BROWSERS_PATH=<repo>\.playwright-browsers` (Windows) when using step 2's second option.
4. `python -m eval score predictions/<model> --with-math`. If Chromium cannot start, math stays unscored and the run says so.

Do **not** use the installed Google Chrome (`channel="chrome"`): it auto-updates, may be blocked from remote
debugging by policy, and breaks the "same build everywhere" rule.

## 6. Statistics and reporting

- Pass rates per stratum with a Wilson 95% interval. Missing predictions count as failures.
- Strata with fewer than **20** scored tests get no rate: *insufficient sample*. Do not merge strata to get above 20.
- **No overall score** across collections, families, dimensions or types.
- Comparisons (`python -m eval compare`) pair identical tests and use an exact McNemar test per stratum.
  p ≥ 0.05 reads as "no significant difference", not "equal".
- Tests on the same page are correlated; intervals computed per test are optimistic. Read page coverage alongside.

## 7. What a result does not tell you

- Production behaviour: latency, throughput, rate limits, cost, version stability.
- Silent failures your pipeline would see (truncation, dropped headers/footers) beyond what the tests catch.
- Document types outside the 7 financial families (e.g. trade-finance documents are not covered).
- Anything about the full public benchmarks: these are subsets with finance-weighted quotas.

## 8. Changing the benchmark

- **GT change** → new data snapshot tag; never inside a comparison.
- **Scorer change that can change any outcome** → bump `eval/__init__.py` version, update the expected outcomes in
  `eval/tests/__main__.py`, and note it in the commit.
- **New collection** → add `eval/<collection>.py` with `<collection>_inputs()` and `score_<collection>()` returning
  rows with an `outcome`, register it in `eval/__main__.py` and `eval/report.py`, add fixtures and tests.
