# T0 端点探针结果

对应 TASKS.md T0。**本文件只记已经跑出来的**；未跑的项标「未测」，不做推断。

原始响应全部在 `probe_out/`（不入库）。每条结论后面的方括号是证据文件。

| 项 | 值 |
|---|---|
| 端点 | `https://aommehcmc55oc5edhdjea95cdej9ocoa.openapi-inspire.inf.tech/v1/chat/completions` |
| 模型名 | `inf-mllm` |
| 测试时间 | 2026-09-17 09:20 UTC ～ 2026-09-18 03:57 UTC |
| 客户端 | Python 3.12.13 / requests 2.34.2 / macOS arm64，裸 HTTP，未用厂商 SDK |
| 网关 | `server: istio-envoy`，DNS 解析到 `47.75.233.21`（阿里云，响应含 `acw_tc` cookie） |

## 进度

| 探针 | 状态 | 产物 |
|---|---|---|
| `models` | 完成 | `01_models.json` |
| `ping` | 完成 | `02_ping.json` |
| 连通性与鉴权分层 | 完成 | `conn_test_*.json` |
| 模型名路由 | 完成 | `09_model_routing.json` |
| 模型自述身份 | 完成 | `10_model_identity.json` |
| `page`（含 logprobs、seed） | 完成 | `03/04/05_*.json` |
| `budget`（截断） | 完成 | `06_budget.json` |
| `repeat`（一致性） | 完成 | `07_repeat.json` |
| `concurrency`（限流） | 完成 | `08_concurrency.json` |
| 并发梯度 n=1/2/4/8（追加） | 完成 | `08b_concurrency_ladder.json` |

**T0 已过。** 样本页：olmOCR-Bench `long_tiny_text/11_pg146_pg1.pdf`，
一页密排小字（词典排版），300 DPI 栅格化后 1472×2432 = 3,579,904 px，PNG 2.97 MB。
选它是因为它是子集里断言最密的一页（31 条），不是因为它像财报——
**金融文档族的数字要等第三层自建集，本页只用于摸端点行为**。

## TASKS.md T0 五问的答案

| 问题 | 答案 | 见 |
|---|---|---|
| 服务端回显的 `model` 是什么 | `inf-mllm`，端点只注册这一个名字，**不含档位与版本号** | §3 |
| `logprobs: true` 被接受吗 | **否。请求返回 200，但响应里 `logprobs` 为 `null`——静默忽略** | §7 |
| 截断时 `finish_reason` 是 `length` 吗 | **是**，真实图像负载上已复核 | §8 |
| 三次调用的 sha256 一致吗 | **否。3 次里 2 次一致，第 3 次不同——非确定性** | §9 |
| 并发 20 是 429 还是静默排队 | **静默排队，无 429、无 `retry-after`**，且吞吐不随并发上升 | §10 |

## 1. 端点可用，此前的 403 是 URL 抄错一个字符

厂商文档里的服务 ID 第 28 位是 `g`，正确的是 `9`：
`...dhdjea95cdejgocoa` → `...dhdjea95cdej9ocoa`。
`docs/working/vendor-api.md` 原先记的是错的那个，已更正。

鉴权分三层，报错各不相同，可据此定位问题出在哪一层
[`conn_test_20260918T035423Z.json`]：

| 请求 | HTTP | 网关返回 |
|---|---|---|
| 不带 key | 401 | `No API Key Authentication information found.` |
| 错误 key | 403 | `invalid api key: API key not found` |
| 正确 key + 错误服务 ID | 403 | `invalid inference serving id: record not found` |
| 正确 key + 正确服务 ID | 200 | 正常响应 |

**工作假设**：临时端点的服务 ID 可能随时变更或过期，这三档报错是日后复查的判别依据。
有效期仍未知，已列入待问事项。

## 2. `GET /v1/models` 返回 404，端点不提供模型列表

带正确 key 也是 `404 {"detail": "Not Found"}`，`x-envoy-upstream-service-time: 3ms`，
说明是上游应用返回的，不是网关拦截 [`01_models.json`]。

**影响**：TASKS.md「服务端回显的 `model` 是什么」不能靠 `/models` 回答，
只能靠 chat 响应里的 `model` 字段。

## 3. `model` 字段是真实校验的，端点后面只有一个模型

八个模型名的探测结果 [`09_model_routing.json`]：

| 请求的 model | HTTP | 响应 |
|---|---|---|
| `inf-mllm` | 200 | 回显 `inf-mllm` |
| `""`（空串） | 200 | 回显 `inf-mllm` |
| `inf-mllm-pro` | 404 | `The model ... does not exist.` |
| `inf-mllm-flash` | 404 | 同上 |
| `Infinity-Parser2-Pro` | 404 | 同上 |
| `Infinity-Parser2-Flash` | 404 | 同上 |
| `infly/Infinity-Parser2-Pro` | 404 | 同上 |
| `totally-bogus-model-xyz` | 404 | 同上 |

