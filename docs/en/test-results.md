# Test Sets and Test Results

> English version. The Chinese original is [`../test-results.md`](../test-results.md). Working documents under `../working/` are in Chinese only.

This file contains only **what was tested and what was measured**. For interpretation and conclusions, see [`evaluation-report.md`](evaluation-report.md).

| Item | Detail |
|---|---|
| Date | 2026-09-24 (round-2 data included) |
| System under test | INF TECH Infinity-Parser2 API, test endpoint; the server echoes the model alias `inf-mllm` |
| Baseline | Azure Document Intelligence `prebuilt-layout`, via the internal company gateway, `outputContentFormat=markdown` |
| How it was called | Both systems parse the same pages through their APIs and output markdown; we do no format conversion. Infinity is called over raw HTTP, not through the vendor SDK |
| How it was judged | Outputs are checked assertion by assertion against the same GT; only pages where both succeeded are compared; McNemar paired test; no composite score |

---

## 1. Test sets

### 1.1 Self-built financial set (used for the comparison)

53 public disclosure documents from CNINFO (A-shares) and HKEXnews (Hong Kong), with 210 pages chosen by deterministic rules
and no random sampling. Selection rules: [`../working/corpus-method.md`](../working/corpus-method.md); source URL and sha256 of every document: `data/corpus/manifest.csv`.

| Document family | Documents | Pages | Text completeness | Amount | Unit & currency | Amount–label | Total assertions |
|---|---|---|---|---|---|---|---|
| A-share annual reports | 8 | 32 | 64 | 128 | 29 | — | 221 |
| A-share interim reports | 8 | 32 | 39 | 128 | 29 | — | 196 |
| A-share ad-hoc announcements | 8 | 29 | 78 | 36 | — | 23 | 137 |
| HK annual reports | 8 | 32 | 82 | 116 | 28 | 4 | 230 |
| HK interim reports | 8 | 32 | 96 | 107 | 25 | 7 | 235 |
| HK KYC-type documents | 8 | 13 | 39 | — | — | — | 39 |
| HK prospectuses | 5 | 40 | 82 | 47 | — | 42 | 171 |
| **Total** | **53** | **210** | **480** | **562** | **111** | **76** | **1,229** |

Time windows (split at the model release date, used as a leakage control): new 95 pages, old 99 pages, older 16 pages.

What each assertion type checks:

| Type | What it checks |
|---|---|
| Text completeness `page_integrity` | 3 text fragments sampled per page; each must appear verbatim in the output (detects missing content and hallucination) |
| Amount `amount` | 4 amounts sampled per page; each must appear verbatim, the correct number of times, with no wrong spellings |
| Unit & currency `unit_currency` | Table headers such as "单位：元" (unit: yuan) or "人民币千元" (RMB thousand) are kept |
| Amount–label `amount_label` | An amount and its line-item label appear next to each other (≤ 120 characters apart) |

### 1.2 Where the GT (assertions) comes from

One YAML per document in `data/assertions/`, 53 in total. Definitions: [`../working/assertions.md`](../working/assertions.md); generation and review process: [`../working/assertions-method.md`](../working/assertions-method.md).

| GT source | Count | Human involvement |
|---|---|---|
| Extracted automatically from the PDF text layer: text completeness | 480 | None; characters are taken from the original |
| Extracted automatically from the PDF text layer: amount, unit & currency | 673 | Audit of 53 sampled amounts, 1 value changed; estimated GT error rate 1.9% [0.3, 9.9] |
| Candidates from a script, each confirmed by a human: amount–label | 76 | Fully human. 76 confirmed, 0 rejected, 1 value changed |

Human review was done on the company workstation and written back to the assertion files there; in the local repository these 76 are still `draft`.

### 1.3 Paired set

Azure failed 19 of 210 pages, **all A-share annual reports**: 16 read timeouts, 2 unknown submission results, 1 gateway failure — all infrastructure problems.
Infinity succeeded on all 210 pages.

| Item | Count |
|---|---|
| Pages where both succeeded | 191 |
| Paired assertions | 1,103 (text completeness 448, amount 486, unit & currency 93, amount–label 76) |
| A-share annual-report pages in the paired set | 13 |

### 1.4 Other test sets

| Test set | Size | Coverage |
|---|---|---|
| Public benchmark olmOCR-Bench | 120 pages and 604 official tests sampled from the official 1,403 pages | Infinity completed all 120; Azure succeeded on 41 |
| Perturbation set | 42 pages from the self-built set × 5 perturbations (100 / 150 DPI, JPEG compression, photocopy, 2° rotation) | Infinity only |
| Repeat consistency | Self-built set, 210 pages × 3 calls | Infinity only |
| Endpoint probe T0 | 13 behaviours: rate limiting, logprobs, determinism, truncation, etc. | Infinity only |

