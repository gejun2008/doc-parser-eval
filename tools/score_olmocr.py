#!/usr/bin/env python3
"""
olmOCR-Bench 判定器（research-plan.md §3.2 第二层）

**判定逻辑不自己写**，直接用 allenai/olmocr 官方 bench 模块
（vendor 在 tools/vendor/olmocr，钉在 commit ab294c6a），
与厂商报 87.6% 时用的是同一套 pass/fail 逻辑，口径不会漂。

输入：runs/<run_id>/raw/*.json（runner.py 的落盘）
输出：runs/<run_id>/olmocr_results.csv  逐条测试 pass/fail
      runs/<run_id>/olmocr_summary.json 按子集、按类型分层

口径声明（报告附录必须写）:
  1. 只跑抽样子集，不是全量 1403 个 PDF，分数**不能**直接与厂商的 87.6% 比大小
  2. 每个子集单独出数，**不合成加权总分**（CLAUDE.md 约定 5）
  3. finish_reason != stop 的页记为调用失败，其上所有测试判 fail，并单列该页数
  4. headers_footers 子集全是 absent 断言，而产品 md 口径默认丢弃页眉页脚，
     天然高分，与解析能力无关——该子集分数必须带这条注释读

用法:
  python tools/score_olmocr.py runs/<run_id>
  python tools/score_olmocr.py runs/<run_id> --skip-math   # 跳过 KaTeX 渲染
"""

import argparse
import csv
import json
import re
import statistics
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vendor"))

BENCH = Path("data/olmocr_bench/bench_data")


def slug(pdf_rel):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(pdf_rel).removesuffix(".pdf"))


