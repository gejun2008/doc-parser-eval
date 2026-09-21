# 架构判定：这是 VLM 推理端点，不是 OCR 流水线

写于 2026-09-21。材料来自已有证据，未新增 API 调用。
出处：`docs/sdk-findings.md`（SDK 源码核实）、`docs/t0-findings.md`（T0 端点实测）、
`probe_out/`（原始响应）、`infinity_parser2==0.4.0` 源码。

## 结论

**已测结论**：Infinity-Parser2 对外暴露的是一个 OpenAI 兼容的
`POST /v1/chat/completions`，单页图像 + 一段自然语言 prompt 进去，
一段自由文本出来。没有检测器、没有识别器、没有版面分析引擎，
整条链路只有一次自回归解码。传统 OCR 流水线的任何一个阶段在这里都不存在。

五条独立证据：

| # | 证据 | 出处 |
|---|---|---|
| 1 | 端点路径就是 `/v1/chat/completions`，响应体是 `object: "chat.completion"`，带 `usage`/`finish_reason` | `probe_out/02_ping.json` |
| 2 | 同一端点能用自然语言问它「你是什么模型」并得到闲聊回答 | `probe_out/10_model_identity.json` |
| 3 | SDK 依赖表里没有任何 OCR/检测组件——只有 `transformers`、`qwen-vl-utils`、`pymupdf`、`openai` | `setup.py::install_requires` |
| 4 | 解析行为由客户端写死的 prompt 决定，服务端不参与 prompt 构造 | `infinity_parser2/prompts.py` |
| 5 | `logprobs`、`seed`、`temperature`、`max_tokens` 这些纯采样参数都被端点接受 | `probe_out/04_page_logprobs_raw.json`、§7 of t0-findings |

**工作假设**（未坐实）：基座是 Qwen3.5 系，Pro 35B-A3B / Flash 2B。
依据是模型自述 + README 致谢 + `qwen-vl-utils` 依赖，三者互相印证但都不是权重级证据。
坐实需要 Flash 指纹比对。

## OCR 流水线和它的差别，逐项

| | Azure DI（流水线） | inf-mllm（单次解码） |
|---|---|---|
| 阶段 | 检测 → 识别 → 版面 → 后处理，各段独立可查 | 一次前向，中间态不可观测 |
| 置信度 | 每个 span 有 confidence | 无。`logprobs` 被静默忽略（t0 §7） |
| bbox 来源 | 几何检测输出 | **生成的 token**，见下 |
| 确定性 | 同输入同输出 | `temperature: 0` 下仍漂移（t0 §9，3 次 2 同） |
| 失败方式 | 识别不出 → 低分/空 | 幻觉、漏读、复读、截断，**且都带着正常的 `finish_reason: stop`** |
| 跨页 | 整文档分析，表格有 span 概念（待验证） | 逐页独立调用，页间零上下文（sdk-findings §2） |
| 长度 | 无输出预算概念 | 撞 `max_tokens` 就断（t0 §8，120 页里 1 页触发） |

## bbox 是模型编出来的，且坐标系没写在任何文档里

基线页 1472×2432 px，返回的 bbox 全部落在 0–1000 区间
（`[64, 64, 504, 936]` 等，`probe_out/03_page_baseline_raw.json`）。
SDK 里 `utils/utils.py::restore_abs_bbox_coordinates` 坐实了口径：

```python
"""Convert normalised [0-1000] bboxes back to pixel coordinates."""
int(x1 / 1000.0 * origin_w)
```

**已测结论**：bbox 是模型逐 token 生成的归一化坐标，由客户端按原图尺寸还原。
它不是任何检测器的几何输出，因此**可以在文字完全正确的情况下指向错误位置**，
而且没有任何信号提示这一点。两轴各自归一化到 1000，非方形页面按方形假设换算会被拉伸。

厂商文档与 SDK prompt 都没有说明坐标系是 0–1000。如果客户自己接 API（不走 SDK），
bbox 会被默认当成像素坐标用——**这是一个会静默出错的集成陷阱**，值得写进报告。

同一页还暴露了另一件事：密排三栏词典页，模型只返回 5 个元素，
两个 `text` 元素各自包了 2371 / 2601 字符——整栏被塞进一个框。
版面粒度由模型自行决定，不受控。

## 对评测的影响

已经体现在设计里的：

- 不走 SDK 走裸 HTTP（`finish_reason`、`usage`、响应头是判断静默失败的唯一入口）
- 重复调用一致性专项（T8）不是可选项，是架构决定的必测项
- 「跨页表格合并正确率」必须重新定义为续表页的失败模式（sdk-findings §2）

本次分析新增的、需要补进计划的：

1. **bbox 准确性要单列为一类断言**，不能和文本准确性混在一起。
   文本对、框错，在人工复核工作流里和文本错一样致命
