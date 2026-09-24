#!/usr/bin/env python3
"""
交接包打包 (迁移到公司电脑)

评测在本机跑，Azure DI 基线与成文在公司电脑跑。本脚本打出一个自包含的包。

**绝不打包**：`.env`、`.venv/`、任何含 key 的文件。打包前会扫描并拒绝。

默认包含（约 12 MB）：
  git bundle        全部代码、文档、断言 YAML、完整提交历史
  runs/             逐页原始响应、逐条判定、汇总（报告附录的复现依据）
  probe_out/        T0 端点探针证据
  data/corpus/*.csv 语料与选页清单（含 source_url、sha256，可据此重新下载）
  HANDOFF.md        在公司电脑上怎么用

`--with-data` 额外包含（约 190 MB）：
  data/olmocr_bench/  第二层基准的 120 个 PDF 与官方测试定义
  data/corpus/**.pdf  第三层自建集的 53 份公开披露文档

**公司内网若无法访问 HuggingFace 与巨潮/HKEX，必须用 --with-data**，
否则那边重新下载不到语料。若网络可达，不带数据更轻，两边按 manifest 各自下载，
sha256 对得上即为同一份文档。

用法:
  python tools/make_handoff.py
  python tools/make_handoff.py --with-data
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 打包前扫描这些形态，命中就中止
SECRET_PAT = re.compile(
    r"(?:api[_-]?key|secret|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9+/=_-]{16,}"
    r"|[A-Za-z0-9+/]{40}=",
    re.I)
NEVER = {".env", ".venv", "__pycache__", ".DS_Store"}

HANDOFF_MD = """# 交接包 · Infinity-Parser2 评测

生成于 {ts}　提交 {commit}

## 这个包里有什么

| 内容 | 说明 |
|---|---|
{bundle_row}| `runs/` | 每次评测的逐页原始响应与逐条判定，报告附录的复现依据 |
| `probe_out/` | T0 端点探针证据 |
| `corpus_manifest/` | 语料与选页清单（含 source_url 与 sha256） |
| `data/` | {data_note} |

**不含** `.env` 与任何凭证。公司电脑上需自行填 Azure 凭证。

{restore_section}
## 二、建环境

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

判定与扰动组还需要额外依赖（olmOCR 官方评分模块已 vendor 在 `tools/vendor/olmocr`）：

```bash
uv pip install --python .venv/bin/python -r requirements-scoring.txt
.venv/bin/python -m playwright install chromium     # math 类断言要 KaTeX 渲染
```

若公司网络装不了 playwright，判定时加 `--skip-math`，math 类记为未评。

## 三、放回评测产物

```bash
cp -R runs probe_out inf-eval/
cp corpus_manifest/*.csv corpus_manifest/*.json inf-eval/data/corpus/
{data_restore}```

## 四、填 Azure 凭证

```bash
cd inf-eval && cp .env.example .env
```

只填这两项：

```
AZURE_DI_ENDPOINT=https://<资源名>.cognitiveservices.azure.com
AZURE_DI_KEY=<key>
```

凭证只进 `.env`，`.env` 已在 `.gitignore` 中。**不要填进 `.env.example`**。

## 五、预检（不花钱）

```bash
.venv/bin/python tools/azure_di_runner.py --dry-run \\
    --pages-csv data/corpus/pages.csv
.venv/bin/python tools/azure_di_runner.py --dry-run \\
    --pages-csv data/olmocr_bench/manifest.csv \\
    --pdf-root data/olmocr_bench/bench_data/pdfs
```

## 六、跑基线

```bash
set -a && source .env && set +a

# 第三层 自建金融场景集 210 页，约 $2.10
.venv/bin/python tools/azure_di_runner.py --concurrency 4 \\
    --pages-csv data/corpus/pages.csv
.venv/bin/python tools/check.py runs/azure_di_layout_<时间戳>

# 第二层 olmOCR-Bench 120 页，约 $1.20
.venv/bin/python tools/azure_di_runner.py --concurrency 4 \\
    --pages-csv data/olmocr_bench/manifest.csv \\
    --pdf-root data/olmocr_bench/bench_data/pdfs
.venv/bin/python tools/score_olmocr.py runs/azure_di_layout_<时间戳>
```

中断了就加 `--resume runs/azure_di_layout_<时间戳>`，已成功的页会跳过。

## 七、比对