def postprocess_doc2md(text):
    """逐字复制自 infinity_parser2/utils/utils.py 的 postprocess_doc2md_result。

    产品拿到模型输出后就做这一步，只剥 ``` 围栏，**不动内容**。
    评测必须走同一步，否则判定的不是产品实际输出。
    """
    text = text.strip()
    text = re.sub(r"^```markdown\s*\n?", "", text)
    text = re.sub(r"^```\s*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def unescape_latex(text):
    """诊断口径，**不是产品口径**。

    实测 doc2md 输出把 LaTeX 反斜杠双写（`\\\\mathbb` 而非 `\\mathbb`），
    公式无法渲染。把双写归一后再判一遍，用来回答「如果厂商修掉这个 bug，
    公式类上限是多少」。两个数字必须分开报，不能用这个替代产品口径的分数。
    """
    return text.replace("\\\\", "\\")


def filtered_tests(pdfs_wanted, tmpdir):
    """只加载本次 run 覆盖到的 PDF 的测试。

    官方 load_tests 会在加载时预渲染 math 公式（约 13 条/秒），
    全量 7019 条要 9 分钟。先按 pdf 过滤再交给它，口径不变。
    """
    from olmocr.bench.tests import load_tests

    out, subset_of = defaultdict(list), {}
    for jf in sorted(BENCH.glob("*.jsonl")):
        keep = [l for l in jf.open(encoding="utf-8")
                if slug(json.loads(l)["pdf"]) in pdfs_wanted]
        if not keep:
            continue
        tmp = Path(tmpdir) / jf.name
        tmp.write_text("".join(keep), encoding="utf-8")
        for t in load_tests(str(tmp)):
            out[slug(t.pdf)].append(t)
            subset_of[slug(t.pdf)] = jf.stem
    return out, subset_of


def wilson(k, n, z=1.96):
    """Wilson 区间。research-plan.md §4.5：每个分层必须带 n 与置信区间。"""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--skip-math", action="store_true",
                    help="math 类需要 playwright+KaTeX 渲染，跳过则该类记为未评")
    ap.add_argument("--diagnose-latex", action="store_true",
                    help="额外跑一遍反斜杠归一后的诊断口径，单列，不替代产品口径")
    a = ap.parse_args()

    run_dir = Path(a.run_dir)
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir():
        sys.exit(f"{raw_dir} 不存在")

    # 1) 读 runner 落盘，pdf -> (content, 是否有效)
    pages = {}
    for f in sorted(raw_dir.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        pages[slug(r["pdf"])] = r
    print(f"读入 {len(pages)} 页原始响应")

    # 2) 读官方测试定义（只加载本次覆盖到的 PDF）
    with tempfile.TemporaryDirectory() as td:
        tests_by_pdf, subset_of = filtered_tests(set(pages), td)
    n_tests = sum(len(v) for v in tests_by_pdf.values())
    print(f"加载 {n_tests} 条官方测试，覆盖 {len(tests_by_pdf)} 个 PDF")

    # 3) 逐条判定
    rows, skipped_math = [], 0
    bad_pages = []
    diag = {"n": 0, "pass_product": 0, "pass_unescaped": 0}
    for key, rec in sorted(pages.items()):
        tests = tests_by_pdf.get(key, [])
        # 产品口径：模型原始输出 -> SDK 的剥围栏后处理
        content = postprocess_doc2md(rec.get("content") or "")
        content_diag = unescape_latex(content) if a.diagnose_latex else None
        page_ok = rec.get("ok")
        if not page_ok:
            bad_pages.append({"pdf": rec["pdf"], "status": rec.get("status"),
                              "finish_reason": rec.get("finish_reason")})
        for t in tests:
            ttype = getattr(t.type, "value", str(t.type))
            if ttype == "math" and a.skip_math:
                skipped_math += 1
                continue
            if not page_ok:
                # 调用失败的页：所有测试判 fail，但单独标注原因，
                # 不要和「解析错了」混在一起解读
                passed, expl = False, f"page_call_failed status={rec.get('status')} " \
                                      f"finish={rec.get('finish_reason')}"
            else:
                try:
                    passed, expl = t.run(content)
                except Exception as e:  # 判定器自身异常单独标，不算模型失分
                    passed, expl = None, f"checker_error: {type(e).__name__}: {e}"
            if content_diag is not None and page_ok and passed is not None:
                try:
                    p2, _ = t.run(content_diag)
                except Exception:
                    p2 = None
                if p2 is not None:
                    diag["n"] += 1
                    diag["pass_product"] += int(passed)
                    diag["pass_unescaped"] += int(p2)
            rows.append({"subset": subset_of.get(key, "?"), "pdf": rec["pdf"],
                         "test_id": t.id, "type": ttype,
                         "pass": "" if passed is None else int(passed),
                         "explanation": (expl or "")[:300]})

    # 4) 落盘逐条结果
    res = run_dir / "olmocr_results.csv"
    with res.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["subset", "pdf", "test_id", "type",
                                           "pass", "explanation"])
        w.writeheader()
        w.writerows(rows)

    # 5) 分层汇总：按子集、按类型，各自带 n 与 Wilson 区间，不合成总分
    def agg(group_key):
        out = {}
        g = defaultdict(list)
        for r in rows:
            g[r[group_key]].append(r)
        for k, rs in sorted(g.items()):
            scored = [r for r in rs if r["pass"] != ""]
            errs = len(rs) - len(scored)
            k_pass = sum(r["pass"] for r in scored)
            lo, hi = wilson(k_pass, len(scored))
            out[k] = {"n_tests": len(scored), "n_pass": k_pass,
                      "pass_rate": round(k_pass / len(scored), 4) if scored else None,
                      "ci95": [lo, hi], "checker_errors": errs,
                      "n_pdfs": len({r["pdf"] for r in rs})}
        return out

    lats = [p["latency_s"] for p in pages.values() if p.get("ok")]
    summary = {
        "run_id": run_dir.name, "scored_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scorer": {"source": "allenai/olmocr olmocr/bench", "pinned_commit": "ab294c6a",
                   "vendored_at": "tools/vendor/olmocr", "reimplemented": False},
        "postprocess": "infinity_parser2 v0.4.0 postprocess_doc2md_result（逐字复制，只剥 ``` 围栏）",
        "diagnostic_latex_unescaped": (
            {"note": "诊断口径，非产品口径：把双写反斜杠归一为单写后重判",
             "n_tests": diag["n"], "pass_product": diag["pass_product"],
             "pass_unescaped": diag["pass_unescaped"]} if a.diagnose_latex else None),
        "caveats": [
            "只跑抽样子集，非全量 1403 PDF，不能直接与厂商 87.6% 比大小",
            "按子集与类型分层，不合成加权总分",
            "调用失败页(finish_reason!=stop)上的测试判 fail，另见 failed_pages",
            "headers_footers 全是 absent 断言，md 口径默认丢弃页眉页脚，天然高分",
        ],
        "n_pages": len(pages), "n_failed_pages": len(bad_pages),
        "failed_pages": bad_pages,
        "math_skipped": skipped_math,
        "page_latency_s": {"n": len(lats),
                           "median": round(statistics.median(lats), 1) if lats else None,
                           "p95": round(sorted(lats)[int(len(lats) * 0.95)], 1) if len(lats) > 1 else None},
        "by_subset": agg("subset"), "by_type": agg("type"),
    }
    (run_dir / "olmocr_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 打印
    print(f"\n按子集（每格 n 为该层测试数，CI 为 Wilson 95%）")
    print(f"{'子集':20} {'pdf':>4} {'tests':>6} {'pass':>6} {'通过率':>8}  95% CI")
    for k, v in summary["by_subset"].items():
        ci = f"[{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}]" if v["ci95"][0] is not None else "-"
        pr = f"{v['pass_rate']:.1%}" if v["pass_rate"] is not None else "-"
        print(f"{k:20} {v['n_pdfs']:4} {v['n_tests']:6} {v['n_pass']:6} {pr:>8}  {ci}")
    print(f"\n按类型")
    for k, v in summary["by_type"].items():
        ci = f"[{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}]" if v["ci95"][0] is not None else "-"
        pr = f"{v['pass_rate']:.1%}" if v["pass_rate"] is not None else "-"
        print(f"{k:20} {'':4} {v['n_tests']:6} {v['n_pass']:6} {pr:>8}  {ci}"
              + (f"  判定器异常 {v['checker_errors']}" if v["checker_errors"] else ""))
    if a.diagnose_latex and diag["n"]:
        print(f"\n诊断口径（非产品口径）：反斜杠双写归一后重判 {diag['n']} 条，"
              f"通过 {diag['pass_product']} -> {diag['pass_unescaped']}。"
              f"\n差值即 doc2md 双写转义这一个 bug 造成的失分，两个数字分开报。")
    if bad_pages:
        print(f"\n！调用失败 {len(bad_pages)} 页，其上测试全部判 fail：")
        for b in bad_pages[:5]:
            print(f"   {b['pdf']}  status={b['status']} finish={b['finish_reason']}")
    print(f"\n-> {res}\n-> {run_dir / 'olmocr_summary.json'}")
    print("不合成总分：按子集看，且 headers_footers 那一行要带口径注释读。")


if __name__ == "__main__":
    main()
