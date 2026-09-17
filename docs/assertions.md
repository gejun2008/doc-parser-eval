# 断言 schema

不做全文 markdown GT——每份要数人日，会拖死整个评测，而且会把评测稀释成
又一次单页 OCR 测试。改用 olmOCR-bench 的 pass/fail 思路。

目标：每份文档 10–20 条可自动判定的断言，全集约 200 条，标注工作量 2–3 人日。

## 文件组织

`data/assertions/<doc_id>.yaml`，一份文档一个文件，入库。

```yaml
doc_id: 000651_2026H1          # 与 data/corpus/ 下文件名对应
source_url: https://...        # 报告附录要列，必填
family: a_share_interim        # 八个文档族之一，分层出数的依据
disclosed_at: 2026-08-22       # 泄漏对照的切分依据，模型发布日 2026-06-08
pages: 128
assertions:
  - id: 000651_2026H1_a01
    type: amount                # 七类之一，见下
    severity: critical          # critical | major | minor
    page: 47                    # 物理页，1-based
    eval_on: md                 # md | json —— 第 6、7 类必须用 json
    rule: exactly_once
    target: "1,234,567,890"
    forbid: ["1,234,567,89", "1234567890"]   # 错位/丢分隔符的常见形态
    note: 合并利润表营业收入
```

`eval_on` 必填。原因见 sdk-findings.md §5：md 输出默认丢弃
header/footer/page_footnote，第 6 类断言在 md 上判会得到假阳性。

## 七类断言

| type | 判定什么 | 典型 severity |
|---|---|---|
| `amount` | 金额/数字精确性。目标串恰好出现一次，且禁止串不出现 | critical |
| `unit_currency` | 单位与币种保留。「人民币千元」表头须在，金额不得被换算或丢单位 | critical |
| `table_span` | 跨页表格。合并后行数、续表页表头处理 | major |
| `reading_order` | 跨页阅读顺序。续表行须挂在前页表头下 | major |
| `page_integrity` | 漏页与幻觉。页锚点串须全在，不得出现原文不存在的科目名 | critical |
| `footnote_scope` | 页眉页脚与脚注归属，脚注不得混入正文流（`eval_on: json`） | major |
| `formatting` | 格式保留，加粗/斜体/删除线（`eval_on: json`） | minor |

第 7 类针对厂商自陈的 bold/italic/strikethrough 缺失，低成本验证其业务影响。

## severity 的用法

critical 一条的代价不等于十条 minor。**报告主推 critical error rate，
不报加权总分。**

| 等级 | 定义 |
|---|---|
| critical | 直接导致业务错误决策：金额漏位/错位、账号错、日期错、单位误判、币种错 |
| major | 需人工返工：跨页合并错、行错位、附注归属错、漏页 |
| minor | 不影响使用：格式、标点、空格、换行 |

## 零成本自动检查

公开年报 PDF 自带文本层，用 pymupdf 抽出作文本级参考。

**它不能当阅读顺序 GT**（文本层顺序常错），但每页取唯一锚点串
（长度 ≥ 12 字符、全文唯一的片段），检查是否全部出现、有无凭空多出，
对漏页与幻觉检测非常好使，且完全自动、零标注成本。

`type: page_integrity` 的断言应该由脚本从文本层批量生成，不手写。

## 扰动组复用

低质扫描扰动组由第 1–7 类文档族派生（重新打印扫描、降分辨率、JPEG 高压缩、
±2° 旋转、高斯噪声），**直接复用原文档的断言文件**，零额外标注成本。

扰动组的衰减幅度比原始分数更接近生产表现——真实银行文档大量是传真与多代影印件。

注意 sdk-findings.md §6：降 DPI 的源文件仍会被按 300 DPI 重新栅格化。
想测低分辨率输入本身，必须直接传图片并调 `min_pixels/max_pixels`。
