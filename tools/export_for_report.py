#!/usr/bin/env python3
"""
导出成文所需的全部数据，汇成一个 report_input.md

**为什么用脚本而不是让 AI 助手总结**：让 AI 用自然语言转述数字，是最容易出错的环节——
四舍五入、合并分层、把「未观察到显著差异」改写成「持平」。本项目的可信度建立在
「每个数字都能追溯到文件」上，中间不能过一道 AI 的手。本脚本只读文件、只做确定性计算，
输出原样贴给成文的人。

**安全**：不导出响应头（Azure 的 Operation-Location 含资源端点地址），
输出前扫描并脱敏端点 URL 与疑似密钥，脱敏条数会打印出来。

自动发现：
  runs/inf-mllm_doc2md_20260921T013924Z   Infinity 自建集
  runs/inf-mllm_doc2md_20260918T065831Z   Infinity olmOCR-Bench
  runs/azure_di_layout_*/results.csv       Azure 自建集
  runs/azure_di_layout_*/olmocr_results.csv Azure olmOCR-Bench
  runs/consistency/summary.json            重复一致性

用法:
  python tools/export_for_report.py
  python tools/export_for_report.py --examples 20     # 每个方向的差异样例条数
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
from compare_systems import mcnemar, wilson  # noqa: E402  与对照工具同一套统计

INF_CORPUS = "inf-mllm_doc2md_20260921T013924Z"
INF_BENCH = "inf-mllm_doc2md_20260918T065831Z"

REDACT = [
    (re.compile(r"https?://[^\s\"'`)]*(?:cognitiveservices|azure|openapi-inspire)[^\s\"'`)]*", re.I),
     "<端点已脱敏>"),
    # 注意 Bearer 后面才是真正的 token。第一版只吃掉了「Bearer」这个词，
    # token 本身漏了出来——单测时发现的
    (re.compile(r"(?i)(ocp-apim-subscription-key|api[_-]?key|authorization)\s*[:=]\s*(?:bearer\s+)?\S+"),
     r"\1: <已脱敏>"),
    (re.compile(r"\b[0-9a-f]{32}\b"), "<疑似密钥已脱敏>"),
]


def slug(p):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(p).removesuffix(".pdf"))


def pp(t):
    """SDK 的 postprocess_doc2md_result，只剥 ``` 围栏。"""
    t = (t or "").strip()
    t = re.sub(r"^```markdown\s*\n?", "", t)
    t = re.sub(r"^```\s*\n?", "", t)
    t = re.sub(r"\n?```$", "", t)
    return t.strip()


def pct(k, n):
    return f"{k / n:.1%}" if n else "-"


def ci_str(k, n):
    lo, hi = wilson(k, n)
    return f"[{lo:.3f}, {hi:.3f}]" if lo is not None else "-"


def read_csv(p):
    return list(csv.DictReader(open(p, encoding="utf-8"))) if Path(p).exists() else []


def load_raw(run_dir):
    out = {}
    for f in (Path(run_dir) / "raw").glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out[f.stem] = r
    return out


def snippet(content, target, width=70):
    """在输出里找目标附近的上下文。目标可能跨行，所以按字符间允许空白来找。"""
    if not content or not target:
        return "（无）"
    t = re.sub(r"\s+", "", str(target))[:24]
    if not t:
        return "（无）"
    pat = r"\s*".join(re.escape(ch) for ch in t)
    m = re.search(pat, content)
    if not m:
        return "（输出中未找到）"
    a, b = max(0, m.start() - width), min(len(content), m.end() + width)
    s = content[a:b].replace("\n", " ⏎ ")
    return ("…" if a else "") + s + ("…" if b < len(content) else "")


def bucket(why):
    """把 check.py 的判定说明归成失败模式。"""
    w = why or ""
    if w.startswith("page_call_failed"):
        return "调用失败"
    if "forbidden form" in w:
        return "格式错（如丢千分位、小数点错位）"
    if "label not found" in w:
        return "科目标签缺失"
    if "label-amount gap" in w:
        return "金额与科目分离（归属错）"
    if "amount not found" in w:
        return "漏读"
    m = re.search(r"expected (?:exactly once|\d+), found (\d+)", w)
    if m:
        found = int(m.group(1))
        exp = re.search(r"expected (\d+)", w)
        want = int(exp.group(1)) if exp else 1
        if found == 0:
            return "漏读"
        return "多出（重复）" if found > want else "少了部分出现"
    if w.startswith("not found"):
        return "漏读"
    return "其他"