2. **bbox 坐标系陷阱写进报告的集成风险节**，附 `restore_abs_bbox_coordinates` 源码
3. **复读/退化检测**要跑在全量输出上。已 vendored `tools/vendor/olmocr/repeatdetect.py`，
   但目前只在 olmOCR 打分路径上用，需要在自建集 runner 里也接上
4. **「文字完全正确的幻觉」这一类失败**——数字被换成另一个格式正确的数字——
   在金融场景是最高危的失败模式，OCR 流水线不会这样错。
   断言设计要专门覆盖：金额、日期、账号三类 token 的逐字比对，不用模糊匹配

## 谈判与选型含义

不重复 sdk-findings §1 的结论（权重 Apache-2.0、SDK 公开、prompt 在客户端）。
补一条：既然是裸 VLM 端点，**「解析准确率」是 prompt + 权重 + 采样参数的联合结果**。
厂商换 prompt、换采样参数、换权重版本都不会改变 API 契约，客户端无从察觉。
端点只回显别名 `inf-mllm`，不含档位与版本号（t0 §3）——
**合同里必须要求版本号可查、变更需通知**，否则今天测的和明天跑的不是同一个东西。

---

# 补充（2026-09-21）：OCR 流水线 ↔ 纯生成 VLM 是一条谱系，不是二分

上文把 inf-mllm 和「OCR 流水线」对立着写，那是为了说清它不是 OCR。
但擂台表里的对手（vendor-benchmark-critique.md）并不都在同一端，
报告里用二分法会失真。真实的谱系是这样：

| 位置 | 代表 | 框从哪来 | 有无置信度 | 确定性 |
|---|---|---|---|---|
| 纯流水线 | Tesseract、PP-OCRv5、EasyOCR、docTR | 检测模型（DBNet/CRAFT） | 有，逐词/逐行 | 有 |
| 商业文档服务 | **Azure DI**、Textract、Google DocAI、ABBYY | 检测模型 | 有，逐 span | 有 |
| **混合** | **PaddleOCR-VL、MinerU2.5** | **检测模型**（PP-DocLayout / DocLayout-YOLO 等） | 检测段有 | 检测段有，识别段无 |
| 纯生成 | **Infinity-Parser2**、dots.ocr、Qwen-VL 直接提示 | **模型生成的 token** | **无** | **无** |

**这解释了一件事**：擂台表里 PaddleOCR-VL 和 MinerU2.5 虽然也叫 VLM，
但它们的 bbox 来自真实检测器，几何可验证、带分数、不会幻觉。
**Infinity-Parser2 处在谱系最右端，把检测器整个去掉了。**

## 这条谱系怎么读：它放弃了什么，换来了什么

**放弃**（三条全是银行最需要的）：逐字段置信度（t0 §7 已测：logprobs 被静默忽略）、
确定性（t0 §9 已测：temperature 0 下仍漂移）、几何可验证的 bbox（本文上半部分）。
外加输出长度预算这个流水线根本不存在的失败模式（t0 §8，120 页里 1 页触发）。

**换来**：表格结构。vendor-benchmark-critique.md §2.2 按厂商自己的数算出来，
他们唯一的显著优势就在 Table Acc（相对次优 1.24×），字符准确率只有 1.01×。

**报告写法**：不要写「VLM 比 OCR 好/差」。写
**「Infinity-Parser2 用置信度、确定性、几何 bbox 三样东西，换了表格结构上的 1.24×。
这笔交易在 HSBC 场景下是否划算」** ——这才是决策问题的正确形状。
Azure DI 在谱系另一端，三样都有。

## 没有任何一个被引用的 benchmark 测 bbox

| benchmark | 测什么 |
|---|---|
| olmOCR-Bench | `present` / `absent` / `order` / `table` / `math` 五类，**无 layout/bbox 类** |
| 厂商 Financial Benchmark | Page / Char / Table / Cell Acc，**无 bbox 指标** |
| ParseBench | 未公开细则 |

olmOCR-Bench 的类型构成有我们自己跑的数据为证：
`runs/inf-mllm_doc2md_20260918T065831Z/olmocr_results.csv` 的 `type` 列只有
table 187 / present 162 / math 105 / order 90 / absent 60。

**含义**：bbox 是下游人工复核、版面还原、定位取证、脱敏这些工作流的唯一依据，
而厂商拿来证明实力的两套 benchmark 一个都不测它。
纯生成模型在这一项上的表现处于**无人测量**状态——
这不是「测出来不好」，是「没人测」，两者在报告里要分清。

**动作**：vendor-benchmark-critique.md §4 的反证清单加一条 R8，
在自建集上做 bbox 专项：把模型返回的框按 0–1000 还原后画回原图，
人工抽检 IoU 与「文字对但框错」的比例。这是全报告里唯一会有的 bbox 数据。