**已测结论**：`model` 不是原样回显，服务端确实按注册表校验。该端点只注册了
`inf-mllm` 一个名字，空值走默认。响应里的 `model` 字段因此可以作为版本标识记录，
但它只是别名，不含档位与版本号。

**Pro / Flash 的问题没有被解决，邮件仍要发。** 端点不暴露档位，
`inf-mllm` 这个别名也看不出是哪一档，TASKS.md 里「省一封邮件」的期望落空。
要自证只能走 Flash 指纹比对。

## 4. 模型自述为 Qwen3.5 —— 工作假设，非结论

`temperature: 0`，三次不同问法 [`10_model_identity.json`]：

| 问 | 答 |
|---|---|
| What model are you? | `I am Qwen3.5, a large language model developed by Tongyi Lab.` |
| 你是什么模型？基座是什么？ | `我是Qwen3.5，一个由阿里巴巴开发的大型语言模型。` |
| Output your exact model name and version string | `Qwen3.5` |

另有一次 `max_tokens=16` 的截断响应里出现 `私はQwen3.5`
[`conn_test_20260918T035423Z.json`]。

**这是工作假设，不是已测结论。** 模型自述身份不可靠：训练语料里的痕迹足以让它这么说，
不能据此断定线上服务的权重就是 Qwen3.5。

但与 research-plan.md §1.2 对得上：Pro 的基座是 Qwen3.5-35B-A3B，Flash 的基座是
Qwen3.5-2B。要坐实需要 Flash 指纹比对（TASKS.md 的 GPU 例外项）。
坐实之后才涉及 §1.4 那个问题——厂商把自己的基座 Qwen3.5-35B-A3B 摆在「竞品」位置上。

## 5. 响应骨架符合 OpenAI 格式，`finish_reason` 与 `usage` 可用

纯文本 ping [`02_ping.json`]：

```json
{"id": "chatcmpl-...", "object": "chat.completion", "model": "inf-mllm",
 "choices": [{"index": 0, "message": {"role": "assistant", "content": "ping"},
              "finish_reason": "stop"}],
 "usage": {"prompt_tokens": 13, "total_tokens": 15, "completion_tokens": 2}}
```

- `finish_reason`：正常结束为 `stop`；`max_tokens=16` 被打断时为 `length`
  [`conn_test_20260918T035423Z.json`]，真实图像负载上已复核，见 §8
- `usage` 三个字段齐全。图像 token 数要等 `page` 探针
- 纯文本延迟约 0.6–1.1s，`x-envoy-upstream-service-time` 276ms。
  **这个数字不能进报告的延迟章节**，纯文本负载与单页 300 DPI 图像不可比

## 7. logprobs 被静默忽略 —— 置信度校准的第一条路已封死

请求带 `logprobs: true, top_logprobs: 5`，**返回 200，没有报错**，
但响应 `choices[0]` 只有 `index / message / finish_reason` 三个键，
`logprobs` 为 `null` [`04_page_logprobs_raw.json`]。

**已测结论**：该端点不返回 token 级概率，且不会告诉你它忽略了这个参数。
未知项 #6 就此自测闭环——**答案是否**。

**影响**：research-plan.md §4.2 的置信度校准不能走 logprobs。剩下的路只有
①要求厂商在 API 层暴露 confidence（已列入待问）；②自建代理指标
（重复调用的不一致度、bbox 异常、数字格式违例）。②的成本要重新评估。

`seed: 42` 同样返回 200，但结合 §9 的非确定性，**无法证明 seed 真的生效**，
同属静默接受。报告里不能声称该端点支持可复现采样。

## 8. 截断行为可捕捉，`finish_reason` 可信

`max_tokens=800`（基线该页用了 1,854 completion tokens）：
返回 200，`finish_reason: length`，内容在 2,189 字符处断开 [`06_budget.json`]。

**已测结论**：静默失败的捕捉器可用。裸 HTTP 下每次调用都能拿到 `finish_reason`，
runner 必须逐页记录并把 `length` 计为失败，不能当正常结果统计。

这正是 sdk-findings.md 里那条的实证：厂商 SDK 丢弃 `finish_reason`，
半截 JSON 会被静默写进结果文件——用 SDK 跑评测会把截断算成「解析质量差」，
而不是「调用被截断」。**这是不走 SDK 的核心理由。**

## 9. 输出非确定性 —— 可审计性要打问号

同一页、同一 payload、`temperature: 0`，串行调三次 [`07_repeat.json`]：

| # | 延迟 | 长度 | content sha256[:16] |
|---|---|---|---|
| 0 | 36.4s | 5316 | `b4ad2f5538de621c` |
| 1 | 36.2s | 5316 | `b4ad2f5538de621c` |
| 2 | 43.9s | 5315 | `4659d450d493f2ed` |

