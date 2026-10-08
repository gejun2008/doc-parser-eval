# ParseBench 500 份：Infinity-Parser2 与 Azure DI 对比总结

| 项 | 值 |
|---|---|
| 日期 | 2026-09-30 |
| 层级 | 第二层 · 中立公开基准（准入门槛，**不是结论依据**） |
| 被测 | Infinity-Parser2（端点回显 `inf-mllm`，厂商答复 Flash 2.1）；Azure DI `prebuilt-layout`（公司网关） |
| 数据 | `llamaindex/ParseBench` 分层子集 500 份，来自 441 份来源文档，两边同一批文件 |
| 判分 | 官方判分器 run-llama/ParseBench `3295d7f`，官方 normalize + 官方各维度主指标，逐文件配对比较 |
| 口径 | `docs/working/parsebench-method.md` |

> **数字来源说明**：Azure 侧与双边比较的数字转录自公司电脑生成的 `parsebench-results.md`
> （`tools/parsebench_report.py` 于 2026-09-30 01:24 UTC 生成）的贴文。贴文是截图识别，个别单元格有乱码，
> 本文只采用能完整辨认的数字。**原始 `parsebench-azure-results.zip` 带回后需逐项复核**，见 §7。
> INF 单边与「去掉 deep parsing」的数字直接来自本机落盘，已与官方汇总逐位核对。

---

## 1. 结论摘要

1. **表格：Azure 更高。**Tables −6.5 分（p=0.003）；难表格 −10.7（p=0.014）；文件名可辨认的金融披露页 −11.8（n=42）。
   这是五个维度里与金融公司场景最相关的一维，方向与第三层自建金融场景集一致。
2. **正文文字保真：Infinity 更高。**Content Faithfulness +4.0（p<0.001），扫描件 OCR 分层 +5.7（p=0.003）。
3. **图表数据：差距全部来自评测框架的额外步骤。**Infinity 58.3 对 Azure 2.1，但去掉 deep parsing
   （把每张图裁出来再调一次模型转表格，客户按 SDK 默认参数拿不到）后 Infinity 为 **2.0**。
   两个产品的默认输出都不含图表数据。
4. **版面溯源（bbox）：PDF 输入 Infinity 更高，低分辨率图片输入 Infinity 失效。**Visual Grounding 整体 +4.7（p=0.007），
   由 PDF 分层驱动；低分辨率图片上 Infinity 常把整页输出成一个元素（17 份图片里 5 份得 0 分）。
5. **格式保留：未观察到显著差异。**Semantic Formatting +6.1，区间不含 0，但符号检验 p=0.19。

## 2. 主结果（主口径：只比两边都有输出的文件）

满分 100，官方各维度主指标，差 = Infinity − Azure。

| 维度 | n | Infinity | Azure | 差 | 差的 95% CI | I 高 / A 高 / 平 | 符号检验 p | 结论 |
|---|---|---|---|---|---|---|---|---|
| Tables | 128 | 76.0 | 82.5 | −6.5 | [−11.5, −1.7] | 40 / 72 / 16 | 0.0032 | Azure 更高 |
| Charts | 100 | 58.3 | 2.1 | +56.2 | [49.1, 63.4] | 83 / 0 / 17 | <0.0001 | Infinity 更高（见 §3） |
| Content Faithfulness | 149 | 87.3 | 83.3 | +4.0 | [2.6, 5.3] | 107 / 41 / 1 | <0.0001 | Infinity 更高 |
| Semantic Formatting | 133 | 46.5 | 40.4 | +6.1 | [1.5, 11.1] | 42 / 30 / 61 | 0.1945 | 未观察到显著差异 |
| Visual Grounding | 118 | 75.8 | 71.1 | +4.7 | [1.4, 8.1] | 61 / 34 / 23 | 0.0073 | Infinity 更高 |

- 两边调用失败均为 0。Infinity 有 4 份调用成功但输出为空（按 0 分计），主口径排除这 4 份。
  参照口径（全部文件、空输出按 0 分）下各维度方向与显著性不变，Tables 为 −7.8（[−13.0, −2.3]，p=0.0019）
- **不合成总分**（CLAUDE.md 约定 5）

## 3. deep parsing 消融：Charts 的差距从哪来

官方 `infinity_parser2_flash` pipeline 在模型输出之后多做一步：每个 `figure` 元素按 bbox 裁图，
用「please convert the image to a markdown table」再调一次模型，结果回填。本次 500 份共触发 825 次这样的额外调用。
这一步写在评测框架的 provider 里，**不在 INF SDK 的默认流程里**。

