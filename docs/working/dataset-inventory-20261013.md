# ocr-benchmark-dataset 结构清单（转录）

来源：公司电脑 `inventory-for-photo.md` 的 10 张照片，2026-10-13 转录。只含结构与计数。
所有表的校验和已逐一核对一致。注意：清单由 Copilot 按 prompt 自行生成，
格式与 `tools/dataset_inventory.py` 的输出不同，计数无法在本地复核。

## 布局

| 内容 | 位置 | 数量 |
|---|---|---|
| 金融 GT | `data/assertions/*.yaml` | 53 文件 / 1,229 断言 |
| 金融输入 | `data/corpus/<family>/<document-id>.pdf` | 53 份完整 PDF，7 族 |
| 金融选页 | `data/corpus/` 下 3 个 csv（含 `run_manifest.csv`、`pages.csv`） | 210 页 |
| olmOCR GT | `data/olmocr_bench/bench_data/<subset>.jsonl` | 7 文件 / 604 测试 |
| olmOCR 输入 | `data/olmocr_bench/bench_data/pdfs/<subset>/<document-id>.pdf` | 120 |
| ParseBench GT | `data/parsebench/subset/<dimension>.jsonl` | 5 文件 / 45,931 规则 |
| ParseBench 输入 | `data/parsebench/subset/docs/{chart,layout,table,text}/` | 500（pdf 482、jpg 10、png 8） |
| 扰动输入 | `data/perturbed/<variant>/<source-page>_<variant>.<ext>` | 210 = 42 × 5 |
| 扰动映射 | `data/perturbed/` 下 2 个 csv | 210 行 |
| `gt/` | 1 个索引 csv | |
| `metadata/` | `checksums.csv`（962 条）、`dataset.json`、`finance_gt_provenance.csv`（53）、ParseBench LICENSE 与来源 README | |

LFS 跟踪 `.pdf .png .jpg`。

## GT 字段

- **金融断言**：`id type severity page eval_on rule target status`，另有 `context`(638) `forbid`(562)
  `n`(673) `label`/`max_gap`(76) `original_status`(137) `original_target`(2)。无 `note`。
  - type：amount 562 / amount_label 76 / page_integrity 480 / unit_currency 111
  - status：auto 480 / auto_textlayer 612 / confirmed 137；original_status：auto_textlayer 61 / draft 76
  - eval_on 全为 md，severity 全为 critical
- **olmOCR**：上游原格式，21 个键（pdf url page id type max_diffs checked …），
  text 类 222 / table 187 / math 105 / order 90
- **ParseBench**：每行一条规则，8 个键 `pdf category id type rule page tags expected_markdown`（rule 为 str）
- **扰动映射**：`variant path doc_id page family window width height pixels bytes source_pdf sha256 seed`

## 一致性（全部 0 异常）

登记输入与实际文件 53/120/500/210 全对上；GT 引用 1,229/604/45,931/210 全找到；
`checksums.csv` 962 条 sha256 全一致；扰动图按 `doc_id + page` 210/210 映射回原始页。

## 现有评测资产（在公司电脑的 doc-parser-eval 副本里）

| 集合 | 判分脚本 | 上游 |
|---|---|---|
| 金融 | `tools/check.py` | 自写 |
| olmOCR | `tools/score_olmocr.py` | `olmocr.bench.tests`（本仓库 vendor 于 `tools/vendor/olmocr`，钉 `ab294c6a`） |
| ParseBench | `tools/parsebench_score.py` | ParseBench 包版本 1.0.4；本仓库钉 `3295d7f` |
| 扰动 | `tools/check.py`（复用金融断言） | — |

四家 OCR 原始输出：均有 markdown 与 JSON；**Mistral 无 bbox、无置信度**，其余三家都有。

选页：规则脚本 `tools/select_pages.py`，记录在 `data/corpus/pages.csv`（score、reason、digit_density、
table_rows 等）与 `pages_meta.json`。**没有任何模型判难易的字段。**

## 运行环境

Python 3.12.7，Windows；Python 进程访问 github.com / huggingface.co / pypi.org **均不通**；
playwright 未装（chromium 在缓存中，不在 PATH）。
