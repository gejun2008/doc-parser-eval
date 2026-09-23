# Azure DI 基线：在公司电脑上运行

**为什么必须有这一项**：报告要回答「换不换」，不是「这东西好不好」。
Infinity-Parser2 在自建集上的 `page_integrity` 91.0% 单独看没有意义——
Azure DI 在**同样这 210 页**上是多少才是结论的依据。
research-plan.md §5 把它标为必保，CLAUDE.md 也写明「不要在没有基线的情况下报绝对分数」。

本机没有 Azure 凭证，脚手架已就位，**在公司电脑上填凭证即可运行**。

## 一次性准备

```bash
git clone <本项目>            # 或解压交接包
cd inf-eval
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

`.env` 里只需填这两项（Infinity-Parser2 的两项在这台机器上用不到）：

```
AZURE_DI_ENDPOINT=https://<资源名>.cognitiveservices.azure.com
AZURE_DI_KEY=<key>
```

凭证只从环境变量读，不进源码、不进日志、不进提交历史。

## 取回语料（147 MB，不随包传输）

语料全部是公开披露文件，按清单重新下载即可，`manifest.csv` 里有每份的
`source_url` 与 `sha256_16`：

```bash
python tools/fetch_corpus.py --per-family 4      # 按同样的族与时间窗口下载
python tools/select_pages.py                     # 确定性选页，必得同样的 210 页
```

选页规则无随机性（`docs/corpus-method.md`），同一批 PDF 必然选出同一批页。
若 `sha256_16` 对不上，说明源站文件有更新，**必须记下来**——
两台机器跑的不是同一份文档，结果不可比。

## 预检（不消耗配额）

```bash
python tools/azure_di_runner.py --dry-run
```

应输出：210 页、`prebuilt-layout`、api-version `2024-11-30`、预估成本 **$2.10**。

## 运行

```bash
set -a && source .env && set +a
python tools/azure_di_runner.py --concurrency 4
python tools/check.py runs/azure_di_layout_<时间戳>
```

断点续跑：`--resume runs/azure_di_layout_<时间戳>`，已成功的页会跳过。

## 关键设计：转换不由我们做

research-plan.md §5 的同口径陷阱：Azure DI 原生输出自有 JSON，
**如果由我们写转换器把它变成可比格式，转换规则就成了影响对手分数的变量，
等于栽赃对手**，内部评审一眼能看出来。

规避办法：调用时带 `outputContentFormat=markdown`，由微软自己决定怎么把版面
转成 markdown，我们直接取 `analyzeResult.content`。
落盘记录里有 `"conversion_by_us": false` 作为证据。

## 仍然存在的不对称（报告必须声明，不要粉饰）

| # | 不对称 | 对谁有利 |
|---|---|---|
| 1 | ~~Azure 按整份文档分析，可能利用全文上下文~~ **已撤回（2026-09-23）**：公司网关实际传给 Azure 的是抽出的单页 PDF，两边都无跨页上下文。仍存在的差异：Azure 收到保留文本层的 PDF，Infinity 收到 300 DPI 渲染图；若 Azure 利用内嵌文本层，而 GT 又取自文本层 | 可能 **Azure 有利** |
| 2 | 两边 markdown 风格由各自厂商决定，表格标记与标题层级不同。我们的断言判「文字/金额在不在输出里」，对风格不敏感，但 `formatting` 类断言不可跨系统比较 | 中性 |
| 3 | Azure 是异步 API，耗时含轮询等待，与同步调用不完全可比 | 延迟不可比 |
| 4 | Azure 返回 span 级 confidence，Infinity-Parser2 没有（t0-findings.md §7）。置信度只能单边报 | 不可比 |
| 5 | 选页刻意偏向财务报表页（docs/corpus-method.md），两边跑同一批页 | 中性，但绝对分数天然偏低 |

第 1 条对 Azure 有利，**要主动写在报告里**。评测的独立性靠的就是把对自己结论
不利的因素也摆出来。

## 跑完之后带回什么

只要这两样，几 MB：

```
runs/azure_di_layout_<时间戳>/raw/*.json      每页原始响应
runs/azure_di_layout_<时间戳>/*.json          run_meta / run_summary / results_summary
runs/azure_di_layout_<时间戳>/results.csv     逐条判定
```

语料 PDF 不用带回，两边按 manifest 各自下载。

## 成本与时间

| 项 | 值 |
|---|---|
| 单价 | $10 / 1000 页，无阶梯折扣 |
| 210 页 | **约 $2.10** |
| 并发 | 默认 4，Azure DI 的配额按资源层级不同，S0 通常够用 |
| 预计耗时 | 取决于配额，异步轮询，估 15–40 分钟 |
