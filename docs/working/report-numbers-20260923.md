# 公司电脑配对数字转录（2026-09-23）

**来源**：公司电脑上由 AI 助手按 `docs/working/photo-numbers-prompt.md` 从
`results.csv`、`comparison_success_only/summary.json`、`data/assertions/*.yaml`
直接计算生成 `report-numbers-for-photo.md`，拍照转出，本文件逐字转录。
公司侧数据不能上传或用 U 盘带出，**本文件是报告中 Azure 对照数字的唯一出处**。

**转录核对**：每张表按「表内所有整数之和」重算，与照片上的校验和逐一比对。
另做了跨表一致性检查（表 1/2/3 是同一批配对断言的三种切法，各列合计必须相等）。

| 表 | 照片校验和 | 重算 | 跨表一致性 |
|---|---|---|---|
| 1 按类型 | 2982 | 2982 ✓ | — |
| 2 按文档族 | 2982 | 2982 ✓ | n/Inf/Az/只Inf/只Az 合计 = 1010/959/886/100/27，与表 1 相同 ✓ |
| 3 按时间窗口 | 2982 | 2982 ✓ | 同上 ✓ |
| 4 人工审核 | 131 | 131 ✓ | — |
| 5 失败明细 | 52 | 52 ✓（`found xN` 中的 N 与字母相连，不算独立整数） | 行数 13 = 表 1 中 amount 的 12（只Az对）+ amount_label 的 1（只Inf对）✓ |
| 6 Azure 服务 | 420 | 420 ✓ | — |

每一行还验了内部恒等式：`Az通过 = (Inf通过 − 只Inf对) + 只Az对`，13 行全部成立。

---

## 表 1 金融层配对：双方成功页，按断言类型

口径（照片原文）：排除 unit_currency 空格匹配问题；amount_label 仅 confirmed。

| 类型 | n | Inf 通过 | Az 通过 | 只 Inf 对 | 只 Az 对 |
|---|---|---|---|---|---|
| page_integrity | 448 | 409 | 325 | 99 | 15 |
| amount | 486 | 474 | 486 | 0 | 12 |
| amount_label | 76 | 76 | 75 | 1 | 0 |

## 表 2 同口径，按文档族

| 文档族 | n | Inf 通过 | Az 通过 | 只 Inf 对 | 只 Az 对 |
|---|---|---|---|---|---|
| a_share_annual | 84 | 76 | 64 | 19 | 7 |
| a_share_interim | 167 | 155 | 143 | 19 | 7 |
| a_share_notice | 137 | 133 | 87 | 46 | 0 |
| hk_annual | 202 | 191 | 195 | 2 | 6 |
| hk_interim | 210 | 202 | 203 | 1 | 2 |
| hk_kyc | 39 | 38 | 36 | 2 | 0 |
| hk_prospectus | 171 | 164 | 158 | 11 | 5 |

## 表 3 同口径，按时间窗口

| 窗口 | n | Inf 通过 | Az 通过 | 只 Inf 对 | 只 Az 对 |
|---|---|---|---|---|---|
| new | 505 | 490 | 453 | 44 | 7 |
| old | 473 | 441 | 405 | 53 | 17 |
| older | 32 | 28 | 28 | 3 | 3 |

## 表 4 人工审核结果

审计抽样仅 amount，原状态为 auto_textlayer；改值按人工改值记录计。

| 审核范围 | confirmed | rejected | 其中改值 |
|---|---|---|---|
| amount_label | 76 | 0 | 1 |
| 审计抽样：amount | 53 | 0 | 1 |

## 表 5 关键字段失败明细

仅 amount 与 amount_label，双方成功页，至少一边失败，共 13 行。
断言 ID 在照片中只有末 20 字符，完整 ID 由本机断言文件补全（末 20 字符唯一匹配）。

| 完整断言 ID | 类型 | Inf 判定 | Az 判定 |
|---|---|---|---|
| a_share_annual_old_002310_2026-04-30_p225_am01 | amount | expected 2, found 1 | found x2 |
| a_share_annual_old_002310_2026-04-30_p225_am02 | amount | expected 4, found 2 | found x4 |
| a_share_annual_old_002310_2026-04-30_p225_am03 | amount | expected 10, found 7 | found x10 |
| a_share_annual_old_002310_2026-04-30_p225_am04 | amount | expected 5, found 4 | found x5 |
| a_share_annual_older_300208_2025-04-30_p11_am04 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_688098_2025-08-29_p170_am01 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_688098_2025-08-29_p170_am02 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_688098_2025-08-29_p170_am03 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_688098_2025-08-29_p170_am04 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_839680_2025-08-30_p9_am01 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_839680_2025-08-30_p9_am03 | amount | expected 1, found 0 | found x1 |
| a_share_interim_old_839680_2025-08-30_p9_am04 | amount | expected 1, found 0 | found x1 |
| a_share_notice_new_605011_2026-09-18_p1_lp02 | amount_label | label-amount gap 9 | label not found: 元（含税） |

## 表 6 Azure 金融层服务数据

耗时向下取整；延迟仅成功页，含网关及轮询，P95 线性插值；总耗时为首末记录墙钟跨度，含中断。

| 成功页数 | 并发 | 单页延迟中位数 (s) | P95 (s) | 总耗时 (min) |
|---|---|---|---|---|
| 191 | 4 | 17 | 21 | 187 |

## critical_metric_status.json 原文

> GT review completed. Punctuation-sensitive failures and proximity-only checks require
> business-error adjudication; do not aggregate them as confirmed business-critical errors.

---

## 表 5 的逐条裁定（本机完成，2026-09-23）