Infinity-Parser2 的对应结果已在包里，两边跑的是同一批页、同一套断言、同一个判定器：

| 层 | Infinity-Parser2 run_id |
|---|---|
| 第二层 olmOCR-Bench | `inf-mllm_doc2md_20260918T065831Z` |
| 第三层 自建集 | `inf-mllm_doc2md_20260921T013924Z` |

```bash
# 第三层
.venv/bin/python tools/compare_systems.py \\
    runs/inf-mllm_doc2md_20260921T013924Z/results.csv \\
    runs/azure_di_layout_<时间戳>/results.csv \\
    --name-a Infinity --name-b AzureDI

# 第二层
.venv/bin/python tools/compare_systems.py \\
    runs/inf-mllm_doc2md_20260918T065831Z/olmocr_results.csv \\
    runs/azure_di_layout_<时间戳>/olmocr_results.csv \\
    --name-a Infinity --name-b AzureDI
```

### 读这张表的三条纪律

两边判的是**同一批断言**，属配对数据，所以用 McNemar 检验而不是比两个置信区间。
表里的 `b/c` 是「只有 A 对」与「只有 B 对」的条数，差异是否显著看它们。

1. **「全部」那一行不是加权总分**，只是同口径汇总。结论按分层写
2. **p ≥ 0.05 写「未观察到显著差异」**，不得写成「持平」「相当」「不相上下」
3. **n < 30 的分层写「样本不足，不下结论」**，不要为了好看合并分层

### 写进报告时必须声明的不对称

- Azure DI 按整份文档分析，即使指定单页也可能利用全文上下文，
  Infinity-Parser2 是逐页独立调用。**这一条对 Azure 有利，要主动写明**
- 两边 markdown 风格由各自厂商决定，`formatting` 类断言不可跨系统比较
- Azure 返回 span 级 confidence，Infinity-Parser2 没有，置信度只能单边报
- 选页刻意偏向财务报表页，两边同批页，但绝对分数天然低于通用文档

完整清单见 `docs/working/azure-di-baseline.md`。

## 注意

- Azure DI 按整份文档分析，即使指定 `pages=N` 也可能用到全文上下文，
  **这一点对 Azure 有利，报告里要主动写明**（见 `docs/working/azure-di-baseline.md`）
- 转换由微软做（`outputContentFormat=markdown`），我们不碰转换规则，
  落盘记录里 `"conversion_by_us": false` 是证据
- 若语料是在公司电脑重新下载的，**核对 `manifest.csv` 里的 sha256**。
  对不上说明源站文件有更新，两边跑的不是同一份文档，结果不可比
