#!/usr/bin/env python3
"""
Azure Document Intelligence 基线 runner (T7)

现状方案，「换不换」的真正对手。research-plan.md §5 标为**必保**基线：
没有基线的绝对分数不可解释，报告的核心句式是「相对现状提升/下降多少」。

## 关键设计：直接要 Azure 自己的 markdown，不自己写转换器

research-plan.md §5 的同口径陷阱：Azure DI 输出自有 JSON，若由我们转换成
可比格式，转换规则就成了影响对手分数的变量——**等于栽赃对手，评审一眼看得出**。

2024-11-30 GA 版支持 `outputContentFormat=markdown`，由微软自己决定怎么把
版面转成 markdown。本脚本用这条路，**我们不碰转换**。
`analyzeResult.content` 直接进 `content` 字段，与 Infinity-Parser2 的
`choices[0].message.content` 处于同一位置，同一套 tools/check.py 判定。

仍存在的不对称（报告必须声明，不要粉饰）：
  1. 两边的 markdown 风格由各自厂商决定，表格标记、标题层级不同。
     我们的断言判的是「这段文字/这个金额在不在输出里」，对风格不敏感，
     但 formatting 类断言不可跨系统比较
  2. Azure DI 按整份文档分析，本脚本用 `pages=N` 只要目标页，
     **它仍可能利用到整份文档的上下文**，这对 Azure 有利。
     Infinity-Parser2 是逐页独立调用（sdk-findings.md §2），拿不到这个便利
  3. Azure DI 返回 span 级 confidence，Infinity-Parser2 没有（t0-findings.md §7）。
     置信度那一节只能单边报，不能对比

## 凭证

只从环境变量读，绝不进源码或日志：
  AZURE_DI_ENDPOINT=https://<resource>.cognitiveservices.azure.com
  AZURE_DI_KEY=<key>

**本机没有凭证也能跑 `--dry-run`**，用于在公司电脑运行前检查清单与配额。

用法:
  python tools/azure_di_runner.py --dry-run          # 不需凭证，只列将要调用什么
  python tools/azure_di_runner.py                    # 需要凭证
  python tools/azure_di_runner.py --resume runs/<id> # 断点续跑
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

API_VERSION = "2024-11-30"
MODEL_ID = "prebuilt-layout"
PRICE_PER_1K_PAGES_USD = 10.0  # research-plan.md §5，无阶梯折扣

_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def slug(p):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(p).removesuffix(".pdf"))


def creds(required=True):
    ep = (os.environ.get("AZURE_DI_ENDPOINT") or "").rstrip("/")
    key = os.environ.get("AZURE_DI_KEY") or ""
    placeholder = (not ep or not key or ep.startswith("https://<")
                   or key.startswith("<"))
    if required and placeholder:
        sys.exit("需要 AZURE_DI_ENDPOINT 与 AZURE_DI_KEY（当前为空或仍是占位符）。\n"
                 "在公司电脑上填 .env 后重跑；本机可用 --dry-run 预检。")
    return ep, key, placeholder


def analyze_page(ep, key, pdf_path, page, timeout=180, poll_s=2.0, max_poll=90):
    """提交一页并轮询到完成。返回落盘用的完整记录。

    Azure DI 是异步 API：POST 返回 202 + Operation-Location，
    要轮询到 status=succeeded。耗时统计包含轮询等待，与
    Infinity-Parser2 的同步调用**不完全可比**——这一点报告要写明。
    """
    ts, t0 = now(), time.perf_counter()
    url = (f"{ep}/documentintelligence/documentModels/{MODEL_ID}:analyze"
           f"?api-version={API_VERSION}&pages={page}&outputContentFormat=markdown")
    try:
        r = requests.post(url, timeout=timeout,
                          headers={"Ocp-Apim-Subscription-Key": key,
                                   "Content-Type": "application/pdf"},
                          data=Path(pdf_path).read_bytes())
        if r.status_code != 202:
            return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                    "status": r.status_code, "response_headers": dict(r.headers),
                    "response_body": _body(r), "n_polls": 0}
        op = r.headers.get("Operation-Location")
        for i in range(max_poll):
            time.sleep(poll_s)
            pr = requests.get(op, timeout=timeout,
                              headers={"Ocp-Apim-Subscription-Key": key})
            body = _body(pr)
            st = (body or {}).get("status")
            if st in ("succeeded", "failed"):
                return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                        "status": pr.status_code, "response_headers": dict(pr.headers),
                        "response_body": body, "n_polls": i + 1, "op_status": st}
        return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                "status": -2, "response_headers": {}, "n_polls": max_poll,
                "response_body": {"_error": "poll timeout"}}
    except requests.RequestException as e:
        return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                "status": -1, "response_headers": {},
                "response_body": {"_exception": repr(e)}, "n_polls": 0}


def _body(r):
    try:
        return r.json()
    except ValueError:
        return {"_raw_text": r.text[:4000]}


def process(job, cfg):
    pdf, page, doc_id = job
    dst = cfg["raw_dir"] / f"{slug(pdf)}_p{page}.json"
    if dst.exists():
        prev = json.loads(dst.read_text(encoding="utf-8"))
        if prev.get("ok"):
            return "cached", prev

    rec = analyze_page(cfg["ep"], cfg["key"], pdf, page, timeout=cfg["timeout"])
    ar = (rec.get("response_body") or {}).get("analyzeResult") or {}
    content = ar.get("content") or ""
    ok = rec.get("op_status") == "succeeded" and bool(content)
    out = {
        "schema": "inf-eval/raw/1",       # 与 Infinity-Parser2 落盘同 schema
        "run_id": cfg["run_id"], "pdf": str(pdf), "page": page, "doc_id": doc_id,
        "system": "azure_di", "model_id": MODEL_ID, "api_version": API_VERSION,
        "task_type": "layout_markdown",
        "request": {"outputContentFormat": "markdown", "pages": page,
                    "conversion_by": "microsoft (outputContentFormat=markdown)",
                    "conversion_by_us": False},
        "ts_utc": rec["ts_utc"], "latency_s": rec["latency_s"],
        "n_polls": rec.get("n_polls"), "status": rec["status"],
        "op_status": rec.get("op_status"),
        "response_headers": rec["response_headers"],
        "served_model": ar.get("modelId"),
        "finish_reason": "stop" if ok else "error",   # 对齐判定器的 ok 判断
        "n_pages_billed": len(ar.get("pages") or []),
        "content": content,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        # confidence 是 Azure 独有，Infinity-Parser2 没有，只能单边报
        "has_confidence": any("confidence" in (w or {})
                              for p in (ar.get("pages") or [])
                              for w in (p.get("words") or [])[:1]),
        "ok": ok,
    }
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return ("ok" if ok else "fail"), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-csv", default="data/corpus/pages.csv")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", default="")
    ap.add_argument("--dry-run", action="store_true", help="不调用，只列清单与预估成本")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.pages_csv, encoding="utf-8")))
    jobs = [(r["local_path"], int(r["page"]), r["doc_id"]) for r in rows]
    if a.limit:
        jobs = jobs[:a.limit]

    ep, key, placeholder = creds(required=not a.dry_run)
    cost = len(jobs) / 1000 * PRICE_PER_1K_PAGES_USD
    print(f"页数 {len(jobs)}  模型 {MODEL_ID}  api-version {API_VERSION}")
    print(f"输出格式 markdown（由微软转换，我们不碰转换规则）")
    print(f"预估成本 ${cost:.2f}（${PRICE_PER_1K_PAGES_USD}/1000 页，无阶梯折扣）")

    if a.dry_run:
        print(f"凭证状态: {'占位符/缺失' if placeholder else '已配置'}")
        fams = {}
        for r in rows[:len(jobs)]:
            fams[r["family"]] = fams.get(r["family"], 0) + 1
        print("\n按族:")
        for k, v in sorted(fams.items()):
            print(f"  {k:18} {v:4} 页")
        print(f"\n将调用: POST {ep or '<AZURE_DI_ENDPOINT>'}"
              f"/documentintelligence/documentModels/{MODEL_ID}:analyze"
              f"?api-version={API_VERSION}&pages=<N>&outputContentFormat=markdown")
        print("在公司电脑上填好 .env 后去掉 --dry-run 即可运行。")
        return

    run_dir = Path(a.resume) if a.resume else Path("runs") / (
        f"azure_di_layout_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    raw = run_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    cfg = {"run_id": run_dir.name, "raw_dir": raw, "ep": ep, "key": key,
           "timeout": a.timeout}
    (run_dir / "run_meta.json").write_text(json.dumps({
        "run_id": cfg["run_id"], "started_utc": now(), "system": "azure_di",
        "model_id": MODEL_ID, "api_version": API_VERSION,
        "output_content_format": "markdown",
        "conversion_by_us": False,
        "pages_csv": a.pages_csv, "n_pages": len(jobs),
        "concurrency": a.concurrency,
        "price_per_1k_pages_usd": PRICE_PER_1K_PAGES_USD,
        "asymmetries": [
            "Azure 按整份文档分析，即使指定 pages=N 也可能用到全文上下文；"
            "Infinity-Parser2 逐页独立调用，拿不到这个便利",
            "Azure 是异步 API，耗时含轮询等待，与同步调用不完全可比",
            "Azure 返回 span 级 confidence，Infinity-Parser2 没有，只能单边报",
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    counts, done, t0 = {"ok": 0, "fail": 0, "cached": 0}, [0], time.perf_counter()

    def work(job):
        state, out = process(job, cfg)
        with _lock:
            counts[state] += 1
            done[0] += 1
            print(f"{'  ' if state != 'fail' else '！'}[{done[0]:3}/{len(jobs)}] "
                  f"{job[2][:40]:40} p{job[1]:<4} {out.get('latency_s', 0):6.1f}s "
                  f"polls={out.get('n_polls')} {out.get('op_status')}")
        return state

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        list(ex.map(work, jobs))

    wall = time.perf_counter() - t0
    (run_dir / "run_summary.json").write_text(json.dumps({
        "run_id": cfg["run_id"], "finished_utc": now(), "wall_s": round(wall, 1),
        "counts": counts, "n_pages": len(jobs),
        "throughput_pages_per_min": round(len(jobs) / wall * 60, 2),
        "estimated_cost_usd": round(cost, 2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {counts}  墙钟 {wall/60:.1f} 分钟  -> {run_dir}")
    print(f"判定：python tools/check.py {run_dir}")


if __name__ == "__main__":
    main()