---

## 2. Test results

### 2.1 By assertion type (paired set)

Bases: strict = whitespace removed only; relaxed = additionally full-width → half-width and all punctuation removed. Amounts use strict only.
The two systems' punctuation habits differ (Azure converts full-width punctuation to half-width), so text completeness and unit & currency use the relaxed basis.

| Type | Basis | n | Infinity [95% CI] | Azure [95% CI] | Inf-only : Az-only | p |
|---|---|---|---|---|---|---|
| Amount | Strict | 486 | 97.5% [95.7, 98.6] | 100.0% [99.2, 100.0] | 0 : 12 | 0.0005 |
| Text completeness | Relaxed | 448 | 93.1% [90.3, 95.1] | 97.1% [95.1, 98.3] | 2 : 20 | 0.0001 |
| Unit & currency | Relaxed | 93 | 98.9% [94.2, 99.8] | 100.0% [96.0, 100.0] | 0 : 1 | 1.0 |
| Amount–label | Strict | 76 | 100.0% [95.2, 100.0] | 98.7% [92.9, 99.8] | 1 : 0 | 1.0 |

Strict basis (not used, kept for reference):

| Type | n | Infinity passes | Azure passes | Inf-only : Az-only |
|---|---|---|---|---|
| Text completeness | 448 | 409 (91.3%) | 325 (72.5%) | 99 : 15 |
| Unit & currency | 93 | 89 (95.7%) | 2 (2.2%) | 87 : 0 |

### 2.2 Amount and amount–label failures, one by one

13 assertions in the paired set failed on at least one side; each was ruled on by opening the raw output and comparing with the PDF text layer.

| Assertion | System | Judgement | Ruling |
|---|---|---|---|
| A-share annual 002310 p225 am01–am04 (4) | Infinity | Fewer occurrences than the text layer | **Business error**: the continuation table at page top was not output, `finish_reason=stop` |
| A-share interim 688098 p170 am01–am04 (4) | Infinity | Not found | **Business error**: the "total" row of the continuation table at page top was not output, `finish_reason=stop` |
| A-share annual 300208 p11 am04 (1) | Infinity | Not found | Not a business error: minus sign written as U+2212 "−", value correct |
| A-share interim 839680 p9 am01 / am03 / am04 (3) | Infinity | Not found | Not a business error: same as above |
| A-share announcement 605011 p1 lp02 (1) | Azure | Label not found | Not a business error: `元（含税）` converted to `元(含税)` |

Total: Infinity 8 business errors (on 2 pages) and 4 formatting differences; Azure 0 business errors and 1 formatting difference.
Full assertion IDs and both systems' verdicts verbatim: [`../working/report-numbers-20260923.md`, table 5](../working/report-numbers-20260923.md#表-5-关键字段失败明细).

### 2.3 Full amount scan

Sampled assertions cover only 4 amounts per page, so every A-share-format amount on the page (thousands separators plus two decimals) was also checked (`tools/amount_scan.py`).

**Paired set**: 54 pages, 1,544 amount occurrences.

| System | Missing occurrences | Miss rate [95% CI] | Pages with misses |
|---|---|---|---|
| Infinity | 11 | 0.7% [0.4, 1.3] | 2 |
| Azure | 6 | 0.4% [0.2, 0.8] | 2 |

| Page | Amounts in text layer | Infinity missing | Azure missing |
|---|---|---|---|
| A-share annual 002310 p225 | 32 | 7 | 0 |
| A-share interim 688098 p170 | 46 | 4 | 4 |
| A-share interim 688098 p202 | 16 | 0 | 2 |

Per page: 1 page missed only by Infinity, 1 only by Azure, 1 by both — no significant difference observed. The cause of Azure's misses is still to be investigated.

**Outside the paired set (Infinity only)**: 73 of 210 pages contain amounts, 2,149 occurrences, 27 missing, on 3 pages.
The third page is A-share annual 300572 p9, where the whole "key quarterly financial indicators" table (16 amounts) was not output; Azure timed out at the gateway on that page, so it cannot be compared.
Three repeated calls missed exactly the same amounts.

### 2.4 By document family and time window (round-1 strict basis, for the record only)

These two tables use the strict basis and mix three assertion types (unit & currency excluded). 99 of the 100 "Inf-only" passes come from punctuation differences in text completeness,
so **they cannot be used to read differences between families**. Relaxed per-family results await round 3.