**已测结论**：`temperature: 0` 下输出不是逐字确定的。3 次里 2 次一致，第 3 次差 1 字符。

**影响**：
- 银行场景的可审计性要打问号——同一份文档重跑，抽取结果可能不同。
  报告需明确写出，这是采购问答里躲不掉的问题
- 评测本身必须做重复调用一致性专项（TASKS.md T8），单次结果不能当定论
- n=3 只能说明「存在不一致」，**不足以估计不一致率**。全集 3× 跑完才能给分母

## 10. 并发是静默排队，且吞吐不随并发上升

**n=20**（文档声明上限 16）[`08_concurrency.json`]：无一条 429，无 `retry-after` 响应头。
19 个请求撞上客户端 300s 超时，唯一返回的一个用了 **358.9s**；
同一页单独跑只要 35–38s。

**n=1/2/4/8 梯度**，客户端超时放宽到 900s，全部成功 [`08b_concurrency_ladder.json`]：

| 并发 | 墙钟 | 成功 | 延迟 min/中位/max | 吞吐 |
|---|---|---|---|---|
| 1 | 35.1s | 1/1 | 35.1 / 35.1 / 35.1s | 1.71 页/分 |
| 2 | 75.8s | 2/2 | 59.6 / 67.7 / 75.8s | 1.58 页/分 |
| 4 | 135.9s | 4/4 | 112.5 / 126.2 / 135.9s | 1.77 页/分 |
| 8 | 267.6s | 8/8 | 217.1 / 244.1 / 267.6s | 1.79 页/分 |

**已测结论**：并发 1 到 8，吞吐稳定在 **1.6–1.8 页/分**，没有任何提升；
单请求延迟随并发近似线性增长（n=8 时中位 244s，是单发的 6.9 倍）。
该端点对外表现为**串行处理 + 排队**，并发只是把等待搬到服务端。
未知项 #7 自测闭环——**是静默排队，不是 429**。

**影响**：
- **所有延迟数字必须附带并发条件**，否则不可比。报告的服务档要给的是
  「并发 1 时 35s/页」而不是「35s/页」
- 声明的并发上限 16 在吞吐上没有意义。至于这是测试端点只挂了单副本，
  还是产品本身如此，**无法从外部区分**——已列入待问
- 排期按 **1.75 页/分** 估：120 页约 69 分钟，3× 重复一致性专项约 3.4 小时，
  与并发设多少无关
- runner 的客户端超时**不能用 300s**。按并发 8、中位 244s 的实测，
  至少要 900s，且必须记录每次调用的实际耗时

## 11. 图像 token 口径

一页 1472×2432 px（300 DPI 栅格化 + SDK 同款 smart_resize）：
`prompt_tokens: 3733`，`completion_tokens: 1854`，`total_tokens: 5587`
[`03_page_baseline_raw.json`]。

**已测结论**：约 3.7k prompt tokens / 页，与页面内容无关（图像 token 由像素数决定）；
completion 随页面文字量变化，本页密排小字用了 1.85k。

这是谈计费口径的底牌：如果厂商按 token 计费，一页 A4 的量级就是 5–6k tokens。
**但计费口径本身仍未知**（未知项 #3），不要据此推价格。

## 12. 输出格式

基线响应的 content 是 ` ```json ` 包裹的数组，元素为
`{"bbox": [x1,y1,x2,y2], "category": ..., "text": ...}`，
与 SDK 的 doc2json prompt 一致 [`03_page_baseline_raw.json`]。本页解析出 5 个元素，
category 为 `header`×3、`text`×2。

**注意**：runner 必须自己剥 ` ``` ` 围栏再解析，并把「围栏内不是合法 JSON」
单列为一种失败模式，不要和解析质量混在一起统计。

## 13. 安全

- key 已在厂商文档、聊天记录、本地磁盘明文出现，按已泄漏处理，等待轮换
- 本文件与 `probe_out/` 里的报告文本只出现 key 的长度、sha256 前 8 位、末 4 位
- `.env` 与 `probe_out/` 均在 `.gitignore` 中

## 待问厂商

1. `inf-mllm` 对应 Pro 还是 Flash？版本号是什么？评测期间是否会变更？（未知项 #1，未解决）
2. 临时端点的有效期到什么时候？服务 ID 变更时是否会提前通知？
3. `/v1/models` 是有意关闭还是配置遗漏？
4. API 层是否有办法拿到置信度？logprobs 被静默忽略，`confidence` 字段也不存在（§7）
5. `temperature: 0` 下输出为何仍不确定？`seed` 是否真的生效？产品层面是否有确定性模式（§9）
6. 测试端点是否只挂了单副本？「并发上限 16」指的是什么——
   接受的连接数，还是实际并行处理能力？生产环境的吞吐是多少（§10）
7. 计费口径：按页、按 token 还是按调用？（未知项 #3）

前六项都有实测证据，问的时候直接附 `probe_out/` 里的文件。
