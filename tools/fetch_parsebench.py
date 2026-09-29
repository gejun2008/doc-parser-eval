#!/usr/bin/env python3
"""
ParseBench 分层子集（500 份文档）抽样与下载（research-plan.md §3.2 第二层 · 中立公开基准）

数据集: llamaindex/ParseBench (Apache-2.0)，钉在 HF revision REV。
全量 2,078 页 / 1,211 份来源文档 / 169,011 条规则，五个维度:
  table / chart / text_content / text_formatting / layout(visual grounding)
每个文件都是从来源文档抽出的单页（PDF 为主，layout 有少量 JPG/PNG）。
text_content 与 text_formatting 共用 docs/text 下同一批文件，抽一份两个维度都评。

厂商在 ParseBench 上自报 74.3%（Pro）/ 72.2%（Flash，FinIE 站点），
与 olmOCR-Bench 一样有泄漏风险，只能当准入门槛，不能当结论依据（research-plan.md §2.1）。

抽样口径（报告附录要能复现）:
  - 按维度配额 QUOTA，维度内按 tag 分层（难度 / 文档类型 / 图表类型 / 输入格式）
  - 同一来源文档最多抽 CAP 页：table 的 503 页里 178 页来自两份 SERFF 保险费率申报，
    不设上限的话「500 份不同文档」会退化成少数几份文档的连续页
  - random.Random(f"{seed}:{dim}:{stratum}")，SEED 固定，任何人重跑得到同一批文件
  - table/hard 下限 40 份（STRATUM_FLOOR），其余层按总体比例，每层至少 6 份
  - domain_guess 是按文件名关键词的**启发式标签**，只用于报告里看覆盖面，不参与分层，
    不能当领域结论（数据集本身没有领域字段）

产物（data/parsebench/subset/ 可直接当 parse-bench 的 --input_dir）:
  data/parsebench/subset/{chart,table,text_content,text_formatting,layout}.jsonl  过滤后的规则
  data/parsebench/subset/docs/...                                               抽中的文件
  data/parsebench/manifest.csv       每份文件一行：维度、分层、sha256、来源文档、领域猜测
  data/parsebench/subset_meta.json   配额、seed、revision、各层实际数量

用法:
  python tools/fetch_parsebench.py              # 先下全量 jsonl（~70MB），再抽样、下载文件
  python tools/fetch_parsebench.py --dry-run    # 只打印抽样结果，不下载文件
"""

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

REV = "2805a1d940f95a203e0ae4b88be9934f7765b3fc"   # 2026-04-19，钉死
REPO = f"https://huggingface.co/datasets/llamaindex/ParseBench/resolve/{REV}"
ROOT = Path("data/parsebench")
SUBSET = ROOT / "subset"
SEED = 20260929
JSONL = ["chart", "table", "text_content", "text_formatting", "layout"]

# 维度 -> (配额, 单一来源文档页数上限)。合计 500。
# table 给最多：金融文档第一痛点；text 一份同时评两个维度。
QUOTA = {
    "table": (130, 6),
    "text": (150, 1),      # docs/text 每份文件本身就是独立文档
    "layout": (120, 2),
    "chart": (100, 3),
}

# 维度内分层的最低份数（小层整层拿走）
MIN_PER_STRATUM = 6
# 个别层的下限上调：按比例 table/hard 只分到 23 份，难表格是金融场景重点
STRATUM_FLOOR = {("table", "hard"): 40}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_doc(pdf):
    """来源文档 id：去掉 _p12 / _page12 / _pg12 页码后缀。"""
    stem = pdf.rsplit("/", 1)[1].rsplit(".", 1)[0]
    return re.sub(r"(_p|_page|_pg)\d+$", "", stem)


