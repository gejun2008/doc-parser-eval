#!/usr/bin/env python3
"""
ParseBench runner：Infinity-Parser2（research-plan.md §3.2 第二层）

裸 HTTP 调用厂商端点（CLAUDE.md 工程约定 1），逐字复刻 ParseBench 官方
`infinity_parser2_flash` pipeline 的调用口径，产物交给官方判分器，判分逻辑一行不写。

## 为什么是 doc2json + deep parsing，而不是产品默认的 doc2md

  1. 厂商在 ParseBench 上的自报分数（leaderboard 73.25 / FinIE 站点 72.2）用的就是这套配置
     （parse_bench/inference/pipelines/parse.py: task_type=doc2json, output_format=json,
     deep_parsing_mode 默认 True）。不同口径的分数不能并列
  2. Visual Grounding 维度要 bbox，只有 doc2json 给
  代价：这不是产品默认口径（产品默认 doc2md，sdk-findings.md），报告必须声明

## 逐字复刻的部分（出处：ParseBench@3295d7f providers/parse/infinity_parser2.py，
##                         infinity_parser2==0.4.0 SDK）

  页面图像     每页 300 DPI 渲染 -> smart_resize(factor=32, min 2048, max 16777216) -> PNG
  主调用       PROMPT_DOC2JSON, max_tokens=32768, temperature=0.0, top_p=1.0
  后处理       extract_json_content -> truncate_last_incomplete_element
               -> restore_abs_bbox_coordinates（按渲染图原始宽高还原 0-1000 坐标）
  deep parsing 每个 category=figure 的元素按 bbox 从渲染图裁出，
               custom prompt "please convert the image to a markdown table", max_tokens=2048，
               原文回填 elem["text"]，不做后处理；任一步异常则整页退回 shallow 结果（同 provider）
  raw_output   {"result": <json 字符串>, "_config": {..., page_width, page_height}}，
               多页再加 page_results。由官方 provider.normalize 转成 result.json

## 与官方 provider 不一致的地方（报告附录必须写）

  1. PDF 渲染用 PyMuPDF，官方 provider 用 pdf2image(poppler)。本机无 poppler；
     INF 自家 SDK 用的也是 PyMuPDF（sdk-findings.md），像素尺寸可能差 1px
  2. 走裸 HTTP，不走 SDK；全量落盘所有调用（主调用 + 每个 figure 调用）
  3. data URL 的 MIME 写 image/png（实际字节就是 PNG）；SDK 对 PIL 输入会标成 image/jpeg。
     服务端按字节解码，预期无影响——工作假设，未单独验证
  4. finish_reason=length 的页：SDK 会把截断内容静默当结果，官方分数也是这样算的。
     本 runner 同样把截断内容交给判分器（与厂商口径一致），但在 run_summary 里单列这些页
  5. 主调用重试耗尽仍失败（非 200 / 网络异常）：写空结果，让判分器按失败计分。
     官方判分器对缺失的结果文件**不计入分母**，不写空结果会让失败页凭空消失、分数虚高

产物:
  runs/<run_id>/raw/<slug>.json                     每份文件全部调用的原始记录（inf-eval/raw/1）
  runs/<run_id>/parsebench/infinity_parser2_flash/<group>/<stem>.raw.json
                                                    官方 RawInferenceResult 格式
  runs/<run_id>/run_meta.json, run_summary.json

用法:
  python tools/parsebench_runner.py --limit 3                 # 先验证管道
  python tools/parsebench_runner.py --concurrency 4
  python tools/parsebench_runner.py --resume runs/<run_id>    # 断点续跑，只重跑失败的
之后:
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run_id>
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from probe import PROMPT_DOC2JSON, smart_resize  # noqa: E402  逐字来自 SDK

API_URL = os.environ.get("INFINITY_PARSER2_API_URL", "")
API_KEY = os.environ.get("INFINITY_PARSER2_API_KEY", "")
MODEL = os.environ.get("INFINITY_PARSER2_MODEL", "inf-mllm")

PIPELINE = "infinity_parser2_flash"
PIPELINE_SPEC = {   # 与 parse_bench/inference/pipelines/parse.py 注册的一致
    "pipeline_name": PIPELINE, "provider_name": "infinity_parser2", "product_type": "parse",
    "config": {"model_name": "infly/Infinity-Parser2-Flash", "backend": "vllm-server",
               "task_type": "doc2json", "output_format": "json"},
    "per_file_timeout": None,
}
DEEP_PROMPT = "please convert the image to a markdown table"   # provider._apply_deep_parsing
DEEP_MAX_TOKENS = 2048
MAX_TOKENS = 32768
DPI = 300
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def slug(rel):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(rel).rsplit(".", 1)[0])


# ---------------------------------------------------------------------------
# 逐字复制自 infinity_parser2/utils/utils.py (v0.4.0)，改动会使口径漂移
# ---------------------------------------------------------------------------

def extract_json_content(text: str) -> str:
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    partial = re.search(r"```json\n(.*)", text, re.DOTALL)
    if partial:
        return partial.group(1).strip()
    return text


def truncate_last_incomplete_element(text: str):
    needs_truncation = len(text) > 65536 or not text.rstrip().endswith("]")
    if not needs_truncation:
        return text, False
    if text.count('{"bbox":') <= 1:
        return text, False
    last_bbox_pos = text.rfind('{"bbox":')
    truncated = text[:last_bbox_pos].rstrip()
    if truncated.endswith(","):
        truncated = truncated[:-1] + "]"
    return truncated, True


def restore_abs_bbox_coordinates(ans: str, origin_h: float, origin_w: float) -> str:
    try:
        data = json.loads(ans)
    except json.JSONDecodeError:
        return ans
    valid = True
    for item in data:
        for key in item:
            if "bbox" not in key:
                continue
            bbox = item[key]
            if len(bbox) == 4 and all(isinstance(c, (int, float)) for c in bbox):
                x1, y1, x2, y2 = bbox
                item[key] = [
                    int(x1 / 1000.0 * origin_w),
                    int(y1 / 1000.0 * origin_h),
                    int(x2 / 1000.0 * origin_w),
                    int(y2 / 1000.0 * origin_h),
                ]
            else:
                valid = False
    return json.dumps(data, ensure_ascii=False) if valid else ans


def postprocess_doc2json(raw_text, pil):
    """= SDK postprocess_doc2json_result(raw, image, "json")"""
    text = extract_json_content(raw_text)
    text, truncated = truncate_last_incomplete_element(text)
    w, h = pil.size
    return restore_abs_bbox_coordinates(text, h, w), truncated


# ---------------------------------------------------------------------------
# 图像
# ---------------------------------------------------------------------------

def load_pages(path):
    """= provider.load_images，但 PDF 用 PyMuPDF 渲染（见文件头不一致第 1 条）。"""
    if path.suffix.lower() == ".pdf":
        import fitz
        doc = fitz.open(path)
        out = []
        for page in doc:
            pix = page.get_pixmap(dpi=DPI)
            out.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        if not out:
            raise ValueError(f"PDF 没有页面: {path}")
        return out
    return [Image.open(path).convert("RGB")]


def encode(pil):
    """= SDK encode_image_to_base64(PIL, min_pixels=2048, max_pixels=16777216)"""
    img = pil.copy()
    h, w = smart_resize(img.size[1], img.size[0])
    img = img.resize((w, h))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    meta = {"orig_w": pil.size[0], "orig_h": pil.size[1], "sent_w": w, "sent_h": h,
            "png_bytes": len(data), "png_sha256": hashlib.sha256(data).hexdigest()[:16]}
    return base64.b64encode(data).decode(), meta


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def call_once(payload, timeout):
    ts, t0 = now(), time.perf_counter()
    try:
        r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}",
                                            "Content-Type": "application/json"},
                          json=payload, timeout=timeout)
        try:
            body = r.json()
        except ValueError:
            body = {"_raw_text": r.text[:8000]}
        return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                "status": r.status_code, "response_headers": dict(r.headers),
                "response_body": body}
    except requests.RequestException as e:
        return {"ts_utc": ts, "latency_s": round(time.perf_counter() - t0, 3),
                "status": -1, "response_headers": {}, "response_body": {"_exception": repr(e)}}


def choice(rec):
    return ((rec.get("response_body") or {}).get("choices") or [{}])[0]


def call(pil, prompt, max_tokens, cfg, kind):
    """一次逻辑调用（带重试）。返回 (content 或 None, 记录)。

    重试条件只有「没拿到 200」。拿到 200 但 finish_reason=length 不重试——
    T0/olmOCR 实测复读退化是确定性的，重试救不回来，只会多烧 token。
    """
    b64, meta = encode(pil)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt}]}],
        "max_tokens": max_tokens, "temperature": 0.0, "top_p": 1.0,
    }
    attempts = []
    for i in range(cfg["retries"] + 1):
        rec = call_once(payload, cfg["timeout"])
        attempts.append(rec)
        if rec["status"] == 200 and choice(rec).get("message"):
            break
        if i < cfg["retries"]:
            time.sleep(cfg["backoff"] * (2 ** i))
    final = attempts[-1]
    ch = choice(final)
    content = (ch.get("message") or {}).get("content") if final["status"] == 200 else None
    return content, {
        "kind": kind, "image": meta, "max_tokens": max_tokens,
        "prompt_sha256_16": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "n_attempts": len(attempts), "attempts": attempts,
        "status": final["status"], "finish_reason": ch.get("finish_reason"),
        "usage": (final.get("response_body") or {}).get("usage"),
        "served_model": (final.get("response_body") or {}).get("model"),
        "latency_s": final["latency_s"], "ok": content is not None,
    }


def deep_parse(result_json, pil, cfg, calls):
    """= provider._apply_deep_parsing。任一步异常 -> 返回 shallow 结果。"""
    try:
        elements = json.loads(result_json)
        if not isinstance(elements, list):
            return result_json, "not_list"
        figs = [e for e in elements if e.get("category", "").strip().lower() == "figure"]
        if not figs:
            return result_json, "no_figure"
        crops = [pil.crop((max(0, int(e["bbox"][0])), max(0, int(e["bbox"][1])),
                           min(pil.width, int(e["bbox"][2])), min(pil.height, int(e["bbox"][3]))))
                 for e in figs]
        texts = []
        for crop in crops:
            if crop.width <= 0 or crop.height <= 0:
                raise ValueError("empty crop")
            content, rec = call(crop, DEEP_PROMPT, DEEP_MAX_TOKENS, cfg, "deep_figure")
            calls.append(rec)
            if content is None:
                # SDK 里 HTTP 异常会抛出，provider 捕获后整页退回 shallow
                raise RuntimeError(f"figure call failed status={rec['status']}")
            texts.append(content)
        for e, t in zip(figs, texts):
            e["text"] = t
        return json.dumps(elements), f"deep_{len(figs)}"
    except Exception as e:  # noqa: BLE001  与 provider 一致：吞掉异常，退回 shallow
        return result_json, f"fallback_shallow: {type(e).__name__}: {e}"


def process(row, cfg):
    rel = row["pdf"]                         # docs/<group>/<file>
    group = rel.split("/")[1]
    stem = rel.rsplit("/", 1)[1].rsplit(".", 1)[0]
    our = cfg["raw_dir"] / f"{slug(rel)}.json"
    pb = cfg["pb_dir"] / group / f"{stem}.raw.json"
    if our.exists():
        prev = json.loads(our.read_text(encoding="utf-8"))
        if prev.get("ok"):
            return "cached", prev

    started = datetime.now()
    t0 = time.perf_counter()
    calls, page_raws, notes = [], [], []
    ok = True
    try:
        pages = load_pages(cfg["root"] / rel)
    except Exception as e:  # noqa: BLE001
        pages, ok = [], False
        notes.append(f"load_error: {e!r}")

    for pil in pages:
        content, rec = call(pil, PROMPT_DOC2JSON, MAX_TOKENS, cfg, "doc2json")
        calls.append(rec)
        if content is None:
            ok = False
            page_raws.append({"result": "", "_config": {}})
            continue
        result, truncated = postprocess_doc2json(content, pil)
        rec["json_truncated_by_postprocess"] = truncated
        result, deep_note = deep_parse(result, pil, cfg, calls)
        notes.append(deep_note)
        page_raws.append({"result": result, "_config": {
            "model_name": PIPELINE_SPEC["config"]["model_name"], "backend": "vllm-server",
            "api_url": "<redacted>", "task_type": "doc2json", "output_format": "json",
            "batch_size": 4, "page_width": float(pil.size[0]), "page_height": float(pil.size[1])}})

    completed = datetime.now()
    main_calls = [c for c in calls if c["kind"] == "doc2json"]
    out = {
        "schema": "inf-eval/raw/1", "run_id": cfg["run_id"], "pdf": rel,
        "dimension": row["dimension"], "stratum": row["stratum"],
        "task_type": "doc2json+deep_parsing", "n_pages": len(pages),
        "calls": calls, "deep_parsing": notes,
        "finish_reasons": [c["finish_reason"] for c in main_calls],
        "length_truncated": any(c["finish_reason"] == "length" for c in main_calls),
        "usage_total": {k: sum((c.get("usage") or {}).get(k) or 0 for c in calls)
                        for k in ("prompt_tokens", "completion_tokens")},
        "served_models": sorted({c["served_model"] for c in calls if c.get("served_model")}),
        "latency_s": round(time.perf_counter() - t0, 3), "ts_utc": now(),
        "ok": ok and bool(pages),
    }
    our.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 官方 RawInferenceResult。主调用失败的页写空 result，由 parsebench_score.py 记为空输出
    raw_output = dict(page_raws[0]) if page_raws else {"result": "", "_config": {}}
    if len(page_raws) > 1:
        raw_output["page_results"] = page_raws
    pb.parent.mkdir(parents=True, exist_ok=True)
    pb.write_text(json.dumps({
        "request": {"example_id": f"{group}/{stem}",
                    "source_file_path": str((cfg["root"] / rel).resolve()),
                    "product_type": "parse", "schema_override": None, "config_override": None},
        "pipeline": PIPELINE_SPEC, "pipeline_name": PIPELINE, "product_type": "parse",
        "raw_output": raw_output,
        "started_at": started.isoformat(), "completed_at": completed.isoformat(),
        "latency_in_ms": int((completed - started).total_seconds() * 1000),
    }, ensure_ascii=False), encoding="utf-8")
    return ("ok" if out["ok"] else "fail"), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/parsebench/manifest.csv")
    ap.add_argument("--root", default="data/parsebench/subset")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--backoff", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dimension", default="", help="只跑某个维度，如 table")
    ap.add_argument("--resume", default="")
    a = ap.parse_args()
    if not API_URL or not API_KEY:
        sys.exit("需要 INFINITY_PARSER2_API_URL 和 INFINITY_PARSER2_API_KEY")
    if a.concurrency > 16:
        sys.exit("并发不超过 16（CLAUDE.md 工程约定 4）")

    rows = list(csv.DictReader(open(a.manifest, encoding="utf-8")))
    if a.dimension:
        rows = [r for r in rows if r["dimension"] == a.dimension]
    if a.limit:
        # 每个维度各取几份，管道验证时四个维度都覆盖到
        per = Counter()
        picked = []
        for r in rows:
            if per[r["dimension"]] < a.limit:
                picked.append(r)
                per[r["dimension"]] += 1
        rows = picked

    run_dir = Path(a.resume) if a.resume else Path("runs") / (
        f"parsebench_inf_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    raw_dir = run_dir / "raw"
    pb_dir = run_dir / "parsebench" / PIPELINE
    raw_dir.mkdir(parents=True, exist_ok=True)
    pb_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"run_id": run_dir.name, "raw_dir": raw_dir, "pb_dir": pb_dir,
           "root": Path(a.root), "timeout": a.timeout, "retries": a.retries,
           "backoff": a.backoff}
    meta_path = run_dir / "run_meta.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({
            "run_id": run_dir.name, "started_utc": now(), "system": "infinity_parser2",
            "model_requested": MODEL, "pipeline_equivalent": PIPELINE_SPEC,
            "prompt_doc2json_sha256_16": hashlib.sha256(PROMPT_DOC2JSON.encode()).hexdigest()[:16],
            "deep_prompt": DEEP_PROMPT, "deep_max_tokens": DEEP_MAX_TOKENS,
            "max_tokens": MAX_TOKENS, "dpi": DPI, "pdf_renderer": "PyMuPDF",
            "manifest": a.manifest, "root": a.root, "n_files": len(rows),
            "concurrency": a.concurrency, "timeout_s": a.timeout, "retries": a.retries,
            "client": {"transport": "raw HTTP (requests)", "sdk_used": False},
            "reference": {"parsebench_commit": "3295d7f", "sdk": "infinity_parser2==0.4.0"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    counts, done, t0 = Counter(), [0], time.perf_counter()

    def work(row):
        try:
            state, out = process(row, cfg)
        except Exception as e:  # noqa: BLE001  单份异常不拖垮整批，记下来
            state, out = "error", {"pdf": row["pdf"], "error": repr(e)}
        with _lock:
            counts[state] += 1
            done[0] += 1
            fr = ",".join(str(x) for x in out.get("finish_reasons", []))
            print(f"{'  ' if state in ('ok', 'cached') else '！'}[{done[0]:3}/{len(rows)}] "
                  f"{row['dimension']:6} {row['pdf'][5:60]:55} {out.get('latency_s', 0):7.1f}s "
                  f"calls={len(out.get('calls', []))} fr={fr} {state}"
                  + (f" {out.get('error', '')}" if state == "error" else ""), flush=True)
        return state

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        list(ex.map(work, rows))

    wall = time.perf_counter() - t0
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw_dir.glob("*.json"))]
    calls = [c for r in recs for c in r.get("calls", [])]
    lat = sorted(c["latency_s"] for c in calls if c["ok"])
    (run_dir / "run_summary.json").write_text(json.dumps({
        "run_id": run_dir.name, "finished_utc": now(), "wall_s_this_session": round(wall, 1),
        "concurrency": a.concurrency, "counts_this_session": dict(counts),
        "n_files_on_disk": len(recs), "n_files_ok": sum(r["ok"] for r in recs),
        "failed_files": [r["pdf"] for r in recs if not r["ok"]],
        "length_truncated_files": [r["pdf"] for r in recs if r.get("length_truncated")],
        "n_calls": len(calls),
        "n_calls_by_kind": dict(Counter(c["kind"] for c in calls)),
        "deep_parsing_fallbacks": [r["pdf"] for r in recs
                                   if any(str(n).startswith("fallback") for n in r.get("deep_parsing", []))],
        "served_models": sorted({m for r in recs for m in r.get("served_models", [])}),
        "tokens": {k: sum(r["usage_total"][k] for r in recs)
                   for k in ("prompt_tokens", "completion_tokens")},
        "call_latency_s": {"n": len(lat), "median": lat[len(lat) // 2] if lat else None,
                           "p95": lat[int(len(lat) * 0.95)] if len(lat) > 1 else None},
        "throughput_files_per_min_this_session": round(len(rows) / wall * 60, 2) if wall else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {dict(counts)}  墙钟 {wall / 60:.1f} 分钟 -> {run_dir}")
    print(f"判分: tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py {run_dir}")


if __name__ == "__main__":
    main()
