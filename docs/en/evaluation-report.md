# Infinity-Parser2 vs Azure DI: Technical Evaluation Report

> English version. The Chinese original is [`../evaluation-report.md`](../evaluation-report.md). Working documents under `../working/` are in Chinese only.

| Item | Detail |
|---|---|
| Date | 2026-09-24 (round-2 data included) |
| Audience | Technical leads and team |
| System under test | INF TECH Infinity-Parser2 API, test endpoint; the server echoes the model alias `inf-mllm` (tier and version unknown, see §3) |
| Current baseline | Azure Document Intelligence `prebuilt-layout`, called through the internal company gateway, `outputContentFormat=markdown` |
| Main data | Self-built financial set: 53 public disclosure documents, 210 pages selected by deterministic rules, 1,229 assertions |
| Comparison basis | **Only pages where both systems succeeded** (Infinity 210/210, Azure 191/210); 1,103 paired assertions; McNemar test |
| Test sets and results | All numbers are collected in [`test-results.md`](test-results.md); this report only analyses and judges |
| Source of numbers | Infinity: local `runs/`, every raw response saved. Azure: computed on the company workstation, transcribed from photos in two rounds, see [`../working/report-numbers-20260923.md`](../working/report-numbers-20260923.md) (every table carries a checksum, all verified) |

This report does not say "recommend / do not recommend". It states which document types can be switched,
which cannot at this stage, the evidence for each, what a POC should test, and when to stop.

---

## 1. Conclusions

### 1.1 Three key findings

**① After normalising punctuation, Infinity is not significantly better than Azure on any parsing-quality metric.**
Text completeness: Azure 97.1%, Infinity 93.1% (Inf-only pass : Az-only pass = 2 : 20, p = 0.0001).
The round-1 figure of "Infinity 91.3% vs Azure 72.5%" came entirely from Azure converting full-width punctuation to half-width
while the checker did not normalise punctuation at the time. On sampled amount assertions Azure scored 100%, Infinity 97.5%.
Unit & currency and amount–label pairing showed no significant difference.

**② Both systems drop amounts, but Infinity's drops are confirmed to be whole missing table segments.**
A full amount scan on the 54 paired A-share pages with amounts: Infinity missed 11 occurrences (2 pages), Azure missed 6 (2 pages);
no significant difference at page level. Both Infinity pages were checked one by one: the continuation table at the top of the page
was not output at all, the call still ended normally (`finish_reason=stop`), and three repeated calls gave identical results.
The cause of Azure's 6 misses is not yet known. On one further page Infinity dropped a whole table of 16 amounts,
but Azure failed on that page, so it cannot be compared.

**③ Engineering constraints: no confidence scores, more concurrency does not help, the cost break-even can be computed.**
The API returns no confidence; a `logprobs` request is silently ignored. On the test endpoint, raising concurrency from 1 to 8 kept throughput at 1.6–1.8 pages/min.
Each page costs about 9.6k tokens; if billed per token, the input-only price must be below **$1.13 / million tokens** to match Azure's list price of $10 / 1,000 pages.