"""


def _in_url(text, pos):
    """命中点是否落在一个 URL 的查询串里。

    olmOCR-Bench 的公开数据集在 `url` 字段里带源文档的预签名链接
    （形如 https://watermark.silverchair.com/x.pdf?token=AQECAHi...），
    那是数据集自带的公开链接，不是我们的凭证。第一次打包被它拦下过。
    """
    head = text[max(0, pos - 200):pos]
    i = max(head.rfind("http://"), head.rfind("https://"))
    if i < 0:
        return False
    return not re.search(r"[\s\"']", head[i:])


def scan_secrets(paths):
    bad = []
    for p in paths:
        if not p.is_file() or p.suffix in (".pdf", ".png", ".jpg", ".bundle"):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in SECRET_PAT.finditer(t):
            frag = m.group(0)
            if "<" in frag or frag.lower().startswith(("api_key=x", "key=<")):
                continue
            if _in_url(t, m.start()):
                continue
            bad.append((p, frag[:24] + "..."))
            break
    return bad


def copytree(src, dst, ignore_pdf=False):
    src, dst = Path(src), Path(dst)
    if not src.exists():
        return 0
    n = 0
    for p in src.rglob("*"):
        if any(part in NEVER for part in p.parts):
            continue
        if ignore_pdf and p.suffix.lower() in (".pdf", ".png", ".jpg"):
            continue
        if p.is_file():
            q = dst / p.relative_to(src)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, q)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-data", action="store_true",
                    help="包含语料 PDF（约 190MB）。公司内网访问不了源站时必须带")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-bundle", action="store_true",
                    help="不放 repo.bundle。打进仓库 dist/ 的证据包必须用它——"
                         "仓库历史里已有上一版证据包，bundle 会把它包进去，"
                         "再提交回仓库就会逐版递归膨胀")
    a = ap.parse_args()

    if Path(".env").exists() and not Path(".git").exists():
        sys.exit("请在仓库根目录运行")

    ts = datetime.now(timezone.utc)
    out = Path(a.out or f"../handoff_{ts:%Y%m%d}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("！工作区有未提交改动，bundle 里不会包含它们：")
        for line in dirty.splitlines()[:8]:
            print("   ", line)

    if not a.no_bundle:
        subprocess.run(["git", "bundle", "create", str(out / "repo.bundle"), "--all"],
                       check=True, capture_output=True)

    n_runs = copytree("runs", out / "runs")
    n_probe = copytree("probe_out", out / "probe_out")
    cm = out / "corpus_manifest"
    cm.mkdir()
    for f in Path("data/corpus").glob("*.csv"):
        shutil.copy2(f, cm / f.name)
    for f in Path("data/corpus").glob("*.json"):
        shutil.copy2(f, cm / f.name)
    # 扰动组清单：判定时靠它把扰动图映射回原页（check.py --alias）
    for f in Path("data/perturbed").glob("*.csv"):
        shutil.copy2(f, cm / f"perturbed_{f.name}")

    n_data = 0
    if a.with_data:
        n_data += copytree("data/olmocr_bench", out / "data/olmocr_bench")
        n_data += copytree("data/corpus", out / "data/corpus")

    # 打包前扫描凭证
    bad = scan_secrets(list(out.rglob("*")))
    if bad:
        print("！包里疑似含凭证，已中止：")
        for p, frag in bad[:5]:
            print(f"   {p}: {frag}")
        shutil.rmtree(out)
        sys.exit(1)
    for stray in out.rglob(".env*"):
        stray.unlink()

    (out / "HANDOFF.md").write_text(HANDOFF_MD.format(
        ts=ts.isoformat(timespec="seconds"), commit=commit or "(未知)",
        bundle_row=("" if a.no_bundle else
                    "| `repo.bundle` | 完整 git 仓库（代码、文档、断言 YAML、提交历史） |\n"),
        restore_section=(
            "## 一、取得仓库\n\n"
            "本包不含仓库快照。代码与文档从仓库获取：\n\n"
            "```bash\ngit clone https://github.com/gejun2008/doc-parser-eval.git inf-eval\n```\n"
            if a.no_bundle else
            "## 一、恢复仓库\n\n```bash\ngit clone repo.bundle inf-eval\n"
            "cd inf-eval\ngit log --oneline | head        # 应看到完整历史\n```\n"),
        data_note=("语料 PDF（olmOCR-Bench 120 份 + 自建集 53 份）"
                   if a.with_data else "未包含语料 PDF，需在公司电脑按 manifest 重新下载"),
        data_restore=("cp -R data/olmocr_bench inf-eval/data/\n"
                      "cp -R data/corpus inf-eval/data/\n" if a.with_data else
                      "# 未带语料，在公司电脑重新下载：\n"
                      "# .venv/bin/python tools/fetch_olmocr_bench.py\n"
                      "# .venv/bin/python tools/fetch_corpus.py --per-family 4\n"
                      "# .venv/bin/python tools/select_pages.py\n")),
        encoding="utf-8")

    files = [p for p in out.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    manifest = {
        "created_utc": ts.isoformat(timespec="seconds"), "commit": commit,
        "with_data": a.with_data, "n_files": len(files),
        "total_mb": round(total / 1e6, 1),
        "uncommitted_changes": bool(dirty),
        "excludes": [".env", ".venv", "review/（可在公司电脑重新生成）"],
        "sha256": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                   for p in files if p.suffix in (".bundle", ".md")},
    }
    (out / "PACK.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    print(f"\n交接包 -> {out.resolve()}")
    print(f"  repo.bundle     提交 {commit}")
    print(f"  runs/           {n_runs} 个文件")
    print(f"  probe_out/      {n_probe} 个文件")
    print(f"  corpus_manifest/{len(list(cm.iterdir()))} 个文件")
    if a.with_data:
        print(f"  data/           {n_data} 个文件（含语料 PDF）")
    print(f"  合计 {len(files)} 个文件，{total/1e6:.1f} MB")
    print("  已扫描凭证：未发现")
    print(f"\n公司电脑上先读 {out.name}/HANDOFF.md")


if __name__ == "__main__":
    main()
