#!/usr/bin/env python3
"""
自建金融场景集语料下载 (T1)

对应 research-plan.md §3.3 第三层。**只用公开披露渠道**：
巨潮资讯网（A 股）与 HKEX 披露易（港股）。两者的检索接口都是公开的。

时间切分是本项目最硬的一张牌（§2.1 泄漏对照）：
  new  = 2026-06-09 之后披露（模型发布日 2026-06-08 之后，不可能进训练集）
  old  = 2025 年全年（有进训练集的可能）
两组数量相当，同族同窗口对比，衰减幅度即泄漏影响的上界估计。

注意：本脚本只下载**整份文档**并记录元数据。选页是下一步
（tools/select_pages.py），因为一份年报 200+ 页，而全集目标才 200–300 页。

用法:
  python tools/fetch_corpus.py --dry-run          # 只列命中数量，不下载
  python tools/fetch_corpus.py --per-family 6     # 每族每窗口下 6 份
  python tools/fetch_corpus.py --family a_share_interim
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path("data/corpus")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

# 模型发布日 2026-06-08（research-plan.md §1.2）。之后披露 = 不可能进训练集。
#
# **泄漏对照必须同族同季节配对**，否则比的是文档类型差异而不是泄漏。
# 一个实测教训：A股年报（FY2025）在 2026 年 3-4 月披露，**早于模型发布日**，
# 因此年报这一族根本凑不出 new 组，只能作「可能已进训练集」的一侧。
# 能做泄漏对照的是中报与临时公告——它们每年同期都有。
POST_RELEASE = "2026-06-09"  # 切分点

# 默认窗口：同季节、相差一年。
WINDOWS = {
    "new": ("2026-08-01", "2026-09-20"),   # 2026 中报季，模型发布日之后
    "old": ("2025-08-01", "2025-09-20"),   # 2025 中报季，同季节
}

# 文档族定义。
#   title_re   必须命中
#   exclude_re 命中即剔除（更正版、摘要、英文版翻译件等噪声）
#   windows    覆盖默认窗口
#   leakage    该族能否构成泄漏对照
# 注意：不要把「公告」放进全局排除词——「权益分派实施公告」本身就带这两个字，
# 之前这么写导致 a_share_notice 两个窗口都是 0 命中。
EXCLUDE_CN = r"更正|摘要|补充|取消|英文版|已取消|修订|修正|图文版|英文版|更新"

FAMILIES = {
    # 1 A股年报/中报
    "a_share_annual": {
        "source": "cninfo", "category": "category_ndbg_szsh",
        "title_re": r"年度报告", "exclude_re": EXCLUDE_CN, "leakage": False,
        "windows": {"old": ("2026-03-15", "2026-04-30"),      # FY2025 年报季
                    "older": ("2025-03-15", "2025-04-30")},   # FY2024 年报季
        "desc": "A股年报。两组均早于模型发布日，不作泄漏对照"},
    "a_share_interim": {
        "source": "cninfo", "category": "category_bndbg_szsh",
        "title_re": r"半年度报告|中期报告", "exclude_re": EXCLUDE_CN, "leakage": True,
        "desc": "A股中报。泄漏对照主力族"},
    # 3 临时公告（含表格）
    "a_share_notice": {
        "source": "cninfo", "category": "category_qyfpxzcs_szsh",
        "title_re": r"权益分派", "exclude_re": EXCLUDE_CN, "leakage": True,
        "desc": "A股权益分派公告，含金额表格"},
    # 2 港股年报/中报（繁体+英文）
    "hk_interim": {
        "source": "hkex", "t1code": "40000",
        "title_re": r"INTERIM REPORT|中期報告", "exclude_re": r"SUPPLEMENT|補充",
        "leakage": True, "desc": "港股中报"},
    "hk_annual": {
        "source": "hkex", "t1code": "40000",
        "title_re": r"ANNUAL REPORT|年報", "exclude_re": r"SUPPLEMENT|補充|SUMMARY",
        "leakage": True,
        # 6 月年结公司在 7-10 月披露年报，窗口比中报宽
        "windows": {"new": ("2026-07-01", "2026-09-20"),
                    "old": ("2025-07-01", "2025-09-20")},
        "desc": "港股年报（6 月年结公司在 9-10 月披露）"},
    # 4 招股书 / 上市文件
    "hk_prospectus": {
        "source": "hkex", "t1code": "30000",
        "title_re": r"PROSPECTUS|LISTING DOCUMENT|招股", "exclude_re": r"SUPPLEMENT",
        # ETF 系列招股通知只有 2 页，不是 IPO 上市文件，按页数卡掉
        "min_pages": 50,
        "leakage": True, "desc": "港股招股书/上市文件"},
    # 7 KYC 类（章程、董事名册）
    "hk_kyc": {
        "source": "hkex", "t1code": "10000",
        "title_re": r"ARTICLES OF ASSOCIATION|MEMORANDUM AND ARTICLES|"
                    r"LIST OF DIRECTORS|組織章程|董事名單|董事會成員",
        "exclude_re": r"", "leakage": True, "desc": "港股章程/董事名册"},
}

# 第 5 类（评级与研究报告）与第 6 类（贸易金融单据）没有统一的公开检索接口，
# 需人工从评级机构官网与 ICC 公开样本取，放 data/corpus/manual/ 并手工登记 manifest。


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cninfo_search(cfg, since, until, limit):
    """巨潮公告检索。返回 [(title, pdf_url, disclosed_at, code, name)]。"""
    out, page = [], 1
    while len(out) < limit and page <= 10:
        r = requests.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                          headers={**UA, "Referer": "http://www.cninfo.com.cn/"},
                          data={"pageNum": page, "pageSize": 30, "column": "szse",
                                "tabName": "fulltext", "category": cfg["category"],
                                "seDate": f"{since}~{until}", "isHLtitle": "true"},
                          timeout=40)
        r.raise_for_status()
        anns = r.json().get("announcements") or []
        if not anns:
            break
        for a in anns:
            title = re.sub(r"</?em>", "", a.get("announcementTitle") or "")
            if cfg["title_re"] and not re.search(cfg["title_re"], title):
                continue
            if cfg.get("exclude_re") and re.search(cfg["exclude_re"], title):
                continue
            if not (a.get("adjunctUrl") or "").lower().endswith(".pdf"):
                continue
            ts = a.get("announcementTime")
            out.append({
                "title": title,
                "url": "http://static.cninfo.com.cn/" + a["adjunctUrl"],
                "disclosed_at": datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
                if ts else "",
                "issuer_code": a.get("secCode"), "issuer_name": a.get("secName"),
                "source_site": "cninfo.com.cn"})
            if len(out) >= limit:
                break
        page += 1
        time.sleep(1.0)  # 对公开站点保持礼貌
    return out


def hkex_search(cfg, since, until, limit):
    """HKEX 披露易标题检索。返回同上结构。

    实测两个坑（写下来免得下次再踩）：
      1. 日期参数是 fromDate/toDate（YYYYMMDD），from/to 会被静默忽略
      2. 默认只返回最新 100 行，而一个中报季有 1700+ 条。不翻页的话，
         标题过滤只作用在最近几天的记录上，老窗口会假性 0 命中。
         翻页靠 rowRange，响应里的 recordCnt 是命中总数。
    """
    out, seen = [], set()
    for row_range in (100, 400, 1200, 3000):
        r = requests.get("https://www1.hkexnews.hk/search/titleSearchServlet.do",
                         headers=UA, timeout=90,
                         params={"sortDir": "0", "sortByOptions": "DateTime", "category": "0",
                                 "market": "SEHK", "stockId": "-1", "documentType": "-1",
                                 "t1code": cfg["t1code"], "t2Gcode": "-2", "t2code": "-2",
                                 "searchType": "1", "lang": "EN", "title": "",
                                 "rowRange": str(row_range),
                                 "fromDate": since.replace("-", ""),
                                 "toDate": until.replace("-", "")})
        r.raise_for_status()
        d = r.json()
        res = d.get("result")
        recs = json.loads(res) if isinstance(res, str) else (res or [])
        for a in recs:
            title = html.unescape(re.sub(r"<[^>]+>", "", a.get("TITLE") or ""))
            code = a.get("STOCK_CODE") or ""
            if "<br" in code:
                continue  # 多代码条目是 ETF 系列招股书，不是 IPO 上市文件
            if cfg["title_re"] and not re.search(cfg["title_re"], title, re.I):
                continue
            if cfg.get("exclude_re") and re.search(cfg["exclude_re"], title, re.I):
                continue
            link = a.get("FILE_LINK", "")
            if not link.lower().endswith(".pdf") or link in seen:
                continue
            seen.add(link)
            dt = (a.get("DATE_TIME") or "").split(" ")[0]  # dd/mm/yyyy
            iso = "-".join(reversed(dt.split("/"))) if "/" in dt else dt
            out.append({"title": title, "url": "https://www1.hkexnews.hk" + link,
                        "disclosed_at": iso, "issuer_code": code,
                        "issuer_name": re.sub(r"<[^>]+>", "", a.get("STOCK_NAME") or ""),
                        "source_site": "hkexnews.hk"})
            if len(out) >= limit:
                return out
        if not d.get("hasNextRow") or len(recs) < row_range:
            break
        time.sleep(1.0)
    return out


def pdf_meta(path):
    """页数 + 是否电子版（有文本层）。扫描件文本层为空，会进扰动组对照。"""
    import pymupdf
    try:
        doc = pymupdf.open(path)
        n = doc.page_count
        probe = min(n, 5)
        chars = sum(len(doc[i].get_text().strip()) for i in range(probe))
        return n, chars / max(probe, 1) > 200
    except Exception as e:
        return 0, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=5, help="每族每个时间窗口下几份")
    ap.add_argument("--family", action="append", help="只跑指定族，可重复")
    ap.add_argument("--dry-run", action="store_true", help="只列命中，不下载")
    ap.add_argument("--max-mb", type=float, default=40.0, help="单文件大小上限")
    a = ap.parse_args()

    fams = a.family or list(FAMILIES)
    unknown = [f for f in fams if f not in FAMILIES]
    if unknown:
        sys.exit(f"未知文档族 {unknown}，可选：{list(FAMILIES)}")

    rows, seen = [], set()
    for fam in fams:
        cfg = FAMILIES[fam]
        for win, (since, until) in (cfg.get("windows") or WINDOWS).items():
            search = cninfo_search if cfg["source"] == "cninfo" else hkex_search
            try:
                # min_pages 会淘汰一部分候选，所以多取几倍
                over = 6 if cfg.get("min_pages") else 1
                hits = search(cfg, since, until, a.per_family * over)
            except Exception as e:
                print(f"！{fam}/{win} 检索失败: {repr(e)[:120]}")
                continue
            print(f"{fam:16} {win:4} {since}~{until}  命中 {len(hits)}")
            kept = 0
            for h in hits:
                if kept >= a.per_family and not a.dry_run:
                    break
                if a.dry_run:
                    print(f"   {h['disclosed_at']} {h['issuer_code']} "
                          f"{(h['issuer_name'] or '')[:12]:12} {h['title'][:40]}")
                    continue
                doc_id = f"{fam}_{win}_{h['issuer_code']}_{h['disclosed_at']}"
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                dst = ROOT / fam / f"{doc_id}.pdf"
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    try:
                        rr = requests.get(h["url"], headers=UA, timeout=180)
                        rr.raise_for_status()
                        if len(rr.content) > a.max_mb * 1e6:
                            print(f"   跳过（{len(rr.content)/1e6:.0f}MB 超限）{h['title'][:30]}")
                            continue
                        dst.write_bytes(rr.content)
                        time.sleep(1.0)
                    except Exception as e:
                        print(f"   ！下载失败 {h['title'][:30]}: {repr(e)[:80]}")
                        continue
                data = dst.read_bytes()
                pages, electronic = pdf_meta(dst)
                if cfg.get("min_pages") and pages < cfg["min_pages"]:
                    print(f"   跳过（{pages} 页 < {cfg['min_pages']}）{h['title'][:36]}")
                    dst.unlink(missing_ok=True)
                    continue
                kept += 1
                rows.append({
                    "doc_id": doc_id, "family": fam, "window": win,
                    "source_url": h["url"], "source_site": h["source_site"],
                    "disclosed_at": h["disclosed_at"], "title": h["title"],
                    "issuer_code": h["issuer_code"], "issuer_name": h["issuer_name"],
                    "pages": pages, "electronic": "" if electronic is None else int(electronic),
                    "bytes": len(data), "sha256_16": hashlib.sha256(data).hexdigest()[:16],
                    "local_path": str(dst),
                })
                print(f"   ✓ {doc_id}  {pages:4} 页  {len(data)/1e6:5.1f}MB  "
                      f"{'电子版' if electronic else '疑似扫描'}")

    if a.dry_run:
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    man = ROOT / "manifest.csv"
    old = list(csv.DictReader(man.open(encoding="utf-8"))) if man.exists() else []
    by_id = {r["doc_id"]: r for r in old}
    by_id.update({r["doc_id"]: r for r in rows})
    fields = ["doc_id", "family", "window", "source_url", "source_site", "disclosed_at",
              "title", "issuer_code", "issuer_name", "pages", "electronic", "bytes",
              "sha256_16", "local_path"]
    with man.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(by_id.values())
    (ROOT / "fetch_meta.json").write_text(json.dumps(
        {"fetched_utc": now(), "windows": WINDOWS, "per_family": a.per_family,
         "families": {f: FAMILIES[f]["desc"] for f in fams},
         "leakage_note": "new = 模型发布日 2026-06-08 之后披露；old = 2025 年，可能进训练集",
         "n_docs": len(by_id),
         "total_pages": sum(int(r["pages"] or 0) for r in by_id.values())},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n清单 {man}：{len(by_id)} 份文档，"
          f"{sum(int(r['pages'] or 0) for r in by_id.values())} 页")
    print("下一步选页（全集目标 200-300 页，不是整份都测）：tools/select_pages.py")


if __name__ == "__main__":
    main()
