# Infinity-Parser2 评估简报

> 本文件是 `briefing-deck.html` 的 Markdown 版，内容与幻灯片一致，一页对应一节。
> 图例：🟢 可以 / 支持　🔴 不可以 / 不支持　🟡 证据不足或未对照　⚪ 未覆盖

---

## 1 / 4　文档类型适用性对比：Azure DI vs Infinity-Parser2

<sub>INFINITY-PARSER2 vs AZURE DOCUMENT INTELLIGENCE · 技术评估简报 · 2026-09-24</sub>

> **一句话：解析质量上 Azure 每项都持平或更好。** 港股披露文件、A 股公告的关键字段没看到差异，可以进 POC；
> 但 A 股年报、中报「页首是续表」的页，Infinity 会**静默丢掉整段表格**。它还**不提供置信度**、**只收 PDF 和图片**。
> 替代理由只能来自成本或私有化部署。

### 支持的文件格式

| | PDF | 图片 | Office（Word / Excel / PPT） | HTML |
|---|---|---|---|---|
| **Azure DI** | 🟢 | 🟢 JPG · PNG · BMP · TIFF · HEIF | 🟢 | 🟢 |
| **Infinity-Parser2** | 🟢 | 🟢 PNG · JPG · BMP · TIFF · WEBP | 🔴 | 🔴 |

Infinity 处理 Word / Excel / PPT 必须先转成 PDF 或图片，原生的文字和结构会丢失。

### 按文档类型（PDF）

| 文档类型 | 判断 | 依据（同一批页配对比较） |
|---|---|---|
| 港股年报 / 中报 / 招股书 | 🟢 **可替代候选 · 进 POC** | 金额、科目归属断言两边都没有失败；分族的正文完整性待第三轮 |
| A 股临时公告 | 🟢 **可替代候选 · 进 POC** | 金额断言两边都没有失败；第一轮 Infinity 的领先已查明是标点造成的 |
| A 股年报 / 中报（报表附注页） | 🔴 **现阶段不可替代** | Infinity 3 页确定性丢表（共 27 个金额），都在页首续表页，没有报错；Azure 也缺了 6 个，原因待查 |
| 需要按置信度分流复核的流程 | 🔴 **不可替代（结构性）** | API 不返回任何置信度，请求 `logprobs` 会被静默忽略 |
| 港股 KYC 类文件 | 🟡 **证据不足** | 只有 39 条正文完整性断言，没有金额断言 |
| 扫描件 / 倾斜件 | 🟡 **未与 Azure 对照** | 仅测了 Infinity：倾斜 2° 的页出现无限复读，打满 32k token，输出作废 |
| 贸易金融单证 | ⚪ **未覆盖** | 没有合规的公开样本，现有结论不能外推 |

<sub>样本：53 份公开披露文档 → 210 页 → 1,229 条断言；配对页 191 页（Azure 19 页因网关超时失败）　·　出处：[evaluation-report.md](evaluation-report.md)</sub>

---

## 2 / 4　解析质量对比：Azure DI vs Infinity-Parser2

<sub>Azure 在各项指标上持平或更好 · 同一批 191 页、同一套断言配对比较</sub>

<table>
<tr>
<td width="55%" valign="top">

### 断言通过率

| 指标 | n | Infinity | Azure DI |
|---|---|---|---|
| **金额**<br><sub>数值是否原样出现、出现次数是否正确</sub> | 486 | 97.5% | **100%** |
| **正文完整性**<br><sub>每页抽 3 行正文，查是否原样输出</sub> | 448 | 93.1% | **97.1%** |
| **单位与币种**<br><sub>表头「单位：元」等是否保留</sub> | 93 | 98.9% | 100% |
| **金额与科目同行**<br><sub>金额与科目标签是否挨在一起</sub> | 76 | 100% | 98.7% |

- **金额**：差异显著（0 : 12，p = 0.0005）。Infinity 的 12 条失败逐条核对后，**8 条是真实遗漏**，另外 4 条只是减号字形不同。
- **正文完整性**：差异显著（2 : 20，p = 0.0001）。**第一轮的 91.3% 对 72.5% 作废**，那是 Azure 把全角标点转成半角造成的。
- **单位与币种、金额与科目同行**：未观察到显著差异。

</td>
<td width="45%" valign="top">

### 🔴 全量金额扫描：两边都会缺，性质不同

<sub>配对 54 页 A 股金额页，1,544 个金额</sub>

| Infinity 缺失 | Azure 缺失 |
|---|---|
| **11 个** · 2 页 | **6 个** · 2 页 |

- **Infinity 已查实**：页首续表整段没输出；调用照常「正常结束」，重复 3 次缺的完全一样
- 配对集外还有一页：**整张 16 个金额的表**不见了（Azure 在该页网关失败，无法对比）
- Azure 缺的 6 个原因待查（第三轮）；页级比较未观察到显著差异

### 服务与成本

<sub>只作参考，两边口径不同，不比优劣</sub>

