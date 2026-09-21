#!/usr/bin/env python3
"""
重复调用一致性专项 (T8)

T0 §9 只证明了「存在不一致」（同一页调 3 次，2 次相同、1 次不同），
n=3、单页，给不出分母。本脚本在全量页上给出分母。

## 三个层次的一致性，业务含义完全不同

  1. 逐字一致    content 的 sha256 是否相同。最严格，但差一个空格也算不一致
  2. 内容一致    空白归一后是否相同。对格式抖动宽容
  3. **结论一致** 同一条断言在多次调用间 pass/fail 是否翻转

**第 3 条才是银行关心的**：同一份文档重跑一次，抽取出来的金额会不会变。
第 1、2 条只是技术现象，第 3 条直接对应「这个系统的输出能不能作为审计证据」。

## 为什么这件事重要

Azure DI 这类流水线是确定性的：同输入同输出。
自回归解码不是（t0-findings.md §9），`temperature: 0` 也不是。
报告的可靠性档必须给出翻转率，采购问答里躲不掉。

用法:
  python tools/consistency.py runs/run_a runs/run_b runs/run_c
"""

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from check import judge, norm, postprocess_doc2md, slug, wilson  # noqa: E402

ASSERT_DIR = Path("data/assertions")


def load_run(run_dir):
    out = {}
    for f in (Path(run_dir) / "raw").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        out[(slug(r["pdf"]), r["page"])] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="两个以上 run 目录")
    ap.add_argument("--out", default="runs/consistency")
    a = ap.parse_args()
    if len(a.runs) < 2:
        sys.exit("至少两个 run")

    runs = [load_run(r) for r in a.runs]
    common = set(runs[0])
    for r in runs[1:]:
        common &= set(r)
    print(f"{len(a.runs)} 次 run，公共页 {len(common)}")

    # --- 层次 1、2：输出本身 ---
    rows, exact, normed, lens = [], 0, 0, []
    for key in sorted(common):
        recs = [r[key] for r in runs]
        if not all(x.get("ok") for x in recs):
            rows.append({"page_key": f"{key[0]}_p{key[1]}", "all_ok": 0,
                         "exact_identical": "", "normalized_identical": "",
                         "len_spread": "", "len_cv": ""})
            continue
        contents = [postprocess_doc2md(x["content"]) for x in recs]
        shas = {hashlib.sha256(c.encode()).hexdigest() for c in contents}
        nshas = {hashlib.sha256(norm(c).encode()).hexdigest() for c in contents}
        ls = [len(c) for c in contents]
        spread = max(ls) - min(ls)
        cv = statistics.pstdev(ls) / statistics.mean(ls) if statistics.mean(ls) else 0
        exact += len(shas) == 1
        normed += len(nshas) == 1
        lens.append(spread)
        rows.append({"page_key": f"{key[0]}_p{key[1]}", "all_ok": 1,
                     "exact_identical": int(len(shas) == 1),
                     "normalized_identical": int(len(nshas) == 1),
                     "len_spread": spread, "len_cv": round(cv, 5)})

    n_ok = sum(r["all_ok"] for r in rows)
    print(f"\n【层次 1】逐字一致（含空白）  {exact}/{n_ok} = {exact/max(n_ok,1):.1%}")
    print(f"【层次 2】内容一致（空白归一）{normed}/{n_ok} = {normed/max(n_ok,1):.1%}")
    if lens:
        lens.sort()
        print(f"          长度差 中位 {statistics.median(lens):.0f} 字符  "
              f"最大 {lens[-1]}  P90 {lens[int(len(lens)*0.9)]}")

    # --- 层次 3：断言结论是否翻转 ---
    flips, per_type, per_assertion = [], defaultdict(Counter), []
    for yf in sorted(ASSERT_DIR.glob("*.yaml")):
        d = yaml.safe_load(yf.read_text(encoding="utf-8"))
        base = slug(d["local_path"])
        for it in d["assertions"]:
            if it.get("status") not in ("auto", "auto_textlayer", "confirmed"):
                continue
            key = (base, it["page"])
            if key not in common:
                continue
            recs = [r[key] for r in runs]
            if not all(x.get("ok") for x in recs):
                continue
            verdicts = []
            for x in recs:
                ok, _ = judge(it, norm(postprocess_doc2md(x["content"])))
                verdicts.append(ok)
            if any(v is None for v in verdicts):
                continue
            flipped = len(set(verdicts)) > 1
            per_type[it["type"]]["flip" if flipped else "stable"] += 1
            per_assertion.append({
                "assertion_id": it["id"], "type": it["type"],
                "doc_id": d["doc_id"], "family": d["family"], "page": it["page"],
                "verdicts": "".join("1" if v else "0" for v in verdicts),
                "flipped": int(flipped),
                "severity": it.get("severity", ""),
            })
            if flipped:
                flips.append((it["id"], it["type"], it.get("severity"),
                              "".join("1" if v else "0" for v in verdicts),
                              str(it.get("target"))[:40]))

    total = len(per_assertion)
    n_flip = sum(p["flipped"] for p in per_assertion)
    lo, hi = wilson(n_flip, total)
    print(f"\n【层次 3】断言结论翻转  {n_flip}/{total} = {n_flip/max(total,1):.2%}"
          f"  95% CI [{lo:.4f}, {hi:.4f}]")
    print(f"{'类型':16} {'稳定':>6} {'翻转':>6} {'翻转率':>8}")
    for t, c in sorted(per_type.items()):
        tot = c["flip"] + c["stable"]
        print(f"{t:16} {c['stable']:6} {c['flip']:6} {c['flip']/tot:8.2%}")

    if flips:
        print(f"\n翻转样例（verdicts 为各次判定，1=pass）：")
        for f in flips[:8]:
            print(f"  {f[3]}  {f[1]:14} {f[2]:8} {f[4]}")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pages.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (out / "assertions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_assertion[0].keys()))
        w.writeheader()
        w.writerows(per_assertion)
    (out / "summary.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": a.runs, "n_runs": len(a.runs), "n_pages_common": len(common),
        "n_pages_all_ok": n_ok,
        "level1_exact_identical": {"n": exact, "rate": round(exact/max(n_ok,1), 4)},
        "level2_normalized_identical": {"n": normed, "rate": round(normed/max(n_ok,1), 4)},
        "len_spread_median": statistics.median(lens) if lens else None,
        "level3_assertion_flip": {
            "n_flipped": n_flip, "n_total": total,
            "rate": round(n_flip/max(total,1), 5), "ci95": [lo, hi],
            "by_type": {t: dict(c) for t, c in per_type.items()}},
        "note": ("层次 3 才是业务口径：同一文档重跑，断言结论是否改变。"
                 "层次 1、2 只是技术现象。"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}/summary.json  {out}/pages.csv  {out}/assertions.csv")


if __name__ == "__main__":
    main()
