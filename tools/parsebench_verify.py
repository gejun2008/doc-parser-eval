#!/usr/bin/env python3
"""
ParseBench 总结复核（在公司电脑上跑）

docs/working/parsebench-summary.md 里 Azure 侧与双边比较的数字，是从公司电脑报告的截图识别转录的，
Azure 结果又不能带出公司。本脚本把总结里引用的每个数字写成 EXPECTED，与公司电脑上的落盘结果逐项比对，
并检查网关返回的 analyzeResult 是否完整（Visual Grounding 能否比较取决于此）。

只读，不改任何结果文件。输出 docs/working/parsebench-verify.md，外加终端摘要。

用法:
  python tools/parsebench_verify.py runs/parsebench_inf_<ts> runs/parsebench_azure_<ts>
前置:
  runs/parsebench_azure_<ts>/parsebench_compare.json   （parsebench_compare.py 产出）
  runs/parsebench_inf_<ts>_nodeep/parsebench_summary.json （parsebench_nodeep.py + parsebench_score.py 产出）
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# (口径, 维度, 层级, 字段, 总结里写的值)。均值 / 差为百分制，保留一位小数。
EXPECTED = [
    # §2 主口径
    ("both_output", "table", "overall", "n", 128),
    ("both_output", "table", "overall", "mean_a", 76.0),
    ("both_output", "table", "overall", "mean_b", 82.5),
    ("both_output", "table", "overall", "diff", -6.5),
    ("both_output", "table", "overall", "a_better", 40),
    ("both_output", "table", "overall", "b_better", 72),
    ("both_output", "table", "overall", "sign_p", 0.0032),
    ("both_output", "table", "overall", "verdict", "B 更高"),
    ("both_output", "chart", "overall", "n", 100),
    ("both_output", "chart", "overall", "mean_a", 58.3),
    ("both_output", "chart", "overall", "mean_b", 2.1),
    ("both_output", "chart", "overall", "diff", 56.2),
    ("both_output", "chart", "overall", "a_better", 83),
    ("both_output", "chart", "overall", "b_better", 0),
    ("both_output", "text_content", "overall", "n", 149),
    ("both_output", "text_content", "overall", "mean_a", 87.3),
    ("both_output", "text_content", "overall", "mean_b", 83.3),
    ("both_output", "text_content", "overall", "diff", 4.0),
    ("both_output", "text_content", "overall", "a_better", 107),
    ("both_output", "text_content", "overall", "b_better", 41),
    ("both_output", "text_content", "overall", "verdict", "A 更高"),
    ("both_output", "text_formatting", "overall", "n", 133),
    ("both_output", "text_formatting", "overall", "mean_a", 46.5),
    ("both_output", "text_formatting", "overall", "mean_b", 40.4),
    ("both_output", "text_formatting", "overall", "diff", 6.1),
    ("both_output", "text_formatting", "overall", "sign_p", 0.1945),
    ("both_output", "text_formatting", "overall", "verdict", "未观察到显著差异"),
    ("both_output", "layout", "overall", "n", 118),
    ("both_output", "layout", "overall", "mean_a", 75.8),
    ("both_output", "layout", "overall", "mean_b", 71.1),
    ("both_output", "layout", "overall", "diff", 4.7),
    ("both_output", "layout", "overall", "a_better", 61),
    ("both_output", "layout", "overall", "b_better", 34),
    ("both_output", "layout", "overall", "sign_p", 0.0073),
    ("both_output", "layout", "overall", "verdict", "A 更高"),
    # §2 参照口径
    ("all", "table", "overall", "diff", -7.8),
    ("all", "table", "overall", "sign_p", 0.0019),
    # §4 分层
    ("both_output", "table", "stratum:easy", "diff", -4.3),
    ("both_output", "table", "stratum:easy", "verdict", "未观察到显著差异"),
    ("both_output", "table", "stratum:hard", "n", 45),
    ("both_output", "table", "stratum:hard", "diff", -10.7),
    ("both_output", "table", "stratum:hard", "sign_p", 0.0137),
    ("both_output", "table", "stratum:hard", "verdict", "B 更高"),
    ("both_output", "table", "domain:financial_filing", "n", 42),
    ("both_output", "table", "domain:financial_filing", "mean_b", 90.1),
    ("both_output", "table", "domain:financial_filing", "diff", -11.8),
    ("both_output", "table", "domain:financial_filing", "verdict", "B 更高"),
    ("both_output", "table", "domain:insurance", "diff", -4.2),
    ("both_output", "text_content", "stratum:ocr", "diff", 5.7),
    ("both_output", "text_content", "stratum:ocr", "sign_p", 0.0033),
    ("both_output", "text_content", "stratum:simple", "diff", 2.8),
    ("both_output", "text_content", "stratum:multilang", "diff", -1.7),
    ("both_output", "text_formatting", "stratum:ocr", "diff", 18.1),
    ("both_output", "text_formatting", "stratum:ocr", "sign_p", 0.0127),
    ("both_output", "layout", "stratum:easy/pdf", "diff", 6.5),
    ("both_output", "layout", "stratum:hard/pdf", "diff", 7.6),
    ("both_output", "layout", "stratum:easy/image", "mean_a", 29.1),
    ("both_output", "layout", "stratum:easy/image", "mean_b", 49.8),
    ("both_output", "chart", "stratum:3d", "mean_a", 21.9),
]

# §3 消融与附表：全部文件口径的单边均值（百分制）
EXPECTED_SIDE = [
    ("inf", "table", 74.8), ("inf", "chart", 58.3), ("inf", "text_content", 86.7),
    ("inf", "text_formatting", 46.5), ("inf", "layout", 75.4),
    ("nodeep", "table", 74.8), ("nodeep", "chart", 2.0), ("nodeep", "text_content", 87.2),
    ("nodeep", "text_formatting", 46.5), ("nodeep", "layout", 75.4),
    ("azure", "table", 82.6), ("azure", "chart", 2.1), ("azure", "text_content", 83.3),
    ("azure", "text_formatting", 40.4), ("azure", "layout", 71.1),
]

PCT = {"mean_a", "mean_b", "diff"}


def actual(cmp_, view, dim, level, field):
    d = cmp_["views"].get(view, {}).get(dim) or {}
    if level == "overall":
        c = d.get("overall")
    else:
        kind, key = level.split(":", 1)
        c = (d.get("by_stratum" if kind == "stratum" else "by_domain_guess") or {}).get(key)
    if not c or field not in c:
        return None
    v = c[field]
    return round(v * 100, 1) if field in PCT else v


def same(field, exp, got):
    if got is None:
        return False
    if isinstance(exp, str):
        return exp == got
    if field in PCT:
        return abs(exp - got) <= 0.05 + 1e-9
    if field == "sign_p":
        return abs(exp - got) <= 0.00005 + 1e-9 or (exp < 0.0001 and got < 0.0001)
    return exp == got


def completeness(azure_run):
    """网关返回的 analyzeResult 是否含 Visual Grounding 需要的结构与坐标。"""
    c = Counter()
    for p in sorted((azure_run / "raw").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        ar = r.get("analyze_result") or {}
        c["files"] += 1
        c["ok"] += bool(r.get("ok"))
        c["has_content"] += bool(ar.get("content"))
        c["has_pages"] += bool(ar.get("pages"))
        paras = ar.get("paragraphs") or []
        c["has_paragraphs"] += bool(paras)
        c["paragraphs_with_bbox"] += bool(paras) and all(x.get("boundingRegions") for x in paras)
        c["has_tables"] += bool(ar.get("tables"))
        c["has_figures"] += bool(ar.get("figures"))
        c["content_format_markdown"] += ar.get("contentFormat") == "markdown"
    return dict(c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inf_run")
    ap.add_argument("azure_run")
    ap.add_argument("--out", default="docs/working/parsebench-verify.md")
    a = ap.parse_args()
    inf, az = Path(a.inf_run), Path(a.azure_run)
    nodeep = inf.with_name(inf.name + "_nodeep")

    cmp_ = json.loads((az / "parsebench_compare.json").read_text(encoding="utf-8"))
    side = {}
    for key, run in (("inf", inf), ("nodeep", nodeep), ("azure", az)):
        f = run / "parsebench_summary.json"
        side[key] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    rows, n_bad = [], 0
    for view, dim, level, field, exp in EXPECTED:
        got = actual(cmp_, view, dim, level, field)
        ok = same(field, exp, got)
        n_bad += not ok
        rows.append((f"{view} · {dim} · {level} · {field}", exp, got, ok))
    for key, dim, exp in EXPECTED_SIDE:
        s = side.get(key)
        got = None if s is None else round(((s["dimensions"].get(dim) or {}).get("mean") or 0) * 100, 1)
        ok = got is not None and abs(exp - got) <= 0.05 + 1e-9
        n_bad += not ok
        rows.append((f"单边 · {key} · {dim} · mean", exp, got if s else "缺少 summary", ok))

    comp = completeness(az)

    L = [f"# ParseBench 总结复核",
         "",
         f"> `tools/parsebench_verify.py` 于 {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC 生成。"
         f"INF run `{inf.name}`，Azure run `{az.name}`。",
         "",
         f"**{len(rows) - n_bad} / {len(rows)} 项一致，{n_bad} 项不一致。**",
         "",
         "## 1. 总结引用数字逐项比对",
         "",
         "| 项 | 总结里写的 | 落盘结果 | 一致 |",
         "|---|---|---|---|"]
    for name, exp, got, ok in rows:
        L.append(f"| {name} | {exp} | {got} | {'✓' if ok else '✗ 不一致'} |")
    L += ["",
          "verdict 取值：`A 更高` = Infinity 更高，`B 更高` = Azure 更高。",
          "",
          "## 2. 网关返回的 analyzeResult 完整性",
          "",
          "| 项 | 文件数 |",
          "|---|---|"]
    for k, v in comp.items():
        L.append(f"| {k} | {v} |")
    L += ["",
          "判读：`paragraphs_with_bbox` 接近 `files` 才说明 Visual Grounding 两边可比；"
          "若为 0 或很少，说明网关只回了文本，Azure 的 Visual Grounding 分数被系统性低估，该维度不能比较。",
          ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"{len(rows) - n_bad}/{len(rows)} 项一致，{n_bad} 项不一致")
    for name, exp, got, ok in rows:
        if not ok:
            print(f"  ✗ {name}: 总结写 {exp}，落盘 {got}")
    print("analyzeResult 完整性:", comp)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
