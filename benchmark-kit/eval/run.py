"""Call an OpenAI-compatible vision endpoint on every benchmark input and write predictions.

    python -m eval run predictions/<model> [--collections ...] [--smoke] [--limit N]

Configuration is the `endpoint:` block of predictions/<model>/run_card.yaml (see README). The API key is
read from the environment variable named by `api_key_env`; it never goes into a file or a log.

- Each input becomes one image (PDF pages are rendered at the card's `dpi`; image inputs are sent as-is)
  and one chat-completions request. The reply's message content is written, unchanged, to
  predictions/<model>/<prediction_path>.
- Success = HTTP 200 and finish_reason "stop". Anything else (an error, a timeout, finish_reason "length",
  i.e. truncated output) writes no prediction, so the scorer counts the input as failed.
- Every attempt's raw response (status, headers, usage, finish_reason, latency, served model, body) is
  saved under predictions/<model>/_raw/ for audit. The request body is saved without the image.
- Re-running skips inputs that already have a prediction: an interrupted run resumes where it stopped.
"""
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import random
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .common import DATA

DEFAULT_PROMPT = ("Convert this document page to Markdown. Transcribe all text, numbers and tables exactly; "
                  "write tables as Markdown or HTML tables. Output only the Markdown.")
MAX_CONCURRENCY = 16
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
DROP_HEADERS = {"set-cookie", "authorization"}


def load_endpoint(card):
    ep = dict(card.get("endpoint") or {})
    missing = [k for k in ("url", "model", "api_key_env") if not ep.get(k)]
    if missing:
        raise SystemExit(f"run_card.yaml endpoint is missing: {', '.join(missing)}")
    if card.get("input_mode", "image") != "image":
        raise SystemExit("OpenAI-compatible endpoints take images: set input_mode: image (and dpi)")
    key = os.environ.get(ep["api_key_env"])
    if not key:
        raise SystemExit(f"Environment variable {ep['api_key_env']} is not set. "
                         f"PowerShell: $env:{ep['api_key_env']} = \"<key>\"")
    ep.setdefault("prompt", DEFAULT_PROMPT)
    ep.setdefault("max_tokens", 16384)
    ep.setdefault("temperature", 0.0)
    ep.setdefault("token_param", "max_tokens")   # newer OpenAI models: max_completion_tokens
    ep.setdefault("timeout_s", 600)
    ep.setdefault("retries", 2)
    ep.setdefault("auth_header", "Authorization")
    ep.setdefault("auth_prefix", "Bearer ")
    ep["concurrency"] = max(1, min(int(ep.get("concurrency", 4)), MAX_CONCURRENCY))
    return ep, key


def render(input_path, page, dpi, data=DATA):
    """(bytes, mime) of the image sent for one input."""
    p = data / input_path.removeprefix("data/")
    ext = p.suffix.lower()
    if ext in MIME:
        return p.read_bytes(), MIME[ext]
    if ext != ".pdf":
        raise ValueError(f"unsupported input type: {p.name}")
    import pymupdf
    with pymupdf.open(p) as doc:
        pix = doc[(int(page) if page else 1) - 1].get_pixmap(dpi=int(dpi))
        return pix.tobytes("png"), "image/png"


def _request_body(ep, image, mime):
    body = {
        "model": ep["model"],
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}},
            {"type": "text", "text": ep["prompt"]},
        ]}],
        ep["token_param"]: ep["max_tokens"],
    }
    if ep["temperature"] is not None:  # some models reject temperature; `temperature: null` omits it
        body["temperature"] = ep["temperature"]
    body.update(ep.get("extra_body") or {})
    return body


