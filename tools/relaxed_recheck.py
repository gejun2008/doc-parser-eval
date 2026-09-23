#!/usr/bin/env python3
"""
宽松口径复判：区分「真的漏了」与「只是标点/字形不同」。

check.py 只归一空白，不归一标点。两家 markdown 的全角/半角习惯不同，
page_integrity 与 unit_currency 的一部分失败可能只是标点差异。
本工具对同一批断言、同一批原始响应判两次：

  严格 = check.py 原口径（去空白）
  宽松 = 再做 NFKC（全角转半角等）并删掉所有标点与符号（Unicode P*/S* 类）

宽松口径下仍失败的，才是「真实缺失候选」。两边用同一套规则，结果对称。
不调 API、不改 results.csv，只打印一张带校验和的整数表，便于拍照。

**只用于 page_integrity 与 unit_currency。** 金额不能删标点（逗号与小数点是数值的一部分）。

用法:
  python tools/relaxed_recheck.py runs/<A目录> runs/<B目录>
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import ASSERT_DIR, judge, norm, postprocess_doc2md, slug  # noqa: E402

TYPES = ("page_integrity", "unit_currency")
ALLOWED = {"auto", "auto_textlayer", "confirmed"}


def loose(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] not in "PSZ")
    return re.sub(r"\s+", "", s)


def load(run_dir):
    out = {}
    for f in (Path(run_dir) / "raw").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("ok"):
            c = postprocess_doc2md(r.get("content"))
            out[(slug(r["pdf"]), int(r["page"]))] = (norm(c), loose(c))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    a = ap.parse_args()
    A, B = load(a.run_a), load(a.run_b)

    # (类型, 口径) -> [n, A过, B过, 只A, 只B]
    tab = {(t, m): [0] * 5 for t in TYPES for m in ("严格", "宽松")}
    for yf in sorted(ASSERT_DIR.glob("*.yaml")):
        d = yaml.safe_load(yf.read_text(encoding="utf-8"))
        base = slug(d["local_path"])
        for it in d["assertions"]:
            if it.get("type") not in TYPES or it.get("status", "draft") not in ALLOWED:
                continue
            key = (base, it["page"])
            if key not in A or key not in B:
                continue  # 配对口径
            lit = dict(it, target=loose(str(it.get("target"))),
                       forbid=[loose(str(f)) for f in (it.get("forbid") or [])])
            for mode, idx, item in (("严格", 0, it), ("宽松", 1, lit)):
                pa = judge(item, A[key][idx])[0]
                pb = judge(item, B[key][idx])[0]
                if pa is None or pb is None:
                    continue
                row = tab[(it["type"], mode)]
                row[0] += 1
                row[1] += pa
                row[2] += pb
                row[3] += pa and not pb
                row[4] += pb and not pa

    na, nb = Path(a.run_a).name, Path(a.run_b).name
    print(f"\nA = {na}\nB = {nb}")
    print("\n类型 | 口径 | n | A通过 | B通过 | 只A对 | 只B对")
    ints = []
    for (t, m), r in tab.items():
        ints += r
        print(f"{t} | {m} | " + " | ".join(map(str, r)))
    print(f"\n校验和 = 表内所有整数之和 = {sum(ints)}")
    print("宽松口径下仍失败的 = n − 通过数，是「真实缺失候选」，需人工抽查确认")


if __name__ == "__main__":
    main()
