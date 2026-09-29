# ParseBench 500 份分层子集：Infinity-Parser2 与 Azure DI

> 由 `tools/parsebench_report.py` 于 2026-09-29 17:25 UTC 从落盘结果生成，数字一律来自下列文件，未手工改动。口径见 `docs/working/parsebench-method.md`。

**这一层是中立公开基准（准入门槛），不是结论依据。** 厂商在 ParseBench 上自报过分数，泄漏风险无法排除；决定性证据仍在自建金融场景集。

## 1. 运行信息

| 项 | Infinity-Parser2 | Azure DI |
|---|---|---|
| run_id | `parsebench_inf_20260929T134509Z` | `—` |
| 开始时间 (UTC) | 2026-09-29T13:45:09.146+00:00 | — |
| 调用口径 | 裸 HTTP，doc2json + deep parsing（= 官方 `infinity_parser2_flash`） | prebuilt-layout，markdown（= 官方 `azure_di_layout`），经公司网关 |
| 服务端回显模型 | inf-mllm | — |
| 并发 | 8 | — |
| 文件数（落盘 / 成功） | 500 / 500 | — / — |
| 空输出（按 0 分计） | 4 | — |
| 判分器 | run-llama/ParseBench `3295d7f`，官方 normalize + 官方指标 | 同左 |

数据集 `llamaindex/ParseBench` revision `2805a1d940f9`，seed `20260929`，500 份文件；规则数 {'chart': 908, 'table': 130, 'text_content': 39825, 'text_formatting': 1554, 'layout': 3514}。

## 2. 按维度（官方主指标，满分 100）

| 维度 | n | Infinity | 95% CI |
|---|---|---|---|
| Tables | 130 | 74.8 | [70.0, 79.5] |
| Charts | 100 | 58.3 | [51.2, 65.2] |
| Content Faithfulness | 150 | 86.7 | [84.0, 89.2] |
| Semantic Formatting | 133 | 46.5 | [40.5, 52.3] |
| Visual Grounding | 120 | 75.4 | [71.2, 79.5] |

Azure 侧尚未运行，本节只有单边结果，按约定不解读绝对分数。

## 3. 按分层（主口径）

分层键见 `data/parsebench/manifest.csv` 的 `stratum` 列。配对数不足的分层只列数字，结论写「样本不足」。

**Tables**（仅 Infinity）

| 分层 | n | Infinity | 95% CI |
|---|---|---|---|
| easy | 83 | 80.8 | [75.4, 85.6] |
| hard | 47 | 64.2 | [55.5, 72.5] |

**Charts**（仅 Infinity）

| 分层 | n | Infinity | 95% CI |
|---|---|---|---|
| 3d | 16 | 21.9 | [6.2, 39.4] |
| exact | 33 | 72.0 | [60.8, 82.7] |
| need_estimate | 51 | 60.8 | [51.5, 69.4] |

**Content Faithfulness**（仅 Infinity）

| 分层 | n | Infinity | 95% CI |
|---|---|---|---|
| dense | 8 | 88.5 | [83.6, 93.3] |
| handwritting | 8 | 64.3 | [42.2, 80.5] |
| misc | 12 | 81.6 | [72.3, 90.3] |
| multicolumns | 26 | 93.2 | [90.1, 95.8] |
| multilang | 15 | 72.9 | [59.6, 85.5] |
| ocr | 31 | 86.5 | [82.1, 90.4] |
| simple | 42 | 92.7 | [89.5, 95.5] |
| sparse | 8 | 88.9 | [81.7, 95.6] |

**Semantic Formatting**（仅 Infinity）

| 分层 | n | Infinity | 95% CI |
|---|---|---|---|
| dense | 5 | 27.1 | [13.1, 38.6] |
| handwritting | 5 | 48.1 | [18.1, 77.8] |
| misc | 9 | 57.2 | [37.9, 75.9] |
| multicolumns | 26 | 52.2 | [39.0, 65.1] |
| multilang | 15 | 45.6 | [28.9, 62.3] |
| ocr | 27 | 43.5 | [28.9, 57.9] |
| simple | 41 | 45.0 | [34.8, 56.5] |
| sparse | 5 | 47.0 | [10.0, 84.0] |

**Visual Grounding**（仅 Infinity）

| 分层 | n | Infinity | 95% CI |
|---|---|---|---|
| easy/image | 10 | 26.2 | [8.2, 47.9] |
| easy/pdf | 53 | 84.1 | [79.9, 87.9] |
| hard/image | 8 | 64.3 | [49.0, 79.1] |
| hard/pdf | 49 | 77.9 | [73.3, 82.1] |

## 4. 按领域猜测（启发式，只看覆盖面）

`domain_guess` 由文件名关键词推断，数据集本身没有领域字段。**不作领域结论。**`text_suite` 是文本维度的人工构造集，`unknown` 是文件名为哈希、看不出领域的文件。

覆盖：{'financial_filing': 102, 'business_industry': 35, 'healthcare': 5, 'insurance': 26, 'unknown': 128, 'energy_climate': 9, 'synthetic_test': 21, 'government_intl': 24, 'text_suite': 150}

