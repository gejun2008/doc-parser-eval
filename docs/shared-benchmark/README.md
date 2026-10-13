<!--
草稿：ocr-benchmark-dataset 仓库的新版 README。
状态：等公司电脑结构清单（copilot-prompt-dataset-inventory.md）回来后定稿。
TBD 标记处：预测文件命名、manifest 文件名、eval CLI 与 skill 尚未实现、金融集 license。
-->

# OCR Benchmark Dataset

Inputs, ground truth and scorers for evaluating document parsers on financial documents.
Bring your parser's outputs, run one command (or one Copilot skill), get a per-collection report.

**Snapshot:** `2026-09-30` · **Financial GT frozen:** `2026-09-23`
**This repository never stores model outputs, scores or credentials.**

## Collections

| Collection | Inputs | Ground truth | What it tests | Metric |
|---|---|---|---|---|
| **Financial disclosures** | 210 pages from 53 CNINFO / HKEX PDFs, 7 families | 1,229 assertions | amounts, units/currency, label–amount, page integrity | assertion pass rate by family × type |
| **olmOCR-Bench subset** | 120 single-page PDFs | 604 upstream tests | tables, multi-column, headers/footers, small text, old scans, math | upstream pass rate by subset |
| **ParseBench subset** | 500 files (482 PDF, 18 images) | 45,931 upstream rules | tables, charts, text content & formatting, layout | upstream metric per dimension |
| **Perturbation** | 210 images = 42 pages × 5 variants | reuses financial GT | low DPI, JPEG, skew, photocopy | pass-rate drop vs. clean page |

The financial collection decides fit for financial documents. The two public subsets are entry checks
only: they may have leaked into training data, so treat a high score there as necessary, not sufficient.

## Quick start

```bash
git lfs install
git clone <repo-url> && cd ocr-benchmark-dataset
pip install -r eval/requirements.txt
python -m eval verify                      # checks LFS files and sha256 against metadata/checksums.csv
```

**1. Run your parser** on the pages listed in `metadata/<collection>_manifest.csv` <!-- TBD 文件名 -->
and save one file per page:

```
predictions/<your-model>/
  run_card.yaml                            # model, version, input mode, date — see below
  financial/<page-id>.md                   # TBD: <page-id> naming
  olmocr/<page-id>.md
  parsebench/<page-id>.md                  # or .json with bboxes to enable Visual Grounding
  perturbation/<page-id>.md
```

Skip any collection you don't need. A listed page with no file is scored as a **failure**, not skipped.

**2. Score:**

```bash
python -m eval score predictions/<your-model>
```

**With Copilot:** open the repo in VS Code agent mode or Copilot CLI and ask
*"run the ocr-benchmark skill on predictions/&lt;your-model&gt;"*. The skill runs the same commands;
all scores come from the scripts, never from the assistant.

## Run card

```yaml
model: my-parser
version: 2.1.0                 # as reported by the service, if it reports one
input_mode: image              # image | pdf
dpi: 300                       # required when input_mode is image
output_format: markdown        # markdown | json
date: 2026-10-13
notes: ""                      # anything that differs from the defaults
```

Image and PDF input are **not** equivalent (a PDF keeps its text layer). Two runs with different
input modes are not comparable; the report prints the input mode next to every number.

## Results

Written to `results/<your-model>/` (git-ignored):

```
results/<your-model>/
  run_card.yaml                 # yours + dataset commit, scorer versions, timestamp
  financial.md                  # pass rate by family × assertion type, failures listed
  olmocr.md                     # pass rate by subset
  parsebench.md                 # one metric per dimension
  perturbation.md               # drop vs. clean page, by variant
  details/*.csv                 # one row per test: page, test id, type, outcome
```

**There is no overall score.** Each collection uses its own metric; do not average across them.
Strata with too few samples are reported as "insufficient sample", not as a number.

ParseBench with markdown only: Tables, Charts, Content Faithfulness and Semantic Formatting are scored;
**Visual Grounding is reported as N/A** (it needs bboxes), never as 0.

## Comparing two models

```bash
python -m eval compare results/<model-a> results/<model-b>
```

Paired on the same pages, with confidence intervals. Only compare runs with the same dataset
snapshot and the same input mode.

## Rules

Most rules are enforced by the scorer. These three are not — they are on you:

1. **Never give the model GT files** (`gt/`) or anything derived from them.
2. **Declare the input mode honestly** in the run card, and use the same mode for every model you compare.
3. **Don't edit GT during a comparison.** Found a GT error? Open an issue; it gets fixed in the next snapshot.

## Repository layout

```
data/        input PDFs and images (Git LFS)
gt/          ground truth: financial YAML, upstream JSONL
metadata/    manifests, checksums, GT provenance
eval/        scorers, specs, fixtures              # TBD: not yet implemented
.github/skills/ocr-benchmark/SKILL.md              # TBD: not yet implemented
docs/
```

## Docs

| Read this | When you need |
|---|---|
| `docs/protocol.md` | the full evaluation protocol: input rendering, failure handling, statistics |
| `docs/eval/financial.md` | assertion types, fields, which statuses are scored |
| `docs/eval/olmocr.md`, `docs/eval/parsebench.md` | sampling, pinned upstream scorer, differences from the official leaderboard |
| `docs/eval/perturbation.md` | how variants were generated |
| `docs/gt-provenance.md` | how the financial GT was built and reviewed |
| `docs/known-limitations.md` | what this benchmark cannot tell you |

## Versioning

Snapshots are tagged `data-YYYY-MM-DD`. Scorers are versioned separately (`eval-vX.Y`).
A result is identified by **dataset tag + scorer version + run card**; the report records all three.

## License

| Collection | Source | License |
|---|---|---|
| olmOCR-Bench subset | `allenai/olmOCR-bench` | ODC-BY |
| ParseBench subset | `llamaindex/ParseBench` @ `2805a1d` | Apache-2.0 |
| Financial disclosures, perturbation | public CNINFO and HKEX filings | TBD |
| Scorers | olmOCR @ `ab294c6a`, ParseBench @ `3295d7f`, own code | upstream licenses; own code TBD |
