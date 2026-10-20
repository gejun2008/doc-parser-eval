# OCR Benchmark Dataset

Inputs, ground truth and scorers for evaluating document parsers on financial documents.
Point it at your model's endpoint (or hand it your parser's outputs), run one command or one Copilot skill, get a report per collection.

**Snapshot:** `2026-09-30` · **Financial GT frozen:** `2026-09-23` · **Scorer:** `eval 0.4.0`
**This repository never stores model outputs, scores or credentials.**

## Collections

| Collection | Inputs | Ground truth | What it tests | Scored by `eval` |
|---|---|---|---|---|
| **Financial disclosures** | 210 pages from 53 CNINFO / HKEX PDFs, 7 families | 1,229 assertions | amounts, units/currency, label–amount, page integrity | yes |
| **olmOCR-Bench subset** | 120 single-page PDFs, 7 subsets | 604 upstream tests | tables, multi-column, headers/footers, small text, old scans, math | yes (math optional) |
| **Perturbation** | 210 images = 42 pages × 5 variants | reuses financial GT | low DPI, JPEG, skew, photocopy | yes |
| **ParseBench subset** | 500 files (482 PDF, 18 images) | 45,931 upstream rules | tables, charts, text content and formatting, layout | yes (Visual Grounding N/A for markdown) |

The financial collection is what decides fit for financial documents. The public subsets are entry checks:
they may be in the training data of the model under test, so a high score there is necessary, not sufficient.

## Start here (3 steps)

This repository is your workspace: test data, ground truth, scorers and the Copilot skill are all in it,
and every model you test gets its own folder next to the others.

```bash
git lfs install                                                   # once per machine
git clone --branch data-2026-09-30 <repo-url> ocr-benchmark-dataset   # a fixed, tagged snapshot
code ocr-benchmark-dataset                                        # open it in VS Code
```

Then, in Copilot **agent mode**, say:

> *Use the ocr-benchmark skill to test my model at https://&lt;host&gt;/v1/chat/completions*

The skill sets up the environment, asks for the model name and the name of the environment variable holding your
API key (you set the key yourself in the terminal; never paste it into chat), runs a 2-input smoke test, tells you
how long the full run will take and lets you choose all collections (default) or only some, then runs, scores
and summarises. Test another model the same way: each one lands in `predictions/<model>/` and `results/<model>/`,
and the skill can put them side by side.

Everything the skill does is a plain command you can also run yourself:

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows; source .venv/bin/activate elsewhere
python -m pip install -r eval/requirements.txt -r eval/requirements-parsebench.txt -r eval/requirements-run.txt
python -m eval.tests                               # self-test on synthetic fixtures
python -m eval verify --quick                      # are the LFS files really here?
```

Then either let the kit call your model (**A**), or run your parser yourself and hand over its outputs (**B**).

### A. Your model has an OpenAI-compatible endpoint

Create `predictions/<your-model>/run_card.yaml`:

```yaml
model: new-ocr
version: test
input_mode: image            # pages are rendered to PNG and sent as images
dpi: 300
endpoint:
  url: https://<host>/v1/chat/completions   # full chat-completions URL
  model: <model name the endpoint expects>
  api_key_env: NEW_OCR_API_KEY              # name of the environment variable, never the key itself
  concurrency: 4                            # max 16
  # optional: prompt, max_tokens (16384), temperature (0), timeout_s (600), retries (2),
  #           auth_header ("Authorization"), auth_prefix ("Bearer "), extra_body: {...}
  # newer OpenAI models: token_param: max_completion_tokens   and   temperature: null (omit it)
