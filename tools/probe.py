#!/usr/bin/env python3
"""
Infinity-Parser2 API 端点探针 (T0)

在碰任何数据集之前跑完这个脚本。目的是把「这个端点到底是什么、有什么行为」
用证据固定下来，而不是靠厂商文档的说法。

所有原始响应（含 HTTP 头、状态码、耗时、usage）落盘到 probe_out/，
报告附录直接引用。

依赖:  pip install requests pymupdf pillow
环境:  export INFINITY_PARSER2_API_URL=...
       export INFINITY_PARSER2_API_KEY=...

用法:
  python probe.py models                      # /v1/models 返回什么
  python probe.py ping                        # 纯文本请求, 看响应骨架
  python probe.py page doc.pdf 7              # 单页 doc2json, 试 logprobs
  python probe.py repeat doc.pdf 7 --n 3      # 同页重复调用一致性
  python probe.py concurrency doc.pdf --n 20  # 压过 16, 看限流真实行为
  python probe.py budget doc.pdf 7 --max-tokens 2000   # 逼出截断, 看 finish_reason
"""

import argparse
import base64
import hashlib
import io
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("probe_out")
OUT.mkdir(exist_ok=True)

API_URL = os.environ.get("INFINITY_PARSER2_API_URL", "")
API_KEY = os.environ.get("INFINITY_PARSER2_API_KEY", "")
MODEL = os.environ.get("INFINITY_PARSER2_MODEL", "inf-mllm")

if not API_URL or not API_KEY:
    sys.exit("需要 INFINITY_PARSER2_API_URL 和 INFINITY_PARSER2_API_KEY")

BASE = API_URL.rsplit("/chat/completions", 1)[0]

