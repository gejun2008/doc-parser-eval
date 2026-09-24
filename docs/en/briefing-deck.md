# Infinity-Parser2 Evaluation Brief

> Markdown version of `briefing-deck.html`, same content as the slides, one section per slide. Chinese original: [`../briefing-deck.md`](../briefing-deck.md).
> Legend: 🟢 yes / supported　🔴 no / not supported　🟡 insufficient evidence or not compared　⚪ not covered

---

## 1 / 4　Document Type Suitability: Azure DI vs Infinity-Parser2

<sub>INFINITY-PARSER2 vs AZURE DOCUMENT INTELLIGENCE · TECHNICAL EVALUATION BRIEF · 2026-09-24</sub>

> **In one sentence: on parsing quality Azure is equal or better on every metric.** No difference was seen on key fields in HK disclosures and A-share announcements, so these can enter a POC;
> but on A-share annual and interim report pages that start with a continuation table, Infinity **silently drops the whole table segment**. It also **provides no confidence** and **accepts only PDF and images**.
> A reason to switch can only come from cost or on-premise deployment.

### Supported file formats

| | PDF | Images | Office (Word / Excel / PPT) | HTML |
|---|---|---|---|---|
| **Azure DI** | 🟢 | 🟢 JPG · PNG · BMP · TIFF · HEIF | 🟢 | 🟢 |
| **Infinity-Parser2** | 🟢 | 🟢 PNG · JPG · BMP · TIFF · WEBP | 🔴 | 🔴 |

For Infinity, Word / Excel / PPT must first be converted to PDF or images, losing native text and structure.

### By document type (PDF)

| Document type | Judgement | Evidence (same pages, paired comparison) |
|---|---|---|
| HK annual / interim reports / prospectuses | 🟢 **Candidate · enter POC** | Neither system failed any amount or label assertion; per-family text completeness awaits round 3 |
| A-share ad-hoc announcements | 🟢 **Candidate · enter POC** | Neither system failed any amount assertion; Infinity's round-1 lead was traced to punctuation |
| A-share annual / interim reports (statements & notes) | 🔴 **Not replaceable yet** | Infinity deterministically dropped tables on 3 pages (27 amounts), all on continuation pages, with no error; Azure also missed 6, cause unknown |
| Workflows routing review by confidence | 🔴 **Not replaceable (structural)** | The API returns no confidence; a `logprobs` request is silently ignored |
| HK KYC-type documents | 🟡 **Insufficient evidence** | Only 39 text-completeness assertions, no amount assertions |
| Scanned / skewed pages | 🟡 **Not compared with Azure** | Infinity only: a page skewed by 2° fell into endless repetition, hit 32k tokens, output unusable |
| Trade-finance documents | ⚪ **Not covered** | No compliant public samples; current conclusions cannot be extrapolated |

<sub>Sample: 53 public disclosure documents → 210 pages → 1,229 assertions; 191 paired pages (19 Azure pages failed on gateway timeouts)　·　Source: [evaluation-report.md](evaluation-report.md)</sub>

---

## 2 / 4　Parsing Quality: Azure DI vs Infinity-Parser2

<sub>Azure is equal or better on every metric · same 191 pages, same assertions, paired comparison</sub>

<table>
<tr>
<td width="55%" valign="top">

### Assertion pass rate

| Metric | n | Infinity | Azure DI |
|---|---|---|---|
| **Amounts**<br><sub>value appears verbatim, the correct number of times</sub> | 486 | 97.5% | **100%** |
| **Text completeness**<br><sub>3 text lines per page must appear verbatim</sub> | 448 | 93.1% | **97.1%** |
| **Unit & currency**<br><sub>headers such as "unit: yuan" are kept</sub> | 93 | 98.9% | 100% |
| **Amount next to label**<br><sub>amount and its line-item label together</sub> | 76 | 100% | 98.7% |

- **Amounts**: significant (0 : 12, p = 0.0005). Of Infinity's 12 failures, checked one by one, **8 are real omissions**; the other 4 differ only in the minus-sign glyph.
- **Text completeness**: significant (2 : 20, p = 0.0001). **Round 1's 91.3% vs 72.5% is void**: it came from Azure converting full-width punctuation to half-width.
- **Unit & currency, amount next to label**: no significant difference.

</td>
<td width="45%" valign="top">

### 🔴 Full amount scan: both miss, for different reasons

<sub>54 paired A-share pages with amounts, 1,544 amounts</sub>

| Missed by Infinity | Missed by Azure |
|---|---|
| **11** · 2 pages | **6** · 2 pages |

- **Infinity, confirmed**: the continuation table at page top was not output; the call still "ended normally", and 3 repeats missed exactly the same
- One more page outside the paired set: **a whole table of 16 amounts** vanished (Azure failed at the gateway on that page, no comparison)
- Cause of Azure's 6 misses to be investigated (round 3); no significant difference at page level

### Service & cost

<sub>Reference only; bases differ, not ranked</sub>

