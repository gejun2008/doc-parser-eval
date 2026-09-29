# Copilot 任务：公司电脑跑 Azure DI × ParseBench 500 份，与 INF 配对比较并出报告

适用环境：公司电脑，**没有 git**，仓库通过 GitHub 网页 **Code → Download ZIP** 取得；
Windows PowerShell。口径见 `docs/working/parsebench-method.md`。

## 你（人）要做的准备

1. 在 GitHub 仓库页面点 **Code → Download ZIP**，下载 `doc-parser-eval-main.zip`（约 130 MB，
   里面已经包含 `handoff\parsebench-*.zip` 交接包）
2. 解压到一个**新目录**，例如 `C:\Users\<用户名>\Downloads\doc-parser-eval-main`，
   **不要**直接解压覆盖你原来的工作目录（里面有之前跑出来的 runs\ 和 .env）
3. 把下面「Prompt」代码块里开头的两个路径改成实际路径，整段粘给 Copilot agent

**交接分两批**：
- 第一批（已在仓库里）：500 份测试数据 + 判分器源码 → Copilot 可以做完第 1–6 步（跑 Azure 并打分）
- 第二批（INF 跑完后推送）：`handoff\parsebench-inf-results.zip` → 到时再下载一次 ZIP，
  让 Copilot 从第 7 步继续（配对比较、生成报告）

## Prompt