# 启发式领域标签。按顺序匹配第一个命中的；都不中记 other。
DOMAIN_RULES = [
    ("synthetic_test", r"synthetic|^test$|^hard$|^llama$|^llong$|long-table|layout with|"
                       r"^\d-column|tabular_\d|drill angle|sparse and no|^p\d+$"),
    ("insurance", r"serff|insur|annuit|\blic\b|ltc|rate.?table|actuar|underwrit|"
                  r"catastroph|sigma|reinsur|axa_|aon"),
    ("financial_filing", r"10-?k|10-?q|def.?14a|proxy|annual.?report|_ar\d|ar20\d\d|urd|"
                         r"integrated.?report|accounts|earnings|\d{10}-\d{2}-\d{6}|"
                         r"^[A-Z]{2,5}\.\d{4}\.page|fund|capital|invest|bank|financ|"
                         r"credit|equity|asset|securit|treasury|derivativ|memorandum|"
                         r"offering|tsla|_ecr_|sri-|q[1-4]"),
    ("government_intl", r"gov|survey|europe|\beu\b|oecd|-en$|world|united.?nations|"
                        r"census|ministry|federal|public|social|employment|education|"
                        r"bls-|tdr20|wtr2|she-figures|eis$"),
    ("energy_climate", r"energy|renewabl|climate|weather|pv.?market|drought|emission"),
    ("healthcare", r"hospital|clinical|guideline|nurse|medic"),
    ("business_industry", r"sustainab|esg|impact|report|presentation|brochure|catalog|"
                          r"market|megatrend|sector|industry|consult|outlook|study|"
                          r"automotive|deloitte|salesforce|professional"),
]
def domain_guess(pdf):
    s = source_doc(pdf)
    if pdf.startswith("docs/text/"):
        return "text_suite"          # 文本维度的人工构造集，文件名只描述版式，不描述领域
    for name, pat in DOMAIN_RULES:
        if re.search(pat, s, flags=re.I):
            return name
    return "unknown"                 # 文件名是哈希或内部编号，看不出领域


def ensure_jsonl():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in JSONL:
        dst = ROOT / f"{name}.jsonl"
        if dst.exists() and dst.stat().st_size > 0:
            continue
        print(f"下载 {name}.jsonl ...")
        r = requests.get(f"{REPO}/{name}.jsonl", timeout=600)
        r.raise_for_status()
        dst.write_bytes(r.content)