def service_stats(run_dir):
    """从 raw 算延迟分布，从 run_summary 取吞吐与计数。不含任何响应头。"""
    rs = {}
    p = Path(run_dir) / "run_summary.json"
    if p.exists():
        s = json.loads(p.read_text(encoding="utf-8"))
        for k in ("finished_utc", "wall_s", "counts", "throughput_pages_per_min",
                  "tokens", "estimated_cost_usd", "n_pages"):
            if k in s:
                rs[k] = s[k]
    m = Path(run_dir) / "run_meta.json"
    if m.exists():
        s = json.loads(m.read_text(encoding="utf-8"))
        for k in ("started_utc", "system", "model_id", "api_version", "model_requested",
                  "task_type", "output_content_format", "conversion_by_us",
                  "concurrency", "params"):
            if k in s:
                rs[k] = s[k]
    lats, fails, served, conf, polls = [], [], Counter(), Counter(), []
    for r in load_raw(run_dir).values():
        if r.get("ok"):
            lats.append(r.get("latency_s") or 0)
            if r.get("n_polls") is not None:
                polls.append(r["n_polls"])
        else:
            body = (r.get("attempts") or [{}])[-1].get("response_body") if r.get("attempts") else None
            err = ""
            if isinstance(body, dict):
                err = str(body.get("error") or body.get("_exception") or body.get("_error") or "")[:120]
            fails.append({"pdf": r.get("pdf"), "page": r.get("page"), "status": r.get("status"),
                          "finish_reason": r.get("finish_reason"),
                          "op_status": r.get("op_status"), "error": err})
        served[str(r.get("served_model"))] += 1
        if "has_confidence" in r:
            conf[bool(r["has_confidence"])] += 1
    lats.sort()
    rs["latency_s"] = ({"n": len(lats), "median": round(statistics.median(lats), 1),
                        "p95": round(lats[int(len(lats) * 0.95)], 1) if len(lats) > 1 else None,
                        "max": round(lats[-1], 1)} if lats else None)
    rs["served_model"] = dict(served)
    if conf:
        rs["has_confidence"] = {str(k): v for k, v in conf.items()}
    if polls:
        rs["azure_polls_median"] = statistics.median(polls)
    rs["failed_pages"] = fails
    return rs


def paired(A, B, key, strata):
    """A、B 为 {id: (pass, meta)}。返回分层配对结果。"""
    common = sorted(set(A) & set(B))
    g = defaultdict(list)
    for k in common:
        pa, meta = A[k]
        pb, _ = B[k]
        g[("全部", "")].append((pa, pb))
        for s in strata:
            g[(s, meta.get(s, ""))].append((pa, pb))
    rows = []
    for (dim, val), pairs in sorted(g.items(), key=lambda x: (x[0][0] != "全部", x[0])):
        n = len(pairs)
        ka, kb = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
        b = sum(1 for x, y in pairs if x == 1 and y == 0)
        c = sum(1 for x, y in pairs if x == 0 and y == 1)
        p, _ = mcnemar(b, c)
        verdict = ("样本不足，不下结论" if n < 30 else
                   "未观察到显著差异" if p >= 0.05 else
                   ("Infinity 显著更高" if b > c else "Azure 显著更高"))
        rows.append({"分层": f"{dim}={val}" if dim != "全部" else "全部（非加权总分）",
                     "n": n, "Infinity": pct(ka, n), "Azure": pct(kb, n),
                     "Inf_CI": ci_str(ka, n), "Az_CI": ci_str(kb, n),
                     "只有Inf对(b)": b, "只有Az对(c)": c, "p": round(p, 4), "判读": verdict})
    return rows, len(common), len(A) - len(common), len(B) - len(common)


