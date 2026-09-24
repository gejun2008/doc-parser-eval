# 厂商信息与未知项

## 厂商提供的（Infinity Parser2 User Guide，2026-09）

| 项 | 值 |
|---|---|
| 端点 | `https://aommehcmc55oc5edhdjea95cdej9ocoa.openapi-inspire.inf.tech/v1/chat/completions` |
| 认证 | API key，Bearer；配置为 `INFINITY_PARSER2_API_KEY` |
| 后端 | 必须指定 `--backend vllm-server`（CLI 默认是 `vllm-engine`，会走本地推理） |
| 模型名 | `inf-mllm`（别名） |
| 并发上限 | 16，超出触发重试 |
| 凭证性质 | **临时**，厂商称生产凭证就绪后通知替换 |
| 输入 | PDF / 图片路径、目录、路径列表 |
| 页选择 | `pages="1-3,5"` 或 `[1,3,5]`，物理页从 1 开始，图片输入忽略 |
| 输出 | `<output_dir>/<basename>/result.md` 与 `result.json` |
| 输出格式 | `md`（默认）/ `json` / `md,json`；**`json` 需 `task_type="doc2json"`** |
| 安装 | `pip install infinity_parser2` |

文档中提到「Follow the supplied Skill」，但该文件未随附，已向厂商索取。

**端点更正（2026-09-18）**：厂商 User Guide 里的服务 ID 第 28 位写作 `g`，实际为 `9`
（`...cdejgocoa` → `...cdej9ocoa`）。用错误 ID 会得到
`403 invalid inference serving id: record not found`，与 key 无关。
上表已更正为可用的地址。实测过程见 `docs/working/t0-findings.md`。

## 安全状态

当前 key 已在厂商文档、聊天记录、本地磁盘中明文出现，**按已泄漏处理**。
已请厂商轮换。新 key 只进环境变量或密钥管理器，不进任何文件。

## 未知项（阻塞评测）

| # | 未知 | 阻塞什么 | 取证路径 |
|---|---|---|---|
| 1 | **Pro / Flash / Fin 三选一**、版本号、评测期间是否变更 | 报告无法标注版本，结论不可复现 | **自测已做，未解决**：`/v1/models` 返回 404，端点只注册 `inf-mllm` 一个别名，不含档位与版本号（t0-findings.md §2、§3）。**2026-09-21 新增：擂台页出现第三个变体 Infinity-Parser2-Fin（2026-05-11），93.56% 归属于它**，见 vendor-benchmark-critique.md §3。Flash 指纹比对只能证伪 Flash，证不了 Fin。仍需厂商答复 |
| 2 | 厂商测试数据集与结果 | research-plan.md §3.1 第一层复现整层做不了 | 只能等厂商 |
| 3 | 计费口径（按页/token/调用）与定价区间 | §4.3 成本对比、ROI 重算 | 只能等厂商；`usage.prompt_tokens` 可推 token 量级 |
| 4 | PDFParser 与 Infinity-Parser2 是否同模型 | 决定对照基线里放哪个产品 | 只能等厂商 |
| 5 | 93.56% 的数据集、样本量、GT 来源、字符准确率算法 | §2 厂商声明核验 | 已问厂商；给不出本身就是发现。**追加：该数字跑了几次、取的哪一次、有无置信区间**（端点输出非确定性，t0-findings.md §9） |
| 6 | ~~是否支持 confidence 或 logprobs~~ | §4.2 置信度校准 | **已闭环：否**。`logprobs: true` 返回 200 但响应里 `logprobs` 为 `null`，静默忽略（t0-findings.md §7）。校准只能走代理指标 |
| 7 | ~~限流真实行为（429 还是静默排队）~~ | 所有延迟数字的可比性 | **已闭环：静默排队**，无 429 无 `retry-after`；且吞吐 1.6–1.8 页/分，不随并发 1→8 上升（t0-findings.md §10）。所有延迟数字必须附并发条件 |

| 8 | 临时端点有效期、服务 ID 变更是否提前通知 | 端点失效会直接打断评测排期 | 已列入待问；三档鉴权报错可用于快速定位（t0-findings.md §1） |
| 9 | **Infinity-Parser2-Fin 的权重是否开源** | 若否，research-plan.md §1.4「权重 Apache-2.0 公开」这条谈判杠杆对真正被宣传的那个模型不成立 | 擂台页只列 Fin，HF 上只有 Pro/Flash。需厂商答复 |
| 10 | **Financial Benchmark 的文档族构成**：只有 HK/MY/US 上市公司财报？有无 UK/EU、KYC、贸易融资 | 决定这张表与 HSBC 场景的相关性，目前看约只对应 §3.3 八族中的一族 | 已列入待问；见 vendor-benchmark-critique.md §2.7 |

第 6、7 项自测即可，不必等厂商，但都需要样本 PDF，见 `docs/working/t0-findings.md` 的进度表。

## 暂不询问的（等技术评测出结论后单独走采购流程）

数据驻留与出境、是否用客户数据训练、留存期、等保/ISO 27001/SOC 2、
SLA 与审计日志、模型版本锁定能力、供应商存续风险。

混进技术问题清单会让对方觉得已进入尽调阶段而变谨慎。
但 research-plan.md §8 要求这些在报告里列出为「采购前必答」。