**Taken together**: a reason to switch **cannot come from parsing quality** — on every quality metric measured in this round Azure was equal or better.
It can only come from cost (awaiting the vendor's quote, A2), deployment (open weights allow on-premise deployment), or other business considerations.

### 1.2 Judgement by document type

| Document type | Judgement | Evidence | Strength of evidence |
|---|---|---|---|
| **Native Word / Excel / PPT / HTML files** | **Cannot replace directly** | Infinity accepts only PDF and images (format whitelist in SDK `utils/file.py`); Office files must first be converted to PDF or images, losing native text and structure. Azure processes Office and HTML directly | Strong: verified in source code |
| **HK annual reports, interim reports, prospectuses** | **No difference on key fields; can enter POC** | Neither system failed any amount or amount–label assertion; no significant difference on unit & currency. On text completeness Azure is better overall; per-family results await round 3 | Medium |
| **A-share ad-hoc announcements** | **No difference on key fields; can enter POC** | Neither system failed any amount assertion. Infinity's 46 : 0 lead in round 1 was caused by punctuation; per-family relaxed results await round 3 | Medium |
| **HK KYC-type documents** | No conclusion this round | Only 39 text-completeness assertions, no amount assertions | Weak |
| **Financial statements and notes pages in A-share annual / interim reports** | **Cannot replace directly at this stage** | Infinity deterministically dropped whole table segments on 3 pages (one of them a whole table of 16 amounts) with no error signal. Azure also missed 6 amount occurrences on 2 paired pages, cause unknown, so **Azure cannot be said to be problem-free on these pages** | Medium: Infinity's mechanism is confirmed and reproducible; the frequency on both sides needs targeted testing |
| **Workflows that route fields to human review by confidence** | **Cannot replace (structural)** | Infinity provides no confidence at all, so selective review is impossible | Strong: measured via the API |
| **Scanned or skewed pages** | Not compared with Azure this round | Infinity only: a page skewed by 2° fell into endless repetition and hit 32,768 tokens | One-sided observation |
| **Trade-finance documents** | **Not covered; current conclusions cannot be extrapolated** | No compliant public samples could be found, see `../working/corpus-method.md` | — |

### 1.3 Recommended POC scope

0. **Precondition: a reason to switch.** Quality gives no reason (§1.1), so before starting a POC either the vendor's quote shows a cost advantage,
   or the business genuinely needs on-premise deployment, or there is another clear business reason. If none holds, a POC is not recommended.
1. **Documents**: HK annual reports, interim reports and prospectuses, plus A-share ad-hoc announcements; native electronic PDFs only.
   A-share periodic reports get **targeted stress testing only** (item 3) and are not in the replacement scope.
2. **Scale**: at least 300 amount-bearing pages per included family, reported per family, no composite score. Both systems run the same pages, compared page by page.
3. **Targeted set**: pick **at least 50 pages that start with a continuation of the previous page's table**, run both systems and compare the rate of whole-segment omission.
4. **Mandatory guardrails** (already in the POC):
   - **Full amount reconciliation**: check every output amount of an electronic PDF against the text layer; prototype in `tools/amount_scan.py`, which still needs HK amount formats.
   - **`finish_reason` monitoring**: treat every `length` as a failed call and route it to a human.
   - **Downstream normalisation**: map U+2212 "−" to the ASCII minus; normalise full-width / half-width punctuation. The two systems' punctuation habits differ, confirmed by measurement in round 2.
5. **Entry conditions**: written vendor answers to A1 (lock the tested model and version), A2 (billing basis), B1 (confidence), B3 (production throughput and SLA);
   the leaked temporary key has been rotated (C3); if trade-finance documents are in scope, the business line provides sample pages.

### 1.4 Exit criteria

If any criterion is triggered, the POC stops for the affected scope. Thresholds are set by the business; the values below are suggested starting points.

| # | Condition | Scope |
|---|---|---|
| E1 | On paired pages, Infinity has **significantly more** "pages with missing or substituted amounts" than Azure (McNemar p < 0.05), and the vendor cannot fix it within the agreed period | That document family |
| E2 | On the targeted continuation-table set, the upper bound of the 95% CI of Infinity's omission page rate exceeds the business threshold (suggested start: 1%) | A-share periodic reports, and every family with tables spanning pages |
| E3 | The vendor cannot provide **version locking** and **advance notice of changes** | All |
| E4 | Recomputed with the actual quote and **HSBC's Azure contract price** (not list price), the effective cost per page is higher than Azure. Effective cost = call cost + human review cost; without confidence, review cost assumes full or sampled review | All |
| E5 | The throughput in the production SLA is below the business peak demand | All |
| E6 | The page rate of repetition degeneration (`finish_reason=length`) exceeds the threshold, or the vendor will not commit to not billing such invalid calls | All |

---

## 2. Paired comparison with Azure DI

### 2.1 Basis

- **Only pages where both systems succeeded.** Azure failed 19 of 210 pages, **all A-share annual reports**: 16 read timeouts, 2 unknown submission results, 1 gateway failure.
  These are infrastructure problems, not recognition errors, but as a result only 13 paired A-share annual-report pages remain —
  exactly the category where Infinity's failures concentrate.
- Both systems are judged with **the same version of the assertions**; human review results have been written back into the assertion files (GT). `amount_label` counts only human-confirmed entries.
  What the reference is, the judging rules, what cannot be measured (**assertions carry no coordinates; this report does not evaluate layout localisation**), and how to check any number yourself: see **Appendix C**.
- **Two judging bases side by side.** Strict: whitespace removed only — the original basis of `check.py`. Relaxed: additionally full-width → half-width and all punctuation removed.
  Amount assertions use only the strict basis, because commas and decimal points are part of the value.
  `page_integrity` and `unit_currency` **use the relaxed basis**: the two systems' punctuation habits differ, which is output style, not content (§2.5).
- Statistics: exact McNemar test, b = only Infinity passes, c = only Azure passes. p ≥ 0.05 is written as "no significant difference observed",
  **never as "equal"**; strata with n < 30 are written as "insufficient sample"; no weighted composite score.
- **Correction**: when round 1 was summarised on the company side, `unit_currency` was excluded as a whole category with the reason "space-matching problem". Round 2 found
  that no such exclusion code exists in the repository — the AI assistant decided it while writing the table, and the reason was wrong: the real cause is punctuation.
  The category is now back in the comparison.

### 2.2 By assertion type

| Type | Basis | n | Infinity [95% CI] | Azure [95% CI] | Inf-only : Az-only | p |
|---|---|---|---|---|---|---|
| `amount` amount present, correct count | Strict | 486 | 97.5% [95.7, 98.6] | 100.0% [99.2, 100.0] | 0 : 12 | 0.0005 |
| `amount_label` amount next to its label | Strict | 76 | 100.0% [95.2, 100.0] | 98.7% [92.9, 99.8] | 1 : 0 | 1.0, no significant difference |
| `unit_currency` unit & currency | **Relaxed** | 93 | 98.9% [94.2, 99.8] | 100.0% [96.0, 100.0] | 0 : 1 | 1.0, no significant difference |
| `page_integrity` text anchors | **Relaxed** | 448 | 93.1% [90.3, 95.1] | **97.1%** [95.1, 98.3] | 2 : 20 | 0.0001 |
| *Reference: `page_integrity`* | *Strict* | *448* | *91.3%* | *72.5%* | *99 : 15* | *Dominated by punctuation; not used* |
| *Reference: `unit_currency`* | *Strict* | *93* | *95.7%* | *2.2%* | *87 : 0* | *Same as above* |

### 2.3 Failure-by-failure ruling on key fields

Each of Infinity's 12 amount failures was checked by opening the raw response and comparing with the PDF text layer.
For Azure's 1 failure, the original output was extracted in round 2.

| Failure | Count | Pages | Ruling |
|---|---|---|---|
| Infinity: the continuation table at the top of the page was not output | 8 | 2 | **Business error: silent omission** |
| Infinity: negative numbers used U+2212 "−" instead of ASCII "-" | 4 | 2 | Not a business error; values correct |
| Azure: `label not found: 元（含税）`. Azure's output was `元(含税)` — full-width brackets converted to half-width | 1 | 1 | Not a business error; punctuation glyph difference |

The two omissions:
- **A-share annual report p225**: the page starts with the last four rows of the previous page's "accounts receivable by ageing" table; Infinity's output starts directly at the next sub-heading.
- **A-share interim report p170**: the page starts with the "total" row of the previous page's table; Infinity did not output it.

**Across amount and amount–label assertions** (n = 562), key errors after ruling: Infinity 8, i.e. 1.4% [0.7, 2.8], concentrated on 2 pages; Azure 0.
These 8 are 2 page-level events and not independent, so **they should be read per page**.
Also, the full scan found misses on the Azure side too (§2.4), so "Azure 0" covers only what the sampled assertions reached.

### 2.4 Full amount scan: both systems checked

`amount` assertions sample only 4 amounts per page, and `page_integrity` anchors exclude number-only lines,
so "a whole table of numbers disappears" is caught only if it happens to be sampled.
`tools/amount_scan.py` checks every A-share-format amount on the page (thousands separators plus two decimals) and compares how many times each appears in the text layer and in the output.

**Paired set (round 2, same rules for both sides)**:

| Item | Infinity | Azure DI |
|---|---|---|
| Paired pages / amount occurrences | 54 pages / 1,544 | Same |
| Missing occurrences | 11, 0.7% [0.4, 1.3] | 6, 0.4% [0.2, 0.8] |
| Pages with misses | 2 (p225, p170) | 2 (p170, p202) |
| Nature of the misses | **Confirmed**: continuation table at page top dropped | **To be investigated** (round 3) |

Per page: 1 page missed only by Infinity, 1 only by Azure, 1 by both — **no significant difference observed**.
On p170 both sides miss 4 occurrences, but Azure passed all sampled assertions on that page, so Azure missed **4 different amounts**.
Which ones will be known from the round-3 `--show-missing` output.

**Outside the paired set (Infinity only)**: A-share annual report p9 — **the whole "key quarterly financial indicators" table (16 amounts) was not output**,
and its title was attached to the head of the continuation table above it. Azure failed on this page with a gateway timeout, so no comparison is possible.
Across all 210 pages for Infinity: 73 pages with amounts, 27 missing occurrences, on 3 pages; three repeated calls gave identical results.

**What Infinity's 3 pages have in common**: each starts with a continuation of the previous page's table, without its own header.
The model may be treating such a fragment as a page-header region, which the SDK discards by default. **This is a working hypothesis, not verified.**

### 2.5 Text completeness: the round-1 gap came from punctuation

Under the strict basis in round 1, Infinity had 99 extra passes and Azure 15. It was already flagged at the time as "must not be read as Azure losing content".
Round 2 re-judged with the relaxed basis:

- **Azure converts full-width punctuation to half-width.** The original excerpt proves it directly (`（含税），` → `(含税),`);
  Azure passing only 2/93 `unit_currency` assertions under the strict basis has the same cause (`单位：元` → `单位:元`).
- With punctuation normalised, the result reverses: **Azure 97.1%, Infinity 93.1%, 2 : 20, p = 0.0001**.
- What still fails under the relaxed basis are "true-omission candidates": Infinity 31, Azure 13. These still need sampled human confirmation.

**Reading**: on text completeness, Azure is significantly better than Infinity.
Azure not keeping the full-width punctuation glyphs is a formatting difference that downstream normalisation solves; it is not a content error.

### 2.6 By document family and time window

The round-1 per-family and per-window tables use the **strict basis** and mix three assertion types. 99 of the 100 "Inf-only" passes come from `page_integrity`,
which round 2 showed to be mostly punctuation. **So Infinity's lead in the round-1 family table does not hold**; the original table is kept in
`../working/report-numbers-20260923.md` for the record only.

Relaxed per-family results await round 3 (`relaxed_recheck.py --by-family`). Until then, only amount assertions can be read per family:
all of Infinity's amount failures are in A-share annual and interim reports; neither system has amount failures in the HK families or A-share announcements.

### 2.7 Remaining asymmetries

| # | Asymmetry | Effect |
|---|---|---|
| 1 | Azure receives a single-page PDF that keeps its text layer; Infinity receives a 300 DPI rendered image. Microsoft does not say whether Azure uses the embedded text layer; if it does, that favours Azure, and our GT is taken from the text layer | May favour Azure |
| 2 | The two systems' markdown punctuation habits differ. The strict basis **strongly favours Infinity**, so `page_integrity` and `unit_currency` use the relaxed basis (§2.5). The relaxed basis has a cost: genuinely wrong punctuation goes undetected | Handled |
| 3 | Azure goes through an asynchronous API and the company gateway, so its time includes polling; latencies are not comparable | See §4 |
| 4 | Only Azure provides confidence, so this item can only be reported one-sidedly | See §3 |
| 5 | GT is taken from the text layer. A human audit of 53 sampled amounts changed 1; estimated GT error rate 1.9% [0.3, 9.9] | Affects both equally |

> **Correction**: earlier documents said "Azure analyses the whole document and may use full-document context". In fact the company gateway sends Azure an extracted single-page PDF; this claim has been withdrawn (see §8).

---


## 3. Structural differences between a VLM and an OCR pipeline

This section compares **how each system fails**, not scores.
When an OCR pipeline cannot read something, it gives low confidence or leaves it blank;
when a VLM cannot read something, it may produce a perfectly formatted wrong result, or output nothing, while the call still ends normally.
The omissions in §2.3 and §2.4 are instances of the latter.

| Dimension | Infinity-Parser2 (measured) | Azure DI |
|---|---|---|
| Confidence | **None**. `logprobs: true` returns 200 without error but the result is `null` — silently ignored | Confidence per span |
| Determinism | Same page called 3 times (`temperature 0`): 99.0% character-identical, assertion outcomes flip 0.17% [0.05, 0.63]. **Zero flips on the 562 amount assertions**; variation is in layout, e.g. `（2）`/`(2)` and checkbox notation | Deterministic pipeline |
| Silent failure | Whole continuation-table segment at page top omitted, `finish_reason=stop` (§2.3, §2.4), confirmed | 6 amount occurrences missing on 2 paired pages, nature unknown; Azure's confidence can help detect such cases |
| Punctuation glyphs | Keeps the original full-width punctuation | **Converts full-width punctuation to half-width** (measured in round 2); downstream normalisation needed |
| Generation degeneration | 2 cases of endless repetition hitting 32,768 tokens: one on a dense numeric table, one on a financial page skewed by 2°. Identical on 3 retries | This failure mode does not exist |
| bbox | Coordinate tokens generated by the model (normalised 0–1000), not measured by a detector | Geometric detection |
| Version observability | The endpoint only echoes the alias `inf-mllm`; `/v1/models` returns 404; tier and version cannot be determined | Has an API version |

**The shape of the trade-off**: Infinity gives up confidence, determinism and geometric bboxes.
In round 1 we thought it gained an advantage in text completeness; after normalising punctuation in round 2, that advantage is gone (§2.5).
In this round's data, **no parsing-quality return for giving up these three can be seen**.
Its possible value lies outside parsing quality: open weights allow on-premise deployment, and cost (awaiting a quote).

**Working hypothesis (not established)**: the model called itself Qwen3.5 three times, consistent with the base model in the public technical report.
But a model's self-description is unreliable, so this is not a conclusion.

---

## 4. Service and cost

### 4.1 Latency and throughput

**Every number reflects only "that measurement period + concurrency + call path"; it does not represent production capacity, and the two columns are not ranked.**

| | Infinity (test endpoint, direct) | Azure DI (via company gateway) |
|---|---|---|
| Measurement date | 2026-09-21 | 2026-09-22 |
| Concurrency | 2 | 4 |
| Successful pages | 210 / 210 | 191 / 210 (19 infrastructure failures) |
| Per-page latency P50 / P95 | 22.5 s / 55.6 s | 17 s / 21 s (includes gateway and polling, rounded down to whole seconds) |
| Whole-batch time | 46.5 min | 187 min (span between first and last record, includes interruptions) |
| Rate limiting | Silent queuing, no 429 and no `retry-after`; throughput constant at 1.6–1.8 pages/min from concurrency 1→8 | Not measured |
| Throughput variation over time | Measured on different days: 1.92 / 3.66 / 4.51 / 5.41 / 5.64 pages/min, a 2–3× spread | Not measured |

For Infinity, latency by document size reduces to a simple formula: **pages × per-page latency ÷ effective concurrency**.
The test endpoint's effective concurrency is close to 1, so a 100-page document takes roughly 40–60 minutes.
Whether production behaves the same cannot be told from outside — which is exactly what question B3 asks.

### 4.2 Token usage (measured, independent of the vendor)

| Item | Financial set, 210 pages |
|---|---|
| Input tokens / page | Median **8,868**. Determined by pixel count after 300 DPI rendering, independent of page content |
| Output tokens / page | Median **984**, P95 1,782, max 3,287 |
| Whole batch | 1.819 M input + 0.202 M output = 2.02 M tokens |
| One degenerate call | 32,768 output tokens, result invalid |

### 4.3 Cost: a break-even price first, no conclusion

- **Azure DI Layout** list price is $10 / 1,000 pages, i.e. $0.01 per page. **HSBC's actual contract price should be used; obtain it from procurement.**
- **If Infinity bills per token**: counting input tokens only, the price must be below $0.01 ÷ 8,868 ≈ **$1.13 / million tokens** to match the list price.
  Including output tokens lowers the threshold further.
- **Cost from a bank's perspective** = cost of effective output per page without key errors + human review cost.
  Without confidence, review cannot be limited to suspicious fields.
  This directly determines whether the "99.7% automation rate" in the vendor's ROI model can hold.

Question A2 in the first letter only asked "how is it billed"; it should be refined into six questions that plug straight into the formula:

1. Is the billing unit pages, tokens, calls, or an annual subscription?
2. If tokens, **what are the unit prices for image input and text output**?
3. **Are degenerate calls that hit the token limit billed**? Each one is about 33k output tokens of invalid result.
4. Input resolution is chosen by the client, and lower resolution means fewer tokens. Which resolution does the vendor recommend? Who bears the accuracy impact of lowering it?
5. Are there tiered prices or committed-volume discounts?
6. How is on-premise deployment licensed and priced? The weights are Apache-2.0 open source — what exactly would procurement be buying?

---

## 5. Verification of vendor claims

| Source | Figure | Basis |
|---|---|---|
| FinIE website home page | 93.56% | "Overall character accuracy" on financial documents; algorithm, dataset and GT source not disclosed |
| Technical report / HF model card | 87.6% | olmOCR-Bench: about 7,000 binary unit tests checking whether key facts appear in the output |
| Technical report | 74.3% | ParseBench |

The vendor has not provided the dataset behind 93.56% (question A3), so the first reproduction layer cannot be done at all.

**The public-benchmark layer is not part of this report's comparison.** On that layer only 41/120 Azure calls succeeded, and it does not test financial documents.
Infinity's one-sided results on the olmOCR-Bench sample are in the appendix, for aligning definitions only.

---

## 6. Additional Infinity-only results

These results have no Azure comparison and are descriptive only.

| Item | Result | How far it goes |
|---|---|---|
| Perturbation (42 pages × 5: 100/150 DPI, JPEG, photocopy, 2° rotation) | CIs all overlap with the control group; the 2° rotation group had 1 deterministic repetition degeneration | No significant degradation observed; degeneration listed separately as a risk |
| Content coverage | Median 0.98, P10 0.94 | Descriptive |
| Public benchmark olmOCR-Bench subset | 120 pages / 604 tests, per-subset results in `../working/olmocr-bench-results.md` | Definition alignment only |

---

## 7. Risks, gaps and open items

**Declared gaps**

- **Trade-finance documents are not covered**; current conclusions cannot be extrapolated to this scenario. If the business needs it, make it a POC entry condition.
- **Only 13 paired A-share annual-report pages**, exactly the category where Infinity's failures concentrate.
- **The full amount scan does not cover HK amounts written without decimals**, so whole-table omissions on HK pages cannot be detected this round.
- **The nature of Azure's 6 missing amount occurrences in the paired set is still unknown** (§2.4).
- **Relaxed per-family results are not yet available** (§2.6).
- **The 44 "true-omission candidates" still failing under the relaxed basis** (Infinity 31, Azure 13) have not been sampled by a human.
- **Coordinate / layout localisation was not evaluated**: assertions locate only the page, with no bbox (Appendix C.4). If downstream needs highlight-to-source, it must be tested separately.
- **Human review results for `amount_label` exist only on the company workstation**: all 76 are confirmed, but the files cannot be taken out, so this row can only be reproduced there (Appendix C.6).

**Round 2 completed** (2026-09-24): Azure full amount scan, relaxed re-judging, lp02 ruling, verification of the `unit_currency` exclusion reason.

**Round 3: to-do on the company workstation** (no API calls needed; see round 3 in `../working/photo-numbers-prompt.md`)

| # | Item | Effort |
|---|---|---|
| 1 | `amount_scan.py --show-missing`: list exactly which 6 amounts Azure missed | 5 min |
| 2 | `relaxed_recheck.py --by-family`: relaxed per-family results | 5 min |
| 3 | Sample from the 44 still failing under the relaxed basis; human judgement of true omission vs other causes | 1 hour, optional |

**Questions that must be answered before procurement**: data residency; whether customer data is used for training; compliance certifications; SLA and audit logs;
**model version locking**; vendor continuity risk.

---

## 8. Methodological transparency: mistakes we made and corrected

**The report's credibility comes from the evaluation process being verifiable, not from the scores themselves.**
Each item below, had it gone unnoticed, would have distorted the numbers, or made them look right while measuring the wrong thing.

| # | Mistake | Consequence | Fix |
|---|---|---|---|
| 1 | Forbidden string was a prefix of the target value | `amount` pass rate falsely shown as **9.9%**; the real value was 97.9% | Forbidden strings must not be substrings of the target |
| 2 | `exactly_once` used for amounts that repeat | 134 assertions bound to fail falsely | Changed to `exactly_n`, with the expected count taken from the text layer |
| 3 | Number-only lines mixed into page anchors | 8 false failures | Anchors must have at least 8 text characters |
| 4 | Coverage compared raw character counts | Inflated to 1.82 by HTML markup, deflated to 0.18 by table-of-contents dot leaders | Count only letters and digits |
| 5 | Treated Chinese "单位" as a unit of measure | Matched "单位：<company name>" (meaning "entity"), making most of 162 assertions useless | Tightened the regex, 111 remain |
| 6 | Wrong HKEX date parameter | Old and new time windows fetched the same documents | Switched to `fromDate`/`toDate` |
| 7 | No HKEX pagination | Old window falsely returned 0 hits | Paginate with `rowRange` |
| 8 | Amounts wrapped across lines in tables were captured only in part | 37 assertions became hollow tests that always pass. **The pass rate happened not to change, but the wrong thing was being tested** | Join wrapped lines |
| 9 | Review IDs drift when assertions are regenerated | Old review decisions could be applied to other assertions | Version check with a review fingerprint; reject if stale |
| 10 | Claimed "Azure can use full-document context, favouring Azure" | Direction of the asymmetry was wrong; the gateway actually sends single-page PDFs | Withdrawn; §2.7 item 1 rewritten |
| 11 | Amount assertions sample only 4 per page, and page anchors exclude number-only lines | **A whole table of 16 amounts disappeared without any assertion catching it** | Added a full amount scan, `amount_scan.py`, run on both systems |
| 12 | The checker normalised whitespace but not punctuation | Text completeness **pointed the wrong way**: strict basis Infinity ahead 99 : 15; with punctuation normalised Azure ahead 20 : 2. The first brief's headline read "Text completeness: Infinity ahead (to be confirmed)" | Added relaxed re-judging, `relaxed_recheck.py`; these two assertion types now use the relaxed basis |
| 13 | While summarising on the company side, the AI assistant excluded the whole `unit_currency` category on its own, with an invalid reason ("space-matching problem") | One assertion type silently dropped out of the comparison | Require the assistant to cite file names and line numbers; after confirming no such code exists, the category was restored |

Had item 1 gone into the report unchecked, the conclusion would have been "this product is very poor at reading amounts", when in truth the checker was wrong.
Item 11 is the opposite: it hid a real defect in Infinity.
Item 12 made Infinity look better than it is; fortunately round 1 had already flagged "must not be read as Azure losing content" and did not state it as a conclusion.
**Anomalies must be investigated to the bottom before being reported, whoever they favour.**

---

## Appendix A Data sources

| Content | Location |
|---|---|
| Infinity financial-set run | `runs/inf-mllm_doc2md_20260921T013924Z/` (raw responses, `results.csv`, `amount_scan.csv`) |
| Infinity repeat consistency | `runs/inf-mllm_doc2md_20260921T042333Z/`, `…050222Z/`, `runs/consistency/` |
| Infinity perturbation set | `runs/inf-mllm_doc2md_20260921T031242Z/` |
| Azure paired numbers | `docs/working/report-numbers-20260923.md` (photo transcription with checksums) |
| Assertions (GT, including written-back human review) | `data/assertions/*.yaml` |
| Corpus manifest, source URLs, sha256 | `data/corpus/manifest.csv` |
| Endpoint probe | `probe_out/`, `docs/working/t0-findings.md` |
| SDK source verification | `docs/working/sdk-findings.md` |
| Vendor question list | `docs/working/vendor-questions.md` |

## Appendix B Method documents

`docs/working/research-plan.md` (scope), `docs/working/corpus-method.md` (page selection), `docs/working/assertions-method.md` (assertion tiers and review process),
`docs/working/metrics-catalog.md` (metric list), `docs/working/azure-di-baseline.md` (Azure call basis), `docs/working/olmocr-bench-method.md` (public benchmark). All in Chinese.

## Appendix C Evaluation method: what the reference is, how it is judged, what it cannot measure

This appendix answers one question: **for every pass rate in the report, what was used as the correct answer, and by which rule was it judged.**
Every item here can be checked against files and code in the repository; there is no need to trust our account.

### C.1 Comparison process

1. Both systems process **the same 210 pages**. The selection rules are deterministic, with no randomness (`docs/working/corpus-method.md`);
   source URLs and sha256 of the corpus are in `data/corpus/manifest.csv`.
2. Each system outputs markdown; **we do no format conversion**. Azure is called with `outputContentFormat=markdown`
   and `analyzeResult.content` is taken as is, so Microsoft decides how layout becomes markdown. Every raw page record contains
   `"conversion_by_us": false` (`tools/azure_di_runner.py`). This keeps conversion rules from becoming a variable that affects the competitor's score.
3. `tools/check.py` judges both outputs with **the same assertion files**; each assertion passes or fails, with the failure reason recorded
   in `results.csv` in each run directory.
4. `tools/compare_systems.py` pairs both systems' results on **the same assertion** and runs a McNemar test:
   only the counts of "only Infinity passes" (b) and "only Azure passes" (c) matter; assertions both fail count as shared difficulty, not as a difference.

### C.2 What the reference (GT) is

The reference is **not a gold-standard markdown of the whole page** but individual **assertions**: "in the output for page N, a given string must appear,
a given number of times, and certain wrong spellings must not appear". One YAML per document, 53 in total, in `data/assertions/<doc_id>.yaml`, committed to the repository.

Why not full-text gold answers: full-text GT for one annual report takes several person-days, and would dilute the evaluation into yet another single-page OCR test.
The assertion approach follows olmOCR-bench's pass/fail idea (`docs/working/assertions.md`).

A real assertion (the Infinity failure in §2.3):

```yaml
- id: a_share_annual_old_002310_2026-04-30_p225_am01
  type: amount
  severity: critical
  page: 225
  eval_on: md
  rule: exactly_n
  n: 2                       # this amount appears twice in the text layer (current and prior period columns)
  target: 23,364,600.49
  forbid:                    # misplaced decimal point, missing thousands separators: must not appear
  - 23,364,60.049
  - '23364600.49'
  status: auto_textlayer
```

**Assertions come from three tiers; only one is purely human**:

| status | Count | Where the GT comes from | Human involvement |
|---|---|---|---|
| `auto`: `page_integrity` text anchors | 480 | Fragments from the PDF text layer that are unique in the document, ≥ 12 characters, ≥ 8 text characters | None. Characters are taken from the original; used only to detect missing content and hallucination |
| `auto_textlayer`: `amount`, `unit_currency` | 673 | PDF text layer | Audit of 53 sampled amounts, 1 value changed; estimated GT error rate 1.9% [0.3, 9.9] |
| `draft` → `confirmed`: `amount_label` label pairing | 76 | Script proposes candidates; a human confirms each against the rendered page image | Fully human. 76 confirmed, 0 rejected, 1 value changed |

1,229 in total. Human review results are in table 4 of `../working/report-numbers-20260923.md`.

**Why label pairing must be human**: the PDF text layer is reliable for "is this string on this page", but not for **order and attribution**.
Joining across columns can pair an amount with a label from the neighbouring column, so the script's labels can only be candidates.
`check.py` evaluates only the `auto`, `auto_textlayer` and `confirmed` statuses; **`draft` assertions are not judged**
(line 166; `--include-draft` is for debugging only and its results never enter the report).

### C.3 Judging rules

All are **plain-text rules**: substring counts on the normalised output text (`judge()` in `tools/check.py`):

| Rule | Meaning |
|---|---|
| `exactly_once` | The target string appears exactly once |
| `exactly_n` | Appears exactly n times, n taken from the actual count in the text layer |
| `forbid` | None of the listed wrong spellings may appear. A forbidden string must not be a substring of the target, or it causes false failures (§8 item 1) |
| `label_proximity` | The amount and its label are both in the output, at most 120 characters apart |

There are two normalisation bases (§2.1): **strict** removes whitespace only; **relaxed** also converts full-width to half-width and removes punctuation. Amounts use strict only.

### C.4 What this method cannot measure

**Assertions carry no coordinates.** Both the assertion YAML and the exported human-review JSON locate only to the **page**, with no bbox or polygon.
This defines the scope of this report:

- **Only whether text and amounts are correct and complete was tested, not layout localisation.**
  Neither Azure's `boundingRegions` nor Infinity's bbox output was scored.
  If downstream needs coordinates (e.g. highlighting the source in the original, or jumping to the original location during review), **there is currently no evidence, and neither side can be judged from this report.**
- **Label pairing is approximated by text distance** (≤ 120 characters) rather than by being on the same line in the layout — a weaker proxy.
  The two systems write table markdown differently, so this distance may not be entirely fair to both.
- **GT is taken from the PDF text layer**, while Azure receives a PDF with its text layer and Infinity receives a rendered image.
  If Azure uses the embedded text layer, this favours Azure (§2.7 item 1).
- Assertions are sampled: only 4 amounts per page, so a full amount scan was added on top (§2.4).

To test coordinates later: take each amount's bbox from the PDF text layer as GT and compute IoU against the coordinates each system returns.
This needs a new assertion type and is out of scope for this round.

### C.5 How to verify any number yourself

Taking Infinity's first amount failure in §2.3 as an example, tracing from assertion to raw response:

| Step | File | What you see |
|---|---|---|
| 1. Assertion | `data/assertions/a_share_annual_old_002310_2026-04-30.yaml`, id `…_p225_am01` | Requires `23,364,600.49` to appear twice |
| 2. Original | The document's `source_url` in `data/corpus/manifest.csv` (public annual report on CNINFO), page 225 | Once each in the current- and prior-period columns |
| 3. Raw model response | `runs/inf-mllm_doc2md_20260921T013924Z/raw/…_002310_2026-04-30_p225.json` | HTTP status, response headers, `usage`, `finish_reason`, UTC timestamp, the `model` echoed by the server, and the full raw output |
| 4. Judgement | `results.csv` in the same run directory | `pass=0`, reason `expected 2, found 1` |
| 5. Re-run the judging | `python tools/check.py runs/inf-mllm_doc2md_20260921T013924Z` | No API calls; uses only the saved raw responses; the result should be identical |

Any pass or fail in the report can be checked with these five steps.

### C.6 Current state of traceability (stated plainly)

- Human review was done on the company workstation and written back to the assertion files there: `amount_label` **all 76 `confirmed`**,
  0 rejected, 1 value changed (table 4 of `../working/report-numbers-20260923.md`; write-back status re-confirmed on the company workstation on 2026-09-24).
  The company environment does not allow files to be taken out, **so in the local repository these 76 are still `draft`**.
  Consequence: re-running `check.py` locally skips `amount_label` (`draft` is not judged), so this row of §2.2 can only be **reproduced on the company workstation**.
  The other assertion types (`auto`, `auto_textlayer`) do not depend on the human write-back and can be fully reproduced locally.
- Azure's numbers were computed on the company workstation and brought back by photo transcription (`../working/report-numbers-20260923.md`, every table with a checksum).
  Azure's raw responses are not available locally; per-assertion checks on that side must be done on the company workstation.
