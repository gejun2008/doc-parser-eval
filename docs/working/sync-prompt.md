# 用 AI 助手同步新版仓库（无 git 环境）

适用场景：公司电脑通过网页 **Download ZIP** 取得仓库，没有 git。
仓库更新后，下载新版 ZIP 解压到另一个目录，把下面这段粘给 Copilot 等助手，
由它比对新旧目录、判断哪些文件要更新、同步后需要重跑哪些步骤。

**用之前把开头两个路径改成实际路径。**

---

## 复制以下内容

```
我有一个评测项目，工作目录是网页下载的 ZIP 解压出来的（没有 git）。
仓库有更新，我又下载了新版 ZIP 解压到另一个目录。请帮我把新版同步到
工作目录，并判断同步后需要重跑哪些步骤。环境是 Windows PowerShell，
Python 用 .venv\Scripts\python。

  工作目录（旧，里面有我跑出来的数据）：C:\Users\<用户名>\<路径>\doc-parser-eval-main
  新版目录（刚下载解压）：            C:\Users\<用户名>\Downloads\doc-parser-eval-main

## 第一步：盘点差异，不要动任何文件

用 Get-FileHash 按内容比对，把新版目录里的每个文件归为四类：
  新增（旧目录没有）/ 修改（内容不同）/ 相同 / 仅旧目录有
按目录汇总报告，不要逐个列出相同的文件。

## 第二步：保护规则，任何情况下不得违反

1. 以下路径绝不覆盖、绝不删除：
   runs\  data\corpus\  data\olmocr_bench\  probe_out\  .venv\  .env
   这些是我跑出来的数据或本机环境，新版 ZIP 里本来也不应该有它们。
   如果新版目录里意外出现了这些路径，停下来告诉我，不要复制。
2. 「仅旧目录有」的文件一律保留，不要删。
3. 如果旧目录的 .env.example 里看起来有真实凭证（不是 <...> 占位符），
   停下来警告我——凭证应该在 .env 里，覆盖 .env.example 会把它弄丢。
4. data\assertions\ 下的 YAML 如果内容有变，要覆盖。覆盖前检查旧文件里
   有没有 review: 字段或 status 为 confirmed/rejected 的条目——有的话说明
   我做过人工审核，告诉我哪些文件、多少条，因为断言更新后这些审核会作废。

## 第三步：给我看同步计划，等我确认

列出：要复制哪些文件、跳过哪些、有没有触发第二步的任何警告。
等我回复「确认」再执行。

## 第四步：执行复制，然后验证

只复制「新增」和「修改」两类。完成后运行：
  Select-String -Path data\assertions\a_share_annual_older_688152_2025-04-29.yaml -Pattern "181,801,731.11"
能搜到说明新版断言已生效。搜不到就停下来报告，不要继续。

## 第五步：根据变化决定要重跑什么

原则：只重跑判定，绝不重新调 API。不要运行 tools\runner.py 或
tools\azure_di_runner.py——原始响应 runs\*\raw\ 没有变，重调既花钱又
会破坏可复现性。

- 如果 data\assertions\ 或 tools\check.py 变了：
  对 runs\ 下每个含 results.csv 的目录重跑
    .venv\Scripts\python tools\check.py runs\<目录名>
  Infinity 与 Azure 两边都要重跑，两边必须用同一版断言判定才能比较。

- 如果上面重跑了，而且已经存在对比结果：之前的对比作废，重跑
    .venv\Scripts\python tools\compare_systems.py runs\<Infinity目录>\results.csv runs\<Azure目录>\results.csv --name-a Infinity --name-b AzureDI
  自建集对应的 Infinity 目录是 inf-mllm_doc2md_20260921T013924Z，
  Azure 目录是 azure_di_layout_ 开头、且含 results.csv 的那个。

- 如果 tools\score_olmocr.py 或 tools\vendor\ 变了：对含 olmocr_results.csv
  的目录重跑 score_olmocr.py。没变就不用动，那一层不受断言影响。

- 如果 data\assertions\ 或 tools\review_assertions.py 变了：重新生成审核页
    .venv\Scripts\python tools\review_assertions.py --audit 60
  完成后才能打开 review\index.html，旧的审核页已过期。

- 如果只有 docs\ 或 .md 文件变了：什么都不用重跑。

## 第六步：汇报

告诉我：更新了哪些文件、重跑了哪些命令、重跑前后关键数字的变化
（results_summary.json 里各类型的通过率）。

如果某个数字变化很大，先查原因再汇报，不要直接下结论——这个项目
出现过判定器 bug 让通过率假性显示 9.9%、真实值 97.9% 的情况。
查法：打开对应 results.csv 看 why 列，再打开 raw\ 下的 json 看实际输出。
```

---

## 为什么这样写

- **保护规则写死在前面。** 助手做「同步」时容易把「仅旧目录有」理解成「应该删掉」，
  那样 `runs\` 里跑出来的 Azure 结果就没了。GitHub 的 ZIP 只含入库文件，
  本来就不含 `runs\`、语料、`.env`、`.venv\`，所以这些在新版目录里「不存在」
  不代表该删
- **先出计划、等确认再动手。** 不让助手自作主张
- **第四步有客观检查点。** 搜得到完整金额 `181,801,731.11` 才算更新成功，
  不靠助手自己说「已完成」。**以后的更新若不涉及这条断言，把检查点换成
  本次更新里某个确定变化的内容**
- **明确「绝不重新调 API」。** 助手看到「数据要更新」有时会想从头重跑，
  那既花钱，又会让结果与原始调用时间戳对不上
- **按「什么变了」决定「重跑什么」。** 断言变了两边都要重判；
  评分器变了才重跑对应那一层；只有文档变了什么都不用动

## 本次更新（2026-09-23）的具体情况

供核对助手的判断是否正确：

| 变化 | 需要的后续动作 |
|---|---|
| `data\assertions\*.yaml`：37 条金额断言的截断目标值修正 | 两边重跑 `check.py`；重跑 `compare_systems.py`；重新生成审核页 |
| `tools\make_assertions.py`、`review_assertions.py`、`apply_review.py`、`make_handoff.py` | 同上（已涵盖） |
| `docs\`、根目录 `.md` | 无 |
| `tools\score_olmocr.py`、`tools\vendor\` | **未变**，olmOCR-Bench 那层不用重跑 |

若之前做过人工审核并跑过 `apply_review.py`，那些审核已作废，需在新审核页上重做。
