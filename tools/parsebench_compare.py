#!/usr/bin/env python3
"""
ParseBench 两系统配对比较（INF vs Azure DI）

输入是两边 parsebench_score.py 产出的 parsebench_per_file.csv。
两边判的是同一批文件、同一套官方指标 —— 配对数据，比两个独立均值会低估检验效力。

每个维度 / 分层给:
  n                配对文件数
  mean_a, mean_b   两边官方主指标均值
  diff             mean_a - mean_b
  diff_ci95        配对 bootstrap（按文件重抽样）95% 区间
  a_better / b_better / tie   逐文件谁高（|差| < 1e-9 记平）
  sign_p           符号检验双侧精确 p（不计平局）

两种口径都出:
  all          全部配对文件，调用失败 / 空输出按 0 分（官方判分器默认会把它们排除出分母）
  both_output  只保留两边都有非空输出的文件——报告主口径，把「调用失败」和「解析质量」分开

口径纪律（CLAUDE.md 约定 5）:
  - 不合成加权总分
  - 配对数 < --min-n 的分层写「样本不足，不下结论」
  - 区间跨 0 且 p ≥ 0.05 写「未观察到显著差异」，不写「持平」

用法:
  python tools/parsebench_compare.py runs/<inf_run>/parsebench_per_file.csv \\
      runs/<azure_run>/parsebench_per_file.csv --name-a Infinity-Parser2 --name-b "Azure DI" \\
      --out runs/<azure_run>/parsebench_compare.json
"""

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path


def load(path):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[(r["dimension"], r["example_id"])] = {
            "score": float(r["score"]), "stratum": r["stratum"],
            "domain_guess": r["domain_guess"], "empty": r["empty_output"] == "True"}
    return out


def sign_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def boot_diff(pairs, n_boot=4000, seed=0):
    if len(pairs) < 2:
        return [None, None]
    rng = random.Random(seed)
    diffs = [a - b for a, b in pairs]
    ms = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n_boot))
    return [round(ms[int(0.025 * n_boot)], 4), round(ms[int(0.975 * n_boot) - 1], 4)]


def cell(pairs, min_n):
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    a_b = sum(1 for a, b in pairs if a - b > 1e-9)
    b_b = sum(1 for a, b in pairs if b - a > 1e-9)
    out = {"n": n,
           "mean_a": round(statistics.fmean(a for a, _ in pairs), 4),
           "mean_b": round(statistics.fmean(b for _, b in pairs), 4),
           "diff": round(statistics.fmean(a - b for a, b in pairs), 4),
           "diff_ci95": boot_diff(pairs),
           "a_better": a_b, "b_better": b_b, "tie": n - a_b - b_b,
           "sign_p": round(sign_p(a_b, b_b), 4)}
    lo, hi = out["diff_ci95"]
    if n < min_n:
        out["verdict"] = "样本不足，不下结论"
    elif lo is not None and (lo > 0 or hi < 0) and out["sign_p"] < 0.05:
        out["verdict"] = "A 更高" if lo > 0 else "B 更高"
    else:
        out["verdict"] = "未观察到显著差异"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("per_file_a")
    ap.add_argument("per_file_b")
    ap.add_argument("--name-a", default="A")
    ap.add_argument("--name-b", default="B")
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    A, B = load(a.per_file_a), load(a.per_file_b)
    keys = sorted(set(A) & set(B))
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))

    result = {"name_a": a.name_a, "name_b": a.name_b, "min_n": a.min_n,
              "n_paired": len(keys), "only_in_a": len(only_a), "only_in_b": len(only_b),
              "empty_a": sum(A[k]["empty"] for k in keys),
              "empty_b": sum(B[k]["empty"] for k in keys),
              "views": {}}
    for view in ("all", "both_output"):
        ks = [k for k in keys if view == "all" or not (A[k]["empty"] or B[k]["empty"])]
        dims = defaultdict(list)
        strata = defaultdict(lambda: defaultdict(list))
        doms = defaultdict(lambda: defaultdict(list))
        for k in ks:
            p = (A[k]["score"], B[k]["score"])
            dims[k[0]].append(p)
            strata[k[0]][A[k]["stratum"]].append(p)
            doms[k[0]][A[k]["domain_guess"]].append(p)
        result["views"][view] = {
            dim: {"overall": cell(dims[dim], a.min_n),
                  "by_stratum": {s: cell(v, a.min_n) for s, v in sorted(strata[dim].items())},
                  "by_domain_guess": {d: cell(v, a.min_n) for d, v in sorted(doms[dim].items())}}
            for dim in sorted(dims)}

    out = Path(a.out) if a.out else Path(a.per_file_b).with_name("parsebench_compare.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"A = {a.name_a}   B = {a.name_b}   配对 {len(keys)}  "
          f"仅 A {len(only_a)}  仅 B {len(only_b)}  空输出 A {result['empty_a']} / B {result['empty_b']}")
    for view, dims in result["views"].items():
        print(f"\n[{view}]")
        print(f"{'维度':16} {'n':>4} {'A':>7} {'B':>7} {'A-B':>7}  {'95% CI':18} "
              f"{'A>B':>4} {'B>A':>4} {'平':>3} {'p':>7}  结论")
        for dim, v in dims.items():
            c = v["overall"]
            if not c.get("n"):
                continue
            print(f"{dim:16} {c['n']:4} {c['mean_a']:7.3f} {c['mean_b']:7.3f} {c['diff']:+7.3f}  "
                  f"{str(c['diff_ci95']):18} {c['a_better']:4} {c['b_better']:4} {c['tie']:3} "
                  f"{c['sign_p']:7.4f}  {c['verdict']}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
