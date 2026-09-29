#!/usr/bin/env python3
"""
OmniDocBench 金融切片下载（research-plan.md §3.2 第二层 · 中立公开基准）

数据集: opendatalab/OmniDocBench（v1.6 全量 1,651 页），钉在 HF revision REV。
切片口径: page_attribute.data_source == "research_report"
（官方定义「Research reports and financial reports」），全量 132 页，不抽样。

与 olmOCR-Bench 的区别：OmniDocBench 给的是整页 GT（逐块文字、表格 HTML、
阅读顺序），判分是连续指标（编辑距离 / TEDS），不是 pass/fail。
按 CLAUDE.md，这些学术指标只进附录，用于和厂商口径对齐。

输入是数据集自带的 PNG（不是 PDF），runner 走图片路径（与 SDK
encode_image_to_base64 对齐），不经过 300 DPI 重栅格化。

用法:
  python tools/fetch_omnidocbench.py
"""

import csv
import hashlib
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

REV = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"  # HF 2026-06-26，v1.6
REPO = f"https://huggingface.co/datasets/opendatalab/OmniDocBench/resolve/{REV}"
ROOT = Path("data/omnidocbench")
IMG_DIR = ROOT / "images"
SLICE = "research_report"


def get(url, dst):
    if dst.exists() and dst.stat().st_size > 0:
        return dst.read_bytes()
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    dst.write_bytes(r.content)
    return r.content


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(exist_ok=True)
    full = json.loads(get(f"{REPO}/OmniDocBench.json", ROOT / "OmniDocBench.json"))
    get(f"{REPO}/README.md", ROOT / "README.md")

    pages = [p for p in full if p["page_info"]["page_attribute"].get("data_source") == SLICE]
    if not pages:
        sys.exit(f"切片 {SLICE} 为空，检查 revision")

    # 官方评测代码读的是 GT json，切片 GT 单独存一份，评测只看这 132 页
    (ROOT / f"gt_{SLICE}.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8")

    def fetch(p):
        name = p["page_info"]["image_path"]
        data = get(f"{REPO}/images/{name}", IMG_DIR / name)
        return name, data

    with ThreadPoolExecutor(max_workers=8) as ex:
        blobs = dict(ex.map(fetch, pages))

    rows = []
    for p in pages:
        name, attr = p["page_info"]["image_path"], p["page_info"]["page_attribute"]
        cats = Counter(b["category_type"] for b in p["layout_dets"])
        rows.append({
            "subset": attr.get("subset"), "pdf": name, "page": 1,
            "language": attr.get("language"), "layout": attr.get("layout"),
            "special_issue": "|".join(attr.get("special_issue") or []),
            "n_tables": cats.get("table", 0), "n_text_blocks": cats.get("text_block", 0),
            "sha256_16": hashlib.sha256(blobs[name]).hexdigest()[:16],
            "bytes": len(blobs[name]),
        })
    with open(ROOT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    meta = {
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": "opendatalab/OmniDocBench", "revision": REV,
        "slice": f"data_source == {SLICE}", "sampling": "none (全量切片)",
        "n_pages": len(rows),
        "by_subset": dict(Counter(r["subset"] for r in rows)),
        "by_language": dict(Counter(r["language"] for r in rows)),
        "n_tables": sum(r["n_tables"] for r in rows),
    }
    (ROOT / "slice_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