| | Infinity (test endpoint) | Azure DI (company gateway) |
|---|---|---|
| Success rate | 210 / 210 | 191 / 210 |
| Latency P50 | 22.5 s (concurrency 2) | 17 s (concurrency 4, incl. polling) |
| Throughput | 1.6–5.6 pages/min, more concurrency no help | — |
| Price | Not quoted | List $10 / 1,000 pages |

<sub>About 9.6k tokens per page. If billed per token, the input price must be below **≈ $1.13 / million tokens** to match Azure's list price.</sub>

</td>
</tr>
</table>

<sub>Test: McNemar paired test; no composite score; no conclusion for strata with n &lt; 30　·　Source: [test-results.md](test-results.md)</sub>

---

## 3 / 4　Technical Approach: Azure DI (OCR Pipeline) vs Infinity-Parser2 (VLM)

<sub>When OCR fails it reports uncertainty; when a VLM fails it delivers anyway · next: POC scope and exit criteria</sub>

<table>
<tr>
<td width="58%" valign="top">

| | Infinity-Parser2 | Azure DI (prebuilt-layout) |
|---|---|---|
| Approach | Vision-language model (VLM), generates the whole page as markdown in one pass | OCR + layout-analysis pipeline |
| Input | Each page rendered to a 300 DPI image, processed independently | PDF (single-page PDFs in this test) |
| Confidence | 🔴 **None** | 🟢 **For every text span** |
| Determinism | Same page called 3 times: 99.0% character-identical (zero change in amounts) | Deterministic |
| Punctuation | Keeps original full-width punctuation | Converts full-width to half-width; downstream normalisation needed |
| When unsure | May omit or generate content; the call still ends normally | Low confidence or left blank |
| Unique failure | Endless repetition hitting the token limit (seen twice) | — |
| Bounding boxes | Generated by the model | Geometric detection |
| Version | Only the alias `inf-mllm` is visible; model and version unknown | API version, can be pinned |
| Model | Open weights (Apache-2.0); claims to be based on Qwen3.5 (unverified) | Closed, hosted service |

</td>
<td width="42%" valign="top">

### Recommended POC scope

- **Precondition: a cost or on-premise reason**; parsing quality alone is not a reason
- HK annual / interim reports and prospectuses + A-share announcements, electronic PDFs only, ≥ 300 pages per family
- **Targeted test on ≥ 50 "continuation table at page top" pages** to measure how often tables are dropped
- Mandatory guardrails: reconcile every amount against the PDF text layer; route every `finish_reason=length` to a human
- Before testing, the vendor must answer: model and version locking, billing, confidence, production SLA

### Exit criteria (stop if any is triggered)

- Significantly more pages with missing or substituted amounts than Azure
- No version locking and no advance notice of changes
- Per-page cost above Azure at contract price, including human review
- Production throughput below business peak; repetition-degeneration rate above threshold

</td>
</tr>
</table>

<sub>Source: [evaluation-report.md](evaluation-report.md)</sub>

---

## 4 / 4　Evaluation Summary

<sub>Conclusion · Details · Method · Data sets</sub>

<table>
<tr><th width="110" align="left">Conclusion</th><td>Azure is significantly better on <b>amounts</b> and <b>text completeness</b>; on <b>unit &amp; currency</b> and <b>amount–label pairing</b> there is no significant difference; Infinity is better on none. Infinity also has two structural gaps: it <b>returns no confidence</b>, and on pages starting with a continuation table it <b>silently drops the table</b>.</td></tr>
<tr><th width="110" align="left">Details</th><td>Test result data: see <a href="test-results.md">test-results.md</a>; analysis and findings: see <a href="evaluation-report.md">evaluation-report.md</a></td></tr>
<tr><th width="110" align="left">Method</th><td>Both systems parse the same pages through their APIs and output markdown, with no conversion on our side; outputs are checked assertion by assertion against the same GT, only pages where both succeeded are compared, a paired test decides significance, and no composite score is computed.</td></tr>
<tr><th width="110" align="left">Data sets</th><td>Self-built financial set: 53 public disclosure documents (CNINFO, HKEXnews) → 210 pages → 1,229 assertions, 191 paired pages. GT is mainly extracted automatically from the PDF text layer; 76 label pairings were confirmed by a human one by one.<br>Public benchmark olmOCR-Bench: 41 pages run.</td></tr>
</table>

<table>
<tr>
<td width="50%" valign="top">

**[test-results.md](test-results.md)**

<sub>Test sets and results: composition, GT sources, every metric and failure detail, service data, sources of numbers</sub>

</td>
<td width="50%" valign="top">

**[evaluation-report.md](evaluation-report.md)**

<sub>Analysis report: conclusions and evidence, judgement by document type, structural differences, POC scope and exit criteria, method (Appendix C)</sub>

</td>
</tr>
</table>

<sub>Sources: [test-results.md](test-results.md)　·　[evaluation-report.md](evaluation-report.md)</sub>
