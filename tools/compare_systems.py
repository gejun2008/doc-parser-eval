#!/usr/bin/env python3
"""
两个系统的对照分析 (T6/T7)

把 Infinity-Parser2 与 Azure DI 在**同一批页、同一套断言**上的结果并列出数。

## 为什么用 McNemar 而不是比两个置信区间

两边判的是同一批断言 —— 这是**配对数据**。
比两个独立 CI 会低估检验效力：同一条难断言两边都错，那是共同难度，不是差异；
真正有信息量的是「A 对 B 错」与「A 错 B 对」的条数差（记作 b 与 c）。
McNemar 检验正是基于 b、c 判断差异是否显著。

  b = A 通过而 B 失败的条数
  c = A 失败而 B 通过的条数
  两者相近 -> 无差异；相差悬殊 -> 有差异

b+c 较小时用二项精确检验，较大时用带连续性校正的卡方。**不依赖 scipy。**

## 口径纪律（CLAUDE.md 约定 5）

  - 按文档族、按断言类型分层出数，**不合成加权总分**
  - 每层给 n、差值、b/c、p 值
  - 分层样本不足就写「样本不足，不下结论」，不要为了好看而合并分层
  - p ≥ 0.05 一律写成「未观察到显著差异」，**不得写成「持平」或「相当」**

用法:
  # 自建集（check.py 的输出）
  python tools/compare_systems.py \\
      runs/inf-mllm_doc2md_20260921T013924Z/results.csv \\
      runs/azure_di_layout_<ts>/results.csv \\
      --name-a Infinity-Parser2 --name-b "Azure DI"

  # olmOCR-Bench（score_olmocr.py 的输出）
  python tools/compare_systems.py \\
      runs/inf-mllm_doc2md_20260918T065831Z/olmocr_results.csv \\
      runs/azure_di_layout_<ts>/olmocr_results.csv
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def mcnemar(b, c):
    """返回 (p 值, 方法)。b、c 为两种不一致的条数。"""
    n = b + c
    if n == 0:
        return 1.0, "no_discordant_pairs"
    if n < 25:
        # 二项精确检验，双侧
        k = min(b, c)
        p = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n) * 2
        return min(1.0, p), "exact_binomial"
    chi = (abs(b - c) - 1) ** 2 / n          # 连续性校正
    p = math.erfc(math.sqrt(chi / 2))         # 卡方 df=1 的上尾
    return min(1.0, p), "chi2_continuity_corrected"


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def load(path):
    """读 check.py 或 score_olmocr.py 的逐条结果。返回 {id: (pass, 分层字段)}。"""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        sys.exit(f"{path} 是空的")
    cols = rows[0].keys()
    if "assertion_id" in cols:          # check.py
        key, strata = "assertion_id", ["type", "family", "window"]
    elif "test_id" in cols:             # score_olmocr.py
        key, strata = "test_id", ["type", "subset"]
    else:
        sys.exit(f"{path} 既不是 results.csv 也不是 olmocr_results.csv")
    out = {}
    for r in rows:
        if r.get("pass", "") == "":      # 判定器异常等，两边都排除
            continue
        out[r[key]] = (int(r["pass"]), {s: r.get(s, "") for s in strata})
    return out, strata


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_a")
    ap.add_argument("results_b")
    ap.add_argument("--name-a", default="A")
    ap.add_argument("--name-b", default="B")
    ap.add_argument("--min-n", type=int, default=30,
                    help="低于这个条数的分层标注「样本不足，不下结论」")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    A, strata = load(a.results_a)
    B, strata_b = load(a.results_b)
    if strata != strata_b:
        sys.exit("两份结果的格式不同，不能比对")

    common = sorted(set(A) & set(B))
    only_a, only_b = len(A) - len(common), len(B) - len(common)
    print(f"{a.name_a}: {len(A)} 条　{a.name_b}: {len(B)} 条　公共 {len(common)} 条")
    if only_a or only_b:
        print(f"！只在一边出现的断言已排除：{a.name_a} {only_a} 条，{a.name_b} {only_b} 条")
    if not common:
        sys.exit("没有公共断言。两边跑的可能不是同一批页。")

    rows, groups = [], defaultdict(list)
    for k in common:
        pa, meta = A[k]
        pb, _ = B[k]
        rows.append({"assertion_id": k, **meta,
                     f"pass_{a.name_a}": pa, f"pass_{a.name_b}": pb,
                     "agree": int(pa == pb)})
        groups[("全部", "全部")].append((pa, pb))
        for s in strata:
            groups[(s, meta[s])].append((pa, pb))

    def block(pairs):
        n = len(pairs)
        ka = sum(p[0] for p in pairs)
        kb = sum(p[1] for p in pairs)
        b = sum(1 for x, y in pairs if x == 1 and y == 0)
        c = sum(1 for x, y in pairs if x == 0 and y == 1)
        p, method = mcnemar(b, c)
        return {"n": n, f"pass_{a.name_a}": ka, f"pass_{a.name_b}": kb,
                f"rate_{a.name_a}": round(ka / n, 4), f"rate_{a.name_b}": round(kb / n, 4),
                "diff": round((ka - kb) / n, 4),
                f"ci_{a.name_a}": wilson(ka, n), f"ci_{a.name_b}": wilson(kb, n),
                "b_a_only": b, "c_b_only": c, "p_value": round(p, 5), "method": method,
                "verdict": ("样本不足，不下结论" if n < a.min_n else
                            "未观察到显著差异" if p >= 0.05 else
                            f"{a.name_a} 显著更高" if b > c else f"{a.name_b} 显著更高")}

    summary = {k: block(v) for k, v in groups.items()}

    print(f"\n{'分层':28} {'n':>5} {a.name_a[:12]:>12} {a.name_b[:12]:>12} "
          f"{'差值':>7} {'b/c':>9} {'p':>8}  判读")
    for (dim, val), st in sorted(summary.items(),
                                 key=lambda x: (x[0][0] != "全部", x[0])):
        label = f"{dim}={val}" if dim != "全部" else "全部（不作为总分）"
        print(f"{label[:28]:28} {st['n']:5} "
              f"{st[f'rate_{a.name_a}']:11.1%} {st[f'rate_{a.name_b}']:11.1%} "
              f"{st['diff']:+7.1%} {st['b_a_only']:4}/{st['c_b_only']:<4} "
              f"{st['p_value']:8.4f}  {st['verdict']}")

    out = Path(a.out or Path(a.results_a).parent / "comparison")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "paired.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (out / "summary.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system_a": {"name": a.name_a, "results": a.results_a, "n": len(A)},
        "system_b": {"name": a.name_b, "results": a.results_b, "n": len(B)},
        "n_common": len(common), "excluded_only_a": only_a, "excluded_only_b": only_b,
        "test": "McNemar（配对数据）",
        "caveats": [
            "按分层看，全部那一行不是加权总分，只是同口径汇总",
            "p >= 0.05 写「未观察到显著差异」，不得写成「持平」或「相当」",
            f"n < {a.min_n} 的分层标注样本不足，不下结论",
            "Azure DI 按整份文档分析，即使指定单页也可能利用全文上下文，这对 Azure 有利",
            "两边 markdown 风格由各自厂商决定，formatting 类断言不可跨系统比较",
        ],
        "strata": {f"{d}={v}": s for (d, v), s in summary.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}/summary.json　{out}/paired.csv")
    print("提醒：全部那一行不是加权总分；p≥0.05 写「未观察到显著差异」，不要写「持平」。")


if __name__ == "__main__":
    main()
