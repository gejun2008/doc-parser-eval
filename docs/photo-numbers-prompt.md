# 拍照专用数字表的 prompt（给公司电脑上的 AI 助手）

公司电脑的数据不能上传、不能用 U 盘带出，只能拍照转给写报告的人。
这段 prompt 让助手把成文需要的数字汇成一页，**全部用整数、每张表带校验和**，
方便拍照，也方便接收方核对有没有看错数字。

在 GitHub 页面上点代码块右上角的复制按钮，整段粘给 Copilot。

---

## 复制以下内容

```
请生成一个新文件 report-numbers-for-photo.md，只放下面这些表，供我拍照转给写报告的人。

硬性要求：
- 所有数字直接从文件计算（results.csv、comparison_success_only/summary.json、
  data/assertions/*.yaml），不要用你之前写的文档里的数字，不要转述
- 只写整数计数，不写百分比，不四舍五入
- 每张表最后一行写「校验和 = 表内所有整数之和」
- 表格列尽量少，字号正常即可，不要把两张表挤在一起
- 不写任何路径、用户名、资源名、端点

表1 金融层配对，仅双方都成功的页，按断言类型分行：
  类型 | n | Inf通过 | Az通过 | 只Inf对 | 只Az对
  类型包括 page_integrity、amount、unit_currency、amount_label（审核后 confirmed 的）

表2 同表1口径，按文档族分行（7 个族）

表3 同表1口径，按时间窗口分行（new / old / older）

表4 人工审核结果：
  amount_label：confirmed 条数 / rejected 条数 / 其中人工改过值的条数
  审计抽样（原 status 为 auto_textlayer、被人工审过的 amount 与 unit_currency）：
    confirmed / rejected / 改值

表5 关键字段失败明细：只列 amount、unit_currency、amount_label 三类，
  只列双方都成功的页，只列至少一边失败的断言：
  断言ID最后20个字符 | 类型 | Inf判定说明(why，截前30字) | Az判定说明(why，截前30字)
  若超过 60 行，只列前 60 行并写明总行数

表6 Azure 金融层服务数据：成功页数 | 并发 | 单页延迟中位数(秒) | P95(秒) | 总耗时(分钟)

最后一段：critical_metric_status.json 里说明关键错误率为空的原因，原文照录。
```

---

## 拍照注意

- 在 VS Code 预览里打开生成的文件，**每张照片一张表**，正对屏幕拍
- **裁掉侧边栏、书签栏、任务栏**，照片里不需要出现内部系统名、带员工编号的路径

## 接收方怎么用这些数字

- 每张表先算一遍校验和，对不上说明照片里有数字看错了，回头核对那张表
- 表 1–3 是报告主体：只在双方都成功的页上配对比较。
  Azure 金融层 19 页失败全在 A 股年报（超时与网关故障，非识别错误），
  所以 A 股年报那一行只剩 13 页，证据最弱，报告里单独注明
- 表 5 用来逐条判断失败是否构成**业务错误**：字符串对不上不等于业务出错，
  例如全角 `（2）` 与半角 `(2)` 不一致是字符串失败但不是业务错误。
  逐条归类后才能给出关键错误率——这正是助手说「关键错误率为空」的原因

---

# 第二轮（2026-09-23）：全量金额扫描与宽松复判

第一轮的数字已写进 `docs/evaluation-report.md`。报告里还有 4 个未决项要靠公司电脑补数，
都**不调 API**，几分钟跑完。

## 先更新两个文件

从 GitHub 下载新版 ZIP，**只把这两个文件**复制到工作目录的 `tools\` 下，其他文件不用动
（断言与判定器没有变化，不需要重跑 check.py）：

```
tools\amount_scan.py
tools\relaxed_recheck.py
```

## 复制以下内容给 Copilot

```
请在仓库根目录运行下面两条命令。不要修改任何文件，不要调用任何 API，
不要运行 runner.py 或任何 Azure 调用脚本。环境 Windows PowerShell，
Python 用 .venv\Scripts\python。

<AZ> 指金融层 Azure 结果目录：runs\ 下含 raw\ 子目录和 results.csv 的
那个 Azure 目录（210 页、191 页成功的那一次）。

1. .venv\Scripts\python tools\amount_scan.py runs\inf-mllm_doc2md_20260921T013924Z runs\<AZ>
2. .venv\Scripts\python tools\relaxed_recheck.py runs\inf-mllm_doc2md_20260921T013924Z runs\<AZ>

如果报 KeyError 或找不到字段：停下，只告诉我 <AZ>\raw\ 下任意一个 json
的顶层字段名列表（不要输出字段值），不要自己改脚本。

然后生成新文件 report-numbers-round2.md，只包含：

第一部分：两条命令的终端输出原样照录，包括校验和行。不改写、不总结、
不重新排版。

第二部分：打开 <AZ>\raw\ 下 a_share_notice_new_605011_2026-09-18 第 1 页
的原始响应，在 content 里找到「20,005,000.00」，原样摘录它前面 30 个字符
和后面 10 个字符。只摘这一处。

第三部分：之前的配对对照把 unit_currency 整类排除了，理由写的是
「空格匹配问题」。说明这个排除是在哪个文件的哪一行做的（文件名+行号，
不写完整路径），以及排除的具体判断条件，原样引用那几行代码。

不写任何路径中的用户名、资源名、端点。
```

## 拍照与回传

- 第一部分每条命令的输出各拍一张；第二、三部分合拍一张
- 接收方用每张表的「校验和」行核对

## 接收方怎么用

| 输出 | 用来回答报告里的哪个未决项 |
|---|---|
| `amount_scan` | §2.4：Azure 在同一批 A 股页上有没有整表遗漏。若 Azure 缺失为 0、Infinity 3 页里有页不在配对集，会在输出里直接看到 |
| `relaxed_recheck` 的 page_integrity 两行 | §2.5：宽松口径下 99 : 15 缩成多少。缩没了＝差距是标点造成的；还在＝有真实内容差异 |
| `relaxed_recheck` 的 unit_currency 两行 | §2.1：单位/币种字段能否恢复进对照 |
| 第二部分摘录 | §2.3：lp02 那条 Azure 失败是不是括号全/半角 |
| 第三部分 | §2.1：unit_currency 的排除理由是否成立 |
