#!/usr/bin/env python3
"""
大文件 edge case 候选筛选：只查检索接口的元数据，不下载 PDF。

用途：给「大文件」压力测试挑公开金融 PDF，目标区间 10–100MB 为主，
外加少量 >100MB 的。来源只用官方披露渠道（巨潮资讯、HKEX 披露易），
与 fetch_corpus.py 同一套公开接口。

文件大小来自检索接口自带的字段，不是 HEAD 实测：
  巨潮   adjunctSize（KB）
  披露易 FILE_INFO（如 "23MB" / "870KB"）
真正入库前请用 --verify-head 对候选再发一次 HEAD，拿 Content-Length 核对。

用法:
  python tools/find_large_pdfs.py                       # 默认全部族，输出 CSV
  python tools/find_large_pdfs.py --family cn_reits --max-pages 20
  python tools/find_large_pdfs.py --verify-head         # 对命中项补 HEAD 核对
输出: data/large_pdf_candidates.csv（纯元数据，可入库）
"""

import argparse
import csv
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
OUT = Path("data/large_pdf_candidates.csv")
MIN_MB = 10.0

# 噪声：提示性公告、摘要、英文翻译、更正。只要「全文正本」。
EXCLUDE_CN = r"提示性公告|摘要|更正|英文|取消|问询|反馈|意见|核查|法律意见|发行公告|上市公告"

FAMILIES = {
    # ---- 巨潮（全文检索 GET 接口；关键词 + 时间段）----
    "cn_ipo_prospectus": {
        "source": "cninfo", "searchkey": "招股说明书",
        "title_re": r"招股说明书", "exclude_re": EXCLUDE_CN + r"|附录|附件",
        "desc": "A股 IPO 招股说明书（注册稿/终稿）"},
    "cn_restructuring": {
        "source": "cninfo", "searchkey": "重大资产重组报告书",
        "title_re": r"重组报告书|重组暨关联交易报告书|购买资产.*报告书",
        "exclude_re": EXCLUDE_CN,
        "desc": "A股重大资产重组报告书（草案/修订稿）"},
    "cn_valuation_audit": {
        "source": "cninfo", "searchkey": "资产评估报告",
        "title_re": r"评估报告|审计报告", "exclude_re": EXCLUDE_CN,
        "desc": "重组/收购附件：资产评估报告、审计报告（常含扫描页）"},
    "cn_reits": {
        "source": "cninfo", "searchkey": "基础设施证券投资基金招募说明书",
        "title_re": r"基础设施.*招募说明书", "exclude_re": EXCLUDE_CN,
        "desc": "公募 REITs 招募说明书（含资产评估、项目证照）"},
    "cn_annual_report": {
        "source": "cninfo", "searchkey": "年度报告",
        "title_re": r"年度报告$|年度报告（", "exclude_re": EXCLUDE_CN + r"|半年度|季度",
        "desc": "A股年报（大型国企/银行偏大）"},
    "cn_esg": {
        "source": "cninfo", "searchkey": "可持续发展报告",
        "title_re": r"可持续发展报告|ESG|社会责任报告", "exclude_re": EXCLUDE_CN,
        "desc": "A股 ESG/可持续发展报告（图片密集）"},
    "cn_bond_prospectus": {
        "source": "cninfo", "searchkey": "募集说明书",
        "title_re": r"募集说明书", "exclude_re": EXCLUDE_CN,
        "desc": "可转债/公司债募集说明书"},
    # ---- 披露易（标题检索；t1code 分类）----
    "hk_prospectus": {
        "source": "hkex", "t1code": "30000",
        "title_re": r"PROSPECTUS|GLOBAL OFFERING|LISTING DOCUMENT|OFFERING CIRCULAR",
        "exclude_re": r"SUPPLEMENT|ALLOTMENT|APPLICATION FORM|NOTICE",
        "desc": "港股招股章程/上市文件/债券发行通函"},
    "hk_phip": {
        "source": "hkex", "t1code": "30000",
        "title_re": r"POST HEARING|PHIP", "exclude_re": r"",
        "desc": "港股聆讯后资料集"},
    "hk_annual_report": {
        "source": "hkex", "t1code": "40000",
        "title_re": r"ANNUAL REPORT", "exclude_re": r"SUPPLEMENT|SUMMARY|NOTIFICATION|NOTICE",
        "desc": "港股年报"},
    "hk_esg": {
        "source": "hkex", "t1code": "40000",
        "title_re": r"ESG|SUSTAINABILITY|ENVIRONMENTAL, SOCIAL", "exclude_re": r"NOTIFICATION",
        "desc": "港股 ESG/可持续发展报告"},
}

# 默认时间段：近两年按季度分段扫。实测披露易 t1code=40000 半年窗口有 3,644 条，
# 超过单次 rowRange=3000 的上限会被截掉，按季度切才能扫全。
DEFAULT_WINDOWS = [("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"),
                   ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
                   ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
                   ("2026-07-01", "2026-09-30"), ("2026-10-01", "2026-11-11")]


def parse_hk_size(s):
    m = re.match(r"([\d.]+)\s*(KB|MB|GB)", (s or "").upper())
    if not m:
        return None
    v = float(m.group(1))
    return {"KB": v / 1024, "MB": v, "GB": v * 1024}[m.group(2)]


