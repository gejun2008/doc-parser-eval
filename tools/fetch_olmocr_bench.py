#!/usr/bin/env python3
"""
olmOCR-Bench 子集下载（research-plan.md §3.2 第二层 · 中立公开基准）

数据集: allenai/olmOCR-bench (ODC-BY), 1,403 个单页 PDF + 7,019 条 pass/fail 单元测试。
厂商在这个 benchmark 上自报 87.6%，**因此它是泄漏风险最高的一层**，
只能当准入门槛，不能当结论依据。见 research-plan.md §2.1、§2.2。

抽样口径（报告附录要能复现）:
  - 按七个子集分层，样本量按金融文档相关性分配，不按原始比例
  - random.Random(SEED).sample，SEED 固定，任何人重跑得到同一批 PDF
  - 以 PDF 为抽样单位（一个 PDF 一页 = 一次 API 调用），该 PDF 的全部测试一并纳入

用法:
  python tools/fetch_olmocr_bench.py            # 按默认配额下载
  python tools/fetch_olmocr_bench.py --all      # 全量 1403 个 PDF
  python tools/fetch_olmocr_bench.py --seed 7   # 换一批（换了要在报告里说明）
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = "https://huggingface.co/datasets/allenai/olmOCR-bench/resolve/main"
ROOT = Path("data/olmocr_bench")
BENCH = ROOT / "bench_data"
PDF_DIR = BENCH / "pdfs"
SEED = 20260918

# 子集 -> 抽多少个 PDF。金融文档场景下表格、跨栏阅读顺序、页眉页脚、
# 小字密排、老扫描件最相关；数学公式相关性最低，只留少量占位。
QUOTA = {
    "table_tests": 40,      # 跨页表格是金融文档第一痛点
    "multi_column": 20,     # 阅读顺序
    "headers_footers": 20,  # 见下面 §注意
    "long_tiny_text": 15,   # 附注小字密排，最接近财报附注页
    "old_scans": 15,        # 影印件，对应扰动组
    "arxiv_math": 5,        # 相关性低，占位
    "old_scans_math": 5,
}

# 注意（写进报告，不要漏）:
# headers_footers 子集全部是 absent 类断言——要求页眉页脚**不出现**在输出里。
# 而 sdk-findings.md §5 已核实 Infinity-Parser2 的 md 输出默认就丢弃
# header/footer/page_footnote。也就是说这一子集它天然高分，且与能力无关。
# 该子集的分数必须单独列出并标注此口径，不能混进总分。


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_tests():
    """读 bench_data/*.jsonl。缺文件就提示先下载。"""
    files = sorted(BENCH.glob("*.jsonl"))
    if not files:
        sys.exit(f"{BENCH} 下没有 jsonl，先下载 bench_data")
    by_subset = defaultdict(lambda: defaultdict(list))
    for f in files:
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            by_subset[f.stem][r["pdf"]].append(r)
    return by_subset


def pick(by_subset, quota, seed, take_all=False):
    """分层抽样。返回 {subset: [pdf, ...]}。"""
    out = {}
    for subset, pdfs in sorted(by_subset.items()):
        names = sorted(pdfs)
        n = len(names) if take_all else min(quota.get(subset, 0), len(names))
        out[subset] = sorted(random.Random(f"{seed}:{subset}").sample(names, n))
    return out


def download(pdf_rel):
    """下载单个 PDF。已存在且非空则跳过（断点续跑）。"""
    dst = PDF_DIR / pdf_rel
    if dst.exists() and dst.stat().st_size > 0:
        data = dst.read_bytes()
        return pdf_rel, len(data), hashlib.sha256(data).hexdigest()[:16], "cached"
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(f"{REPO}/bench_data/pdfs/{pdf_rel}", timeout=120)
    r.raise_for_status()
    dst.write_bytes(r.content)
    return pdf_rel, len(r.content), hashlib.sha256(r.content).hexdigest()[:16], "downloaded"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--all", action="store_true", help="下载全量 1403 个 PDF")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    by_subset = load_tests()
    chosen = pick(by_subset, QUOTA, a.seed, a.all)
    flat = [(s, p) for s, ps in chosen.items() for p in ps]
    print(f"抽样 seed={a.seed}  子集 {len(chosen)} 个  PDF {len(flat)} 个")

    results = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for rel, size, sha, how in ex.map(lambda sp: download(sp[1]), flat):
            results[rel] = (size, sha, how)
    cached = sum(1 for v in results.values() if v[2] == "cached")
    print(f"下载 {len(results) - cached} 个，跳过已存在 {cached} 个")

    # manifest：报告附录靠它复现抽样
    man = ROOT / "manifest.csv"
    types_total = Counter()
    with man.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["subset", "pdf", "sha256_16", "bytes", "n_tests",
                    "test_types", "source_url"])
        for subset, pdfs in sorted(chosen.items()):
            for rel in pdfs:
                tests = by_subset[subset][rel]
                tc = Counter(t["type"] for t in tests)
                types_total.update(tc)
                size, sha, _ = results[rel]
                w.writerow([subset, rel, sha, size, len(tests),
                            ";".join(f"{k}={v}" for k, v in sorted(tc.items())),
                            tests[0].get("url", "")])
    meta = {
        "fetched_utc": now(), "seed": a.seed, "take_all": a.all,
        "dataset": "allenai/olmOCR-bench", "license": "ODC-BY",
        "quota": QUOTA if not a.all else "all",
        "n_pdfs": len(flat), "n_tests": sum(types_total.values()),
        "test_types": dict(types_total),
        "per_subset": {s: len(p) for s, p in chosen.items()},
    }
    (ROOT / "subset_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'子集':18} {'pdf':>4} {'tests':>6}")
    for s, ps in sorted(chosen.items()):
        nt = sum(len(by_subset[s][p]) for p in ps)
        print(f"{s:18} {len(ps):4} {nt:6}")
    print(f"\n合计 {len(flat)} 个 PDF / {sum(types_total.values())} 条测试 "
          f"{dict(types_total)}")
    print(f"-> {man}\n-> {ROOT / 'subset_meta.json'}")


if __name__ == "__main__":
    main()
