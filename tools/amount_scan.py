#!/usr/bin/env python3
"""
全量金额扫描：页上每一个金额都查，不抽样。

为什么需要它：`amount` 断言每页只抽 4 个金额（make_assertions.py），
`page_integrity` 锚点又排除了纯数字行。于是「整张数字表被静默丢掉」这种失败，
只有碰巧抽中的金额才会暴露。2026-09-23 在 Infinity 输出里就发现了一页
丢了整张「分季度主要财务指标」表（16 个金额），抽样断言一条都没抓到。

口径：
  - 金额 = 千分位 + 两位小数（A 股口径，如 1,234,567.89）。港股常见的
    无小数写法不在范围内，所以覆盖的主要是 A 股页。这是本工具的已知盲区
  - 期望次数取 PDF 文本层（折行金额先拼接），实际次数取模型输出
  - 比对前去空白；U+2212「−」与全角「－」视同 ASCII「-」——
    减号字形是格式问题，不是数值错误，单独在 docs 里记为下游归一化事项
  - 只报「少了」：输出次数少于文本层次数记为缺失。多出来的不计
    （表格重复表头等会造成合法的多出）

用法:
  python tools/amount_scan.py runs/<A目录> [runs/<B目录>]
  python tools/amount_scan.py runs/<A目录> runs/<B目录> --show-missing
给两个目录时只比双方都成功的页（配对口径，与 compare_systems.py 一致）。
--show-missing 额外列出每页每个系统缺了哪些金额（公开披露数字），用于判断缺失性质。
输出 <每个目录>/amount_scan.csv，并打印一张带校验和的整数表，便于拍照。
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

AMOUNT = re.compile(r"(?<![\d,.])-?\d{1,3}(?:,\d{3})+\.\d{2}(?!\d)")


def slug(pdf_rel):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(pdf_rel).removesuffix(".pdf"))


def norm_out(s):
    s = (s or "").replace("−", "-").replace("－", "-")
    return re.sub(r"\s+", "", s)


def join_wrapped(txt):
    # 与 make_assertions.join_wrapped_numbers 同一思路：表格窄列里金额会折行
    t = re.sub(r"(\d,\d{1,2})\s*\n\s*(\d)", r"\1\2", txt)
    t = re.sub(r"(\d,\d{3}(?:,\d{3})*)\s*\n\s*(\d{0,3}\.\d{2})", r"\1\2", t)
    t = re.sub(r"(\d{1,3},)\s*\n\s*(\d)", r"\1\2", t)
    return re.sub(r"[ \t]+", "", t)


def load_run(run_dir):
    recs = {}
    for f in (run_dir / "raw").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        recs[(slug(r["pdf"]), int(r["page"]))] = r
    return recs


def scan_page(pdf, page, content):
    txt = pymupdf.open(pdf)[page - 1].get_text()
    want = Counter(x.lstrip("-") for x in AMOUNT.findall(join_wrapped(txt)))
    out = norm_out(content)
    missing, detail = 0, []
    for amt, n in want.items():
        got = len(re.findall(r"(?<![\d,.])" + re.escape(amt) + r"(?!\d)", out))
        if got < n:
            missing += n - got
            detail.append(f"{amt}(应{n}得{got})")
    return sum(want.values()), missing, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--manifest", default="data/corpus/run_manifest.csv")
    ap.add_argument("--show-missing", action="store_true")
    a = ap.parse_args()
    if len(a.run_dirs) > 2:
        sys.exit("最多两个目录")

    runs = [Path(d) for d in a.run_dirs]
    loaded = [load_run(d) for d in runs]
    pages = list(csv.DictReader(open(a.manifest, encoding="utf-8")))

    rows = []
    for p in pages:
        key = (slug(p["pdf"]), int(p["page"]))
        recs = [L.get(key) for L in loaded]
        if not all(r and r.get("ok") for r in recs):
            continue  # 配对口径：任一方失败的页不比
        res = [scan_page(p["pdf"], int(p["page"]), r.get("content")) for r in recs]
        if res[0][0] == 0:
            continue
        rows.append((p["doc_id"], p["family"], int(p["page"]), res[0][0],
                     [m for _, m, _ in res], [d for _, _, d in res]))

    for i, d in enumerate(runs):
        with (d / "amount_scan.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["doc_id", "family", "page", "amounts_in_textlayer", "missing"])
            for doc, fam, pg, n, ms, _ in rows:
                w.writerow([doc, fam, pg, n, ms[i]])

    names = [d.name for d in runs]
    total = sum(r[3] for r in rows)
    print(f"\n配对页（双方都成功、且含 A 股口径金额）：{len(rows)} 页，金额出现 {total} 次")
    print("\n系统 | 缺失次数 | 有缺失的页数")
    ints = [len(rows), total]
    for i, nm in enumerate(names):
        miss = sum(r[4][i] for r in rows)
        pg = sum(1 for r in rows if r[4][i] > 0)
        ints += [miss, pg]
        print(f"{nm} | {miss} | {pg}")
    print("\n有缺失的页（ID末20字符 | 页 | 文本层金额数 | 各系统缺失）")
    for doc, fam, pg, n, ms, _ in rows:
        if any(ms):
            ints += [pg, n, *ms]
            print(f"{doc[-20:]} | {pg} | {n} | " + " | ".join(map(str, ms)))
    print(f"\n校验和 = 以上所有整数之和 = {sum(ints)}（不含 ID 中的数字）")
    if a.show_missing:
        print("\n缺失明细（ID末20字符 p页 | 系统 | 金额(应出现次数 得到次数)）")
        for doc, fam, pg, n, ms, ds in rows:
            for i, d in enumerate(ds):
                if d:
                    print(f"{doc[-20:]} p{pg} | {names[i]} | " + " ".join(d))


if __name__ == "__main__":
    main()