def get_json(url, **kw):
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=90, **kw)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            wait = 2 ** (i + 1)
            print(f"  retry {i + 1} in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    return None


def cninfo_scan(fam, cfg, since, until, max_pages, min_mb):
    out = []
    for page in range(1, max_pages + 1):
        d = get_json("https://www.cninfo.com.cn/new/fulltextSearch/full",
                     params={"searchkey": cfg["searchkey"], "sdate": since, "edate": until,
                             "isfulltext": "false", "sortName": "pubdate", "sortType": "desc",
                             "pageNum": page, "pageSize": 50})
        anns = (d or {}).get("announcements") or []
        if not anns:
            break
        for a in anns:
            title = re.sub(r"</?em>", "", a.get("announcementTitle") or "")
            if not re.search(cfg["title_re"], title):
                continue
            if cfg["exclude_re"] and re.search(cfg["exclude_re"], title):
                continue
            mb = (a.get("adjunctSize") or 0) / 1024
            if mb < min_mb or (a.get("adjunctType") or "").upper() != "PDF":
                continue
            ts = a.get("announcementTime")
            out.append({
                "family": fam, "source": "cninfo.com.cn",
                "issuer_code": a.get("secCode"), "issuer_name": a.get("secName"),
                "title": title, "listed_size_mb": round(mb, 1),
                "disclosed_at": datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
                if ts else "",
                "url": "https://static.cninfo.com.cn/" + a["adjunctUrl"]})
        time.sleep(1.0)  # 对公开站点保持礼貌
    return out


def hkex_scan(fam, cfg, since, until, max_rows, min_mb):
    d = get_json("https://www1.hkexnews.hk/search/titleSearchServlet.do",
                 params={"sortDir": "0", "sortByOptions": "DateTime", "category": "0",
                         "market": "SEHK", "stockId": "-1", "documentType": "-1",
                         "t1code": cfg["t1code"], "t2Gcode": "-2", "t2code": "-2",
                         "searchType": "1", "lang": "EN", "title": "",
                         "rowRange": str(max_rows),
                         "fromDate": since.replace("-", ""), "toDate": until.replace("-", "")})
    res = (d or {}).get("result")
    recs = json.loads(res) if isinstance(res, str) else (res or [])
    out = []
    for a in recs:
        title = html.unescape(re.sub(r"<[^>]+>", "", a.get("TITLE") or ""))
        if not re.search(cfg["title_re"], title, re.I):
            continue
        if cfg["exclude_re"] and re.search(cfg["exclude_re"], title, re.I):
            continue
        mb = parse_hk_size(a.get("FILE_INFO"))
        link = a.get("FILE_LINK") or ""
        if mb is None or mb < min_mb or not link.lower().endswith(".pdf"):
            continue
        dt = (a.get("DATE_TIME") or "").split(" ")[0]
        out.append({
            "family": fam, "source": "hkexnews.hk",
            "issuer_code": re.sub(r"<[^>]+>", " ", a.get("STOCK_CODE") or "").strip(),
            "issuer_name": re.sub(r"<[^>]+>", " ", a.get("STOCK_NAME") or "").strip(),
            "title": title[:200], "listed_size_mb": round(mb, 1),
            "disclosed_at": "-".join(reversed(dt.split("/"))) if "/" in dt else dt,
            "url": "https://www1.hkexnews.hk" + link})
    time.sleep(1.0)
    return out


def head_size(url):
    try:
        r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
        n = r.headers.get("Content-Length")
        return round(int(n) / 1024 / 1024, 1) if n else None
    except requests.RequestException:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", action="append", choices=sorted(FAMILIES))
    ap.add_argument("--max-pages", type=int, default=15, help="巨潮每窗口最多翻页数（50 条/页）")
    ap.add_argument("--max-rows", type=int, default=3000, help="披露易每窗口最多行数")
    ap.add_argument("--min-mb", type=float, default=MIN_MB)
    ap.add_argument("--verify-head", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows, seen = [], set()
    for fam in args.family or FAMILIES:
        cfg = FAMILIES[fam]
        for since, until in DEFAULT_WINDOWS:
            if cfg["source"] == "cninfo":
                hits = cninfo_scan(fam, cfg, since, until, args.max_pages, args.min_mb)
            else:
                hits = hkex_scan(fam, cfg, since, until, args.max_rows, args.min_mb)
            new = [h for h in hits if h["url"] not in seen]
            seen.update(h["url"] for h in new)
            rows += new
            print(f"{fam:20s} {since}~{until}: {len(new)} hits >= {args.min_mb}MB", file=sys.stderr)

    if args.verify_head:
        for r in rows:
            r["head_size_mb"] = head_size(r["url"])
            time.sleep(0.5)

    rows.sort(key=lambda r: (r["family"], -r["listed_size_mb"]))
    cols = ["family", "source", "issuer_code", "issuer_name", "title", "listed_size_mb",
            "head_size_mb", "disclosed_at", "url"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}  (scanned_at {datetime.now(timezone.utc).isoformat(timespec='seconds')})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
