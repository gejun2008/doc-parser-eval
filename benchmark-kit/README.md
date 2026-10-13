# OCR Benchmark Dataset

Inputs, ground truth and scorers for evaluating document parsers on financial documents.
Run your parser, drop its outputs in a folder, run one command (or one Copilot skill), get a report per collection.

**Snapshot:** `2026-09-30` · **Financial GT frozen:** `2026-09-23` · **Scorer:** `eval 0.2.0`
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

## Quick start

```bash
git lfs install && git clone <repo-url> && cd ocr-benchmark-dataset
python -m pip install -r eval/requirements.txt     # Python 3.12, internal pip mirror
python -m pip install -r eval/requirements-parsebench.txt   # only if you score ParseBench
python -m eval.tests                               # scorer self-test on synthetic fixtures
python -m eval verify --quick                      # are the LFS files really here?
python -m eval inputs                              # writes inputs.csv: every input and its prediction file
```

**1. Run your parser** on each `input_path` in `inputs.csv` and save the output as Markdown at
`predictions/<your-model>/<prediction_path>`. The rule behind `prediction_path`:

```
data/<path>/<name>.<ext>            ->  predictions/<model>/<path>/<name>.md
data/corpus/<family>/<doc>.pdf, p.7 ->  predictions/<model>/corpus/<family>/<doc>_p7.md   (financial: one file per selected page)
```

Add `predictions/<your-model>/run_card.yaml`:

```yaml
model: my-parser
version: 2.1.0            # as reported by the service, if it reports one
input_mode: image         # image | pdf   (pdf = extracted single-page PDF)
dpi: 300                  # required when input_mode is image
output_format: markdown
date: 2026-10-13
notes: ""                 # anything that differs from docs/protocol.md
```

**2. Score:**

```bash
python -m eval score predictions/<your-model>
```

Reports land in `results/<your-model>/` (git-ignored). Collections without a folder under
`predictions/<your-model>/` are skipped, so you can submit only the ones you need.

**With Copilot:** open the repository in VS Code agent mode or Copilot CLI and ask
*"run the ocr-benchmark skill on predictions/&lt;your-model&gt;"*. The skill runs the same commands;
every number comes from the scripts, never from the assistant.

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

## Comparing two models

```bash
python -m eval compare results/<model-a> results/<model-b>
```

Pairs the same tests on both sides, per stratum, with an exact McNemar test
(ParseBench: paired per-file score difference with a bootstrap interval). It warns if the two runs
used a different dataset commit, input mode or scorer version.

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
eval/                          scorers (python -m eval), tests (python -m eval.tests), vendored upstream code
.github/skills/ocr-benchmark/  Copilot skill
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