| Document family | n | Inf passes | Az passes | Inf-only | Az-only |
|---|---|---|---|---|---|
| A-share annual reports | 84 | 76 | 64 | 19 | 7 |
| A-share interim reports | 167 | 155 | 143 | 19 | 7 |
| A-share ad-hoc announcements | 137 | 133 | 87 | 46 | 0 |
| HK annual reports | 202 | 191 | 195 | 2 | 6 |
| HK interim reports | 210 | 202 | 203 | 1 | 2 |
| HK KYC-type documents | 39 | 38 | 36 | 2 | 0 |
| HK prospectuses | 171 | 164 | 158 | 11 | 5 |

| Time window | n | Inf passes | Az passes | Inf-only | Az-only |
|---|---|---|---|---|---|
| new | 505 | 490 | 453 | 44 | 7 |
| old | 473 | 441 | 405 | 53 | 17 |
| older | 32 | 28 | 28 | 3 | 3 |

Only amounts can be read per family: all of Infinity's amount failures are in A-share annual and interim reports; neither system has amount failures in the HK families or A-share announcements.

### 2.5 Service and cost

The two columns differ in measurement date, concurrency and call path, so they are **for reference only and not ranked**.

| | Infinity (test endpoint, direct) | Azure (via company gateway) |
|---|---|---|
| Measurement date | 2026-09-21 | 2026-09-22 |
| Concurrency | 2 | 4 |
| Successful pages | 210 / 210 | 191 / 210 |
| Per-page latency P50 / P95 | 22.5 s / 55.6 s | 17 s / 21 s (includes gateway and polling) |
| Whole-batch time | 46.5 min | 187 min (includes interruptions) |
| Rate limiting | Silent queuing, no 429; throughput constant at 1.6–1.8 pages/min from concurrency 1→8 | Not measured |
| Throughput variation over time | On different days: 1.92 / 3.66 / 4.51 / 5.41 / 5.64 pages/min | Not measured |
| Price | Not quoted | List price $10 / 1,000 pages |

Infinity token usage (210 pages): median input 8,868 / page, median output 984 / page (P95 1,782).
If billed per token, counting input only, the price must be below **≈ $1.13 / million tokens** to match Azure's list price.

### 2.6 Infinity-only results (no Azure comparison)

| Item | Result |
|---|---|
| Confidence | Not returned; a `logprobs: true` request returns 200 with a `null` result |
| Repeat consistency (210 pages × 3 calls) | 99.0% character-identical; assertion outcomes flip 0.17% [0.05, 0.63]; zero flips on the 562 amount assertions |
| Generation degeneration | 2 cases of endless repetition hitting 32,768 tokens: one on a dense numeric table, one on a page skewed by 2°; identical on 3 retries |
| Perturbation (42 pages × 5) | CIs all overlap with the control group; the 2° rotation group had 1 repetition degeneration |
| Content coverage | Median 0.98, P10 0.94 |
| olmOCR-Bench subset (120 pages) | Per subset from 0.0% (arxiv_math) to 87.5% (long_tiny_text), no composite score; details in [`../working/olmocr-bench-results.md`](../working/olmocr-bench-results.md) |

---

## 3. Sources of the numbers

| Data | Location |
|---|---|
| Infinity financial set | `runs/inf-mllm_doc2md_20260921T013924Z/`: raw responses per page, `results.csv`, `amount_scan.csv` |
| Infinity repeat consistency | `runs/inf-mllm_doc2md_20260921T042333Z/`, `…050222Z/` |
| Infinity perturbation set | `runs/inf-mllm_doc2md_20260921T031242Z/` |
| Infinity olmOCR-Bench | `runs/inf-mllm_doc2md_20260918T065831Z/` |
| Azure financial set | `azure_gateway_corpus_20260922`, on the company workstation; numbers transcribed from photos with a checksum per table, see [`../working/report-numbers-20260923.md`](../working/report-numbers-20260923.md) |
| Assertions (GT) | `data/assertions/*.yaml` |
| Corpus manifest, source URLs, sha256 | `data/corpus/manifest.csv`, `pages.csv` |

`runs/` and the corpus manifest are packed in [`dist/evidence_20260923.zip`](../../dist/evidence_20260923.zip);
corpus PDFs are in [Release v0.1-interim](https://github.com/gejun2008/doc-parser-eval/releases/tag/v0.1-interim).
Steps to check any number: [`evaluation-report.md`, Appendix C.5](evaluation-report.md#c5-how-to-verify-any-number-yourself).