| | Infinity（测试端点） | Azure DI（公司网关） |
|---|---|---|
| 成功率 | 210 / 210 | 191 / 210 |
| 延迟 P50 | 22.5 s（并发 2） | 17 s（并发 4，含轮询） |
| 吞吐 | 1.6–5.6 页/分，加并发无效 | — |
| 价格 | 未报价 | 牌价 $10 / 千页 |

<sub>每页约 9.6k token。若按 token 计费，输入单价要低于 **≈ $1.13 / 百万 token** 才能与 Azure 牌价持平。</sub>

</td>
</tr>
</table>

<sub>检验方法：McNemar 配对检验；不合成总分；n &lt; 30 的分层不下结论　·　出处：[test-results.md](test-results.md)</sub>

---

## 3 / 4　技术路线对比：Azure DI（OCR 流水线）vs Infinity-Parser2（VLM）

<sub>OCR 出错时会报不确定，VLM 出错时照常交付 · 下一步：POC 范围与退出标准</sub>

<table>
<tr>
<td width="58%" valign="top">

| | Infinity-Parser2 | Azure DI（prebuilt-layout） |
|---|---|---|
| 技术路线 | 视觉语言模型（VLM），一次生成整页 markdown | OCR + 版面分析流水线 |
| 输入 | 整页渲染成 300 DPI 图像，逐页独立处理 | PDF（本次为单页 PDF） |
| 置信度 | 🔴 **无** | 🟢 **每个文本片段都有** |
| 确定性 | 同一页调用 3 次，99.0% 逐字相同（金额零变化） | 确定性 |
| 标点 | 保留原文全角 | 全角转半角，下游需要归一化 |
| 认不出时 | 可能漏掉或生成内容，调用照常正常结束 | 给低置信度或留空 |
| 特有失败 | 无限复读、打满 token 上限（观测到 2 次） | — |
| 坐标框 | 由模型生成 | 几何检测得出 |
| 版本 | 只看得到别名 `inf-mllm`，型号与版本不可知 | 有 API 版本号，可指定 |
| 模型 | 开源权重（Apache-2.0）；自称基于 Qwen3.5（待证实） | 闭源托管服务 |

</td>
<td width="42%" valign="top">

### POC 建议范围

- **先决条件：有成本或私有化部署上的动因**，解析质量本身不构成动因
- 港股年报、中报、招股书 + A 股公告，只用电子版 PDF，每族 ≥ 300 页
- **定向测试 ≥ 50 页「页首续表」**，测丢表的发生频率
- 强制护栏：金额与 PDF 文本层逐个对账；`finish_reason=length` 一律转人工
- 开测前厂商须答复：型号与版本锁定、计费方式、置信度、生产 SLA

### 退出标准（任一触发即停）

- 丢失或替换金额的页，显著多于 Azure
- 不能锁定版本，也不承诺变更前通知
- 按合同价计入人工复核后，单页成本高于 Azure
- 生产吞吐达不到业务峰值；复读退化率超过阈值

</td>
</tr>
</table>

<sub>出处：[evaluation-report.md](evaluation-report.md)</sub>

---

## 4 / 4　评测总结

<sub>结论 · 详细 · 方法 · 数据集</sub>

<table>
<tr><th width="90" align="left">结论</th><td>Azure 在<b>金额</b>、<b>正文完整性</b>两项上显著更好，<b>单位币种</b>、<b>金额科目归属</b>两项差异不显著，没有一项 Infinity 更好。Infinity 另有两个结构性缺陷：<b>不返回置信度</b>；页首是续表的页会<b>静默丢表</b>。</td></tr>
<tr><th width="90" align="left">详细</th><td>测试结果数据：参考 <a href="test-results.md">test-results.md</a>；分析报告查询信息：参考 <a href="evaluation-report.md">evaluation-report.md</a></td></tr>
<tr><th width="90" align="left">方法</th><td>两边都通过调用 API 解析同一批页，各自输出 markdown，我方不做转换；输出与同一套 GT（断言）逐条比对，只比两边都成功的页，用配对检验判断差异是否显著，不合成总分。</td></tr>
<tr><th width="90" align="left">数据集</th><td>自建金融集：53 份公开披露文档（巨潮资讯网、HKEX 披露易）→ 210 页 → 1,229 条断言，配对 191 页。GT 以 PDF 文本层自动提取为主，76 条科目归属人工逐条确认。<br>公共基准 olmOCR-Bench：跑了 41 页。</td></tr>
</table>

<table>
<tr>
<td width="50%" valign="top">

**[test-results.md](test-results.md)**

<sub>测试集与测试结果：测试集构成、GT 来源、各项指标与逐条失败明细、服务数据、数字出处</sub>

</td>
<td width="50%" valign="top">

**[evaluation-report.md](evaluation-report.md)**

<sub>分析报告：结论与依据、按文档类型的判断、结构性差异、POC 范围与退出标准、评测方法（附录 C）</sub>

</td>
</tr>
</table>

<sub>出处：[test-results.md](test-results.md)　·　[evaluation-report.md](evaluation-report.md)</sub>
