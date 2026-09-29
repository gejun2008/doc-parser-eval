# Copilot 任务：公司网关跑 Azure DI × olmOCR-Bench，与 INF 配对比较

在公司电脑上把下面「Prompt」一节整段交给 Copilot agent 执行。

背景：`tools/azure_di_runner.py` 按 Azure 官方端点写（`Ocp-Apim-Subscription-Key` + 202 异步轮询），
公司内部网关的调用方式不同，不能直接跑。所以让 Copilot 另写网关适配器，只负责落盘；
打分与配对比较沿用仓库现有脚本，一行不改，保证与 INF 那一侧同一判定口径。

前置：已 `git pull`，并在仓库根目录解压 `handoff/olmocr-inf-results_20260918.zip`
（sha256 `99137f6e1cfe66bbe0e845d3039e4840b425aca694cec586600b3a7de4c4b9b4`）。

## Prompt

```text
你在 inf-eval 仓库根目录工作。目标：用公司内部的 Azure Document Intelligence 网关 API，
跑 olmOCR-Bench 的 120 页抽样子集，用仓库现有的判定器打分，再和 INF（Infinity-Parser2）
已有的结果做逐条配对比较。INF 的结果已经在 runs/inf-mllm_doc2md_20260918T065831Z/，
抽样数据在 data/olmocr_bench/（由 handoff/olmocr-inf-results_20260918.zip 解压而来）。

## 硬性规则（任何一条都不能违反）
1. 不要修改这些文件：tools/score_olmocr.py、tools/compare_systems.py、tools/vendor/ 下的任何文件、
   runs/inf-mllm_doc2md_20260918T065831Z/ 下的任何文件、data/olmocr_bench/ 下的任何文件。
   判定逻辑必须和 INF 那一侧完全相同。
2. 网关的 key/token 只从环境变量读取，不写进源码、日志、落盘的 JSON、git 提交。
   落盘前删掉响应头里所有与认证有关的字段（Authorization、Cookie、Set-Cookie、*key*、*token*）。
3. 不自己写版面到 markdown 的转换器。必须让 Azure 自己输出 markdown
   （Azure DI 的 outputContentFormat=markdown，api-version 2024-11-30，模型 prebuilt-layout），
   取 analyzeResult.content。如果网关不支持 markdown 输出，立刻停下来告诉我，不要自己转换。
4. 不要提交 runs/ 下的任何东西（.gitignore 已排除 runs/）。

## 第 0 步：环境与数据核对
- 安装依赖：pip install -r requirements.txt -r requirements-scoring.txt，
  再执行 python -m playwright install chromium（math 类测试要用它渲染 KaTeX）。
  如果公司网络装不上 playwright，记下来，后面打分时加 --skip-math。
- 核对数据：data/olmocr_bench/manifest.csv 应有 120 行（不含表头）。
  对每一行，计算 data/olmocr_bench/bench_data/pdfs/<pdf 列> 的 sha256，取前 16 位，
  和 sha256_16 列逐一比对，全部一致才继续。有不一致就停下来报告。

## 第 1 步：写网关适配器 tools/azure_gw_runner.py
参考 tools/azure_di_runner.py 的结构（读清单、并发、断点续跑、run_meta/run_summary），
只把 HTTP 调用部分换成公司网关的调用方式。要求：
- 输入清单：data/olmocr_bench/manifest.csv，用 pdf 列；PDF 路径 = data/olmocr_bench/bench_data/pdfs/<pdf>。
  每个 PDF 都是单页，page 固定为 1。
- 输出目录：runs/azure_di_layout_<UTC 时间戳，格式 %Y%m%dT%H%M%SZ>/raw/
- 每页落一个文件，文件名 = slug(pdf) + "_p1.json"，其中
  slug(p) = re.sub(r"[^A-Za-z0-9_.-]", "__", p.removesuffix(".pdf"))
- 每个 JSON 至少包含下面这些字段（与 azure_di_runner.py 的 process() 保持同一 schema）：
  schema="inf-eval/raw/1", run_id, pdf（必须和 manifest 的 pdf 列一字不差，
  例如 "tables/b5c5b8661b5a272e7a175cdb20d49e67ba0d_pg4.pdf"）, page=1, system="azure_di",
  model_id, api_version, request（记录 outputContentFormat 和 conversion_by_us=false）,
  ts_utc（UTC ISO 时间）, latency_s, status（HTTP 状态码；异常记 -1，轮询超时记 -2）,
  op_status, response_headers（已脱敏）, served_model（analyzeResult.modelId）,
  content（analyzeResult.content 原文，不做任何处理）, content_sha256,
  ok（true 当且仅当分析成功且 content 非空）, finish_reason（ok 时写 "stop"，否则写 "error"）,
  error_detail（失败时保存网关返回的错误体，截断到 4000 字符）。
- 失败页也要落盘（ok=false），不能跳过。它们在打分时整页判 fail，并且要单独统计。
- 每页失败后重试 2 次，并记录尝试次数 n_attempts；并发默认 2，可以用参数调。
- 支持 --resume <run_dir>：已经 ok 的页跳过，只重跑失败页。
- 支持 --dry-run：不发请求，只打印将要调用的页数、按 subset 列的分布、网关 URL（不打印 key）。
- 先用 --limit 3 试跑，打开一个落盘 JSON 确认 content 是 markdown、pdf 字段格式正确，再跑全量。

## 第 2 步：全量运行并排查失败
- 全量跑 120 页。跑完统计 ok/失败页数。
- 之前一轮 Azure 在这批页上只成功了 41/120，所以失败原因必须查清：
  把失败页按 status 和 error_detail 分类计数（比如文件大小限制、页数限制、超时、限流、网关拒绝），
  写到 runs/<run_dir>/failure_breakdown.csv。
- 如果失败原因是可以修的（限流、超时），用 --resume 降低并发重跑；
  如果是网关或 Azure 本身拒绝这类文件，就原样记录，不要去改 PDF。
- 确认网关传给 Azure 的就是这份单页 PDF 原文件（不做二次抽页或栅格化），写进汇报。

## 第 3 步：打分（用现成脚本，不改）
python tools/score_olmocr.py runs/azure_di_layout_<ts>
（装不上 playwright 就加 --skip-math，并在最后的汇报里写明 math 类没有评分。）
打分完成后，确认 olmocr_results.csv 覆盖了 120 个 PDF，测试条数和 INF 那边一致（604 条；如果用了 --skip-math 则少掉 math 类）。

## 第 4 步：配对比较，两种口径都跑
口径 A（含调用失败页，失败页判 fail）：
python tools/compare_systems.py runs/inf-mllm_doc2md_20260918T065831Z/olmocr_results.csv runs/azure_di_layout_<ts>/olmocr_results.csv --name-a Infinity-Parser2 --name-b "Azure DI" --out runs/azure_di_layout_<ts>/compare_all

口径 B（只比两边都调用成功的页，这是报告主口径）：
写一个一次性脚本（放在 runs/azure_di_layout_<ts>/ 下，不入库）：从两个 olmocr_results.csv 中
去掉 explanation 以 "page_call_failed" 开头的行所在的 pdf（只要任一边失败，这个 pdf 两边都去掉），
分别写出 inf_both_ok.csv 和 azure_both_ok.csv，然后用同样的 compare_systems.py 命令跑一遍，
--out 设为 runs/azure_di_layout_<ts>/compare_both_ok。
如果用了 --skip-math，两边都要去掉 type=math 的行后再比较。

## 第 5 步：汇报（直接贴给我，不要写结论性判断）
1. 调用成功页数 / 120，失败原因分类计数
2. score_olmocr.py 打印的按子集、按类型表格（Azure 单边）
3. 两种口径的 compare_systems.py 完整输出（每层的 n、差值、b/c、p 值）
4. 是否用了 --skip-math；manifest sha256 是否全部一致
5. 网关的具体调用方式（URL 形态、是同步还是异步、是否确认用了 outputContentFormat=markdown、
   网关收到的是否就是单页 PDF 原文件），不含 key
规则：不合成总分；p ≥ 0.05 一律写「未观察到显著差异」，不写「持平」；
headers_footers 子集要附注「两边对页眉页脚的输出口径不同，这一层不同口径」。
```

## 结果回来后要看的

- 成功页数：若仍只有四十来页，口径 B 各分层都会样本不足，只能写「样本不足，不下结论」
- 失败原因分类：决定是网关问题还是 Azure 对这类文件的真实失败，两者在报告里写法不同
- 网关是否只传单页原文件：对应 `azure-di-baseline.md` 不对称第 1 条，本次在 olmOCR 页上再确认一次
