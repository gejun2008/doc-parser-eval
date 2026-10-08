# ParseBench 评测口径

对应 research-plan.md §3.2 第二层（中立公开基准 · 准入门槛），与 `olmocr-bench-method.md` 同一定位。
**这一层不产生决定性结论**，决定性证据在第三层自建金融场景集。

报告附录靠本文件复现。每个可能影响分数的选择都写在这里，包括对我们不利的。

## 为什么加这一层

- 厂商在 ParseBench 上自报：技术报告 Pro **74.3%**；FinIE 站点「Arena」页 Flash **72.2**、Pro **74.3**（2026-09-29 截图）
- 官方 leaderboard（`run-llama/ParseBench` 仓库 `leaderboard.csv`）同时收录了
  Infinity-Parser2-Flash / Pro 和 **Azure Document Intelligence (Layout)**，是唯一一个三者都在的公开基准
- 数据来自保险、金融、政府等企业文档，比 olmOCR-Bench 更接近金融公司场景
- 五个维度里的 Visual Grounding（bbox 溯源）对应「可审计」要求，是前两层没测过的

泄漏风险与 olmOCR-Bench 相同：厂商报过分的 benchmark，无法排除进过训练集。

## 数据

| 项 | 值 |
|---|---|
| 数据集 | `llamaindex/ParseBench`，Apache-2.0 |
| revision | `2805a1d940f95a203e0ae4b88be9934f7765b3fc`（2026-04-19），钉死 |
| 全量 | 2,078 页 / 1,211 份来源文档 / 169,011 条规则，五个维度 |
| 本次子集 | **500 份文件**，来自 441 份不同来源文档 |
| 抽样脚本 | `tools/fetch_parsebench.py`，seed `20260929` |
| 清单 | `data/parsebench/manifest.csv`（每份文件的维度、分层、sha256、来源文档、领域猜测） |
| 子集规则数 | chart 908 / table 130 / text_content 39,825 / text_formatting 1,554 / layout 3,514 |

每个文件都是从来源文档抽出的单页（PDF 为主，layout 维度有 42 份 JPG/PNG）。
text_content 与 text_formatting 共用 `docs/text/` 下同一批文件，所以 150 份 text 文件两个维度都评。

### 配额与分层

| 维度 | 份数 | 单一来源上限 | 分层键（实际抽中 / 总体） |
|---|---|---|---|
| table | 130 | 6 页 | easy 83/427，**hard 47/76** |
| text（content + formatting） | 150 | 1 | simple 42，ocr 31，multicolumns 26，multilang 15，misc 12，dense 8，handwritting 8，sparse 8 |
| layout | 120 | 2 页 | easy/pdf 53，hard/pdf 49，easy/image 10，hard/image 8 |
| chart | 100 | 3 页 | need_estimate 51，exact 33，3d 16 |

- 维度内按总体比例分配，每层至少 6 份；**table/hard 下限上调到 40**（按比例只有 23 份，难表格是金融场景重点）
- **单一来源上限**：table 的 503 页里 178 页来自两份 SERFF 保险费率申报，不设上限的话
  「500 份不同文档」会退化成少数几份文档的连续页
- 维度配额按金融相关性给（table 最多），**不是**官方各维度的原始比例

### 领域猜测（启发式）

数据集没有领域字段。`domain_guess` 按文件名关键词推断，**只用于看覆盖面，不参与分层，不作领域结论**：

text_suite 150（文本维度的人工构造集）· unknown 128（文件名是哈希）· financial_filing 102 ·
business_industry 35 · insurance 26 · government_intl 24 · synthetic_test 21 · energy_climate 9 · healthcare 5

## 调用口径

### Infinity-Parser2：`tools/parsebench_runner.py`

逐字复刻官方 `infinity_parser2_flash` pipeline（ParseBench@`3295d7f`
`providers/parse/infinity_parser2.py` + `infinity_parser2==0.4.0` SDK），但走裸 HTTP、全量落盘。

| 项 | 值 | 出处 |
|---|---|---|
| 任务 | **doc2json**（不是产品默认的 doc2md） | pipelines/parse.py |
| 页面图像 | 300 DPI 渲染 → smart_resize(32, 2048, 16777216) → PNG | provider.load_images + SDK encode_image_to_base64 |
| 主调用 | PROMPT_DOC2JSON，max_tokens 32768，temperature 0，top_p 1 | SDK vllm_server.parse_batch |
| 后处理 | 抽 JSON → 截掉末尾不完整元素 → bbox 从 0–1000 还原为像素 | SDK postprocess_doc2json_result |
| deep parsing | 每个 figure 按 bbox 裁图，custom prompt「please convert the image to a markdown table」，max_tokens 2048，原文回填 | provider._apply_deep_parsing |
| normalize | 官方 provider.normalize()（未改一行） | parsebench_score.py |

**为什么用 doc2json + deep parsing**：厂商的 ParseBench 分数就是这套配置跑出来的；
Visual Grounding 需要 bbox，只有 doc2json 给。代价是它**不是产品默认口径**。
deep parsing 是评测框架里的额外工程（每张图再调一次模型把图表转成表格），会抬高 Charts 维度，
客户用 SDK 默认参数拿不到这一步。

与官方 provider 的不一致（都在 runner 文件头写明）：

1. PDF 渲染用 PyMuPDF，官方用 pdf2image（poppler）。本机无 poppler；INF 自家 SDK 用的也是 PyMuPDF。像素尺寸可能差 1px
2. data URL 的 MIME 写 `image/png`（字节本来就是 PNG）；SDK 对 PIL 输入标 `image/jpeg`。预期无影响——工作假设
3. 走裸 HTTP，记录 `finish_reason`、`usage`、响应头；`finish_reason=length` 的截断内容**仍交判分**
   （SDK 就是这么做的，厂商分数也包含这种情况），但在 `run_summary.json` 单列

