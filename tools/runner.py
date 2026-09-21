#!/usr/bin/env python3
"""
评测 runner (T4)

裸 HTTP 调用 Infinity-Parser2 端点，逐页落盘原始响应。理由见 CLAUDE.md 工程约定 1：
厂商 SDK 丢弃 finish_reason / usage / 响应头 / 耗时，而这些是报告里静默失败与服务档
两节的原料。

口径与 SDK 对齐（infinity_parser2==0.4.0，逐字核对过）：
  prompt          prompts.py 的 PROMPT_DOC2MD / PROMPT_DOC2JSON
  栅格化          PyMuPDF 300 DPI -> qwen_vl_utils.smart_resize -> PNG base64
  请求参数        max_tokens=32768, temperature=0.0, top_p=1.0
不对齐的地方只有一处：走裸 HTTP 而不是 openai SDK，且全量落盘。

T0 实测对 runner 的三点约束（docs/t0-findings.md）：
  §7   logprobs 静默忽略，不必再请求
  §10  静默排队，吞吐 1.6-1.8 页/分且不随并发上升 -> 默认并发 2，超时 900s
  §8   finish_reason=length 必须计为失败，不能当正常结果统计

用法:
  python tools/runner.py --manifest data/olmocr_bench/manifest.csv \
      --pdf-root data/olmocr_bench/bench_data/pdfs --task doc2md
  python tools/runner.py ... --resume runs/<run_id>     # 断点续跑
  python tools/runner.py ... --limit 5                  # 先跑 5 页验证管道
"""

import argparse
import base64
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

sys.path.insert(0, str(Path(__file__).parent))
from probe import render_page, smart_resize  # noqa: E402  同口径栅格化，不重复实现

API_URL = os.environ.get("INFINITY_PARSER2_API_URL", "")
API_KEY = os.environ.get("INFINITY_PARSER2_API_KEY", "")
MODEL = os.environ.get("INFINITY_PARSER2_MODEL", "inf-mllm")
if not API_URL or not API_KEY:
    sys.exit("需要 INFINITY_PARSER2_API_URL 和 INFINITY_PARSER2_API_KEY")

# 逐字复制自 infinity_parser2/prompts.py v0.4.0。改动会使结果与产品默认口径不可比。
PROMPT_DOC2MD = """
You are an AI assistant specialized in converting PDF images to Markdown format. Please follow these instructions for the conversion:

1. Text Processing:
- Accurately recognize all text content in the PDF image without guessing or inferring.
- Convert the recognized text into Markdown format.
- Maintain the original document structure, including headings, paragraphs, lists, etc.

2. Mathematical Formula Processing:
- Convert all mathematical formulas to LaTeX format.
- Enclose inline formulas with $ $. For example: This is an inline formula $E = mc^2$
- Enclose block formulas with $$ $$. For example: $$\\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$

3. Table Processing:
- Convert tables to HTML format.

4. Figure Handling:
- Ignore figures content in the PDF image. Do not attempt to describe or convert images.

5. Output Format:
- Ensure the output Markdown document has a clear structure with appropriate line breaks between elements.
- For complex layouts, try to maintain the original document's structure and format as closely as possible.

Please strictly follow these guidelines to ensure accuracy and consistency in the conversion. Your task is to accurately convert the content of the PDF image into Markdown format without adding any extra explanations or comments.
"""

from probe import PROMPT_DOC2JSON  # noqa: E402  同样逐字来自 SDK

PROMPTS = {"doc2md": PROMPT_DOC2MD, "doc2json": PROMPT_DOC2JSON}

_print_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def slug(pdf_rel):
    """data/pdfs/tables/abc_pg4.pdf -> tables__abc_pg4，用作落盘文件名。"""
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(pdf_rel).removesuffix(".pdf"))