def load_rules():
    """{jsonl 名: {pdf: [rule, ...]}}"""
    out = {}
    for name in JSONL:
        g = defaultdict(list)
        for line in (ROOT / f"{name}.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            g[r["pdf"]].append(r)
        out[name] = g
    return out


def stratum(dim, pdf, rules):
    """页面级分层键。tag 在页面内一致（已核对）。"""
    tags = set(rules[0].get("tags") or [])
    if dim == "table":
        return "hard" if "hard" in tags else "easy"
    if dim == "chart":
        if "3d_chart" in tags:
            return "3d"
        return "need_estimate" if "need_estimate" in tags else "exact"
    if dim == "layout":
        diff = "hard" if "hard" in tags else "easy"
        kind = "image" if pdf.lower().endswith((".png", ".jpg", ".jpeg")) else "pdf"
        return f"{diff}/{kind}"
    if dim == "text":
        kinds = sorted(tags - {"easy", "hard"})
        return kinds[0] if kinds else "untagged"
    raise ValueError(dim)


def allocate(sizes, total, floor, overrides=None):
    """按层大小比例分配 total，每层至少 min(floor, 层大小)。最大余数法补齐。"""
    overrides = overrides or {}
    alloc = {k: min(overrides.get(k, floor), n) for k, n in sizes.items()}
    left = total - sum(alloc.values())
    rest = {k: n - alloc[k] for k, n in sizes.items()}
    pool = sum(rest.values())
    if left <= 0 or pool == 0:
        return alloc
    raw = {k: left * rest[k] / pool for k in sizes}
    for k in sizes:
        alloc[k] += min(rest[k], int(raw[k]))
    short = total - sum(alloc.values())
    for k in sorted(sizes, key=lambda k: raw[k] - int(raw[k]), reverse=True):
        if short <= 0:
            break
        if alloc[k] < sizes[k]:
            alloc[k] += 1
            short -= 1
    return alloc


def pick_dim(dim, pages, quota, cap, seed):
    """pages: {pdf: rules}。先分层，再在层内按来源文档轮转抽，保证每份来源不超过 cap。"""
    by_stratum = defaultdict(list)
    for pdf, rules in pages.items():
        by_stratum[stratum(dim, pdf, rules)].append(pdf)
    alloc = allocate({k: len(v) for k, v in by_stratum.items()}, quota, MIN_PER_STRATUM,
                     {st: n for (d, st), n in STRATUM_FLOOR.items() if d == dim})

    used_per_src = Counter()
    chosen = {}
    for st in sorted(by_stratum):
        rng = random.Random(f"{seed}:{dim}:{st}")
        cands = sorted(by_stratum[st])
        rng.shuffle(cands)
        # 按来源文档轮转：第一轮每份来源取 1 页，第二轮再取 1 页……
        by_src = defaultdict(list)
        for p in cands:
            by_src[source_doc(p)].append(p)
        order, rnd = [], 0
        while any(by_src.values()):
            for src in sorted(by_src, key=lambda s: rng.random()):
                if by_src[src]:
                    order.append(by_src[src].pop(0))
            rnd += 1
        take = []
        for p in order:
            if len(take) >= alloc[st]:
                break
            if used_per_src[source_doc(p)] >= cap:
                continue
            take.append(p)
            used_per_src[source_doc(p)] += 1
        for p in take:
            chosen[p] = st
    return chosen, alloc, {k: len(v) for k, v in by_stratum.items()}


def download(pdf):
    dst = SUBSET / pdf
    if dst.exists() and dst.stat().st_size > 0:
        data = dst.read_bytes()
        return pdf, len(data), hashlib.sha256(data).hexdigest()[:16], "cached"
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(f"{REPO}/{quote(pdf)}", timeout=180)
    r.raise_for_status()
    dst.write_bytes(r.content)
    return pdf, len(r.content), hashlib.sha256(r.content).hexdigest()[:16], "downloaded"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ensure_jsonl()
    rules = load_rules()
    # 维度 -> {pdf: rules}；text 用 text_content 的文件集合（formatting 是其子集）
    dims = {
        "table": rules["table"], "chart": rules["chart"], "layout": rules["layout"],
        "text": rules["text_content"],
    }
    chosen, report = {}, {}
    for dim, (quota, cap) in QUOTA.items():
        c, alloc, sizes = pick_dim(dim, dims[dim], quota, cap, a.seed)
        chosen.update({p: (dim, st) for p, st in c.items()})
        got = Counter(c.values())
        report[dim] = {"quota": quota, "cap_per_source": cap, "picked": len(c),
                       "strata": {st: {"population": sizes[st], "alloc": alloc[st],
                                       "picked": got.get(st, 0)} for st in sorted(sizes)},
                       "source_docs": len({source_doc(p) for p in c})}
        print(f"{dim:8} 配额 {quota:3}  抽中 {len(c):3}  来源文档 {report[dim]['source_docs']:3}  "
              + "  ".join(f"{st}={got.get(st, 0)}/{sizes[st]}" for st in sorted(sizes)))
    print(f"合计 {len(chosen)} 份文件")
    doms = Counter(domain_guess(p) for p in chosen)
    print("领域（启发式）:", dict(doms.most_common()))
    if a.dry_run:
        return

    SUBSET.mkdir(parents=True, exist_ok=True)
    results = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for pdf, size, sha, how in ex.map(download, sorted(chosen)):
            results[pdf] = (size, sha, how)
    cached = sum(1 for v in results.values() if v[2] == "cached")
    print(f"下载 {len(results) - cached} 个，跳过已存在 {cached} 个")

    # 过滤后的 jsonl：parse-bench 的 --input_dir 直接可用
    n_rules = Counter()
    for name in JSONL:
        with (SUBSET / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for pdf in sorted(rules[name]):
                if pdf in chosen:
                    for r in rules[name][pdf]:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                        n_rules[name] += 1

    with (ROOT / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dimension", "stratum", "pdf", "sha256_16", "bytes", "source_doc",
                    "domain_guess", "tags", "n_rules"])
        for pdf in sorted(chosen):
            dim, st = chosen[pdf]
            names = ["text_content", "text_formatting"] if dim == "text" else [dim]
            nr = sum(len(rules[n].get(pdf, [])) for n in names)
            tags = ";".join(sorted(set((dims[dim][pdf][0].get("tags") or []))))
            size, sha, _ = results[pdf]
            w.writerow([dim, st, pdf, sha, size, source_doc(pdf), domain_guess(pdf), tags, nr])

    (ROOT / "subset_meta.json").write_text(json.dumps({
        "fetched_utc": now(), "dataset": "llamaindex/ParseBench", "license": "Apache-2.0",
        "hf_revision": REV, "seed": a.seed, "min_per_stratum": MIN_PER_STRATUM,
        "n_files": len(chosen), "n_rules": dict(n_rules),
        "per_dimension": report, "domain_guess": dict(doms),
        "domain_guess_note": "按文件名关键词的启发式标签，不参与分层，不作领域结论",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {SUBSET}  {dict(n_rules)}")


if __name__ == "__main__":
    main()
