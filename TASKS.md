# TASKS

按顺序做。每个 gate 不过，后面的不要开工——T0 的实测结果决定 runner 的形状。

## 进度总览（2026-09-21）

| 任务 | 状态 | 产物 |
|---|---|---|
| T0 端点探针 | ✅ | `docs/t0-findings.md`、`probe_out/` |
| T1 语料与选页 | ✅ 53 份 / 6,978 页 → 选 210 页 | `docs/corpus-method.md`、`data/corpus/` |
| T2 扰动组 | ✅ 42 页 × 5 种 | `runs/inf-mllm_doc2md_20260921T031242Z` |
| T3 断言 | ⚠️ 生成 1,236 条；**141 条待人工核对** | `data/assertions/`、`docs/assertions-method.md` |
| T4 runner | ✅ | `tools/runner.py` |
| T5 判定器 | ✅ | `tools/check.py` |
| T6 指标汇总 | ⚠️ 分层已出；**critical error rate 缺** | `runs/*/results_summary.json` |
| T7 对照基线 | ⛔ **Azure DI 待公司电脑跑** | `docs/azure-di-baseline.md`、脚手架已就绪 |
| T8 专项 | ⚠️ 一致性 ✅、泄漏对照 ✅、扰动 ✅；**置信度校准做不了**（端点不给 logprobs） | `runs/consistency/` |
| T9 成文 | ⛔ 等 T7 | `docs/report-outline.md` 逐节对照 |
| 第二层 olmOCR-Bench | ✅ 120 页 / 604 断言 | `docs/olmocr-bench-results.md` |
| 第一层 厂商数据集复现 | ⛔ 厂商未提供数据集 | — |

**缺口**：贸易融资单证未覆盖（找不到合规公开源）；第 5 类评级报告建议不补。

下面是原始任务说明，保留供复现。

---

## T0 · 端点探针 ✅ 已完成 2026-09-18

**结果见 `docs/t0-findings.md`**，五个验收问题都有答案，原始响应在 `probe_out/`。
样本页用的是 olmOCR-Bench 的 `long_tiny_text/11_pg146_pg1.pdf`，不是财报页——
金融文档族的数字要等第三层自建集。下面保留原始说明供复现。

`tools/probe.py` 已可运行。找一份年报 PDF，挑一页密集的合并报表页当样本。

```bash
pip install -r requirements.txt
set -a && source .env && set +a
python tools/probe.py models
python tools/probe.py ping
python tools/probe.py page       报表.pdf 7
python tools/probe.py budget     报表.pdf 7 --max-tokens 2000
python tools/probe.py repeat     报表.pdf 7 --n 3
python tools/probe.py concurrency 报表.pdf --n 20
```

**验收**：`probe_out/` 下 01–08 齐全，并能回答这五个问题：

| 问题 | 影响 |
|---|---|
| 服务端回显的 `model` 是什么 | 可能直接解决 Pro/Flash，省一封邮件 |
| `logprobs: true` 被接受吗 | 决定置信度校准走哪条路（sdk-findings.md §3） |
| 截断时 `finish_reason` 是 `length` 吗 | 确认静默失败的捕捉器可用 |
| 三次调用的 sha256 一致吗 | 决定报告要不要对可审计性打问号 |
| 并发 20 是 429 还是静默排队 | 排队则所有延迟数字必须附带并发条件 |

顺带记录 `usage.prompt_tokens`——一页 A4@300DPI 的图像 token 数，
乘上文档量就是谈计费口径的底牌。

---

## T1 · 语料下载

`tools/fetch_corpus.py`（待写）。八个文档族见 research-plan.md §3.3。

- **1–5 类优先取 2026-06-08 之后披露**的文档（模型发布日，泄漏对照的切分点）
- 另设一组 2025 年的老文档作泄漏对照，两组数量相当
- 每份文档记录 `source_url` 与 `disclosed_at`，报告附录要列
- 目标 200–300 页

**验收**：`data/corpus/` 下有清单 `manifest.csv`，字段含 doc_id、family、
source_url、disclosed_at、pages、是否电子版。

## T2 · 扰动组生成

`tools/perturb.py`（待写）。由 1–7 类派生：重新打印扫描、降分辨率 150/100 DPI、
JPEG 高压缩、±2° 旋转、高斯噪声。断言文件直接复用原文档的。

注意 sdk-findings.md §6 的口径陷阱。

## T3 · 断言标注

schema 见 `docs/assertions.md`。约 200 条，2–3 人日。

`page_integrity` 类由脚本从 PDF 文本层批量生成，不手写。

---

## T4 · 评测 runner

**T0 未完成不要动这一项。**

`tools/runner.py`。要求：

- 裸 HTTP，不用厂商 SDK（理由见 CLAUDE.md 工程约定 1）
- 原始响应全量落盘 `runs/<run_id>/raw/<doc>_p<page>.json`，
  含状态码、响应头、`usage`、`finish_reason`、UTC 时间戳、回显的 `model`
- 并发 ≤ 16，可配置；失败重试要记录重试次数，不能静默吞掉
- 断点续跑：已有 raw 文件的页跳过
- `run_id` 里带模型版本与时间戳

## T5 · 断言判定器

`tools/check.py`。读 `data/assertions/*.yaml` 与 `runs/<run_id>/raw/`，
逐条判 pass/fail，输出 `runs/<run_id>/results.csv`。

`eval_on: json` 的断言必须在 layout JSON 上判（sdk-findings.md §5）。

## T6 · 指标汇总

`tools/metrics.py`。**按文档族、按字段类型分层出数，不合成加权总分。**

每个分层标 n 与置信区间。200 样本上 87% vs 89% 不显著，不得称「更好」。
样本量不足的分层明确写「样本不足，不下结论」。

正文指标：字段级准确率、critical error rate、跨页表格失败模式分布、
幻觉率、格式保留率。学术指标（编辑距离/TEDS/CDM）只进附录。

---

## T7 · 对照基线

| 基线 | 优先级 | 注意 |
|---|---|---|
| Azure DI (Layout) | 必保 | 输出自有 JSON，**转换规则必须在附录公开**，否则等于栽赃对手 |
| PDFParser | 必保 | 同厂商内部对照 |
| Gemini-3-Pro / GPT-5.4 | 保留 | 直接要 markdown，无需转换 |

Azure DI 跑第二、三层；PDFParser 与闭源模型跑第三层。

## T8 · 专项

- 置信度校准曲线（路径取决于 T0 的 logprobs 结果）
- 重复调用一致性，3× 全集
- 扰动组 vs 原始组衰减对比
- **6 月前 vs 6 月后泄漏对照**——全报告最硬的一张牌
- 延迟 P50/P95 按页数分档

## T9 · 成文

结构见 research-plan.md §7。正文 10 页内，结论先行。

---

## 砍项优先级

时间不够时依次砍：olmOCR-Bench 子集 → Extract 模式 → Gemini/GPT 基线 →
第 5、6 类文档族。

**不可砍**：自建集主体、critical error rate、置信度校准、泄漏对照、Azure DI 基线。
