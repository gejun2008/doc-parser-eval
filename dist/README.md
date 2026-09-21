# dist — 评测证据包

`evidence_<日期>.zip`（约 2.6 MB）含：

| 内容 | 说明 |
|---|---|
| `runs/` | 5 次评测的逐页原始响应、逐条判定、汇总。**不可再生**，是报告附录的复现依据 |
| `probe_out/` | T0 端点探针证据 |
| `corpus_manifest/` | 语料与选页清单（含 source_url、sha256） |
| `repo.bundle` | 仓库快照，作为 clone 之外的备用 |
| `HANDOFF.md` | 在公司电脑上的操作步骤 |

**不含**：`.env`、`.venv`、语料 PDF。打包前扫描过凭证形态。

## 语料 PDF 不在这里

约 166 MB（olmOCR-Bench 120 份 + 自建集 53 份），不进 git——
PDF 无法增量存储，会永久留在历史里。两种取法：

1. **GitHub Release 附件**下载 `inf-eval-corpus.zip`
2. 网络可达时按清单重新下载，**seed 固定必得同一批**：
   ```bash
   python tools/fetch_olmocr_bench.py
   python tools/fetch_corpus.py --per-family 4
   python tools/select_pages.py
   ```
   下完核对 `manifest.csv` 里的 sha256，对不上说明源站文件有更新，
   两边跑的不是同一份文档，结果不可比。

重新打包：`python tools/make_handoff.py`（不带数据）或 `--with-data`。
