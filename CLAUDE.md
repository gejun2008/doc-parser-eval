# CLAUDE.md

Claude Code 每次进入本仓库先读这份文件。

## 这是什么项目

对 INF TECH（无限光年）的 **Infinity-Parser2** 文档解析 API 做独立技术评测，
判断能否在 HSBC 金融文档场景下替代现状方案（Azure Document Intelligence）。
产出一份内部技术评估报告，读者是技术主管与团队。

完整评测设计见 `docs/research-plan.md`，那是权威范围文档，本文件不复述它。

**报告的说服力不来自分数高低，来自评测过程的独立性可被验证。**
每个数字都要能追溯到：谁产生的、用什么数据、什么口径、什么时候跑的、模型版本号是什么。

## 硬约束

- **只测 API，不自建**。厂商给了临时端点。不做 GPU 部署（唯一例外见 TASKS.md 中的 Flash 指纹比对）
- **只能用公开金融文档**。巨潮资讯网、HKEX 披露易、评级机构官网、ICC 公开样本
- **周期 2–3 周**。砍项顺序写在 research-plan.md §6
- **本轮只做 Parse（OCR/解析）**，不做 FinIE 的 Chat 模式

## 已经确定的事实，不要重新推导

`docs/sdk-findings.md` 是对 PyPI 上 `infinity_parser2==0.4.0` 源码的逐文件核实结果，
带文件名和函数名。里面的结论（逐页独立调用、无置信度字段、客户端静默截断、
header/footer 默认丢弃、300 DPI 固定等）已经是证据，直接引用即可。
需要复核时再拉源码，不要凭记忆改写这些结论。

`docs/vendor-api.md` 是厂商给的信息 + 仍然未知的项 + 已发出的问题清单。

## 工程约定

1. **评测不走厂商 SDK，走裸 HTTP。** SDK 丢弃 `finish_reason`、`usage`、响应头、
   耗时，而这些正是报告里静默失败和服务档两节的原料。
   SDK 只作为「同口径参照实现」被阅读，不作为运行时依赖。
2. **每次调用的原始响应全量落盘**，含 HTTP 状态码、响应头、`usage`、
   `finish_reason`、UTC 时间戳、服务端回显的 `model` 字段。
   落盘路径 `runs/<run_id>/raw/<doc>_p<page>.json`。报告附录靠这些文件复现。
3. **API key 绝不进入源码、日志、提交历史。** 只从环境变量读。
   当前 key 是厂商临时凭证且已在文档与聊天中明文出现，按已泄漏处理，等待轮换。
4. **并发不超过 16**（厂商声明上限）。实际限流行为以 `probe.py concurrency` 的
   实测结果为准；如果是静默排队而非 429，所有延迟数字都必须附带并发条件。
5. **不合成加权总分。** 按文档族、按字段类型分层出数。
   分层样本量不足就写「样本不足，不下结论」，不要为了好看而合并分层。
6. **区分已测结论与工作假设。** 代码注释和报告里都要分开写。

## 目录

```
README.md                    从哪读起、环境、工具清单
docs/research-plan.md        评测设计（权威范围文档）
docs/interim-brief.md        中期简报（面向技术主管）
docs/report-outline.md       成文对照表：每节对应哪些数据文件
docs/sdk-findings.md         SDK 源码核实结果（证据）
docs/vendor-api.md           厂商信息 + 未知项
docs/vendor-questions.md     待厂商答复清单，标了优先级
docs/assertions.md           断言 schema 与七类定义
docs/assertions-method.md    实际实现的分层口径（auto / auto_textlayer / draft）
docs/t0-findings.md          T0 端点探针结果
docs/olmocr-bench-method.md  第二层口径
docs/olmocr-bench-results.md 第二层结果
docs/corpus-method.md        第三层语料与选页口径
docs/corpus-results-partial.md 第三层结果（部分指标）
docs/azure-di-baseline.md    在公司电脑跑基线的步骤
tools/                       见 README 的工具表
data/corpus/                 下载的公开文档（不入库）
data/assertions/             断言文件，每份文档一个 YAML（入库，这是 GT）
runs/<run_id>/               每次评测的原始响应与指标（不入库）
```

## 当前状态（2026-09-21）

**已完成**：T0 端点探针、第二层 olmOCR-Bench（120 页）、T1 语料与选页（53 份 → 210 页）、
T2 扰动组（42 页 × 5 种）、T3 断言生成（1,229 条）、T4/T5 runner 与判定器、
第三层首轮（210 页）、T8 重复一致性（210 页 × 3 次）。约 900 次调用，原始响应全量落盘。

**阻塞报告成文的三件事**（都不在代码侧）：

1. **Azure DI 基线未跑**——在公司电脑跑，约 $3.30。没有基线，绝对分数按约定不能报
2. **136 条人工核对未做**——`critical error rate` 主指标出不来
3. **厂商六条必答未回**——见 `docs/vendor-questions.md` 顶部

**已声明缺口**：贸易融资单证未覆盖（找不到合规公开源，五类来源排除过程见
`docs/corpus-method.md`）；第 5 类评级报告建议不补，结构与已测族重合。

端点关键行为（决定 runner 形状，已固化进代码）：
logprobs 静默忽略；限流是静默排队无 429；吞吐 1.6–5.6 页/分且不随并发上升、
随时段波动 2–3 倍；`temperature: 0` 下输出非确定性。

成文对照见 `docs/report-outline.md`，进度见 `TASKS.md`。

## 不要做的事

- 不要把评测跑成又一次单页 OCR benchmark。决定结论的是自建金融场景集的分层结果
- 不要用编辑距离/TEDS 当正文指标，它们只进附录，用于和厂商数字对齐口径
- 不要在没有基线的情况下报绝对分数
- 不要替厂商解释数据。93.56%、87.6%、74.3% 三个数字并列成表，不加评论
- 不要写「推荐/不推荐」，写「X 类可替代（证据…）、Y 类不可（证据…）、
  POC 范围建议 Z、退出标准…」