def md_table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--examples", type=int, default=15)
    ap.add_argument("--out", default="report_input.md")
    a = ap.parse_args()
    R = Path(a.runs_dir)

    # ---- 发现 run ----
    az_corpus = sorted(p for p in R.glob("azure_di_layout_*") if (p / "results.csv").exists())
    az_bench = sorted(p for p in R.glob("azure_di_layout_*") if (p / "olmocr_results.csv").exists())
    inf_corpus, inf_bench = R / INF_CORPUS, R / INF_BENCH
    L = []
    L.append(f"# 成文输入数据\n\n生成于 {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
             f"，由 tools/export_for_report.py 确定性导出，**未经任何人工或 AI 转述**。\n")

    # ---- 断言版本与审核状态 ----
    h = hashlib.sha256()
    st, ty = Counter(), Counter()
    for f in sorted(Path("data/assertions").glob("*.yaml")):
        h.update(f.read_bytes())
        for it in yaml.safe_load(f.read_text(encoding="utf-8"))["assertions"]:
            st[it.get("status")] += 1
            ty[it["type"]] += 1
    L.append("## 0. 断言版本与人工审核状态\n")
    L.append(f"- 断言目录指纹：`{h.hexdigest()[:12]}`（两边必须基于同一版断言判定）")
    L.append(f"- 按类型：{dict(ty)}")
    L.append(f"- 按状态：{dict(st)}")
    L.append(f"- 人工审核：{'**未完成**，draft 仍有 ' + str(st['draft']) + ' 条' if st['draft'] else '已完成'}"
             f"；confirmed {st['confirmed']}，rejected {st['rejected']}\n")
    L.append(f"- 发现的 run：Infinity 自建集 `{inf_corpus.name}` {'✓' if inf_corpus.exists() else '✗ 缺'}；"
             f"Infinity 基准 `{inf_bench.name}` {'✓' if inf_bench.exists() else '✗ 缺'}；"
             f"Azure 自建集 {[p.name for p in az_corpus] or '✗ 缺'}；"
             f"Azure 基准 {[p.name for p in az_bench] or '✗ 缺'}\n")
    if len(az_corpus) > 1 or len(az_bench) > 1:
        L.append("> ！发现多个 Azure run，以下取最新一个。请确认这是你要用的那次。\n")

    # 过期检查：results.csv 若是用旧版断言判的，配对结果会错且看不出来。
    # 逐条比对 results.csv 里记录的目标值与当前断言文件，不一致即过期。
    cur = {}
    for f in Path("data/assertions").glob("*.yaml"):
        for it in yaml.safe_load(f.read_text(encoding="utf-8"))["assertions"]:
            cur[it["id"]] = str(it.get("target"))[:80]
    stale_any = False
    for label, rd in [("Infinity 自建集", inf_corpus), ("Azure 自建集", az_corpus[-1] if az_corpus else None)]:
        if not rd or not (rd / "results.csv").exists():
            continue
        rows_ = read_csv(rd / "results.csv")
        bad = sum(1 for r in rows_ if r["assertion_id"] in cur and r["target"] != cur[r["assertion_id"]])
        gone = sum(1 for r in rows_ if r["assertion_id"] not in cur)
        if bad or gone:
            stale_any = True
            L.append(f"> ！**{label} 的 results.csv 基于旧版断言**：{bad} 条目标值与当前断言不符，"
                     f"{gone} 条断言已不存在。**必须先重跑** `python tools/check.py runs/{rd.name}`，"
                     "否则下面的配对结果无效。\n")
    if not stale_any:
        L.append("- 过期检查：两边 results.csv 均与当前断言一致 ✓\n")

    # ---- 服务档 ----
    L.append("## 1. 服务档（延迟 / 吞吐 / 失败页 / 成本）\n")
    for label, rd in [("Infinity 自建集", inf_corpus), ("Infinity 基准", inf_bench),
                      ("Azure 自建集", az_corpus[-1] if az_corpus else None),
                      ("Azure 基准", az_bench[-1] if az_bench else None)]:
        if not rd or not rd.exists():
            L.append(f"### {label}\n\n（缺）\n")
            continue
        L.append(f"### {label} · `{rd.name}`\n\n```json\n"
                 + json.dumps(service_stats(rd), ensure_ascii=False, indent=1) + "\n```\n")

    # ---- 自建集：分层 + 配对 ----
    L.append("## 2. 第三层 自建金融场景集（决定性证据）\n")
    if inf_corpus.exists() and az_corpus:
        az = az_corpus[-1]
        ri, ra = read_csv(inf_corpus / "results.csv"), read_csv(az / "results.csv")

        def as_map(rows):
            return {r["assertion_id"]: (int(r["pass"]), r) for r in rows if r.get("pass") not in ("", None)}
        A, B = as_map(ri), as_map(ra)
        rows, nc, oa, ob = paired(A, B, "assertion_id", ["type", "family", "window"])
        L.append(f"公共断言 {nc} 条（只在 Infinity 侧 {oa}、只在 Azure 侧 {ob}，已排除）。"
                 "McNemar 配对检验；p≥0.05 写「未观察到显著差异」，n<30 写「样本不足」。\n")
        L.append(md_table(rows, ["分层", "n", "Infinity", "Azure", "Inf_CI", "Az_CI",
                                 "只有Inf对(b)", "只有Az对(c)", "p", "判读"]) + "\n")

        # 失败模式
        L.append("### 失败模式分布\n")
        fm = defaultdict(Counter)
        for name, rs_ in (("Infinity", ri), ("Azure", ra)):
            for r in rs_:
                if r.get("pass") == "0":
                    fm[(r["type"], bucket(r["why"]))][name] += 1
        fmr = [{"类型": t, "失败模式": b_, "Infinity": c.get("Infinity", 0), "Azure": c.get("Azure", 0)}
               for (t, b_), c in sorted(fm.items())]
        L.append(md_table(fmr, ["类型", "失败模式", "Infinity", "Azure"]) + "\n")

        # 差异样例
        raw_i, raw_a = load_raw(inf_corpus), load_raw(az)
        docs = {}
        for f in Path("data/assertions").glob("*.yaml"):
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            docs[d["doc_id"]] = d["local_path"]
        for title, cond in (("只有 Infinity 对（Azure 错）", lambda x, y: x == 1 and y == 0),
                            ("只有 Azure 对（Infinity 错）", lambda x, y: x == 0 and y == 1)):
            ids = [k for k in sorted(set(A) & set(B)) if cond(A[k][0], B[k][0])]
            L.append(f"### 差异样例：{title}，共 {len(ids)} 条，列前 {min(len(ids), a.examples)} 条\n")
            for k in ids[:a.examples]:
                r_i, r_a = A[k][1], B[k][1]
                key = f"{slug(docs.get(r_i['doc_id'], ''))}_p{r_i['page']}"
                ci = pp((raw_i.get(key) or {}).get("content"))
                ca = pp((raw_a.get(key) or {}).get("content"))
                L.append(f"- `{k}` · {r_i['type']} · {r_i['family']}/{r_i['window']} 第 {r_i['page']} 页\n"
                         f"  - 目标：`{r_i['target']}`\n"
                         f"  - Infinity：{r_i['why']} ｜ {snippet(ci, r_i['target'])}\n"
                         f"  - Azure：{r_a['why']} ｜ {snippet(ca, r_i['target'])}")
            L.append("")
    else:
        L.append("（缺 Infinity 或 Azure 自建集结果，无法配对）\n")

    # ---- olmOCR-Bench ----
    L.append("## 3. 第二层 olmOCR-Bench（准入门槛，厂商曾在此报分）\n")
    if inf_bench.exists() and az_bench:
        azb = az_bench[-1]
        bi, ba = read_csv(inf_bench / "olmocr_results.csv"), read_csv(azb / "olmocr_results.csv")

        def bmap(rows):
            return {r["test_id"]: (int(r["pass"]), r) for r in rows if r.get("pass") not in ("", None)}
        BA, BB = bmap(bi), bmap(ba)
        rows, nc, oa, ob = paired(BA, BB, "test_id", ["subset", "type"])
        L.append(f"公共测试 {nc} 条（只在 Infinity 侧 {oa}、只在 Azure 侧 {ob}）。\n")
        L.append(md_table(rows, ["分层", "n", "Infinity", "Azure", "Inf_CI", "Az_CI",
                                 "只有Inf对(b)", "只有Az对(c)", "p", "判读"]) + "\n")
        for name, rd in (("Infinity", inf_bench), ("Azure", azb)):
            p = rd / "olmocr_summary.json"
            if p.exists():
                s = json.loads(p.read_text(encoding="utf-8"))
                keep = {k: s.get(k) for k in ("n_failed_pages", "failed_pages", "math_skipped",
                                              "diagnostic_latex_unescaped", "page_latency_s")}
                L.append(f"{name} olmocr_summary 摘要：\n```json\n"
                         + json.dumps(keep, ensure_ascii=False, indent=1) + "\n```\n")
        for title, cond in (("只有 Infinity 对", lambda x, y: x == 1 and y == 0),
                            ("只有 Azure 对", lambda x, y: x == 0 and y == 1)):
            ids = [k for k in sorted(set(BA) & set(BB)) if cond(BA[k][0], BB[k][0])]
            L.append(f"### 基准差异样例：{title}，共 {len(ids)} 条，列前 {min(len(ids), 10)} 条\n")
            for k in ids[:10]:
                L.append(f"- `{k}` · {BA[k][1]['subset']}/{BA[k][1]['type']}："
                         f"Inf「{BA[k][1]['explanation'][:90]}」／Az「{BB[k][1]['explanation'][:90]}」")
            L.append("")
    else:
        L.append("（缺 Infinity 或 Azure 基准结果，无法配对）\n")

    # ---- 一致性 ----
    cp = R / "consistency" / "summary.json"
    if cp.exists():
        s = json.loads(cp.read_text(encoding="utf-8"))
        L.append("## 4. Infinity 重复一致性（3 次调用）\n\n```json\n"
                 + json.dumps({k: s.get(k) for k in ("n_runs", "n_pages_all_ok",
                               "level1_exact_identical", "level2_normalized_identical",
                               "level3_assertion_flip")}, ensure_ascii=False, indent=1)
                 + "\n```\n\nAzure 未做重复调用。流水线式 OCR 通常同输入同输出，"
                 "但**本评测未对 Azure 实测验证这一点**，报告里不得写成已测结论。\n")

    text = "\n".join(L)
    n_red = 0
    for pat, rep in REDACT:
        text, k = pat.subn(rep, text)
        n_red += k
    Path(a.out).write_text(text, encoding="utf-8")
    kb = len(text.encode("utf-8")) / 1024
    print(f"-> {a.out}  {kb:.0f} KB  脱敏 {n_red} 处")
    if kb > 120:
        print("！文件较大，粘贴可能被截断。可用 --examples 8 减少样例条数")


if __name__ == "__main__":
    main()