def call_once(payload, timeout):
    """一次裸 HTTP 调用。返回落盘用的完整记录，异常也记录，不抛。"""
    ts, t0 = now(), time.perf_counter()
    try:
        r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}",
                                            "Content-Type": "application/json"},
                          json=payload, timeout=timeout)
        dt = time.perf_counter() - t0
        try:
            body = r.json()
        except ValueError:
            body = {"_raw_text": r.text[:8000]}
        return {"ts_utc": ts, "latency_s": round(dt, 3), "status": r.status_code,
                "response_headers": dict(r.headers), "response_body": body}
    except requests.RequestException as e:
        return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                "status": -1, "response_headers": {}, "response_body": {"_exception": repr(e)}}


def ok(rec):
    """成功 = HTTP 200 且 finish_reason 为 stop。length 是截断，按失败处理（§8）。"""
    if rec["status"] != 200:
        return False
    ch = (rec["response_body"].get("choices") or [{}])[0]
    return ch.get("finish_reason") == "stop"


def process(job, cfg):
    """一页：栅格化 -> 调用（带重试）-> 落盘。已有成功结果则跳过。"""
    pdf_rel, page = job
    dst = cfg["raw_dir"] / f"{slug(pdf_rel)}_p{page}.json"
    if dst.exists():
        try:
            prev = json.loads(dst.read_text(encoding="utf-8"))
            if prev.get("ok"):
                return "cached", prev
        except json.JSONDecodeError:
            pass  # 文件损坏就重跑

    pdf_path = cfg["pdf_root"] / pdf_rel
    b64, meta = render_page(pdf_path, page, dpi=cfg["dpi"])
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": cfg["prompt"]}]}],
        "max_tokens": cfg["max_tokens"], "temperature": 0.0, "top_p": 1.0,
    }

    attempts = []
    for i in range(cfg["retries"] + 1):
        rec = call_once(payload, cfg["timeout"])
        attempts.append(rec)
        if ok(rec):
            break
        if i < cfg["retries"]:
            time.sleep(cfg["backoff"] * (2 ** i))

    final = attempts[-1]
    ch = (final["response_body"].get("choices") or [{}])[0]
    content = (ch.get("message") or {}).get("content") or ""
    out = {
        "schema": "inf-eval/raw/1",
        "run_id": cfg["run_id"], "pdf": str(pdf_rel), "page": page,
        "task_type": cfg["task"], "prompt_sha256": cfg["prompt_sha"],
        "request": {"model_requested": MODEL, "max_tokens": cfg["max_tokens"],
                    "temperature": 0.0, "top_p": 1.0, "timeout_s": cfg["timeout"],
                    "concurrency": cfg["concurrency"]},
        "image": meta,
        # 失败也留全部尝试，重试次数不能被静默吞掉
        "n_attempts": len(attempts), "attempts": attempts,
        "ts_utc": final["ts_utc"], "latency_s": final["latency_s"],
        "status": final["status"], "response_headers": final["response_headers"],
        "served_model": final["response_body"].get("model"),
        "finish_reason": ch.get("finish_reason"),
        "usage": final["response_body"].get("usage"),
        "content": content,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "ok": ok(final),
    }
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return ("ok" if out["ok"] else "fail"), out


