"""Paired comparison of two scored runs on identical tests (exact McNemar test)."""
from collections import defaultdict
from math import comb
from pathlib import Path

import yaml

from .common import MIN_N, read_csv

STRATUM = {"financial": "test_type", "olmocr": "subset", "perturbed": "variant"}


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def compare(dir_a, dir_b):
    a, b = Path(dir_a), Path(dir_b)
    card_a = yaml.safe_load((a / "run_card.yaml").read_text(encoding="utf-8"))
    card_b = yaml.safe_load((b / "run_card.yaml").read_text(encoding="utf-8"))
    lines = [f"# {card_a.get('model')} vs {card_b.get('model')}", ""]
    for k in ("dataset_commit", "input_mode", "dpi", "eval_version"):
        if card_a.get(k) != card_b.get(k):
            lines.append(f"> **WARNING:** `{k}` differs ({card_a.get(k)} vs {card_b.get(k)}). "
                         "Results may not be comparable.")
    lines.append("")
    for coll, skey in STRATUM.items():
        fa, fb = a / f"{coll}.csv", b / f"{coll}.csv"
        if not (fa.exists() and fb.exists()):
            continue
        key = lambda r: (r["test_id"], r["variant"])  # noqa: E731
        ra = {key(r): r for r in read_csv(fa) if r["outcome"] in ("pass", "fail", "missing")}
        rb = {key(r): r for r in read_csv(fb) if r["outcome"] in ("pass", "fail", "missing")}
        cells = defaultdict(lambda: [0, 0, 0, 0])  # both, a only, b only, neither
        for k in ra.keys() & rb.keys():
            pa, pb = ra[k]["outcome"] == "pass", rb[k]["outcome"] == "pass"
            c = cells[ra[k][skey]]
            c[0 if pa and pb else 1 if pa else 2 if pb else 3] += 1
        lines += [f"## {coll} (paired tests: {sum(map(sum, cells.values()))})", "",
                  "| Stratum | n | A pass | B pass | Only A | Only B | McNemar p | Reading |",
                  "|---|---:|---:|---:|---:|---:|---:|---|"]
        for s, (both, ao, bo, nei) in sorted(cells.items()):
            n = both + ao + bo + nei
            p = mcnemar_p(ao, bo)
            reading = ("insufficient sample" if n < MIN_N else
                       "no significant difference" if p >= 0.05 else
                       ("A higher" if ao > bo else "B higher"))
            lines.append(f"| {s} | {n} | {both + ao} | {both + bo} | {ao} | {bo} | {p:.3g} | {reading} |")
        lines.append("")
    lines.append("Missing predictions count as failures on both sides. No overall score.")
    return "\n".join(lines)