def _call(ep, key, body):
    """One HTTP attempt. Returns a record of what happened (never raises for HTTP/network errors)."""
    req = urllib.request.Request(ep["url"], data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", ep["auth_header"]: f"{ep['auth_prefix']}{key}"})
    t0 = time.monotonic()
    rec = {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
    try:
        with urllib.request.urlopen(req, timeout=ep["timeout_s"]) as r:
            rec["status"], raw, headers = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        rec["status"], raw, headers = e.code, e.read(), dict(e.headers or {})
    except Exception as e:  # noqa: BLE001  timeouts, DNS, TLS, connection resets
        rec.update(status=None, error=f"{type(e).__name__}: {e}"[:500], latency_s=round(time.monotonic() - t0, 3))
        return rec
    rec["latency_s"] = round(time.monotonic() - t0, 3)
    rec["response_headers"] = {k: v for k, v in headers.items() if k.lower() not in DROP_HEADERS}
    try:
        rec["response_body"] = json.loads(raw)
    except ValueError:
        rec["response_body"] = raw.decode("utf-8", "replace")[:5000]
    return rec


def _outcome(rec):
    """(content or None, finish_reason, usage, served_model)."""
    b = rec.get("response_body")
    if rec.get("status") != 200 or not isinstance(b, dict) or not b.get("choices"):
        return None, None, None, None
    ch = b["choices"][0]
    return ((ch.get("message") or {}).get("content"), ch.get("finish_reason"), b.get("usage"), b.get("model"))


def run_one(item, ep, key, pred_root, dpi, data=DATA):
    """Process one input. Returns ('ok' | 'fail', latency, usage)."""
    out = Path(pred_root) / item["prediction_path"]
    raw_path = Path(pred_root) / "_raw" / (item["prediction_path"].removesuffix(".md") + ".json")
    try:
        image, mime = render(item["input_path"], item["page"], dpi, data)
    except Exception as e:  # noqa: BLE001  missing file / unreadable PDF: record it, count as failure
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps({"schema": "ocrbench/raw/1", "input_path": item["input_path"],
                                        "page": item["page"], "ok": False,
                                        "error": f"render: {type(e).__name__}: {e}"[:500]},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
        raise
    body = _request_body(ep, image, mime)
    attempts = []
    for i in range(ep["retries"] + 1):
        rec = _call(ep, key, body)
        attempts.append(rec)
        if rec.get("status") not in RETRY_STATUS and rec.get("status") is not None:
            break
        if i < ep["retries"]:
            time.sleep(2 ** (i + 1) + random.random())
    final = attempts[-1]
    content, finish, usage, served = _outcome(final)
    ok = content is not None and finish == "stop"
    logged = {k: v for k, v in body.items() if k != "messages"}
    logged["prompt_sha256_16"] = hashlib.sha256(ep["prompt"].encode()).hexdigest()[:16]
    logged["image"] = {"mime": mime, "bytes": len(image), "sha256_16": hashlib.sha256(image).hexdigest()[:16],
                       "dpi": dpi if item["input_path"].lower().endswith(".pdf") else None}
    record = {"schema": "ocrbench/raw/1", "input_path": item["input_path"], "page": item["page"],
              "url": ep["url"], "request": logged, "n_attempts": len(attempts), "attempts": attempts,
              "status": final.get("status"), "finish_reason": finish, "usage": usage,
              "served_model": served, "latency_s": final.get("latency_s"), "ok": ok}
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    if ok:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return ("ok" if ok else "fail"), final.get("latency_s"), usage or {}


def run(pred_root, card, items, limit=None, data=DATA, log=print):
    """Run every item that has no prediction yet. Returns a summary dict."""
    ep, key = load_endpoint(card)
    dpi = card.get("dpi") or 300
    pending = [it for it in items if not (Path(pred_root) / it["prediction_path"]).is_file()]
    todo, per = [], {}
    for it in pending:
        per[it["collection"]] = per.get(it["collection"], 0) + 1
        if limit is None or per[it["collection"]] <= limit:
            todo.append(it)
    log(f"{len(items)} inputs: {len(items) - len(pending)} already have a prediction, "
        f"{len(todo)} to call now (concurrency {ep['concurrency']})")
    counts, lats, tokens, t0 = {"ok": 0, "fail": 0}, [], [0, 0], time.monotonic()
    with cf.ThreadPoolExecutor(ep["concurrency"]) as pool:
        futs = {pool.submit(run_one, it, ep, key, pred_root, dpi, data): it for it in todo}
        for n, f in enumerate(cf.as_completed(futs), 1):
            it = futs[f]
            try:
                state, lat, usage = f.result()
            except Exception as e:  # noqa: BLE001  rendering or file errors: report, keep going
                state, lat, usage = "fail", None, {}
                log(f"  ! {it['input_path']} p{it['page']}: {type(e).__name__}: {e}")
            tokens[0] += usage.get("prompt_tokens") or 0
            tokens[1] += usage.get("completion_tokens") or 0
            counts[state] += 1
            if lat:
                lats.append(lat)
            if state == "fail" or n % 20 == 0 or n == len(todo):
                el = time.monotonic() - t0
                eta = el / n * (len(todo) - n)
                log(f"  [{n}/{len(todo)}] ok {counts['ok']} fail {counts['fail']}  "
                    f"elapsed {el / 60:.1f} min, remaining ~{eta / 60:.0f} min"
                    + (f"  (fail: {it['prediction_path']})" if state == "fail" else ""))
    wall = time.monotonic() - t0
    remaining = sum(not (Path(pred_root) / it["prediction_path"]).is_file() for it in items)
    per_input = wall / len(todo) if todo else None
    settings = {k: v for k, v in ep.items() if k != "prompt"}
    settings["prompt_sha256_16"] = hashlib.sha256(ep["prompt"].encode()).hexdigest()[:16]
    return {"endpoint": settings, "dpi": dpi, "called": len(todo), **counts, "wall_s": round(wall, 1),
            "prompt_tokens": tokens[0], "completion_tokens": tokens[1],
            "median_latency_s": round(statistics.median(lats), 1) if lats else None,
            "remaining_without_prediction": remaining,
            "estimated_minutes_for_remaining": round(per_input * remaining / 60) if per_input else None}