用已落盘的主调用输出、跳过这一步重新判分（没有重新调用 API）：

| 维度 | Infinity（官方配置，含 deep parsing） | Infinity（去掉 deep parsing） | Azure |
|---|---|---|---|
| Tables | 74.8 | 74.8 | 82.6 |
| Charts | 58.3 | **2.0** | 2.1 |
| Content Faithfulness | 86.7 | 87.2 | 83.3 |
| Semantic Formatting | 46.5 | 46.5 | 40.4 |
| Visual Grounding | 75.4 | 75.4 | 71.1 |

（全部文件口径；Infinity 两列来自本机落盘，`runs/parsebench_inf_20260929T134509Z{,_nodeep}`，消融由 `tools/parsebench_nodeep.py` 生成。09-30 初稿 Tables 写成 74.4，是临时脚本对文件名含点号的 1 份文件匹配错误，已更正）

- Charts 维度的 +56 分几乎全部来自 deep parsing；其余四维基本不受影响
- 含义：图表数据抽取需要**额外的第二次调用**。若 POC 需要这项能力，要把它当作独立的工程集成与成本项，
  而不是产品默认能力
- 3D 图表即使有 deep parsing 也只有 21.9（n=16，样本不足）

## 4. 分维度发现

### Tables（Azure 更高，与金融场景最相关）

| 分层 | n | Infinity | Azure | 差 | 95% CI | p | 结论 |
|---|---|---|---|---|---|---|---|
| easy | 83 | 80.8 | 85.1 | −4.3 | [−10.6, 2.4] | 0.0912 | 未观察到显著差异 |
| hard | 45 | 67.1 | 77.8 | −10.7 | [−19.1, −2.4] | 0.0137 | Azure 更高 |
| 领域猜测 financial_filing | 42 | 78.3 | 90.1 | −11.8 | — | — | Azure 更高 |
| 领域猜测 insurance | 20 | 82.1 | 86.2 | −4.2 | — | — | 未观察到显著差异 |

难表格（合并单元格、多级表头）上差距扩大。领域是按文件名推断的启发式标签，只作参考。

### Content Faithfulness（Infinity 更高）

| 分层 | n | Infinity | Azure | 差 | p | 结论 |
|---|---|---|---|---|---|---|
| ocr | 31 | 86.5 | 80.8 | +5.7 | 0.0033 | Infinity 更高 |
| simple | 42 | 92.7 | 89.9 | +2.8 | 0.0436 | Infinity 更高 |
| multicolumns | 26 | 93.2 | 90.2 | +3.0 | 0.0755 | 未观察到显著差异 |
| multilang | 15 | 72.9 | 74.5 | −1.7 | 1.0000 | 样本不足，不下结论 |
| dense / handwriting / misc / sparse | 7–12 | — | — | +3.1 ～ +10.3 | — | 样本不足，不下结论 |

### Semantic Formatting（整体未观察到显著差异）

扫描件 OCR 分层 +18.1（n=27，p=0.0127，Infinity 更高）；simple、multicolumns 未观察到显著差异；其余分层样本不足。

### Visual Grounding（PDF 输入 Infinity 更高；图片输入另论）

| 分层 | n | Infinity | Azure | 差 | p | 结论 |
|---|---|---|---|---|---|---|
| easy/pdf | 52 | 83.8 | 77.3 | +6.5 | 0.0139 | Infinity 更高 |
| hard/pdf | 49 | 77.9 | 70.3 | +7.6 | 0.0436 | Infinity 更高 |
| easy/image | 9 | 29.1 | 49.8 | −20.6 | 0.0703 | 样本不足，不下结论 |
| hard/image | 8 | 64.3 | 60.2 | +4.1 | 0.4531 | 样本不足，不下结论 |

图片分层样本不足，但现象明确，已排查：bbox 坐标换算正确（均落在原图尺寸内），
低分辨率图片（如 408×370、800×557）上模型只输出**一个覆盖整页的元素**，版面结构全部丢失。
这是模型行为，不是评测管道问题。INF SDK 对小图不做放大（smart_resize 只设 2048 像素下限）。

注意：Infinity 的 bbox 是模型生成的坐标 token，Azure 是几何检测；得分相近不代表可靠性相同。

## 5. 成本与调用（工作假设，待厂商确认计量单位）

按 09-28 报价单 Flash 牌价（输入 ¥3 / 输出 ¥12 每百万 token，单位是工作假设，同 evaluation-report §4.3），USD/CNY 按 7.10：