```

```bash
$env:NEW_OCR_API_KEY = "<key>"                       # PowerShell; export NEW_OCR_API_KEY=... elsewhere
python -m eval run predictions/new-ocr --smoke       # 2 inputs per collection: check it works
python -m eval run predictions/new-ocr               # everything (1,040 inputs); re-run to resume
python -m eval score predictions/new-ocr
```

**A full run is long.** Throughput depends on the endpoint: at 1.6–5.6 pages a minute (measured on one vendor API),
1,040 inputs take about 3–11 hours. `--smoke` prints an estimate for the rest. To start smaller, pick collections, e.g. only the two public subsets (620 inputs):

```bash
python -m eval run predictions/new-ocr --collections parsebench olmocr
```

An interrupted run resumes where it stopped; failed inputs are retried on the next run. Every response is kept
under `predictions/new-ocr/_raw/` (status, latency, usage, finish_reason). A truncated answer
(`finish_reason: length`) or an error is a failure, never a prediction.

### Quick comparison of several models on a fixed sample

To compare a few models fast, score them all on the **same** small sample instead of all 1,040 inputs:

```bash
python -m eval sample --name quick100        # 100 inputs: financial 40, ParseBench 30, olmOCR 20, perturbation 10
# one run card per model (same endpoint, different endpoint.model), e.g. predictions/luna, predictions/sol, predictions/astra
python -m eval run   predictions/luna --inputs samples/quick100.csv
python -m eval score predictions/luna --inputs samples/quick100.csv
#   ... same two lines for each model ...
python -m eval table                          # all models side by side
```

- The sample is stratified (document family / subset / variant / file group) and fixed by a seed: the same command
  gives the same file. Commit `samples/quick100.csv` if others should test on exactly the same inputs.
- `--quota financial=60 parsebench=40` changes the mix; `--seed` changes the draw.
- Only sampled inputs are scored; the rest are out of scope, not failures. The sample is recorded in each
  `results/<model>/run_card.yaml`, and `table` / `compare` warn when two runs used different samples.
- **Small sample, wide intervals.** Many strata will have fewer than 20 items and show *insufficient sample*.
  A sample is for a first cut between models; confirm the choice on the full set.
- The run prints prompt and completion tokens, so cost per model is tokens × price.

### B. You run the parser yourself

`python -m eval inputs` writes `inputs.csv`: every input and the file its output must go to. Save one Markdown
file per input at `predictions/<your-model>/<prediction_path>`:

```
data/<path>/<name>.<ext>            ->  predictions/<model>/<path>/<name>.md
data/corpus/<family>/<doc>.pdf, p.7 ->  predictions/<model>/corpus/<family>/<doc>_p7.md   (financial: one file per selected page)
```

Add `predictions/<your-model>/run_card.yaml` with `model`, `version`, `input_mode` (`image` or `pdf`),
`dpi` (for images), `date` and `notes`, then `python -m eval score predictions/<your-model>`.
Collections without a folder are skipped.

## Reading the results

```
results/<your-model>/
  run_card.yaml        your card + dataset commit, scorer version, time, whether math was scored
  financial.md         pass rate by assertion type, family, family × window
  olmocr.md            pass rate by subset and test type
  perturbed.md         pass rate by variant + drop vs. the clean page
  parsebench.md        mean official score per dimension and stratum (Visual Grounding N/A for markdown)
  parsebench_official/ the official ParseBench evaluator's own per-file results and log
  <collection>.csv     one row per test: item, test id, outcome (pass / fail / missing / not_scored), detail
  summary.json
```

- **There is no overall score.** Each collection has its own metric; do not average across them.
- A page with no prediction file counts as **failed**, never skipped (ParseBench: scored as an empty document).
- A stratum with fewer than 20 scored tests is shown as *insufficient sample*, without a rate.
- olmOCR math tests are **skipped by default** (reported as not scored). To score them, see `docs/protocol.md` → Math tests.

## Comparing models

```bash
python -m eval table                                      # every model under results/, side by side
python -m eval compare results/<model-a> results/<model-b>   # paired test between two models
```

`table` writes `results/side_by_side.md`: one table per collection, one column per model, each cell with its n
and missing count. It is descriptive only: no overall score, no ranking, no test.
`compare` pairs the same tests on both sides, per stratum, with an exact McNemar test (ParseBench: paired
per-file score difference with a bootstrap interval). Both warn when runs used a different dataset commit,
input mode or scorer version.

## Rules the scorer cannot enforce

1. **Never give the model under test anything from `data/assertions/`, `gt/` or the `*.jsonl` test files.**
2. **Declare the input mode honestly** and use the same mode for every model you compare.
   Image and PDF input are not equivalent: a PDF keeps its text layer.
3. **Don't edit GT during a comparison.** Found a GT error? Open an issue; it is fixed in the next snapshot.

## Repository layout

```
data/
  assertions/                  financial GT, one YAML per document
  corpus/                      financial PDFs + run_manifest.csv (the 210 selected pages)
  olmocr_bench/bench_data/     olmOCR tests (*.jsonl) + pdfs/<subset>/
  parsebench/subset/           ParseBench rules (*.jsonl) + docs/<dimension>/
  perturbed/                   perturbation images + manifest.csv
gt/                            index
metadata/                      checksums.csv, dataset.json, GT provenance, upstream licenses
eval/                          runner + scorers (python -m eval), tests (python -m eval.tests), vendored upstream code
.github/skills/ocr-benchmark/  Copilot skill (available as soon as the repository is open in VS Code)
predictions/<model>/           your run cards, model outputs and raw responses (git-ignored)
results/<model>/               reports per model; results/side_by_side.md (git-ignored)
docs/protocol.md               full evaluation protocol
docs/sources.md                data sources, attribution and rights
```

## Versioning

Data snapshots are tagged `data-YYYY-MM-DD`; the scorer has its own version (`eval/__init__.py`).
A result is identified by **dataset commit + scorer version + run card**, all recorded in `results/<model>/run_card.yaml`.
Any change to a scorer that can change an outcome bumps the scorer version.

## License

| Content | Source | License |
|---|---|---|
| olmOCR-Bench subset | `allenai/olmOCR-bench` | ODC-BY |
| ParseBench subset | `llamaindex/ParseBench` @ `2805a1d` | Apache-2.0 (`metadata/parsebench_LICENSE.txt`) |
| Financial disclosures, perturbation | public CNINFO and HKEX filings | source terms apply; see `docs/sources.md` |
| Vendored scorer code | olmocr @ `ab294c6a`, ParseBench @ `3295d7f`, KaTeX | Apache-2.0, Apache-2.0, MIT (`eval/vendor/NOTICE.md`) |
