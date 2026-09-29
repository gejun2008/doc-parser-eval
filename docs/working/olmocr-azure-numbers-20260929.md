# olmOCR-Bench：Azure DI 结果与配对对照（公司电脑，拍照转录）

| 项 | 值 |
|---|---|
| 来源 | 公司电脑 Copilot 会话输出，5 张拍照，2026-09-29 转录 |
| Azure run | `azure_di_layout_20260929T133601Z` |
| Infinity run | `inf-mllm_doc2md_20260918T065831Z`（见 `olmocr-bench-results.md`） |
| Azure 口径 | UAT 网关，异步 POST + 轮询，`prebuilt-layout`，api `2024-11-30`，`outputContentFormat=markdown`，原样读 `analyzeResult.content`，输入为 manifest 单页 PDF 原始字节（SHA-256 120/120 一致），无二次栅格化 |
| 调用覆盖 | 120/120 成功，0 失败；82 页本次 UAT 新跑，38 页复用历史成功结果（输入哈希已重验）；并发 2；墙钟 590.6 s；全部 `finish_reason=stop` |
| math | **Azure 未评分**（`--skip-math`，公司网络无法下载 Chromium）。双方都删掉 math：604 → 499 条，涉及 110 个 PDF（另 10 个 PDF 只有 math 测试） |

**校验**：下表所有数字已做交叉核对——子集 n 之和 = 类型 n 之和 = 499；
Azure 通过数 7+99+51+21+162 = 340（68.1%）；Infinity 通过数与 09-18 run 一致（334，66.9%）；
每行「INF 通过 − Azure 通过 = b − c」全部成立。标 † 的行照片被截断，由算术反推。

## Azure 单边（n=499，不含 math）

| 子集 | PDF | n | 通过 | 通过率 | Wilson 95% CI |
|---|---|---|---|---|---|
| headers_footers | 20 | 49 | 7 | 14.3% | [0.071, 0.267] |
| long_tiny_text | 15 | 120 | 99 | 82.5% | [0.747, 0.883] |
| multi_column | 20 | 68 | 51 | 75.0% | [0.636, 0.838] |
| old_scans | 15 | 75 | 21 | 28.0% | [0.191, 0.390] |
| table_tests | 40 | 187 | 162 | 86.6% | [0.810, 0.908] |

| 类型 | n | 通过 | 通过率 | Wilson 95% CI |
|---|---|---|---|---|
| absent | 60 | 14 | 23.3% | [0.144, 0.354] |
| order | 90 | 56 | 62.2% | [0.519, 0.715] |
| present | 162 | 108 | 66.7% | [0.591, 0.735] |
| table † | 187 | 162 | 86.6% | [0.810, 0.908] |

## 配对对照，口径 A：保留 Infinity 调用失败页（整页判 fail）

差值 = Infinity − Azure；b = 只 Inf 对，c = 只 Azure 对；McNemar 精确检验。

| 分层 | n | INF | Azure | 差值 | b/c | p | 判读 |
|---|---|---|---|---|---|---|---|
| 全部（不作总分） | 499 | 66.9% | 68.1% | −1.2% | 58/64 | 0.651 | 未观察到显著差异 |
| headers_footers | 49 | 30.6% | 14.3% | +16.3% | 9/1 | 0.0215 | INF 显著更高（口径不同，见下） |
| long_tiny_text | 120 | 87.5% | 82.5% | +5.0% | 11/5 | 0.210 | 未观察到显著差异 |
| multi_column | 68 | 82.3% | 75.0% | +7.3% | 8/3 | 0.227 | 未观察到显著差异 |
| old_scans | 75 | 50.7% | 28.0% | +22.7% | 19/2 | 0.00022 | INF 显著更高 |
| table_tests | 187 | 64.2% | 86.6% | −22.5% | 11/53 | 2.98e−7 | Azure 显著更高 |
| type=absent | 60 | 41.7% | 23.3% | +18.3% | 13/2 | 0.0074 | INF 显著更高 |
| type=order | 90 | 70.0% | 62.2% | +7.8% | 11/4 | 0.118 | 未观察到显著差异 |
| type=present | 162 | 77.8% | 66.7% | +11.1% | 23/5 | 0.0013 | INF 显著更高 |
| type=table | 187 | 64.2% | 86.6% | −22.5% | 11/53 | 2.98e−7 | Azure 显著更高 |

## 配对对照，口径 B：只比双方都成功的页

去掉 Infinity 复读退化的 1 页（`7d3aedd0…_pg8`），table 类少 2 条，n = 497。
其余分层与口径 A 完全相同，只列变化的行和交叉分层。

| 分层 | n | INF | Azure | 差值 | b/c | p | 判读 |
|---|---|---|---|---|---|---|---|
| 全部（不作总分） | 497 | 67.2% | 68.0% | −0.8% | 58/62 | 0.784 | 未观察到显著差异 |
| table_tests = type=table | 185 | 64.9% | 86.5% | −21.6% | 11/51 | 7.31e−7 | Azure 显著更高 |
| old_scans × absent | 11 | 90.9% | 63.6% | +27.3% | 4/1 | 0.375 | 样本不足 |
| old_scans × present | 42 | 50.0% | 21.4% | +28.6% | 12/0 | 0.00049 | INF 显著更高 |
| old_scans × order † | 22 | 31.8% | 22.7% | +9.1% | 3/1 | 0.625 | 样本不足 |

`headers_footers` 公司侧原注：两边对页眉页脚的输出口径不同，这一层不同口径。

产物（公司电脑）：`compare_all/`、`compare_both_ok/`（各含 `summary.json`、`paired.csv`），
`olmocr_results.csv`、`olmocr_summary.json`、`failure_breakdown.csv`，
筛选脚本 `prepare_both_ok.py`，过滤结果 `inf_both_ok.csv`、`azure_both_ok.csv`。
