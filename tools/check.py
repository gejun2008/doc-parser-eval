#!/usr/bin/env python3
"""
断言判定器 (T5)

读 data/assertions/*.yaml 与 runs/<run_id>/raw/，逐条判 pass/fail，
输出 runs/<run_id>/results.csv 与 results_summary.json。

**只执行 status 为 auto 或 confirmed 的断言。**
draft 未经人工核对，执行它等于拿可能错的 GT 去判模型，结果不可信；
rejected 是人工判定为无效的。两者都记数但不判，出现在报告的「未执行」一栏。

判定口径:
  eval_on: md    对 content 套 SDK 的 postprocess_doc2md_result（只剥 ``` 围栏）
  eval_on: json  对 layout JSON 判（sdk-findings.md §5），本轮 md 口径暂不支持

  文本比对前做空白归一：模型会把 PDF 的硬换行合并成段落，
  而锚点串取自文本层的物理行。不归一会产生大量假失败。
  归一 = 去掉所有空白字符（中文无词间空格，英文合并后也不受影响）。
  **这一步会放宽判定**，等于不检查空格与换行是否正确——
  格式类问题由 formatting 类断言单独负责，不在这里混判。

用法:
  python tools/check.py runs/<run_id>
  python tools/check.py runs/<run_id> --include-draft   # 仅用于调试，结果不可进报告
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ASSERT_DIR = Path("data/assertions")


def postprocess_doc2md(text):
    """逐字复制自 infinity_parser2/utils/utils.py 的 postprocess_doc2md_result。"""
    text = (text or "").strip()
    text = re.sub(r"^```markdown\s*\n?", "", text)
    text = re.sub(r"^```\s*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def norm(s):
    """空白归一。见模块 docstring 中对判定放宽的说明。"""
    return re.sub(r"\s+", "", s or "")


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def slug(pdf_rel):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(pdf_rel).removesuffix(".pdf"))


def judge(a, content_n):
    """返回 (pass, 说明)。content_n 已空白归一。"""
    t = a.get("target")
    if t is None:
        return None, "assertion_missing_target"
    tn = norm(str(t))
    if not tn:
        return None, "assertion_empty_target"
    cnt = content_n.count(tn)
    rule = a.get("rule", "exactly_once")

    if rule == "exactly_once" and cnt != 1:
        return False, f"expected exactly once, found {cnt}"
    if rule == "at_least_once" and cnt < 1:
        return False, "not found"

    for f in (a.get("forbid") or []):
        fn = norm(str(f))
        if fn and fn != tn and fn in content_n:
            return False, f"forbidden form present: {f}"
    return True, f"found x{cnt}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--include-draft", action="store_true",
                    help="调试用。draft 未经人工核对，结果不可进报告")
    a = ap.parse_args()

    run_dir = Path(a.run_dir)
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir():
        sys.exit(f"{raw_dir} 不存在")

    # 页 -> 原始响应
    pages = {}
    for f in raw_dir.glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        pages[(slug(r["pdf"]), r["page"])] = r
    print(f"读入 {len(pages)} 页原始响应")

    allowed = {"auto", "confirmed"} | ({"draft"} if a.include_draft else set())
    rows, skipped, missing_pages = [], Counter(), set()

    for yf in sorted(ASSERT_DIR.glob("*.yaml")):
        d = yaml.safe_load(yf.read_text(encoding="utf-8"))
        key_base = slug(d["local_path"])
        for it in d["assertions"]:
            st = it.get("status", "draft")
            if st not in allowed:
                skipped[st] += 1
                continue
            rec = pages.get((key_base, it["page"]))
            if rec is None:
                missing_pages.add((d["doc_id"], it["page"]))
                continue
            if it.get("eval_on") == "json":
                skipped["eval_on_json_unsupported"] += 1
                continue

            if not rec.get("ok"):
                ok, why = False, (f"page_call_failed status={rec.get('status')} "
                                  f"finish={rec.get('finish_reason')}")
            else:
                ok, why = judge(it, norm(postprocess_doc2md(rec.get("content"))))
            rows.append({
                "doc_id": d["doc_id"], "family": d["family"], "window": d["window"],
                "page": it["page"], "assertion_id": it["id"], "type": it["type"],
                "severity": it.get("severity", ""), "status": st,
                "pass": "" if ok is None else int(ok),
                "target": str(it.get("target"))[:80], "why": why[:160],
            })

    if not rows:
        sys.exit("没有可执行的断言。先用 tools/review_assertions.py 审核草稿。")

    out = run_dir / "results.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def agg(*keys):
        g = defaultdict(list)
        for r in rows:
            g[tuple(r[k] for k in keys)].append(r)
        out = {}
        for k, rs in sorted(g.items()):
            scored = [r for r in rs if r["pass"] != ""]
            kp = sum(r["pass"] for r in scored)
            lo, hi = wilson(kp, len(scored))
            out[" / ".join(k)] = {
                "n": len(scored), "pass": kp,
                "rate": round(kp / len(scored), 4) if scored else None,
                "ci95": [lo, hi], "errors": len(rs) - len(scored),
                "n_docs": len({r["doc_id"] for r in rs})}
        return out

    summary = {
        "run_id": run_dir.name,
        "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "executed": len(rows), "skipped": dict(skipped),
        "include_draft": a.include_draft,
        "caveats": [
            "只执行 status=auto/confirmed 的断言；draft 未经人工核对不判",
            "文本比对做了空白归一，等于不检查空格与换行",
            "按族与窗口分层，不合成加权总分",
            "分层样本量小，多数分层不足以做显著性判断",
        ],
        "by_type": agg("type"),
        "by_family": agg("family"),
        "by_family_window": agg("family", "window"),
        "by_type_window": agg("type", "window"),
    }
    (run_dir / "results_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def show(title, table):
        print(f"\n{title}")
        print(f"{'分层':34} {'n':>5} {'pass':>5} {'通过率':>8}  95% CI")
        for k, v in table.items():
            ci = (f"[{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}]"
                  if v["ci95"][0] is not None else "-")
            rate = f"{v['rate']:.1%}" if v["rate"] is not None else "-"
            print(f"{k:34} {v['n']:5} {v['pass']:5} {rate:>8}  {ci}")

    show("按类型", summary["by_type"])
    show("按文档族", summary["by_family"])
    show("按族 × 窗口（泄漏对照看这张）", summary["by_family_window"])
    if skipped:
        print(f"\n未执行：{dict(skipped)}")
    if missing_pages:
        print(f"！{len(missing_pages)} 个断言指向的页不在本次 run 里")
    print(f"\n-> {out}\n-> {run_dir / 'results_summary.json'}")


if __name__ == "__main__":
    main()
