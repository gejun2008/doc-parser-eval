# inf-eval

对 INF TECH（无限光年）**Infinity-Parser2** 文档解析 API 的独立技术评测。
判断能否在 HSBC 金融文档场景下替代现状方案（Azure Document Intelligence）。

**报告的说服力不来自分数高低，来自评测过程的独立性可被验证。**
每个数字都要能追溯到：谁产生的、用什么数据、什么口径、什么时候跑的、模型版本号是什么。

## 从哪读起

| 你要做什么 | 读这个 |
|---|---|
| 了解项目范围与设计 | `docs/research-plan.md`（权威范围文档） |
| 看目前测出了什么 | `docs/interim-brief.md`（中期简报） |
| 在公司电脑跑 Azure DI 基线 | `docs/azure-di-baseline.md` |
| 写报告 | `docs/report-outline.md`（逐节对照数据文件） |
| 向厂商提问 | `docs/vendor-questions.md` |
| 改代码前 | `CLAUDE.md`（工程约定与硬约束） |
| 用 AI 助手接手本项目 | `docs/ai-assistant-prompt.md`（起始 prompt，含口径纪律） |
| 无 git 环境下同步新版仓库 | `docs/sync-prompt.md`（让 AI 助手比对新旧目录、判断要重跑什么） |

## 当前状态（2026-09-21）

已完成并有数字：T0 端点探针、第二层 olmOCR-Bench（120 页）、
第三层自建金融场景集首轮（210 页）、T2 扰动组（42 页 × 5 种）、
T8 重复一致性（210 页 × 3 次）。约 900 次调用，原始响应全量落盘。

**三件事阻塞报告成文**：

1. **Azure DI 基线未跑**——没有基线，绝对分数按约定不能报（在公司电脑跑，约 $3.30）
2. **136 条人工核对未做**——`critical error rate` 主指标出不来
3. **厂商六条必答未回**——版本标注、计费口径、置信度、生产 SLA

已声明的缺口：贸易融资单证未覆盖（找不到合规公开源，排除过程见 `corpus-method.md`）。

## 环境

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
# 判定与扰动组另需：
uv pip install --python .venv/bin/python -r requirements-scoring.txt
.venv/bin/python -m playwright install chromium     # math 类断言要 KaTeX 渲染
cp .env.example .env                                 # 填凭证，.env 不入库
```

## 工具

| 脚本 | 作用 |
|---|---|
| `probe.py` | T0 端点探针 |
| `conn_test.py` | 连通性分层诊断（可直接发给厂商复现） |
| `fetch_olmocr_bench.py` | 第二层基准分层抽样下载（固定 seed） |
| `fetch_corpus.py` | 第三层语料下载（巨潮 / HKEX 公开接口） |
| `select_pages.py` | 确定性选页 |
| `make_assertions.py` | 断言生成（分 auto / auto_textlayer / draft 三层） |
| `review_assertions.py` | 本地 HTML 人工审核页 |
| `apply_review.py` | 审核结果合并回 YAML |
| `perturb.py` | 扰动组生成（图片输入，避开 300 DPI 重栅格化） |
| `runner.py` | 评测 runner（裸 HTTP、全量落盘、断点续跑） |
| `check.py` | 断言判定器 |
| `score_olmocr.py` | olmOCR-Bench 判定（调官方评分代码，不重写） |
| `consistency.py` | 重复一致性三层分析 |
| `azure_di_runner.py` | Azure DI 基线 runner |
| `compare_systems.py` | 两系统配对对照（McNemar） |
| `make_handoff.py` | 交接包打包（扫描凭证后才允许出包） |

## 典型流程

```bash
set -a && source .env && set +a
.venv/bin/python tools/runner.py --manifest data/corpus/run_manifest.csv --pdf-root . --task doc2md
.venv/bin/python tools/check.py runs/<run_id>
.venv/bin/python tools/compare_systems.py runs/<inf_run>/results.csv runs/<azure_run>/results.csv
```

## 不入库的目录

`data/corpus/`、`data/olmocr_bench/`、`data/perturbed/` 的图片与 PDF、
`runs/`、`probe_out/`、`review/`、`.venv/`、`.env`。

例外：`data/perturbed/*.csv` 强制入库——扰动组判定要用它把扰动图映射回原页
（`check.py --alias`），没有它就得重跑 perturb.py 才能复算。

语料按 `manifest.csv` 里的 `source_url` 可重新下载，也可从
[Release v0.1-interim](https://github.com/gejun2008/doc-parser-eval/releases/tag/v0.1-interim)
下载 `inf-eval-corpus.zip`（174.6 MB）。
评测证据在 `dist/evidence_20260923.zip`（约 2 MB，含全部原始响应与判定结果）。
**断言 `data/assertions/*.yaml` 入库**——那是评测的 GT。

## 三条最容易违反的纪律

1. **不合成加权总分。** 按文档族、按类型分层出数；样本不足就写「样本不足，不下结论」
2. **异常值必须查到底再报。** 本项目出现过一次判定器 bug 让通过率假性显示 9.9%
   （真实 97.9%）。错误不会只朝一个方向
3. **对自己结论不利的因素要主动写出来。** 例如 Azure 可利用整份文档上下文这一点
   对 Azure 有利——评测的独立性靠的就是这个