公司侧助手把关键错误率留空，理由是字符串失败不等于业务错误，需要逐条裁定。
Infinity 一侧的原始输出在本机，**12 条 Infinity 失败已逐条打开原始响应、对照 PDF 文本层裁定**。
Azure 一侧 1 条的原始输出在公司电脑，本机无法裁定。

| 断言 | 页 | 裁定 | 依据 |
|---|---|---|---|
| p225 am01–am04（4 条） | 002310 年报 p225 | **业务错误：静默遗漏** | 页首是上一页「应收账款按账龄披露」表的续表（1 年以内 / 3 年以上 / 5 年以上 / 合计 四行）。Infinity 输出从下一个小标题「（2）按坏账计提方法分类披露」开始，**整段续表缺失**，`finish_reason=stop`。四个金额在页内其他表格仍出现，所以表现为「次数少了」而不是「找不到」 |
| p170 am01–am04（4 条） | 688098 中报 p170 | **业务错误：静默遗漏** | 页首是上一页表格的「合计」行（4 个金额）。Infinity 输出从「(2). 营业收入、营业成本的分解信息」开始，**合计行缺失**，`finish_reason=stop` |
| p11 am04（1 条） | 300208 年报 p11 | 非业务错误：减号字形 | 输出为 `−310,302,902.32`（U+2212 数学减号），数值正确；GT 为 ASCII `-` |
| p9 am01/am03/am04（3 条） | 839680 中报 p9 | 非业务错误：减号字形 | 同上，三个负数都用了 U+2212，数值正确 |
| p1 lp02（1 条，Azure 侧） | 605011 公告 p1 | **待裁定** | Azure 报「label not found: 元（含税）」，大概率是全角/半角括号差异（判定器只归一空白，不归一标点）。需在公司电脑打开 Azure 原始输出确认 |

**裁定结果**：Infinity 8 条业务错误，集中在 2 页；4 条格式差异；Azure 0 条已确认业务错误，1 条待裁定。

**同一现象在全量扫描中的规模**：见 `tools/amount_scan.py`。Infinity 在 210 页中 73 页含
A 股口径金额（2,149 次出现），缺失 27 次，集中在 3 页——除上面两页外，
`a_share_annual_old_300572_2026-04-30` p9 **整张「分季度主要财务指标」表（16 个金额）缺失**，
且该表的标题被挂到了上方续表的头上。抽样断言只抽中了该页续表里的 4 个金额，全部通过，
所以表 5 里没有它。三次重复调用（`013924Z` / `042333Z` / `050222Z`）缺失完全相同，是确定性失败。

---

# 第二轮（2026-09-24）：全量金额扫描与宽松复判

**来源**：公司电脑运行 `tools/amount_scan.py` 与 `tools/relaxed_recheck.py`，
A = `inf-mllm_doc2md_20260921T013924Z`，B = `azure_gateway_corpus_20260922`，
由助手原样照录进 `report-numbers-round2.md`，拍照转出。

| 输出 | 照片校验和 | 重算 | 其他核对 |
|---|---|---|---|
| amount_scan | 2327 | 2327 ✓ | Infinity 缺失 11 = 7 + 4，与本机单边扫描中配对页部分一致 ✓ |
| relaxed_recheck | 3168 | 3168 ✓ | 「严格」page_integrity 行 448/409/325/99/15 与第一轮表 1 完全一致 ✓；四行恒等式全部成立 |

## 全量金额扫描（配对页）

配对页（双方都成功、且含 A 股口径金额）：**54 页，金额出现 1,544 次**。

| 系统 | 缺失次数 | 有缺失的页数 |
|---|---|---|
| Infinity | 11 | 2 |
| Azure DI | 6 | 2 |

| 页 | 文本层金额数 | Infinity 缺失 | Azure 缺失 |
|---|---|---|---|
| a_share_annual_old_002310_2026-04-30 p225 | 32 | 7 | 0 |
| a_share_interim_old_688098_2025-08-29 p170 | 46 | 4 | 4 |
| a_share_interim_old_688098_2025-08-29 p202 | 16 | 0 | 2 |

`a_share_annual_old_300572_2026-04-30` p9（Infinity 丢了整张 16 个金额的表）**不在配对集内**：
Azure 在该页调用失败（网关超时），所以这一页没法对比。

## 宽松复判

宽松 = NFKC（全角转半角）+ 删除所有标点与符号；严格 = check.py 原口径（只去空白）。

| 类型 | 口径 | n | Inf 通过 | Az 通过 | 只 Inf 对 | 只 Az 对 |
|---|---|---|---|---|---|---|
| page_integrity | 严格 | 448 | 409 | 325 | 99 | 15 |
| page_integrity | 宽松 | 448 | 417 | 435 | 2 | 20 |
| unit_currency | 严格 | 93 | 89 | 2 | 87 | 0 |
| unit_currency | 宽松 | 93 | 92 | 93 | 0 | 1 |

## 原文摘录（公告 p1，lp02）

Azure 输出：`基数,每股派发现金红利0.05元(含税),共计派发现金红利20,005,000.00元。`
文本层原文：`…元（含税），共计派发现金红利20,005,000.00元。`

Azure 把全角括号、全角逗号转成了半角，所以严格口径下「元（含税）」匹配不到。
**裁定：非业务错误**（标点字形差异）。

## unit_currency 排除理由核实

助手报告：「空格匹配问题」这几个字只出现在它生成的 `report-numbers-for-photo.md` 第 1 行，
仓库里**没有**按类型整类排除 unit_currency 的代码。配对筛选的代码只要求两边都有判定、页面调用都成功。

**结论**：这个排除是助手写表时的人为决定，理由也不对。真实原因是 Azure 把「单位：元」
这类全角冒号转成了半角（严格口径 Azure 只过了 2/93，宽松口径 93/93），不是空格问题。