| | 每份平均 token（输入 / 输出） | 每千份调用成本 |
|---|---|---|
| Infinity 主调用（doc2json） | 9,092 / 2,296 | ¥54.8（约 $7.7） |
| Infinity deep parsing 额外调用 | 885 / 631 | ¥10.2（约 $1.4） |
| Infinity 合计 | 9,977 / 2,926 | ¥65.0（约 $9.2） |
| Azure DI Layout 牌价 | — | $10 |

- doc2json 每页输出 token（2,296）明显高于 doc2md（第三层实测约 963），因为要输出坐标
- 单次调用耗时中位数 19.6 s，P95 291.6 s（并发 8，端点静默排队）；Azure 每份 1 次调用
- 主调用 7 份撞到 32,768 token 上限（`finish_reason=length`），截断内容按厂商口径仍交判分

## 6. 替代范围判断（本层证据，需与第三层合并）

按 CLAUDE.md 的写法，不写「推荐 / 不推荐」：

| 类别 | 本层证据 | 判断 |
|---|---|---|
| 表格密集的金融披露页 | Tables −6.5，难表格 −10.7，金融披露页 −11.8 | **不支持替代**：本层与第三层方向一致，Azure 更高 |
| 扫描件与普通正文的文字保真 | Content Faithfulness +4.0，OCR 分层 +5.7 | **可作为 POC 待验证项**：本层唯一有显著正向信号的质量维度；但第三层自建金融集未观察到 Infinity 的优势，需在金融扫描件上单独复核后才能纳入范围 |
| 图表数据抽取 | 默认输出两边都 ≈2 分；Infinity 需额外调用才到 58.3 | **两者默认都不提供**；若需要，按独立工程项评估 Infinity 的二次调用方案 |
| bbox 溯源（审计要求） | PDF 输入 Infinity +6.5 ～ +7.6；低分辨率图片 Infinity 整页塌缩 | **仅限 PDF 输入**；图片输入需先规定最低分辨率并单独测 |
| 格式保留（加粗、上下标、标题层级） | 未观察到显著差异 | 不作为替代理由 |

POC 退出条件建议补一条：**表格维度在金融披露页上相对 Azure 的差距不收窄，则表格类文档不进入替代范围。**

## 7. 局限与待办

- **泄漏风险**：厂商在 ParseBench 上自报过分数，无法排除训练集接触过这些文档，可能对 Infinity 有利
- **输入不对称**：Azure 收到原始 PDF（含文本层），Infinity 收到 300 DPI 渲染图；可能对 Azure 有利
- **评测配置不是产品默认**：Infinity 用 doc2json + deep parsing（厂商 ParseBench 分数的配置），不是产品默认的 doc2md
- **子集构成**：难表格有意超配（47/130），领域靠文件名推断（128 份看不出领域），不能与全量 leaderboard 比大小
- **待复核**：带回 `parsebench-azure-results.zip`，在本机重跑 `parsebench_compare.py` 与 `parsebench_report.py`，
  用生成文件替换本文 §2、§4 的转录数字；同时核对网关返回的 analyzeResult 是否含 paragraphs / tables / figures 的 boundingRegions

## 附：参照数字（并列，不加评论）

| 来源 | 样本 | Tables | Charts | Content Faithfulness | Semantic Formatting | Visual Grounding | Overall |
|---|---|---|---|---|---|---|---|
| 本次 · Infinity-Parser2 | 500 份子集 | 74.8 | 58.3 | 86.7 | 46.5 | 75.4 | 不合成 |
| 本次 · Infinity-Parser2（去掉 deep parsing） | 500 份子集 | 74.8 | 2.0 | 87.2 | 46.5 | 75.4 | 不合成 |
| 本次 · Azure DI (Layout) | 500 份子集 | 82.6 | 2.1 | 83.3 | 40.4 | 71.1 | 不合成 |
| 官方 leaderboard · Azure DI (Layout) | 全量 2,078 页 | 86.00 | 1.56 | 84.93 | 51.93 | 73.78 | 59.64 |
| 官方 leaderboard · Infinity-Parser2-Flash | 全量 | 82.88 | 55.56 | 89.52 | 57.7 | 80.61 | 73.25 |
| 官方 leaderboard · Infinity-Parser2-Pro | 全量 | 86.4 | 61.3 | 89.7 | 59.1 | 74.9 | 74.28 |
| FinIE 站点 · Infinity-Parser2-Flash | 未说明 | — | — | — | — | — | 72.2 |
| FinIE 站点 / 技术报告 · Infinity-Parser2-Pro | 未说明 | — | — | — | — | — | 74.3 |