# SDK 的 doc2json prompt, 逐字复制自 infinity_parser2/prompts.py v0.4.0
PROMPT_DOC2JSON = """
- Extract layout information from the provided PDF image.
- For each layout element, output its bbox, category, and the text content within the bbox.
- Bbox format: [x1, y1, x2, y2].
- Allowed layout categories: ['header', 'title', 'text', 'figure', 'table', 'formula', 'figure_caption', 'table_caption', 'formula_caption', 'figure_footnote', 'table_footnote', 'page_footnote', 'footer'].
- Text extraction and formatting:
  1) For 'figure', the text field must be an empty string.
  2) For 'formula', format text as LaTeX.
  3) For 'table', format text as HTML.
  4) For all other categories (e.g., text, title), format text as Markdown.
- The output text must be exactly the original text from the image, with no translation or rewriting.
- Sort all layout elements in human reading order.
- Final output must be a single JSON object.
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def save(name, obj):
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {p}")


def smart_resize(h, w, factor=32, min_pixels=2048, max_pixels=16777216):
    """复刻 qwen_vl_utils.smart_resize, 保证与 SDK 送出的像素完全一致。"""
    h_bar = max(factor, round(h / factor) * factor)
    w_bar = max(factor, round(w / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((h * w) / max_pixels)
        h_bar = max(factor, math.floor(h / beta / factor) * factor)
        w_bar = max(factor, math.floor(w / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        h_bar = math.ceil(h * beta / factor) * factor
        w_bar = math.ceil(w * beta / factor) * factor
    return h_bar, w_bar


def render_page(pdf_path, page_no, dpi=300):
    """按 SDK 口径栅格化: PyMuPDF 300 DPI -> smart_resize -> PNG base64。"""
    import fitz
    from PIL import Image

    doc = fitz.open(pdf_path)
    pix = doc[page_no - 1].get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    h, w = smart_resize(img.size[1], img.size[0])
    img = img.resize((w, h))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    meta = {
        "pdf": str(pdf_path),
        "page": page_no,
        "render_dpi": dpi,
        "sent_w": w,
        "sent_h": h,
        "sent_pixels": w * h,
        "png_bytes": len(data),
        "png_sha256": hashlib.sha256(data).hexdigest()[:16],
    }
    return base64.b64encode(data).decode(), meta


def post(payload, timeout=300):
    """裸 HTTP 调用。返回 (耗时, 状态码, 响应头, 解析后 body 或原文)。"""
    t0 = time.perf_counter()
    try:
        r = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        dt = time.perf_counter() - t0
        try:
            body = r.json()
        except Exception:
            body = {"_raw_text": r.text[:4000]}
        return dt, r.status_code, dict(r.headers), body
    except Exception as e:
        return time.perf_counter() - t0, -1, {}, {"_exception": repr(e)}


def summarize(body):
    """抽出报告要用的字段。choices[0].message.content 只留长度和头尾。"""
    if not isinstance(body, dict) or "choices" not in body:
        return body
    ch = (body.get("choices") or [{}])[0]
    content = (ch.get("message") or {}).get("content") or ""
    return {
        "served_model": body.get("model"),
        "id": body.get("id"),
        "finish_reason": ch.get("finish_reason"),
        "usage": body.get("usage"),
        "content_len": len(content),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest()[:16],
        "content_head": content[:400],
        "content_tail": content[-200:],
        "has_logprobs": ch.get("logprobs") is not None,
    }


def img_payload(b64, max_tokens=32768, temperature=0.0, extra=None):
    p = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": PROMPT_DOC2JSON},
            ],
        }],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 1.0,
    }
    if extra:
        p.update(extra)
    return p


# ---------------------------------------------------------------- probes

def probe_models():
    """真正服务的模型 id 是什么, max_model_len 多少。"""
    print("[models]")
    r = requests.get(BASE + "/models",
                     headers={"Authorization": f"Bearer {API_KEY}"}, timeout=30)
    out = {"ts": now(), "status": r.status_code, "headers": dict(r.headers)}
    try:
        out["body"] = r.json()
    except Exception:
        out["body"] = r.text[:2000]
    print(json.dumps(out.get("body"), ensure_ascii=False)[:800])
    save("01_models", out)


def probe_ping():
    """纯文本请求。响应里的 model 字段会暴露服务端真实模型名。"""
    print("[ping]")
    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": "ping"}],
               "max_tokens": 16}
    dt, code, hdr, body = post(payload, timeout=60)
    out = {"ts": now(), "latency_s": round(dt, 3), "status": code,
           "headers": hdr, "body": body}
    print(f"  {code}  {dt:.2f}s  served_model={body.get('model')}")
    save("02_ping", out)


def probe_page(pdf, page, logprobs=True):
    """单页解析。同时试 logprobs —— 能开就意味着置信度校准那节还活着。"""
    print(f"[page] {pdf} p{page}")
    b64, meta = render_page(pdf, page)
    print(f"  sent {meta['sent_w']}x{meta['sent_h']} = {meta['sent_pixels']:,}px, "
          f"{meta['png_bytes']:,} bytes")

    results = {}
    # A: 基线, 与 SDK 完全同口径
    dt, code, hdr, body = post(img_payload(b64))
    results["baseline"] = {"latency_s": round(dt, 2), "status": code,
                           "summary": summarize(body)}
    print(f"  baseline: {code} {dt:.1f}s "
          f"finish={results['baseline']['summary'].get('finish_reason')} "
          f"usage={results['baseline']['summary'].get('usage')}")
    save("03_page_baseline_raw", {"ts": now(), "meta": meta,
                                  "headers": hdr, "body": body})

    if logprobs:
        # B: 网关是否放行 logprobs
        dt, code, hdr, body = post(
            img_payload(b64, extra={"logprobs": True, "top_logprobs": 5}))
        ok = code == 200 and summarize(body).get("has_logprobs")
        results["logprobs"] = {"latency_s": round(dt, 2), "status": code,
                               "accepted": bool(ok),
                               "error": body.get("error") if code != 200 else None}
        print(f"  logprobs: {code}  accepted={bool(ok)}")
        save("04_page_logprobs_raw", {"ts": now(), "headers": hdr, "body": body})

        # C: seed 是否被接受（影响可复现性声明）
        dt, code, _, body = post(img_payload(b64, extra={"seed": 42}))
        results["seed"] = {"status": code,
                           "error": body.get("error") if code != 200 else None}
        print(f"  seed:     {code}")

    save("05_page_summary", {"ts": now(), "meta": meta, "results": results})


def probe_budget(pdf, page, max_tokens):
    """故意把 max_tokens 压低, 确认截断时 finish_reason 是否为 length。
    SDK 在这种情况下会静默截掉半截 JSON —— 这是静默失败那一节的证据。"""
    print(f"[budget] max_tokens={max_tokens}")
    b64, meta = render_page(pdf, page)
    dt, code, hdr, body = post(img_payload(b64, max_tokens=max_tokens))
    s = summarize(body)
    print(f"  {code} {dt:.1f}s finish={s.get('finish_reason')} "
          f"content_len={s.get('content_len')}")
    save("06_budget", {"ts": now(), "max_tokens": max_tokens,
                       "meta": meta, "summary": s})


def probe_repeat(pdf, page, n):
    """同一页串行调 n 次, temperature=0。逐字不一致即非确定性。"""
    print(f"[repeat] n={n}")
    b64, meta = render_page(pdf, page)
    rows = []
    for i in range(n):
        dt, code, _, body = post(img_payload(b64))
        s = summarize(body)
        rows.append({"i": i, "latency_s": round(dt, 2), "status": code,
                     "sha256": s.get("content_sha256"),
                     "len": s.get("content_len"),
                     "finish_reason": s.get("finish_reason")})
        print(f"  {i}: {code} {dt:.1f}s len={s.get('content_len')} "
              f"sha={s.get('content_sha256')}")
    identical = len({r["sha256"] for r in rows}) == 1
    print(f"  逐字一致: {identical}")
    save("07_repeat", {"ts": now(), "meta": meta, "identical": identical,
                       "runs": rows})


def probe_concurrency(pdf, n, page=1):
    """压过文档声明的 16。要分清是 429 明确拒绝, 还是静默排队 ——
    后者会污染所有 P95 数字, 必须在报告里声明。"""
    print(f"[concurrency] n={n} (文档声明上限 16)")
    b64, meta = render_page(pdf, page)
    payload = img_payload(b64, max_tokens=512)

    def one(i):
        t0 = time.perf_counter()
        dt, code, hdr, body = post(payload)
        return {"i": i, "start_offset_s": round(t0 - T0, 3),
                "latency_s": round(dt, 2), "status": code,
                "retry_after": hdr.get("retry-after"),
                "finish_reason": summarize(body).get("finish_reason")
                if code == 200 else None,
                "error": str(body.get("error"))[:200] if code != 200 else None}

    T0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as ex:
        rows = list(ex.map(one, range(n)))
    codes = {}
    for r in rows:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    lat = sorted(r["latency_s"] for r in rows if r["status"] == 200)
    print(f"  状态分布: {codes}")
    if lat:
        print(f"  成功请求延迟 min/中位/max: "
              f"{lat[0]:.1f} / {lat[len(lat)//2]:.1f} / {lat[-1]:.1f}s")
    save("08_concurrency", {"ts": now(), "n": n, "meta": meta,
                            "status_counts": codes, "runs": rows})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models")
    sub.add_parser("ping")
    p = sub.add_parser("page"); p.add_argument("pdf"); p.add_argument("page", type=int)
    p = sub.add_parser("budget"); p.add_argument("pdf"); p.add_argument("page", type=int)
    p.add_argument("--max-tokens", type=int, default=2000)
    p = sub.add_parser("repeat"); p.add_argument("pdf"); p.add_argument("page", type=int)
    p.add_argument("--n", type=int, default=3)
    p = sub.add_parser("concurrency"); p.add_argument("pdf")
    p.add_argument("--n", type=int, default=20); p.add_argument("--page", type=int, default=1)
    a = ap.parse_args()

    if a.cmd == "models":
        probe_models()
    elif a.cmd == "ping":
        probe_ping()
    elif a.cmd == "page":
        probe_page(a.pdf, a.page)
    elif a.cmd == "budget":
        probe_budget(a.pdf, a.page, a.max_tokens)
    elif a.cmd == "repeat":
        probe_repeat(a.pdf, a.page, a.n)
    elif a.cmd == "concurrency":
        probe_concurrency(a.pdf, a.n, a.page)


if __name__ == "__main__":
    main()
