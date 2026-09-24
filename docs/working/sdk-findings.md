# SDK 源码核实结果

对象：PyPI 上的 `infinity_parser2==0.4.0`（公开包，`pip download infinity_parser2`）。
核实日期：2026-09-17。以下每条都带出处，可复查。

## 1. 这个 API 是裸 VLM 推理端点，不是文档解析服务

`backends/vllm_server.py::VLLMServerBackend.parse_batch` 的完整逻辑：

1. PDF 经 `utils/pdf.py::convert_pdf_to_images` 用 PyMuPDF 栅格化，**DPI 固定 300**
2. 每页图像单独发一次 `POST /v1/chat/completions`
3. 取 `response.choices[0].message.content`，就是全部返回值

prompt 写死在客户端 `prompts.py` 里（`PROMPT_DOC2JSON` / `PROMPT_DOC2MD`），
服务端不参与 prompt 构造。**没有任何金融领域后处理。**

> 报告含义（research-plan.md §8 谈判杠杆）：权重 Apache-2.0 公开、SDK 在 PyPI 公开、
> prompt 在客户端。采购能买到的只剩托管与 SLA。这条现在是源码级证据。

## 2. 逐页独立调用，页与页之间零上下文

`utils/utils.py::convert_json_to_markdown` 把各页结果 `"\n\n".join()` 拼接，仅此而已。

**「跨页表格合并正确率」这个指标要重新定义**——模型架构上不可能合并。
应测的是续表页的失败模式：表头被幻觉补全 / 被当作新表 / 留空。

待验证假设（未测）：Azure DI Layout 是整文档级分析，表格有跨页 span 概念，
若成立则这是结构性差异，比任何准确率数字更能决定结论。

## 3. 全包零 confidence / score / logprob

`grep -ri "confidence\|score\|logprob" infinity_parser2/` 零命中。
响应里只有 markdown/JSON 字符串。

research-plan.md §4.2 的置信度校准曲线缺地基。三条路按顺序试：

1. 绕开 SDK，请求体加 `logprobs: true, top_logprobs: 5`。vLLM OpenAI server 原生支持，
   看网关是否屏蔽。拿到 token 级 logprob 后对金额/账号 token 聚合，校准曲线照做，
   且比厂商自带 confidence 更硬
2. 被屏蔽则用 self-consistency 代理：同页 `temperature=0.7` 跑 N 次，
   字段级投票一致率当置信度。成本 N 倍，只在关键字段子集上跑
3. 两条都不通，**结论本身就是结论**：该 API 不返回任何置信度信号，
   按字段分流人工复核在工程上无法实现，99.7% 自动化率宣称失去落地路径

第 1 条由 `tools/probe.py page` 回答。

## 4. 客户端内置静默截断

`utils/utils.py::postprocess_doc2json_result` 调用 `truncate_last_incomplete_element`：
输出撞到 `max_tokens`（默认 32768）导致 JSON 不完整时，**截到最后一个可解析元素，
不报错、不告警**。密集财报表格页容易触发。

runner 必须记录每次调用的 `finish_reason`，`length` 标红并计入静默失败率。
这是 research-plan.md §4.2 静默失败那节的现成素材。

## 5. Markdown 输出默认丢弃 header / footer / page_footnote

`convert_json_to_markdown(ans, keep_header_footer=False)` 是默认值。

**断言第 6 类（页眉页脚与脚注归属）在 md 上判会得到假阳性**——
脚注不是「混入正文」，是整个消失了。这类断言必须在 `result.json` 上判定。

## 6. 图像处理口径

`utils/image.py::encode_image_to_base64`：
- `qwen_vl_utils.smart_resize`，`factor=32`，`min_pixels=2048`，`max_pixels=16777216`
- A4@300DPI ≈ 2480×3508 = 8.7M 像素，低于上限，**不触发缩放**，整页全分辨率送出

> 扰动组含义：源文件降到 150/100 DPI 后仍会被按 300 DPI 重新栅格化，
> 实际考验的是「低质图像内容」而非「低分辨率输入」。
> 想测后者必须直接传图片并调 `min_pixels/max_pixels`。

**已知缺陷**：MIME 类型按原文件后缀推断，但图像总是重编码为 PNG 再发。
传 `.jpg` 会得到 `data:image/jpeg` 头配 PNG 字节。vLLM 通常能嗅探过去，
若遇到诡异的解码失败先查这里。

## 7. 采样参数

`parse_batch` 默认 `temperature=0.0`、`top_p=1.0`、`max_tokens=32768`，
均可经 `**kwargs` 覆盖。

temperature 0 不等于确定性——vLLM 连续批处理下，同一请求随批次组成不同仍可能漂移。
重复一致性测试照跑，但必须固定并发条件否则不可比。
`seed` 参数是否被网关接受由 `probe.py page` 回答。

## 8. 模型身份

`model_name` 默认值是 `infly/Infinity-Parser2-Pro`，但厂商要求传别名 `inf-mllm`，
**别名不透露真身是 Pro 还是 Flash**。

两条取证路径：
- `GET /v1/models` 与响应体中回显的 `model` 字段（vLLM 通常回显真实 served name）
- Flash 是 2B，本地 RTX 2000 8GB 勉强能跑（BF16 权重约 4.5GB，单页、控分辨率）。
  同批页面本地 Flash 与 API 逐字比对，一致即基本坐实是 Flash，不一致至少排除。
  Pro 是 70GB 本地无解，只能反证