| 维度 | 领域猜测 | n | Infinity | 95% CI |
|---|---|---|---|---|
| Tables | business_industry | 2 | 96.0 | [92.0, 100.0] |
| Tables | energy_climate | 1 | 100.0 | — |
| Tables | financial_filing | 42 | 78.3 | [71.1, 85.4] |
| Tables | government_intl | 4 | 81.1 | [48.1, 99.4] |
| Tables | healthcare | 3 | 100.0 | [100.0, 100.0] |
| Tables | insurance | 20 | 82.1 | [72.3, 90.8] |
| Tables | synthetic_test | 17 | 52.7 | [35.6, 69.1] |
| Tables | unknown | 41 | 72.9 | [64.8, 80.5] |
| Charts | business_industry | 18 | 74.6 | [62.3, 85.8] |
| Charts | energy_climate | 8 | 58.8 | [35.0, 81.2] |
| Charts | financial_filing | 27 | 50.2 | [34.6, 65.6] |
| Charts | government_intl | 19 | 56.8 | [39.6, 73.1] |
| Charts | insurance | 5 | 38.0 | [14.0, 62.0] |
| Charts | unknown | 23 | 60.3 | [46.6, 74.0] |
| Content Faithfulness | text_suite | 150 | 86.7 | [84.2, 89.1] |
| Semantic Formatting | text_suite | 133 | 46.5 | [40.9, 52.7] |
| Visual Grounding | business_industry | 15 | 81.4 | [74.1, 88.1] |
| Visual Grounding | financial_filing | 33 | 76.5 | [70.2, 82.4] |
| Visual Grounding | government_intl | 1 | 88.2 | — |
| Visual Grounding | healthcare | 2 | 83.9 | [67.7, 100.0] |
| Visual Grounding | insurance | 1 | 87.5 | — |
| Visual Grounding | synthetic_test | 4 | 89.4 | [84.0, 96.2] |
| Visual Grounding | unknown | 64 | 71.9 | [64.8, 78.5] |

## 5. 参照数字（并列，不加评论）

下表前两行来自本次 500 份子集；其余来自厂商自报或官方全量 leaderboard（2,078 页）。样本与构成不同，**不能直接比大小**。

| 来源 | 样本 | Tables | Charts | Content Faithfulness | Semantic Formatting | Visual Grounding | Overall |
|---|---|---|---|---|---|---|---|
| 本次 · Infinity-Parser2 (Flash 2.1，厂商答复) | 500 份子集，全部文件 | 74.8 | 58.3 | 86.7 | 46.5 | 75.4 | 不合成 |
| 官方 leaderboard · Azure Document Intelligence (Layout) | 全量 | 86.00 | 1.56 | 84.93 | 51.93 | 73.78 | 59.64 |
| 官方 leaderboard · Infinity-Parser2-Pro | 全量 | 86.4 | 61.3 | 89.7 | 59.1 | 74.9 | 74.28 |
| 官方 leaderboard · Infinity-Parser2-Flash | 全量 | 82.88 | 55.56 | 89.52 | 57.7 | 80.61 | 73.25 |
| FinIE 站点 · Infinity-Parser2-Flash | 未说明 | — | — | — | — | — | 72.2 |
| FinIE 站点 / 技术报告 · Infinity-Parser2-Pro | 未说明 | — | — | — | — | — | 74.3 |

## 6. 调用层观察

| 项 | Infinity-Parser2 | Azure DI |
|---|---|---|
| 调用失败文件 | 0 | 0 |
| 主调用 finish_reason=length（截断内容仍交判分，与厂商口径一致） | 7 | 不适用 |
| deep parsing 退回 shallow 的文件 | 6 | 不适用 |
| 调用次数（按类型） | {'doc2json': 500, 'deep_figure': 825} | 每份 1 次 |
| token（输入 / 输出） | 4988310 / 1463228 | 不适用（按页计费，— 页） |
| 单次调用耗时中位数 / P95（秒） | 19.603 / 291.553（并发 8） | 见 run 目录 |

## 7. 口径声明

- 500 份分层子集，非全量 2,078 页，不能直接与厂商 72.2 / 73.25 或 leaderboard 比大小
- 按维度、分层出数，不合成加权总分
- 调用失败 / 空输出的文件按空 markdown 计分（官方判分器默认会把缺失文件排除出分母）
- domain_guess 是文件名启发式标签，只看覆盖面，不作领域结论
- Infinity 用 doc2json + deep parsing（厂商 ParseBench 自报分的配置），**不是产品默认的 doc2md**
- Infinity 的 PDF 用 PyMuPDF 300 DPI 渲染（与 INF SDK 一致），官方 provider 用 pdf2image；像素尺寸可能差 1px
- Azure 收到原始文件（PDF 保留文本层），Infinity 收到渲染图；若 GT 取自文本层，这一点可能对 Azure 有利
- Visual Grounding 依赖 bbox：Infinity 的 bbox 是模型生成的坐标 token，Azure 是几何检测

## 8. 复现

```
python tools/fetch_parsebench.py                     # 同 seed、同 revision 必得同一批 500 份
python tools/parsebench_runner.py --concurrency 8    # INF
tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py   # Azure（公司电脑）
tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run> [--pipeline azure_di_layout]
python tools/parsebench_compare.py <inf>/parsebench_per_file.csv <azure>/parsebench_per_file.csv
python tools/parsebench_report.py runs/<inf_run> runs/<azure_run>
```
