#!/usr/bin/env python3
"""
olmOCR-Bench 配对结果的两项诊断（不改判定器、不改产品口径）

诊断 1 · 页面装饰注释
  Azure DI 的 markdown 输出把页眉、页脚、页码写成 HTML 注释：
      <!-- PageHeader="..." -->  <!-- PageFooter="..." -->  <!-- PageNumber="..." -->
  官方判定器的 normalize_text 不剥注释，`absent` 测试会把注释里的文字当成「出现了」。
  于是 Azure「已经识别出这是页眉」反而被判 fail。
  本诊断把这三类注释从**两边**的输出里一并删除（对称处理），用同一判定器重判，
  产出与 olmocr_results.csv 同 schema 的 CSV，可直接喂给 compare_systems.py。
  这是诊断口径，**不替代产品口径**，两组数字并列报（同 --diagnose-latex 的做法）。

诊断 2 · old_scans 失败归因
  对 old_scans 每一条测试，并列两边的判定、最佳匹配度、宽松匹配结果和匹配片段，
  再按规则给一个**机器初判**（格式差异 / 部分识别错误 / 内容缺失），供人工复核。
  同时把 15 页两边的完整输出写成 markdown，便于对着 PDF 看。
  机器初判只是分拣，结论以人工复核为准。

两项诊断都先用产品口径重算一遍通过数，与 score_olmocr.py 已落盘的 CSV 核对，
不一致就停，保证诊断用的是同一份数据、同一套判定。

用法（在仓库根目录）:
  python tools/olmocr_diag.py ^
      --inf   runs/inf-mllm_doc2md_20260918T065831Z ^
      --azure runs/azure_di_layout_20260929T133601Z ^
      --skip-math
产物默认写到 <azure_run>/diag/
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score_olmocr import filtered_tests, postprocess_doc2md, slug, wilson  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent / "vendor"))
from olmocr.bench.tests import normalize_text  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

FURNITURE = re.compile(r"<!--\s*Page(Header|Footer|Number)\s*=\s*\".*?\"\s*-->", re.S)
ANY_COMMENT = re.compile(r"<!--.*?-->", re.S)
FIELDS = ["subset", "pdf", "test_id", "type", "pass", "explanation"]


def strip_furniture(text):
    return FURNITURE.sub(" ", text)


def load_pages(run_dir):
    pages = {}
    for f in sorted((Path(run_dir) / "raw").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        pages[slug(r["pdf"])] = r
    if not pages:
        sys.exit(f"{run_dir}/raw 下没有原始响应")
    return pages


def score(pages, tests_by_pdf, subset_of, transform, skip_math):
    """与 score_olmocr.py 相同的判定流程，只在喂给判定器前多一步 transform。"""
    rows = []
    for key, rec in sorted(pages.items()):
        content = transform(postprocess_doc2md(rec.get("content") or ""))
        for t in tests_by_pdf.get(key, []):
            ttype = getattr(t.type, "value", str(t.type))
            if ttype == "math" and skip_math:
                continue
            if not rec.get("ok"):
                passed, expl = False, (f"page_call_failed status={rec.get('status')} "
                                       f"finish={rec.get('finish_reason')}")
            else:
                try:
                    passed, expl = t.run(content)
                except Exception as e:
                    passed, expl = None, f"checker_error: {type(e).__name__}: {e}"
            rows.append({"subset": subset_of.get(key, "?"), "pdf": rec["pdf"],
                         "test_id": t.id, "type": ttype,
                         "pass": "" if passed is None else int(passed),
                         "explanation": (expl or "")[:300]})
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def verify_against_disk(name, rows, run_dir, skip_math):
    """产品口径重算结果必须与 score_olmocr.py 落盘的逐条结果完全一致。"""
    disk = {}
    with open(Path(run_dir) / "olmocr_results.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if skip_math and r["type"] == "math":
                continue
            disk[r["test_id"]] = r["pass"]
    mine = {r["test_id"]: str(r["pass"]) for r in rows}
    diff = [k for k in set(disk) | set(mine) if disk.get(k) != mine.get(k)]
    n_pass = sum(1 for v in mine.values() if v == "1")
    print(f"  {name}: 产品口径重算 {len(mine)} 条，通过 {n_pass}；与已落盘结果不一致 {len(diff)} 条")
    if diff:
        sys.exit(f"  ！{name} 重算与落盘不一致（例：{diff[:3]}），停止。请确认 run 目录与判定器版本。")
    return n_pass


def layer_table(rows_a, rows_b, key):
    g = defaultdict(lambda: [0, 0, 0])
    for ra, rb in zip(rows_a, rows_b):
        k = ra[key]
        g[k][0] += 1
        g[k][1] += int(ra["pass"] or 0)
        g[k][2] += int(rb["pass"] or 0)
    return g


def pairs(rows_prod, rows_diag):
    """按 test_id 对齐同一系统的两种口径。"""
    d = {r["test_id"]: r for r in rows_diag}
    return [(r, d[r["test_id"]]) for r in rows_prod]


# ---------- 诊断 2 用 ----------

def relaxed(s):
    """宽松归一：小写、接上断行连字符、只留字母数字。只用于分拣，不用于打分。"""
    s = normalize_text(s or "").lower()
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s)
    return re.sub(r"[^0-9a-z]+", "", s)


def best(query, content):
    """返回 (匹配度 0-1, 片段)。与官方 present/absent 一致，用 partial_ratio。"""
    q, c = normalize_text(query), normalize_text(content)
    if not q or not c:
        return 0.0, ""
    al = fuzz.partial_ratio_alignment(q, c)
    lo, hi = max(0, al.dest_start - 30), min(len(c), al.dest_end + 30)
    return round(al.score / 100, 3), c[lo:hi]


def threshold(t, q):
    q = normalize_text(q)
    return 1.0 - (t.max_diffs / (len(q) or 1))


def triage(t, ttype, content, passed):
    """机器初判。只对失败条目给类别。"""
    if passed:
        return "", {}
    if ttype == "order":
        rb, _ = best(t.before, content)
        ra, _ = best(t.after, content)
        info = {"before_ratio": rb, "after_ratio": ra}
        if min(rb, ra) >= threshold(t, t.before) - 1e-9 and min(rb, ra) >= threshold(t, t.after) - 1e-9:
            return "顺序错误（两段都找到）", info
        return "片段缺失或识别错误导致顺序无法判定", info
    if ttype == "absent":
        return "应删未删（文字出现在输出里）", {}
    # present
    r, _ = best(t.text, content)
    if relaxed(t.text) and relaxed(t.text) in relaxed(content):
        return "格式差异（宽松归一后可找到）", {"ratio": r}
    if r >= 0.8:
        return "部分识别错误（大部分字符对得上）", {"ratio": r}
    return "内容缺失或严重识别错误", {"ratio": r}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inf", required=True, help="INF 的 run 目录")
    ap.add_argument("--azure", required=True, help="Azure 的 run 目录")
    ap.add_argument("--skip-math", action="store_true")
    ap.add_argument("--out", default="", help="默认 <azure>/diag")
    a = ap.parse_args()

    out = Path(a.out or Path(a.azure) / "diag")
    out.mkdir(parents=True, exist_ok=True)
    inf, az = load_pages(a.inf), load_pages(a.azure)
    if set(inf) != set(az):
        sys.exit(f"两边页集合不同：只 INF {len(set(inf) - set(az))}，只 Azure {len(set(az) - set(inf))}")

    with tempfile.TemporaryDirectory() as td:
        tests_by_pdf, subset_of = filtered_tests(set(inf), td)

    # ---- 0. 产品口径重算并核对 ----
    print("[0] 产品口径重算，核对与已落盘结果一致")
    ident = lambda s: s  # noqa: E731
    inf_prod = score(inf, tests_by_pdf, subset_of, ident, a.skip_math)
    az_prod = score(az, tests_by_pdf, subset_of, ident, a.skip_math)
    verify_against_disk("INF  ", inf_prod, a.inf, a.skip_math)
    verify_against_disk("Azure", az_prod, a.azure, a.skip_math)

    # ---- 1. 页面装饰注释 ----
    print("\n[1] 诊断口径：两边都删除 PageHeader/PageFooter/PageNumber 注释后重判")
    comment_stats = {}
    for name, pages in (("INF", inf), ("Azure", az)):
        kinds, n_pages = Counter(), 0
        for rec in pages.values():
            c = rec.get("content") or ""
            hits = FURNITURE.findall(c)
            kinds.update("Page" + h for h in hits)
            n_pages += bool(hits)
            others = len(ANY_COMMENT.findall(c)) - len(hits)
            kinds["其他注释（不删）"] += others
        comment_stats[name] = {"pages_with_furniture": n_pages, **kinds}
        print(f"  {name:5}: 含页面装饰注释的页 {n_pages}/{len(pages)}；{dict(kinds)}")

    inf_diag = score(inf, tests_by_pdf, subset_of, strip_furniture, a.skip_math)
    az_diag = score(az, tests_by_pdf, subset_of, strip_furniture, a.skip_math)
    write_csv(out / "inf_strip_results.csv", inf_diag)
    write_csv(out / "azure_strip_results.csv", az_diag)

    changed = []
    for name, prod, diag in (("INF", inf_prod, inf_diag), ("Azure", az_prod, az_diag)):
        for p, d in pairs(prod, diag):
            if p["pass"] != d["pass"]:
                changed.append({"system": name, "subset": p["subset"], "pdf": p["pdf"],
                                "test_id": p["test_id"], "type": p["type"],
                                "product": p["pass"], "strip": d["pass"]})
    with open(out / "strip_changed_tests.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["system", "subset", "pdf", "test_id", "type", "product", "strip"])
        w.writeheader()
        w.writerows(changed)

    summary = {"comment_stats": comment_stats, "by_subset": {}, "by_type": {}}
    for key, label in (("subset", "by_subset"), ("type", "by_type")):
        print(f"\n  按{'子集' if key == 'subset' else '类型'}：通过率 产品口径 → 诊断口径")
        print(f"  {'':18}{'n':>5}   {'INF':>15}   {'Azure':>15}")
        gi = layer_table(inf_prod, inf_diag, key)
        ga = layer_table(az_prod, az_diag, key)
        for k in sorted(gi):
            n, ip, idg = gi[k]
            _, ap_, adg = ga[k]
            summary[label][k] = {"n": n, "inf_product": ip, "inf_strip": idg,
                                 "azure_product": ap_, "azure_strip": adg,
                                 "azure_strip_ci95": wilson(adg, n)}
            print(f"  {k:18}{n:5}   {ip / n:6.1%} → {idg / n:6.1%}   {ap_ / n:6.1%} → {adg / n:6.1%}")
    (out / "strip_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 配对比较：用仓库现成脚本，口径与 compare_all 相同（含调用失败页）
    cmp_out = out / "compare_strip"
    cmd = [sys.executable, str(Path(__file__).parent / "compare_systems.py"),
           str(out / "inf_strip_results.csv"), str(out / "azure_strip_results.csv"),
           "--name-a", "Infinity-Parser2", "--name-b", "Azure DI", "--out", str(cmp_out)]
    print("\n  配对比较（诊断口径，含调用失败页）：", flush=True)
    subprocess.run(cmd, check=True)

    # ---- 2. old_scans 失败归因 ----
    print("\n[2] old_scans 逐条归因")
    rev_dir = out / "old_scans_review"
    rev_dir.mkdir(exist_ok=True)
    tmap = {t.id: t for ts in tests_by_pdf.values() for t in ts}
    ip = {r["test_id"]: r for r in inf_prod}
    rows, cls_count = [], defaultdict(Counter)
    for r in az_prod:
        if r["subset"] != "old_scans":
            continue
        t, key = tmap[r["test_id"]], slug(r["pdf"])
        a_txt = postprocess_doc2md(az[key].get("content") or "")
        i_txt = postprocess_doc2md(inf[key].get("content") or "")
        a_pass, i_pass = int(r["pass"] or 0), int(ip[r["test_id"]]["pass"] or 0)
        a_cls, a_info = triage(t, r["type"], a_txt, a_pass)
        i_cls, i_info = triage(t, r["type"], i_txt, i_pass)
        query = t.text if r["type"] in ("present", "absent") else f"{t.before} ⟶ {t.after}"
        _, a_snip = best(query if r["type"] != "order" else t.before, a_txt)
        _, i_snip = best(query if r["type"] != "order" else t.before, i_txt)
        if not a_pass:
            cls_count["Azure"][a_cls] += 1
        if not i_pass:
            cls_count["INF"][i_cls] += 1
        rows.append({"pdf": r["pdf"], "test_id": r["test_id"], "type": r["type"],
                     "INF": i_pass, "Azure": a_pass,
                     "配对": {(1, 0): "只INF对", (0, 1): "只Azure对", (1, 1): "都对", (0, 0): "都错"}[(i_pass, a_pass)],
                     "测试文本": query[:200],
                     "Azure初判": a_cls, "Azure匹配度": json.dumps(a_info, ensure_ascii=False),
                     "Azure片段": a_snip[:200],
                     "INF初判": i_cls, "INF片段": i_snip[:200],
                     "手写或打字(人工填)": "", "人工结论(人工填)": ""})
    rows.sort(key=lambda x: (x["配对"] != "只INF对", x["pdf"], x["test_id"]))
    with open(out / "old_scans_review.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    for key in sorted({slug(r["pdf"]) for r in rows}):
        pdf = inf[key]["pdf"]
        body = [f"# {pdf}\n", "## Azure DI（原样 content）\n", "```text",
                postprocess_doc2md(az[key].get("content") or ""), "```\n",
                "## Infinity-Parser2（原样 content）\n", "```text",
                postprocess_doc2md(inf[key].get("content") or ""), "```\n"]
        (rev_dir / f"{key}.md").write_text("\n".join(body), encoding="utf-8")

    for name in ("Azure", "INF"):
        print(f"  {name} 失败条目机器初判：{dict(cls_count[name])}")
    print(f"  配对分布：{dict(Counter(r['配对'] for r in rows))}")

    print(f"\n产物 -> {out}")
    print("  strip_summary.json / strip_changed_tests.csv / compare_strip/  （诊断 1）")
    print("  old_scans_review.csv / old_scans_review/*.md                 （诊断 2）")
    print("诊断口径不替代产品口径；机器初判不替代人工复核。")


if __name__ == "__main__":
    main()
