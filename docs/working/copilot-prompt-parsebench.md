# Copilot 任务：公司电脑跑 Azure DI × ParseBench 500 份，与 INF 配对比较并出报告

在公司电脑上把下面「Prompt」一节整段交给 Copilot agent 执行。口径见 `docs/working/parsebench-method.md`。

背景：INF（Infinity-Parser2）在 500 份 ParseBench 分层子集上用官方判分器打分，
结果随交接包提供。**交接分两批**：第一批是数据与判分器（可以立即跑第 0–5 步的 Azure），
第二批是 INF 结果包 `parsebench-inf-results.zip`（到了再跑第 6–9 步）。公司电脑只需要用公司的 Azure DI 网关跑**同一批 500 份文件**，
用**同一个判分脚本**打分，然后配对比较、生成报告。判分、比较、报告的代码都已在仓库里，
Copilot 唯一需要写的是「怎么调用公司网关」这一个函数。

## Prompt

```text
你在 inf-eval 仓库根目录工作（先 git pull 拿到最新代码）。目标：用公司内部的
Azure Document Intelligence 网关，跑 ParseBench 500 份分层子集，用仓库现有脚本打分，
与 INF（Infinity-Parser2）已有结果逐文件配对比较，最后生成一份 markdown 报告。

## 硬性规则（任何一条都不能违反）
1. 不修改这些文件：tools/parsebench_score.py、tools/parsebench_compare.py、tools/parsebench_report.py、
   tools/vendor/parsebench_src/ 下任何文件、data/parsebench/ 下任何文件、
   runs/parsebench_inf_*/ 下任何文件。判分逻辑必须与 INF 那一侧完全相同。
2. tools/parsebench_azure_runner.py 里**只允许改 analyze() 这一个函数**，让它走公司网关；
   返回值必须保持为 (analyzeResult 字典或 None, 调用记录)。其余代码不动。
3. 网关的 key/token 只从环境变量读取，不写进源码、日志、落盘 JSON、git 提交。
   调用记录里的响应头已由 redact() 脱敏，不要绕过它。
4. 不写任何版面到 markdown 的转换规则。必须让 Azure 自己输出 markdown
   （prebuilt-layout，outputContentFormat=markdown，api-version 2024-11-30）。
   网关如果不支持 markdown 输出，立刻停下来告诉我。
5. 不要手工改任何分数或报告里的数字；报告只能由 tools/parsebench_report.py 生成。
6. 不要把 runs/ 或 data/ 提交到 git（.gitignore 已排除）。

## 第 0 步：解压交接包并核对
handoff/ 目录下有这些文件（每个都有同名 .sha256）：
  parsebench-data-chart.zip / -layout.zip / -table.zip / -text.zip   500 份文件 + 清单（按维度拆包）
  parsebench-inf-results.zip          INF 的 run 目录（含官方判分产物）——第二批，可能还没到
  parsebench-scorer-src_3295d7f.zip   ParseBench 判分器源码（commit 3295d7f）
- 先逐个核对 sha256，不一致就停下报告。
- 在仓库根目录直接解压（zip 内已带完整相对路径，解压目标就是仓库根目录）：
  4 个 data 包、scorer 包；inf-results 包如果已到也一起解压。解压后应有：
    data/parsebench/manifest.csv（500 行，不含表头）
    data/parsebench/subset/{chart,table,text_content,text_formatting,layout}.jsonl
    data/parsebench/subset/docs/{chart,layout,table,text}/...
    runs/parsebench_inf_<时间戳>/parsebench_per_file.csv   （第二批到了才有）
    tools/vendor/parsebench_src/pyproject.toml
- 按 manifest.csv 核对 500 份文件：data/parsebench/subset/<pdf 列> 的 sha256 前 16 位
  必须等于 sha256_16 列。全部一致才继续。

## 第 1 步：环境（Python 3.12 或更高，与主 venv 分开）
parse-bench 要求 Python >= 3.12。
  python3.12 -m venv tools/vendor/.venv-parsebench
  tools/vendor/.venv-parsebench/bin/pip install -e tools/vendor/parsebench_src azure-ai-documentintelligence pdf2image requests
（Windows 上可执行文件在 tools\vendor\.venv-parsebench\Scripts\，下文命令相应替换。）
验证：tools/vendor/.venv-parsebench/bin/parse-bench version 应输出 1.0.4。
不需要 poppler，也不需要 INF 的 key。

## 第 2 步：改 analyze() 走公司网关
- 打开 tools/parsebench_azure_runner.py，读文件头说明。analyze(path) 的默认实现是 Azure 官方 REST
  （POST :analyze -> 202 + Operation-Location -> 轮询）。
- 如果之前为 olmOCR-Bench 写过公司网关适配器（例如 tools/azure_gw_runner.py），复用它的调用方式。
- 要求：整份文件原样发送（不加 pages 参数、不转图片）；PDF 用 application/pdf，
  JPG/PNG 用对应的图片 content-type；返回 REST 响应里 "analyzeResult" 那一层的完整字典，
  **必须包含 content、pages、tables、paragraphs、figures 等全部字段**，不能只返回 content。
  如果网关只返回 content 或者只返回 markdown，立刻停下来告诉我——
  Visual Grounding 维度需要 paragraphs/tables/figures 上的 boundingRegions。
- 先 dry-run：tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --dry-run
  应显示 500 份（chart=100 layout=120 table=130 text=150）。

## 第 3 步：试跑 4 份
tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --limit 1
- 打开 runs/parsebench_azure_<ts>/raw/ 下一个 JSON，确认：ok=true；analyze_result.content 是 markdown；
  analyze_result 里有 pages、paragraphs（带 boundingRegions）；layout 那份 JPG 也成功。
- 打开 runs/parsebench_azure_<ts>/parsebench/azure_di_layout/ 下对应的 .raw.json，
  确认 raw_output 里有 content、pages、paragraphs 等键。
- 试跑的 run 目录删掉，不要和正式运行混用。

## 第 4 步：全量运行
tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --concurrency 4
- 跑完看 run_summary.json 的 n_files_ok 和 failed_files。
- 失败如果是限流 / 超时，用 --resume runs/parsebench_azure_<ts> --concurrency 2 重跑失败项；
  如果是网关或 Azure 拒绝这类文件（大小、格式、页数），原样记录，不要改文件。
- 把失败原因按 status 和 error 分类计数，写进最后的汇报。

## 第 5 步：打分（现成脚本，不改）
tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/parsebench_azure_<ts> --pipeline azure_di_layout
确认输出了 runs/parsebench_azure_<ts>/parsebench_summary.json 和 parsebench_per_file.csv，
五个维度都有 n。

## 第 6 步：配对比较（需要第二批 INF 结果包）
如果 handoff/parsebench-inf-results.zip 还不存在，到这里先停，把第 0–5 步的结果汇报给我；
包到了（git pull 后出现）再核对 sha256、在仓库根目录解压，继续往下。
python tools/parsebench_compare.py runs/parsebench_inf_<INF 时间戳>/parsebench_per_file.csv runs/parsebench_azure_<ts>/parsebench_per_file.csv --name-a Infinity-Parser2 --name-b "Azure DI" --out runs/parsebench_azure_<ts>/parsebench_compare.json
（这个脚本只用标准库，主 venv 或 parse-bench venv 都能跑。）

## 第 7 步：生成报告
python tools/parsebench_report.py runs/parsebench_inf_<INF 时间戳> runs/parsebench_azure_<ts> --out docs/working/parsebench-results.md
打开生成的 docs/working/parsebench-results.md，检查：
- 第 1 节两列都有 run_id、文件数；
- 第 2 节两张表（主口径 / 参照口径）五个维度都有数；
- 第 5 节参照数字表里有官方 leaderboard 的三行。

## 第 8 步：带回的东西
把下面这些打成 parsebench-azure-results.zip（不含 key，不含网关 URL 以外的任何凭证）：
  runs/parsebench_azure_<ts>/run_meta.json、run_summary.json、parsebench_summary.json、
  parsebench_per_file.csv、parsebench_compare.json、parsebench/_normalize_log.json
  docs/working/parsebench-results.md
不要带 raw/ 目录（体积大，且含网关响应头）；如果我需要再单独要。

## 第 9 步：汇报（直接贴给我，不要写结论性判断）
1. sha256 核对是否全部通过
2. 公司网关的调用方式：URL 形态（不含 key）、同步还是异步、是否确认 outputContentFormat=markdown、
   返回的 analyzeResult 是否完整（有无 paragraphs/tables/figures 的 boundingRegions）
3. 成功文件数 / 500，失败原因分类计数
4. parsebench_compare.py 的完整终端输出
5. docs/working/parsebench-results.md 的第 2 节原文
规则：不合成总分；p ≥ 0.05 或区间跨 0 一律写「未观察到显著差异」，不写「持平」；
不要写「推荐 / 不推荐」。
```

## 结果回来后要看的

- **analyzeResult 是否完整**：网关若只回 content，Visual Grounding 这一维 Azure 会被系统性低估，不能比
- **失败文件**：olmOCR-Bench 那一轮 Azure 只成功 41/120，这次要看失败是否集中在某个维度（如 layout 的图片输入）
- **主口径 vs 参照口径**：两者差距大，说明差异主要来自调用失败而非解析质量，报告里要分开写