def load_jobs(manifest, pdf_root, limit):
    rows = list(csv.DictReader(open(manifest, encoding="utf-8")))
    jobs = [(r["pdf"], int(r.get("page") or 1)) for r in rows]
    missing = [p for p, _ in jobs if not (pdf_root / p).exists()]
    if missing:
        sys.exit(f"{len(missing)} 个 PDF 不存在，例如 {missing[:3]}")
    return jobs[:limit] if limit else jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/olmocr_bench/manifest.csv")
    ap.add_argument("--pdf-root", default="data/olmocr_bench/bench_data/pdfs")
    ap.add_argument("--task", choices=list(PROMPTS), default="doc2md")
    ap.add_argument("--concurrency", type=int, default=2,
                    help="T0 §10：吞吐不随并发上升，调高只会拉长单请求延迟")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--backoff", type=float, default=5.0)
    ap.add_argument("--max-tokens", type=int, default=32768)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", default="", help="已有 run 目录，续跑")
    ap.add_argument("--note", default="", help="写进 run_meta 的说明")
    a = ap.parse_args()

    if a.concurrency > 16:
        sys.exit("并发上限 16（厂商声明），且实测吞吐不随并发上升")

    prompt = PROMPTS[a.task]
    run_dir = Path(a.resume) if a.resume else Path("runs") / (
        f"{MODEL}_{a.task}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    cfg = {"run_id": run_dir.name, "raw_dir": raw_dir, "pdf_root": Path(a.pdf_root),
           "task": a.task, "prompt": prompt,
           "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
           "max_tokens": a.max_tokens, "dpi": a.dpi, "timeout": a.timeout,
           "retries": a.retries, "backoff": a.backoff, "concurrency": a.concurrency}

    jobs = load_jobs(a.manifest, cfg["pdf_root"], a.limit)
    print(f"run_id   {cfg['run_id']}\n任务     {a.task} (prompt sha {cfg['prompt_sha']})\n"
          f"页数     {len(jobs)}  并发 {a.concurrency}  超时 {a.timeout}s\n"
          f"预计     约 {len(jobs) / 1.75:.0f} 分钟（按 T0 实测 1.75 页/分）\n")

    (run_dir / "run_meta.json").write_text(json.dumps({
        "run_id": cfg["run_id"], "started_utc": now(), "note": a.note,
        "endpoint": API_URL, "model_requested": MODEL, "task_type": a.task,
        "prompt_sha256_16": cfg["prompt_sha"], "manifest": a.manifest,
        "pdf_root": a.pdf_root, "n_pages": len(jobs),
        "params": {"max_tokens": a.max_tokens, "temperature": 0.0, "top_p": 1.0,
                   "dpi": a.dpi, "concurrency": a.concurrency, "timeout_s": a.timeout,
                   "retries": a.retries},
        "client": {"transport": "raw HTTP (requests)", "sdk_used": False},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    t0 = time.perf_counter()
    counts = {"ok": 0, "fail": 0, "cached": 0}
    done = [0]

    def work(job):
        state, out = process(job, cfg)
        with _print_lock:
            counts[state] += 1
            done[0] += 1
            el = time.perf_counter() - t0
            rate = done[0] / el * 60
            flag = {"ok": "  ", "cached": "= ", "fail": "！"}[state]
            print(f"{flag}[{done[0]:3}/{len(jobs)}] {job[0]:<46} "
                  f"{out.get('latency_s', 0):6.1f}s finish={out.get('finish_reason')} "
                  f"try={out.get('n_attempts')} | {rate:.2f} 页/分")
        return state

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        list(ex.map(work, jobs))

    wall = time.perf_counter() - t0
    usages, lats = [], []
    for f in raw_dir.glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("usage"):
            usages.append(r["usage"])
        if r.get("ok"):
            lats.append(r["latency_s"])
    summary = {
        "run_id": cfg["run_id"], "finished_utc": now(), "wall_s": round(wall, 1),
        "counts": counts, "n_raw_files": len(list(raw_dir.glob("*.json"))),
        "throughput_pages_per_min": round(len(jobs) / wall * 60, 2),
        "latency_s": {"n": len(lats), "min": min(lats, default=None),
                      "max": max(lats, default=None),
                      "median": sorted(lats)[len(lats)//2] if lats else None},
        "tokens": {"prompt": sum(u.get("prompt_tokens", 0) for u in usages),
                   "completion": sum(u.get("completion_tokens", 0) for u in usages),
                   "total": sum(u.get("total_tokens", 0) for u in usages)},
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {counts}  墙钟 {wall/60:.1f} 分钟  "
          f"{summary['throughput_pages_per_min']} 页/分")
    print(f"tokens prompt={summary['tokens']['prompt']:,} "
          f"completion={summary['tokens']['completion']:,}")
    print(f"-> {run_dir}")
    if counts["fail"]:
        print(f"！{counts['fail']} 页失败，重跑同一目录续跑：\n"
              f"  python tools/runner.py --resume {run_dir} --task {a.task}")


if __name__ == "__main__":
    main()