### Azure DI：`tools/parsebench_azure_runner.py`（公司电脑）

对应官方 `azure_di_layout`：prebuilt-layout，`outputContentFormat=markdown`，整份文件原样发送。
网关返回的 REST `analyzeResult` 用 Azure SDK 的 `AnalyzeResult(dict)` 包起来，
再交给**官方 provider 的** `_convert_result_to_dict()` 和 `normalize()`。
我们不写任何版面→markdown 的转换规则（同 `azure-di-baseline.md` 的原则）。
这条转换链已用构造的 REST 样例核对过：表格（含 columnHeader）、段落角色、figure、bbox 都能完整走到 normalize。

## 判分

`tools/parsebench_score.py`，在独立环境 `tools/vendor/.venv-parsebench`（Python ≥3.12）里运行：

1. `*.raw.json` → 官方 provider.normalize() → `*.result.json`。**不实例化 provider**：
   INF provider 的 `__init__` 会连 vLLM 服务，Azure 的要读 SDK 凭证，而 normalize 不依赖任何实例字段（已核对）
2. **失败 / 空输出的文件写空 markdown 结果，按 0 分计**。官方判分器对缺失的结果文件
   不计入分母——不补的话失败页凭空消失、分数虚高（已用构造的失败样例验证）
3. `parse-bench run <pipeline> --skip_inference`：官方判分，一行不改
4. 按官方各维度主指标（`analysis/aggregation_report.py` 的 `_DEFAULT_METRICS`）逐文件汇总：

| 维度 | 官方主指标 |
|---|---|
| Tables | `grits_trm_composite`（GriTS 与 TableRecordMatch 的均值） |
| Charts | `rule_pass_rate`（ChartDataPointMatch） |
| Content Faithfulness | `content_faithfulness` |
| Semantic Formatting | `semantic_formatting` |
| Visual Grounding | `layout_element_rule_pass_rate` |

**不合成 Overall**。官方 leaderboard 的 Overall 是五维平均，本评测按 CLAUDE.md 约定 5 不合成。

## 两系统比较

`tools/parsebench_compare.py`：同一批文件逐文件配对，给均值差的配对 bootstrap 95% 区间、
逐文件胜负平、符号检验 p。两种口径：

- **主口径 `both_output`**：只比两边都有非空输出的文件，把「调用失败」与「解析质量」分开
- **参照口径 `all`**：失败按 0 分

配对数 < 20 的分层写「样本不足，不下结论」；区间跨 0 或 p ≥ 0.05 写「未观察到显著差异」。

## 不能与哪些数字直接比

- 厂商自报 72.2 / 74.3、官方 leaderboard（全量 2,078 页）：样本量与维度构成都不同，只并列不比较
- 本评测第三层（自建金融场景集）：指标体系不同（断言 vs 官方规则）

## 已知不对称

| # | 不对称 | 对谁有利 |
|---|---|---|
| 1 | Azure 收到原始文件（PDF 保留文本层），Infinity 收到 300 DPI 渲染图。若 GT 取自文本层 | 可能 **Azure 有利** |
| 2 | Infinity 用 deep parsing（每个 figure 多一次调用），客户默认拿不到 | **Infinity 有利**（Charts） |
| 3 | Visual Grounding：Infinity 的 bbox 是模型生成的坐标 token，Azure 是几何检测 | 中性，但含义不同 |
| 4 | 厂商报过这个 benchmark 的分数，存在训练集泄漏可能 | 可能 **Infinity 有利** |

## 运行记录（INF）

| 项 | 值 |
|---|---|
| run_id | `parsebench_inf_20260929T134509Z` |
| 时间 | 2026-09-29 13:45–17:21 UTC（首轮 179 分钟 + 续跑 37 分钟），并发 8 |
| 服务端回显模型 | `inf-mllm`（厂商答复为 Flash 2.1，端点本身不回显版本） |
| 结果 | 500/500 成功；调用 1,325 次（主调用 500 + figure 调用 825）；token 输入 4,988,310 / 输出 1,463,228 |
| 单次调用耗时 | 中位数 19.6 s，P95 291.6 s（并发 8，端点排队） |

- **中途网络中断**：16:24–16:38 UTC 本机到端点的 HTTPS 连接失败（SSLError / ProxyError / connection reset，
  全部是客户端网络层异常，没有一次是端点返回的业务错误），74 份 text 文件三次重试都落在这个窗口内。
  用 `--resume` 在同一 run 目录续跑，74 份全部成功。原始记录里保留了首轮失败的尝试
- **主调用截断（finish_reason=length）7 份**：table 4（其中 2 份 synthetic_invoice）、text 3。
  截断内容按 SDK 行为交判分（与厂商口径一致），见 `run_summary.json` 的 `length_truncated_files`
- **deep parsing 退回 shallow 6 份**：figure 调用或裁图异常，按官方 provider 行为整页用 shallow 结果
- **空输出 4 份**：调用成功，但官方 normalize 后 markdown 为空（截断后 JSON 无法解析等），按 0 分计：
  `layout/multi_col_40665`、`table/synthetic_invoice_page1`、`table/synthetic_invoice_page2`、`text/text_handwritting__address`
- **Semantic Formatting n=133 而非 138**：5 份文件只有斜体/下划线规则，官方 `semantic_formatting` 不覆盖这两类，
  官方自己的汇总也不计入它们（已核对我们的均值与官方 `avg_semantic_formatting` 逐位一致，五个维度都一致）

单边结果（仅供参照，按约定不解读绝对分数）：`docs/working/parsebench-results-inf.md`。
