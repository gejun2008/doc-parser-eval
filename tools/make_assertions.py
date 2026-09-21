#!/usr/bin/env python3
"""
断言草稿生成 (T3 前半段)

schema 见 docs/assertions.md。目标：把人工工作量从「录入」压成「核对」。

三类产出，**可信度完全不同，不要混**：

  page_integrity  全自动，**不需要人工**。锚点串取自 PDF 文本层，
                  长度 ≥ 12 且全文唯一。用于查漏页与幻觉，assertions.md
                  明确规定这类由脚本批量生成。

  amount          **草稿，必须人眼核对**。从文本层正则抽千分位金额。
  unit_currency   **草稿，必须人眼核对**。抽「人民币千元 / RMB'000」类表头。

为什么 amount 必须人工核对：文本层的数字**不等于**版面上的数字。
PDF 文本层可能顺序错乱、跨列拼接、把两栏数字连在一起。
脚本抽错而人没看出来，错的就是 GT 本身，整份报告的可信度都塌了。
所以草稿一律标 `status: draft`，判定器**拒绝**执行 draft 断言。

用法:
  python tools/make_assertions.py                 # 全部选中页
  python tools/make_assertions.py --doc-id xxx    # 单份文档
"""

import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
import yaml

PAGES = Path("data/corpus/pages.csv")
OUT = Path("data/assertions")

# 千分位金额：1,234,567 或 1,234,567.89，允许括号负数
AMOUNT_RE = re.compile(r"\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")
# 单位与币种表头
UNIT_RE = re.compile(
    r"(人民币|港币|美元|新台币)?\s*(千元|万元|百万元|元)|"
    r"(RMB|HK\$|US\$|USD|HKD|CNY)\s*[''']?\s*(000|million|M)?|"
    r"單位[：:]\s*[^\n]{1,20}|单位[：:]\s*[^\n]{1,20}",
    re.I)


def anchors(page_text, doc_text, n=3, min_len=12):
    """取 n 条长度 ≥ min_len 且在全文唯一的锚点串。

    唯一性是关键：重复出现的串无法区分「这一页漏了」和「别处还有」。
    """
    out = []
    for line in (l.strip() for l in page_text.splitlines()):
        line = re.sub(r"\s+", " ", line)
        if len(line) < min_len or len(out) >= n:
            continue
        if any(line in o or o in line for o in out):
            continue
        if doc_text.count(line) == 1:
            out.append(line)
    return out


def amount_drafts(page_text, limit=6):
    """抽候选金额与其所在行（作为人工核对的上下文）。"""
    seen, out = set(), []
    for line in page_text.splitlines():
        for m in AMOUNT_RE.finditer(line):
            v = m.group(0)
            if v in seen or len(v.replace(",", "").replace(".", "").strip("()-")) < 4:
                continue
            seen.add(v)
            ctx = re.sub(r"\s+", " ", line).strip()[:80]
            out.append((v, ctx))
            if len(out) >= limit:
                return out
    return out


def forbid_forms(v):
    """金额的常见错误形态：丢分隔符、少一位、多一位。判定器要求这些都不出现。"""
    plain = v.strip("()")
    no_sep = plain.replace(",", "")
    forms = {no_sep}
    digits = re.sub(r"[^\d]", "", plain)
    if len(digits) > 4:
        forms.add(plain[:-1])          # 少末位
        forms.add(plain.replace(",", "", 1))  # 丢一个分隔符
    return sorted(f for f in forms if f and f != plain)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", action="append")
    ap.add_argument("--amounts-per-page", type=int, default=4)
    a = ap.parse_args()

    rows = list(csv.DictReader(PAGES.open(encoding="utf-8")))
    by_doc = defaultdict(list)
    for r in rows:
        if a.doc_id and r["doc_id"] not in a.doc_id:
            continue
        by_doc[r["doc_id"]].append(r)

    OUT.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    for doc_id, prs in sorted(by_doc.items()):
        meta = prs[0]
        doc = pymupdf.open(meta["local_path"])
        doc_text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
        items = []
        for pr in sorted(prs, key=lambda r: int(r["page"])):
            page_no = int(pr["page"])
            text = doc[page_no - 1].get_text()

            for i, anc in enumerate(anchors(text, doc_text), 1):
                items.append({
                    "id": f"{doc_id}_p{page_no}_pi{i:02d}",
                    "type": "page_integrity", "severity": "critical",
                    "page": page_no, "eval_on": "md", "rule": "exactly_once",
                    "target": anc, "status": "auto",
                    "note": "文本层唯一锚点，自动生成，用于漏页与幻觉检测",
                })
                stats["page_integrity"] += 1

            for i, (v, ctx) in enumerate(amount_drafts(text, a.amounts_per_page), 1):
                items.append({
                    "id": f"{doc_id}_p{page_no}_am{i:02d}",
                    "type": "amount", "severity": "critical",
                    "page": page_no, "eval_on": "md", "rule": "exactly_once",
                    "target": v, "forbid": forbid_forms(v),
                    "status": "draft",
                    "context": ctx,
                    "note": "草稿：必须对照渲染页人工确认该金额及其所属科目",
                })
                stats["amount_draft"] += 1

            um = UNIT_RE.search(text)
            if um:
                items.append({
                    "id": f"{doc_id}_p{page_no}_uc01",
                    "type": "unit_currency", "severity": "critical",
                    "page": page_no, "eval_on": "md", "rule": "exactly_once",
                    "target": re.sub(r"\s+", " ", um.group(0)).strip(),
                    "status": "draft",
                    "note": "草稿：确认单位/币种表头是否确实出现在该页且未被换算",
                })
                stats["unit_currency_draft"] += 1
        doc.close()

        payload = {
            "doc_id": doc_id, "family": meta["family"], "window": meta["window"],
            "source_url": meta["source_url"], "disclosed_at": meta["disclosed_at"],
            "local_path": meta["local_path"],
            "pages_selected": sorted(int(p["page"]) for p in prs),
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator": "tools/make_assertions.py",
            "review_note": ("status=auto 的 page_integrity 可直接使用；"
                            "status=draft 的必须人工核对后改为 confirmed，"
                            "判定器拒绝执行 draft"),
            "assertions": items,
        }
        (OUT / f"{doc_id}.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8")
        stats["docs"] += 1

    print(f"生成 {stats['docs']} 份断言文件 -> {OUT}/")
    print(f"  page_integrity  {stats['page_integrity']:4} 条  自动，可直接用")
    print(f"  amount          {stats['amount_draft']:4} 条  草稿，待人工核对")
    print(f"  unit_currency   {stats['unit_currency_draft']:4} 条  草稿，待人工核对")
    print(f"  合计 {sum(v for k, v in stats.items() if k != 'docs')} 条")
    print("\n下一步：python tools/review_assertions.py 生成本地审核页")


if __name__ == "__main__":
    main()
