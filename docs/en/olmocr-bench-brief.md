# Infinity-Parser2 vs Azure DI: Public Benchmark Comparison (Summary)

| Item | Detail |
|---|---|
| Date | 2026-09-30 |
| Under test | Infinity-Parser2 API (endpoint echoes `inf-mllm`; vendor states Flash 2.1), run 2026-09-18 |
| Baseline | Azure Document Intelligence `prebuilt-layout`, API `2024-11-30`, via the company UAT gateway, run 2026-09-29 |
| Role | **Entry check** on a public benchmark. Whether Infinity can replace Azure is decided by the in-house financial document set (see `evaluation-report.md`) |

**In one line**: on the same pages, scored by the same code, we observed no significant overall difference.
**Azure is clearly better on tables.** Infinity's advantage shows up on handwritten historical letters, which have little to do with our use case.

---

## 1. Test set: what we tested on

**olmOCR-Bench**: a public PDF parsing benchmark released by AllenAI (ODC-BY licence), 1,403 pages and 7,019 tests.
Why this benchmark:

- **Third-party questions**: neither we nor the vendor wrote the tests or the scoring code
- **Official scorer used as-is**: pinned to commit `ab294c6a`, not a single line changed
- **Reproducible**: fixed random seed for sampling; every raw output is kept, so any number can be recomputed

We sampled **120 pages / 499 tests** weighted towards financial-document relevance (formula tests excluded, see §3):

| Subset | Pages | Tests | What it checks | Relevance to financial documents |
|---|---|---|---|---|
| Tables | 40 | 187 | Cell values and row/column relationships | **Highest**: core of financial statements and notes |
| Long tiny text | 15 | 120 | No dropped text in small, dense print | High: close to notes pages |
| Multi-column | 20 | 68 | Reading order | Medium |
| Old scans | 15 | 75 | Historical letters | Low: 10 of the 15 pages are handwritten |
| Headers & footers | 20 | 49 | Page headers/footers kept out of body text | Medium, but the two systems format them differently (§3) |

## 2. Method: how we scored

1. **Every test is pass or fail.** For example: "this sentence must appear", "paragraph A must come before B", "the cell to the right of X must be Y".
2. **Both systems run the same pages and the same tests**, compared test by test.
3. **Only disagreements count**: how many tests only Infinity passed, and how many only Azure passed.
   A McNemar test decides whether the difference is significant (p < 0.05). Tests both pass or both fail do not affect the result.
4. **No composite score**: results are reported per subset. When p ≥ 0.05 we write "no significant difference observed", never "equal".

## 3. Fairness: every known bias on the table

| Issue | How we handled it |
|---|---|
| **Vendor home ground**: the vendor has published a score on this benchmark (87.6% on the full set); we cannot rule out that it saw this data in training | Stated openly; favours Infinity. We ran a sample, so our numbers are not compared with 87.6% |
| **Different inputs**: Azure receives the original PDF, Infinity receives a 300 DPI image (what the vendor SDK does) | Each system called the way its product is meant to be used |
| **Headers & footers**: Azure writes page headers/footers as HTML comments; the scorer still counts them as "in the body" and fails Azure | This row is **not compared** |
| **Formula tests**: the company network could not install the component needed to render formulas, so Azure could not be scored | Formula tests removed on both sides: 604 tests down to 499 |
| **Call failures**: 1 Infinity page fell into a repetition loop and was truncated; all 120 Azure pages succeeded | Scored both ways: failed page counted as wrong, or dropped on both sides. Same conclusions |

## 4. Results

| Subset | Tests | Infinity | Azure | Only Inf : only Az | Conclusion |
|---|---|---|---|---|---|
| **Tables** | 187 | 64.2% | **86.6%** | 11 : 53 | **Azure significantly better** |
| Long tiny text | 120 | 87.5% | 82.5% | 11 : 5 | No significant difference observed |
| Multi-column | 68 | 82.3% | 75.0% | 8 : 3 | No significant difference observed |
| Old scans | 75 | 50.7% | 28.0% | 19 : 2 | Infinity higher, **but mostly handwriting**; a manual look at both outputs shows a smaller real gap than the scores suggest |
| Headers & footers | 49 | 30.6% | 14.3% | 9 : 1 | Not compared (different output formats) |
| *All, for reference only* | *499* | *66.9%* | *68.1%* | *58 : 64* | *No significant difference observed (p = 0.65)* |

**Why tables differ so much**: on 14 of 40 pages Infinity **did not recognise the table as a table**.
The whole table came out as a run of plain text, with rows and columns lost and no error raised.
When it did recognise a table, 91% of its cells were correct.
This "flattened table" failure is the highest risk for financial statements.

## 5. What this layer tells us

- **It shows**: on neutral public tests, Infinity's basic parsing is at Azure's level and can move to the next stage;
  tables are the risk to watch.
- **It does not show**: this benchmark contains no financial statements. Replacement in the financial company's setting depends on
  per-document-type results from the in-house financial document set.

---

*Reproduce: raw outputs and per-test scores are in `runs/inf-mllm_doc2md_20260918T065831Z/` (local machine) and
`runs/azure_di_layout_20260929T133601Z/` (company machine); method details in `working/olmocr-bench-method.md`;
Azure figures transcribed in `working/olmocr-azure-numbers-20260929.md`.*
