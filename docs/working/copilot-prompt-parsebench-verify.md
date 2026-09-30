# Copilot 任务：在公司电脑上复核 ParseBench 总结并定稿报告

适用环境：公司电脑，没有 git（Download ZIP），Windows PowerShell。
前提：已按 `copilot-prompt-parsebench.md` 跑完 Azure 500 份、打分、配对比较，
即 `runs\parsebench_azure_<时间戳>\parsebench_compare.json` 已存在。

背景：`docs/working/parsebench-summary.md` 是在公司外根据报告截图写的总结，
Azure 侧数字靠截图识别转录，可能有误；Azure 结果又不能带出公司。所以复核和定稿都在公司电脑上做：
- `tools/parsebench_verify.py` 把总结里引用的每个数字与公司电脑上的落盘结果逐项比对，
  并检查网关返回的 analyzeResult 是否含 bbox（决定 Visual Grounding 能否比较）
- `tools/parsebench_nodeep.py` 重现总结 §3 的「去掉 deep parsing」消融（不调用 API，不需要 INF 的 key）

## 你（人）要做的准备

1. GitHub 仓库页面 **Code → Download ZIP**，解压到一个新目录
2. 把下面 Prompt 开头的两个路径改成实际路径，整段粘给 Copilot agent

## Prompt

```text
我有一个评测项目，Windows PowerShell，没有 git，仓库是 GitHub 网页 Download ZIP 下载的。

  工作目录（旧，里面有我跑出来的 runs\、data\、.venv、.env）：C:\Users\<用户名>\<路径>\doc-parser-eval-main
  新版目录（刚下载解压）：                                     C:\Users\<用户名>\Downloads\doc-parser-eval-main

任务：同步新版代码，然后复核 docs\working\parsebench-summary.md 里的数字，定稿报告。
所有命令在「工作目录」执行。开始前先执行一次：$env:PYTHONUTF8 = "1"

## 硬性规则
1. 同步时以下路径绝不覆盖、绝不删除：
   runs\  data\  probe_out\  .venv\  .env  tools\vendor\parsebench_src\  tools\vendor\.venv-parsebench\
   「仅旧目录有」的文件一律保留（包括我改过 analyze() 的 tools\parsebench_azure_runner.py——
   如果新版目录里这个文件和旧目录不同，**保留旧目录的版本**，不要覆盖）。
2. 不重新调用 Azure 或 INF。不运行 tools\parsebench_runner.py、tools\parsebench_azure_runner.py。
3. 不修改 runs\ 下任何已有文件；不修改任何 tools\ 下的脚本。
4. 只允许改 docs\working\parsebench-summary.md，且只按第 5 步的规则改。

## 第 1 步：同步（先盘点，等我确认）
用 Get-FileHash 按内容比对，列出新增 / 修改 / 相同 / 仅旧目录有，按目录汇总。
给我看同步计划，我回复「确认」再复制，只复制「新增」和「修改」（规则 1 的例外除外）。
复制后确认存在：tools\parsebench_nodeep.py、tools\parsebench_verify.py、docs\working\parsebench-summary.md

## 第 2 步：确认前置文件
- 找到 INF run 目录 runs\parsebench_inf_<INF时间戳>（含 raw\ 和 parsebench_per_file.csv）
- 找到 Azure run 目录 runs\parsebench_azure_<时间戳>（含 parsebench_per_file.csv）
- 如果 runs\parsebench_azure_<时间戳>\parsebench_compare.json 不存在，先运行：
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_compare.py runs\parsebench_inf_<INF时间戳>\parsebench_per_file.csv runs\parsebench_azure_<时间戳>\parsebench_per_file.csv --name-a Infinity-Parser2 --name-b "Azure DI" --out runs\parsebench_azure_<时间戳>\parsebench_compare.json

## 第 3 步：重现 deep parsing 消融（不调用 API）
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_nodeep.py runs\parsebench_inf_<INF时间戳>
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_score.py runs\parsebench_inf_<INF时间戳>_nodeep
第二条会跑官方判分器，几分钟。完成后应有 runs\parsebench_inf_<INF时间戳>_nodeep\parsebench_summary.json，
终端里 chart 一行的均值应约为 0.020。

## 第 4 步：复核
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_verify.py runs\parsebench_inf_<INF时间戳> runs\parsebench_azure_<时间戳>
生成 docs\working\parsebench-verify.md。把终端输出原样贴给我。

## 第 5 步：按复核结果修订总结（只改数字与受影响的判断）
打开 docs\working\parsebench-verify.md 和 docs\working\parsebench-summary.md：
- 若全部一致：只把 parsebench-summary.md 开头「数字来源说明」那段引用块替换为：
  > **已复核**：<日期> 在公司电脑用 `tools/parsebench_verify.py` 逐项比对，N/N 项与落盘结果一致，
  > 明细见 `docs/working/parsebench-verify.md`。
- 若有不一致：把 parsebench-summary.md 里对应的数字改成 parsebench-verify.md「落盘结果」列的值；
  如果改动导致某个「结论」变化（例如 verdict 从「A 更高」变成「未观察到显著差异」），
  同步修改 §1 结论摘要和 §6 判断表里引用它的句子，**并在汇报里逐条列出改了什么**；
  然后把「数字来源说明」替换为：
  > **已复核并更正**：<日期> 在公司电脑用 `tools/parsebench_verify.py` 比对，更正 K 项（见文末「复核更正」），
  > 明细见 `docs/working/parsebench-verify.md`。
  并在文末加一节「## 复核更正」，列出每项：原值 → 更正值。
- 看 parsebench-verify.md 第 2 节 analyzeResult 完整性：
  如果 paragraphs_with_bbox 明显小于 files（比如不到一半），在 parsebench-summary.md §4 的 Visual Grounding 小节开头加一句：
  「**注意**：公司网关返回的 analyzeResult 中只有 X/500 份带段落 bbox，Azure 的 Visual Grounding 分数被系统性低估，本维度两边不可比，§1 与 §6 中关于 Visual Grounding 的判断作废。」
  并把 §1 第 4 条、§6 表中 bbox 一行标注「（不可比，见 §4）」。

## 第 6 步：最终报告
最终报告由三份文件组成，都在 docs\working\：
  parsebench-summary.md   总结（已复核）
  parsebench-results.md   parsebench_report.py 生成的完整数据（如不存在，按 copilot-prompt-parsebench.md 第 9 步生成）
  parsebench-verify.md    复核明细
如果本机有 pandoc，另外生成一份 Word：
  pandoc docs\working\parsebench-summary.md -o docs\working\parsebench-summary.docx
没有 pandoc 就跳过，不要安装。

## 第 7 步：汇报（直接贴给我）
1. 同步了哪些文件
2. 第 3 步 parsebench_score.py 终端最后的五行（各维度 n / 均值）
3. 第 4 步 parsebench_verify.py 的完整终端输出
4. 第 5 步改了什么（逐条）；若全部一致就说「未改数字」
5. analyzeResult 完整性那一行
```

## 结果回来后要看的

- `N/N 项一致`：一致就说明总结可以直接用；不一致的项要看是否翻转了结论
- `paragraphs_with_bbox`：决定 Visual Grounding 一维是否保留
- 消融 chart ≈ 0.020：在公司电脑上重现，说明 deep parsing 结论与环境无关
