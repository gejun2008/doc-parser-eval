#!/usr/bin/env python3
"""
选页 (T1 后半段)

一份年报 200–300 页，而全集目标才 200–300 页（research-plan.md §3.3），
所以必须选页。**选页规则本身会影响所有分数，因此它必须是确定性的、可复现的、
并且公开在报告附录里。**

规则（无随机性，同一份 PDF 永远选出同一批页）：
  1. 短文档（≤ max_all 页）整份纳入——临时公告、董事名册本来就只有 1–5 页
  2. 长文档按页打分取前 K：
       关键词命中（合并资产负债表 / Consolidated Statement of ... 等）+8
       数字密度（数字字符占比）             最多 +3
       表格线索（连续空格分隔的数字列）      最多 +2
     同分按页码升序，保证确定性
  3. 每份文档选出的页在文档内去重且按页码排序

**刻意偏向财务报表页**：金融文档解析的价值与风险都集中在金额、单位、跨页表格上，
均匀随机抽页会把分数稀释成「正文 OCR 好不好」，那不是本评测要回答的问题。
这个偏向对厂商不利也不利于我们——它同时抬高了所有基线的难度，
Azure DI 跑的是同一批页。

用法:
  python tools/select_pages.py                # 按默认配额选页
  python tools/select_pages.py --dry-run      # 只看分布
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path("data/corpus")

# 每份文档选几页；短文档整份纳入的阈值
QUOTA = {
    "a_share_annual":  {"per_doc": 4, "max_all": 8},
    "a_share_interim": {"per_doc": 4, "max_all": 8},
    "a_share_notice":  {"per_doc": 3, "max_all": 8},
    "hk_annual":       {"per_doc": 4, "max_all": 8},
    "hk_interim":      {"per_doc": 4, "max_all": 8},
    "hk_prospectus":   {"per_doc": 8, "max_all": 8},
    "hk_kyc":          {"per_doc": 3, "max_all": 8},
}

# 财务报表页关键词。简中 / 繁中 / 英文各一组。
KEYWORDS = [
    # 简体
    r"合并资产负债表", r"合并利润表", r"合并现金流量表", r"合并所有者权益变动表",
    r"母公司资产负债表", r"应收账款", r"营业收入", r"每股收益",
    # 繁体
    r"綜合財務狀況表", r"綜合損益表", r"綜合全面收益表", r"綜合現金流量表",
    r"權益變動表", r"每股盈利",
    # 英文
    r"CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
    r"CONSOLIDATED STATEMENT OF PROFIT OR LOSS",
    r"CONSOLIDATED STATEMENT OF CASH FLOWS",
    r"CONSOLIDATED BALANCE SHEET",
    r"CONSOLIDATED INCOME STATEMENT",
    r"ACCOUNTANTS.? REPORT",
    r"NOTES TO THE (?:CONSOLIDATED )?FINANCIAL STATEMENTS",
    r"EARNINGS PER SHARE",
]
KW_RE = re.compile("|".join(KEYWORDS), re.I)
# 连续两个以上由空白分隔的数字列 = 表格行的典型形态
TABLE_ROW_RE = re.compile(r"(?:[\d,.()%-]{2,}\s{2,}){2,}[\d,.()%-]{2,}")


def score_page(text):
    """返回 (总分, 命中的关键词, 数字密度, 表格行数)。无随机性。"""
    if not text.strip():
        return 0.0, "", 0.0, 0
    # 用 search 而不是 findall：findall 遇到捕获组会返回组内容而不是整段匹配，
    # 之前那么写导致命中词记成空串、reason 全变 score_only
    m = KW_RE.search(text)
    kw = 8.0 if m else 0.0
    digits = sum(c.isdigit() for c in text)
    density = digits / max(len(text), 1)
    table_rows = len(TABLE_ROW_RE.findall(text))
    return (kw + min(density * 10, 3.0) + min(table_rows * 0.2, 2.0),
            (m.group(0) if m else "")[:40], round(density, 3), table_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    man = ROOT / "manifest.csv"
    docs = list(csv.DictReader(man.open(encoding="utf-8")))
    rows, per_family = [], defaultdict(int)

    for d in docs:
        fam = d["family"]
        q = QUOTA.get(fam, {"per_doc": 3, "max_all": 8})
        path = Path(d["local_path"])
        if not path.exists():
            print(f"！缺文件 {path}")
            continue
        doc = pymupdf.open(path)
        n = doc.page_count

        if n <= q["max_all"]:
            picks = [(i + 1, 0.0, "short_doc_all_pages", 0.0, 0) for i in range(n)]
        else:
            scored = []
            for i in range(n):
                t = doc[i].get_text()
                s, kw, dens, tr = score_page(t)
                scored.append((s, i + 1, kw, dens, tr))
            # 先按分降序、再按页码升序 -> 确定性
            scored.sort(key=lambda x: (-x[0], x[1]))
            picks = [(p, round(s, 2), kw or "score_only", dens, tr)
                     for s, p, kw, dens, tr in scored[:q["per_doc"]]]
            picks.sort(key=lambda x: x[0])

        for page, s, why, dens, tr in picks:
            rows.append({"doc_id": d["doc_id"], "family": fam, "window": d["window"],
                         "local_path": d["local_path"], "page": page,
                         "score": s, "reason": why, "digit_density": dens,
                         "table_rows": tr, "doc_pages": n,
                         "disclosed_at": d["disclosed_at"], "source_url": d["source_url"]})
            per_family[fam] += 1
        doc.close()

    print(f"{'文档族':18} {'页数':>5}")
    for f, c in sorted(per_family.items()):
        print(f"{f:18} {c:5}")
    print(f"{'合计':18} {len(rows):5}  （目标 200–300）")

    if a.dry_run:
        return
    out = ROOT / "pages.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (ROOT / "pages_meta.json").write_text(json.dumps({
        "selected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule": "短文档整份纳入；长文档按 关键词+数字密度+表格行 打分取前 K，同分按页码升序",
        "deterministic": True, "quota": QUOTA, "keywords": KEYWORDS,
        "n_pages": len(rows), "per_family": dict(per_family),
        "bias_note": "刻意偏向财务报表页，理由见脚本 docstring。所有基线跑同一批页。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}\n-> {ROOT / 'pages_meta.json'}")


if __name__ == "__main__":
    main()
