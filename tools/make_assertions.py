#!/usr/bin/env python3
"""
断言草稿生成 (T3 前半段)

schema 见 docs/working/assertions.md。目标：把人工工作量从「录入」压成「核对」。

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
# 单位与币种表头。
# 第一版这里错得离谱，教训记下来：
#   - 匹配 `单位[：:]...` 抓到了「单位：海目星激光科技集团股份有限公司」——
#     中文「单位」也指公司，不只是计量单位
#   - 匹配裸 `元` / `RMB` 抓到 39 条 '元'、37 条 'RMB'，一页里到处都是，判了没意义
# 现在要求必须带计量语境（千元/万元/百万元）或显式币种声明。
UNIT_RE = re.compile(
    r"(?:单位|單位)\s*[：:]\s*(?:人民币|人民幣|港币|港幣|美元)?\s*(?:千元|万元|萬元|百万元|百萬元|元)"
    r"(?:\s*(?:币种|幣種)\s*[：:]\s*(?:人民币|人民幣|港元|港币|美元))?"
    r"|(?:币种|幣種)\s*[：:]\s*(?:人民币|人民幣|港元|港币|美元)"
    r"|(?:RMB|HK\$|US\$|USD|HKD|CNY)\s*[‘’']\s*000"
    r"|(?:in\s+thousands?|in\s+millions?)\s+of\s+(?:RMB|HKD|USD|Hong\s+Kong\s+dollars)",
    re.I)


# 锚点必须含足够的文字内容。纯数字行不能当锚点：
# 报表里同一金额在本期/上期两列出现是正常的，用 exactly_once 判必然假失败；
# 而金额的正确性本来就归 amount 类管，不该混进「漏页与幻觉」这一类。
# 这个教训来自第一版：58 条失败里有 8 条是同一金额出现两次的误判。
WORD_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbfA-Za-z]")


def anchors(page_text, doc_text, n=3, min_len=12, min_words=8):
    """取 n 条长度 ≥ min_len、含 ≥ min_words 个文字字符、且在全文唯一的锚点串。

    唯一性是关键：重复出现的串无法区分「这一页漏了」和「别处还有」。
    """
    out = []
    for line in (l.strip() for l in page_text.splitlines()):
        line = re.sub(r"\s+", " ", line)
        if len(line) < min_len or len(out) >= n:
            continue
        words = len(WORD_RE.findall(line))
        if words < min_words:
            continue          # 纯数字/符号行
        if words / len(line) < 0.3:
            continue          # 文字占比过低，实质仍是数字行
        if any(line in o or o in line for o in out):
            continue
        if doc_text.count(line) == 1:
            out.append(line)
    return out


LABEL_RE = re.compile(r"^[一-鿿A-Za-z][一-鿿A-Za-z（）()、/\s]{2,28}")

# 表格单元格窄时，金额会在版面上折行，PDF 文本层也就成了两行甚至三行：
#     181,801,7 / 31.11        ->  实际是 181,801,731.11
#     317,1 / 38,41 / 4.87     ->  实际是 317,138,414.87
# 逐行扫描只能匹配到 "181,801"，**断言的目标值本身就是错的**，
# 而 amount 类是 auto_textlayer、不经人工，等于把错的 GT 直接用上。
# 实测 645 条金额类断言里 37 条（5.7%）中招。
#
# 判据：完整的千分位数字绝不会以「逗号 + 1~2 位数字」结尾。
# 行尾出现这种形态且下一行以数字开头，就说明数字被折断了，拼接即可。
INCOMPLETE_TAIL = re.compile(r"\d,\d{1,2}$")


def join_wrapped_numbers(text):
    """把在版面上折行的数字拼回一行。反复执行直到稳定（可能折三行）。"""
    lines = text.splitlines()
    out = []
    for ln in lines:
        if out and INCOMPLETE_TAIL.search(out[-1].rstrip()) and ln.lstrip()[:1].isdigit():
            out[-1] = out[-1].rstrip() + ln.lstrip()
        else:
            out.append(ln)
    return "\n".join(out)


def nows(t):
    return re.sub(r"\s+", "", t or "")


def amount_drafts(page_text, limit=6):
    """抽候选金额、所在行、行首标签，以及该金额在本页出现的次数。

    次数很重要：报表里同一金额在本期/上期两栏出现是**正常**的，
    用 exactly_once 判必然假失败。第一版就栽在这里——564 条里 134 条如此。
    现在按文本层实际次数生成 exactly_n。
    """
    page_n = nows(page_text)
    seen, out = set(), []
    for line in join_wrapped_numbers(page_text).splitlines():
        for m in AMOUNT_RE.finditer(line):
            v = m.group(0)
            if v in seen or len(v.replace(",", "").replace(".", "").strip("()-")) < 4:
                continue
            # 保守兜底：拼接后若匹配结尾仍紧跟逗号或数字，说明仍不完整，
            # 宁可不出这条断言，也不产出一个截断的 GT
            if line[m.end():m.end() + 1] in (",", "0", "1", "2", "3", "4",
                                              "5", "6", "7", "8", "9"):
                continue
            seen.add(v)
            clean = re.sub(r"\s+", " ", line).strip()
            lm = LABEL_RE.match(clean)
            label = lm.group(0).strip() if lm else ""
            out.append((v, clean[:80], label, page_n.count(nows(v))))
            if len(out) >= limit:
                return out
    return out


def forbid_forms(v):
    """金额的常见错误形态，判定器要求这些都不出现。

    **禁止串绝不能是目标值的子串**，否则正确金额一出现就必然误判失败。
    第一版犯了这个错：把「少末位」（100,000 -> 100,00）当禁止串，
    而它是正确值的前缀，564 条 amount 里 500 条被判成假失败、通过率假性跌到 9.9%。

    所以这里只保留结构上不可能是子串的形态：
      丢掉全部千分位分隔符（1,234,567.89 -> 1234567.89）
      小数点左移一位（金额缩小 10 倍的典型错位）
    并在返回前逐个校验「不是目标的子串」。
    """
    plain = v.strip("()")
    forms = {plain.replace(",", "")}
    m = re.match(r"^(-?[\d,]+)\.(\d+)$", plain)
    if m:
        intp, dec = m.group(1), m.group(2)
        if len(intp.replace(",", "")) > 1:
            forms.add(f"{intp[:-1]}.{intp[-1]}{dec}")   # 小数点左移一位
    tn = re.sub(r"\s+", "", plain)
    return sorted(f for f in forms
                  if f and f != plain and re.sub(r"\s+", "", f) not in tn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", action="append")
    ap.add_argument("--amounts-per-page", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="覆盖已含人工审核结果的文件")
    a = ap.parse_args()

    rows = list(csv.DictReader(PAGES.open(encoding="utf-8")))
    by_doc = defaultdict(list)
    for r in rows:
        if a.doc_id and r["doc_id"] not in a.doc_id:
            continue
        by_doc[r["doc_id"]].append(r)

    OUT.mkdir(parents=True, exist_ok=True)
    if not a.force:
        reviewed = []
        for f in OUT.glob("*.yaml"):
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            if any(i.get("status") in ("confirmed", "rejected") for i in d["assertions"]):
                reviewed.append(f.name)
        if reviewed:
            raise SystemExit(
                f"！{len(reviewed)} 份文件已含人工审核结果，重新生成会覆盖掉。"
                f"\n  例如 {reviewed[:3]}\n  确认要重来请加 --force")
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

            for i, (v, ctx, label, n_occ) in enumerate(
                    amount_drafts(text, a.amounts_per_page), 1):
                # 存在性与次数：文本层是可靠 GT（字符本来就来自它），机器可验证。
                # **只测「这串数字在不在、出现几次」，不测它挂在哪个科目下。**
                items.append({
                    "id": f"{doc_id}_p{page_no}_am{i:02d}",
                    "type": "amount", "severity": "critical",
                    "page": page_no, "eval_on": "md",
                    "rule": "exactly_n", "n": n_occ,
                    "target": v, "forbid": forbid_forms(v),
                    "status": "auto_textlayer",
                    "context": ctx,
                    "note": ("文本层派生：只验存在性与出现次数，不验科目归属。"
                             "GT 来源是文本层而非人工，需抽样审计估计其错误率"),
                })
                stats["amount_auto"] += 1

                # 归属：金额必须仍然挨着它的行标签。这是机器判不了的部分——
                # 文本层跨列拼接会把标签配错，必须人眼对着渲染页确认。
                if label and len(label) >= 3:
                    items.append({
                        "id": f"{doc_id}_p{page_no}_lp{i:02d}",
                        "type": "amount_label", "severity": "critical",
                        "page": page_no, "eval_on": "md",
                        "rule": "label_proximity", "max_gap": 120,
                        "target": v, "label": label,
                        "status": "draft",
                        "context": ctx,
                        "note": ("草稿：对着渲染页确认『该科目』与『该金额』确实同行。"
                                 "文本层跨列拼接会把标签配错，机器验不了这一类"),
                    })
                    stats["amount_label_draft"] += 1

            um = UNIT_RE.search(text)
            if um:
                tgt = re.sub(r"\s+", " ", um.group(0)).strip()
                items.append({
                    "id": f"{doc_id}_p{page_no}_uc01",
                    "type": "unit_currency", "severity": "critical",
                    "page": page_no, "eval_on": "md",
                    "rule": "exactly_n", "n": nows(text).count(nows(tgt)),
                    "target": tgt, "status": "auto_textlayer",
                    "note": "文本层派生：验单位/币种表头是否保留。不验金额有没有被换算",
                })
                stats["unit_currency_auto"] += 1
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
    print(f"  page_integrity  {stats['page_integrity']:4} 条  自动（文本层锚点）")
    print(f"  amount          {stats['amount_auto']:4} 条  自动（文本层，只验存在与次数）")
    print(f"  unit_currency   {stats['unit_currency_auto']:4} 条  自动（文本层）")
    print(f"  amount_label    {stats['amount_label_draft']:4} 条  **需人工**（科目归属）")
    print(f"  合计 {sum(v for k, v in stats.items() if k != 'docs')} 条")
    print("\n下一步：python tools/review_assertions.py 生成本地审核页")


if __name__ == "__main__":
    main()