```text
我有一个评测项目，环境是 Windows PowerShell，没有 git。仓库是从 GitHub 网页 Download ZIP 下载的。

  工作目录（旧，里面有我之前跑出来的数据、.venv、.env）：C:\Users\<用户名>\<路径>\doc-parser-eval-main
  新版目录（刚下载解压）：                              C:\Users\<用户名>\Downloads\doc-parser-eval-main

任务分两段：先把新版同步进工作目录；再在工作目录里用公司 Azure Document Intelligence 网关
跑 ParseBench 500 份分层子集，用仓库现有脚本打分，与 INF（Infinity-Parser2）结果配对比较，生成报告。
以下所有命令都在「工作目录」里执行。开始前先在 PowerShell 里执行一次
  $env:PYTHONUTF8 = "1"
（脚本会输出中文，Windows 控制台默认编码可能报错）。

## 硬性规则（任何一条都不能违反）
1. 同步时以下路径绝不覆盖、绝不删除：
   runs\  data\corpus\  data\olmocr_bench\  data\parsebench\  probe_out\  .venv\  .env
   tools\vendor\parsebench_src\  tools\vendor\.venv-parsebench\
   「仅旧目录有」的文件一律保留（例如我之前写的 tools\azure_gw_runner.py）。
2. 不修改这些文件：tools\parsebench_score.py、tools\parsebench_compare.py、tools\parsebench_report.py、
   tools\vendor\parsebench_src\ 下任何文件、data\parsebench\ 下任何文件、runs\parsebench_inf_*\ 下任何文件。
3. tools\parsebench_azure_runner.py 里只允许改 analyze() 这一个函数，让它走公司网关；
   返回值保持为 (analyzeResult 字典或 None, 调用记录)。其余代码不动。
4. 网关的 key/token 只从环境变量读取，不写进源码、日志、落盘 JSON。响应头已由 redact() 脱敏，不要绕过。
5. 不写任何版面到 markdown 的转换规则。必须让 Azure 自己输出 markdown
   （prebuilt-layout，outputContentFormat=markdown，api-version 2024-11-30）。网关不支持就停下来告诉我。
6. 不要手工改任何分数或报告里的数字；报告只能由 tools\parsebench_report.py 生成。
7. 不要重跑 INF（tools\parsebench_runner.py、tools\runner.py），这台电脑没有 INF 的 key，也不需要。

## 第 1 步：同步新版代码（先盘点，等我确认再复制）
- 用 Get-FileHash 按内容比对新版目录与工作目录，把新版目录的文件分为：新增 / 修改 / 相同 / 仅旧目录有。
  按目录汇总告诉我，不要逐个列出相同的文件。
- 列出同步计划（复制哪些、跳过哪些、有没有触发规则 1 的路径），等我回复「确认」再执行。
- 只复制「新增」和「修改」两类。复制后确认工作目录里有：
    tools\parsebench_azure_runner.py、tools\parsebench_score.py、tools\parsebench_compare.py、
    tools\parsebench_report.py、docs\working\parsebench-method.md、handoff\parsebench-data-chart.zip

## 第 2 步：核对并解压交接包
handoff\ 下每个 parsebench-*.zip 都有同名 .sha256 文件（内容是「小写哈希  文件名」）。
- 逐个用 (Get-FileHash <zip> -Algorithm SHA256).Hash 计算，与 .sha256 里的哈希**忽略大小写**比较，
  不一致就停下来报告。
- 在工作目录根目录解压（zip 内已带完整相对路径，目标就是当前目录）：
    Expand-Archive handoff\parsebench-data-chart.zip  -DestinationPath . -Force
    Expand-Archive handoff\parsebench-data-layout.zip -DestinationPath . -Force
    Expand-Archive handoff\parsebench-data-table.zip  -DestinationPath . -Force
    Expand-Archive handoff\parsebench-data-text.zip   -DestinationPath . -Force
    Expand-Archive handoff\parsebench-scorer-src_3295d7f.zip -DestinationPath . -Force
  （handoff\parsebench-inf-results.zip 如果已经存在，也用同样方式解压；不存在就先跳过。）
- 解压后应有：
    data\parsebench\manifest.csv（500 行，不含表头）
    data\parsebench\subset\{chart,table,text_content,text_formatting,layout}.jsonl
    data\parsebench\subset\docs\{chart,layout,table,text}\...
    tools\vendor\parsebench_src\pyproject.toml
- 按 manifest.csv 核对 500 份文件：data\parsebench\subset\<pdf 列>（把 / 换成 \）的 SHA256
  取前 16 位（小写）必须等于 sha256_16 列。全部一致才继续。

## 第 3 步：建 ParseBench 专用环境（Python >= 3.12，与 .venv 分开）
- 先看有没有 3.12：py -3.12 --version。没有就停下来告诉我，不要用 3.11 硬装。
    py -3.12 -m venv tools\vendor\.venv-parsebench
    tools\vendor\.venv-parsebench\Scripts\python -m pip install -e tools\vendor\parsebench_src azure-ai-documentintelligence pdf2image requests
- 验证：tools\vendor\.venv-parsebench\Scripts\parse-bench version 应输出 1.0.4。
  不需要 poppler，也不需要 INF 的 key。
- pip 如果被公司代理拦，把报错原文告诉我。

## 第 4 步：改 analyze() 走公司网关，试跑 4 份
- 打开 tools\parsebench_azure_runner.py，读文件头说明。analyze(path) 的默认实现是 Azure 官方 REST
  （POST :analyze -> 202 + Operation-Location -> 轮询）。
- 如果工作目录里有之前为 olmOCR-Bench 写的公司网关适配器（例如 tools\azure_gw_runner.py），复用它的调用方式和环境变量名。
- 要求：整份文件原样发送（不加 pages 参数、不转图片）；PDF 用 application/pdf，JPG/PNG 用对应图片 content-type；
  返回 REST 响应里 "analyzeResult" 那一层的**完整**字典，必须包含 content、pages、tables、paragraphs、figures。
  网关如果只返回 content / markdown，立刻停下来告诉我——Visual Grounding 维度需要 boundingRegions。
- dry-run：tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_azure_runner.py --dry-run
  应显示 500 份（chart=100 layout=120 table=130 text=150）。
- 试跑：tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_azure_runner.py --limit 1
  打开 runs\parsebench_azure_<时间戳>\raw\ 下的 JSON，确认 ok=true、analyze_result.content 是 markdown、
  analyze_result 里有 pages 和带 boundingRegions 的 paragraphs；layout 那份 JPG 也要成功。
  确认后把这个试跑目录删掉，不要和正式运行混用。

## 第 5 步：全量运行 500 份
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_azure_runner.py --concurrency 4
- 看 runs\parsebench_azure_<时间戳>\run_summary.json 的 n_files_ok 与 failed_files。
- 失败如果是限流 / 超时：加 --resume runs\parsebench_azure_<时间戳> --concurrency 2 重跑失败项；
  如果是网关或 Azure 拒绝某类文件（大小、格式），原样记录，不要改文件。
- 把失败原因按 status 和 error 分类计数，写进汇报。

## 第 6 步：打分（现成脚本，不改）
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_score.py runs\parsebench_azure_<时间戳> --pipeline azure_di_layout
确认生成了 parsebench_summary.json 和 parsebench_per_file.csv，五个维度都有 n。
**如果 handoff\parsebench-inf-results.zip 还没有，到这里停下，按第 10 步汇报第 1–6 步的结果。**

## 第 7 步：解压 INF 结果（第二批）
我会再下载一次新版 ZIP。按第 1 步的规则同步（只会多出 handoff\parsebench-inf-results.zip 等少数文件），
核对 sha256 后：
    Expand-Archive handoff\parsebench-inf-results.zip -DestinationPath . -Force
应出现 runs\parsebench_inf_<时间戳>\parsebench_per_file.csv。

## 第 8 步：配对比较
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_compare.py runs\parsebench_inf_<INF时间戳>\parsebench_per_file.csv runs\parsebench_azure_<时间戳>\parsebench_per_file.csv --name-a Infinity-Parser2 --name-b "Azure DI" --out runs\parsebench_azure_<时间戳>\parsebench_compare.json

## 第 9 步：生成报告
    tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_report.py runs\parsebench_inf_<INF时间戳> runs\parsebench_azure_<时间戳> --out docs\working\parsebench-results.md
打开 docs\working\parsebench-results.md 检查：第 1 节两列都有 run_id 和文件数；第 2 节两张表五个维度都有数；
第 5 节有官方 leaderboard 的三行。

## 第 10 步：汇报与带回（直接贴给我，不要写结论性判断）
汇报：
1. 同步了哪些文件；sha256 核对是否全部通过
2. 公司网关调用方式：URL 形态（不含 key）、同步还是异步、是否确认 outputContentFormat=markdown、
   analyzeResult 是否完整（有无 paragraphs/tables/figures 的 boundingRegions）
3. 成功文件数 / 500，失败原因分类计数
4. （做到第 8 步时）parsebench_compare.py 的完整终端输出
5. （做到第 9 步时）docs\working\parsebench-results.md 第 2 节原文
带回：把下面这些压成 parsebench-azure-results.zip（不含 key，不带 raw\ 目录）：
  runs\parsebench_azure_<时间戳>\ 下的 run_meta.json、run_summary.json、parsebench_summary.json、
  parsebench_per_file.csv、parsebench_compare.json、parsebench\_normalize_log.json
  docs\working\parsebench-results.md
规则：不合成总分；p >= 0.05 或区间跨 0 一律写「未观察到显著差异」，不写「持平」；不要写「推荐 / 不推荐」。
```

## 结果回来后要看的

- **analyzeResult 是否完整**：网关若只回 content，Visual Grounding 这一维 Azure 会被系统性低估，不能比
- **失败文件**：olmOCR-Bench 那一轮 Azure 只成功 41/120，这次要看失败是否集中在某个维度（如 layout 的图片输入）
- **主口径 vs 参照口径**：两者差距大，说明差异主要来自调用失败而非解析质量，报告里要分开写
