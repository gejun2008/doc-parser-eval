#!/usr/bin/env python3
"""
Infinity-Parser2 端点连通性测试（可直接发给厂商复现）

只依赖 requests。key 只从环境变量读，输出里只出现 key 的长度、
sha256 前 8 位和末 4 位，不会泄露完整 key。

环境:  INFINITY_PARSER2_API_URL   形如 https://<serving-id>.openapi-inspire.inf.tech/v1/chat/completions
       INFINITY_PARSER2_API_KEY
       INFINITY_PARSER2_MODEL     默认 inf-mllm

用法:  python conn_test.py            # 打印可粘贴的报告，并落盘 probe_out/conn_test_<ts>.json

测试项:
  1. DNS 解析端点域名
  2. 不带 key 调 /v1/models         -> 对照组，看网关对「缺 key」怎么报
  3. 带错误 key 调 /v1/models       -> 对照组，看网关对「key 不存在」怎么报
  4. 带真实 key 调 /v1/models
  5. 带真实 key 调 /v1/chat/completions（纯文本 ping，max_tokens=16）
2、3 与 4、5 的报错不同，说明真实 key 已通过 key 校验、卡在后续环节。
"""

import hashlib
import json
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

API_URL = os.environ.get("INFINITY_PARSER2_API_URL", "")
API_KEY = os.environ.get("INFINITY_PARSER2_API_KEY", "")
MODEL = os.environ.get("INFINITY_PARSER2_MODEL", "inf-mllm")
if not API_URL or not API_KEY:
    sys.exit("需要 INFINITY_PARSER2_API_URL 和 INFINITY_PARSER2_API_KEY")

BASE = API_URL.rsplit("/chat/completions", 1)[0]
HOST = urlparse(API_URL).hostname
FAKE_KEY = "invalid-key-for-control-test-000000000000"

# 响应头里可能帮厂商定位请求的字段
TRACE_HEADERS = ("date", "server", "x-request-id", "x-trace-id", "traceparent",
                 "x-envoy-upstream-service-time", "content-type", "content-length")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def key_fp(k):
    return {"len": len(k), "sha256_8": hashlib.sha256(k.encode()).hexdigest()[:8],
            "tail4": k[-4:]}


def call(name, method, url, key=None, payload=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    ts = now()
    t0 = time.perf_counter()
    try:
        r = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
        dt = time.perf_counter() - t0
        try:
            body = r.json()
        except ValueError:
            body = r.text[:2000]
        resp_headers = {k: v for k, v in r.headers.items()}
        status = r.status_code
    except requests.RequestException as e:
        dt, status, resp_headers, body = time.perf_counter() - t0, None, {}, repr(e)
    return {
        "name": name, "ts_utc": ts, "method": method, "url": url,
        "auth": ("none" if key is None else
                 "fake" if key == FAKE_KEY else f"real {key_fp(key)}"),
        "request_body": payload,
        "status": status, "latency_s": round(dt, 3),
        "response_headers": resp_headers, "response_body": body,
    }


def main():
    report = {
        "generated_utc": now(),
        "client": {"python": platform.python_version(), "requests": requests.__version__,
                   "os": platform.platform()},
        "endpoint": API_URL, "model": MODEL, "key": key_fp(API_KEY),
        "tests": [],
    }

    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(HOST, 443)})
        report["dns"] = {"host": HOST, "resolved": ips}
    except OSError as e:
        report["dns"] = {"host": HOST, "error": repr(e)}

    ping = {"model": MODEL, "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 16}
    report["tests"] = [
        call("models_no_key", "GET", BASE + "/models"),
        call("models_fake_key", "GET", BASE + "/models", key=FAKE_KEY),
        call("models_real_key", "GET", BASE + "/models", key=API_KEY),
        call("chat_ping_real_key", "POST", API_URL, key=API_KEY, payload=ping),
    ]

    out = Path("probe_out")
    out.mkdir(exist_ok=True)
    path = out / f"conn_test_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 可粘贴的文本报告
    k = report["key"]
    print("=== Infinity-Parser2 endpoint connectivity test ===")
    print(f"time (UTC) : {report['generated_utc']}")
    print(f"endpoint   : {API_URL}")
    print(f"model      : {MODEL}")
    print(f"api key    : len={k['len']} sha256[:8]={k['sha256_8']} tail=...{k['tail4']}")
    print(f"dns        : {report['dns']}")
    print(f"client     : {report['client']}")
    for t in report["tests"]:
        trace = {h: v for h, v in t["response_headers"].items() if h.lower() in TRACE_HEADERS}
        body = t["response_body"]
        body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        print(f"\n[{t['name']}] {t['method']} {t['url']}")
        print(f"  auth     : {t['auth']}")
        print(f"  sent at  : {t['ts_utc']}")
        print(f"  status   : {t['status']}  ({t['latency_s']}s)")
        print(f"  headers  : {trace}")
        print(f"  body     : {body[:500]}")
    print(f"\nraw json: {path}")


if __name__ == "__main__":
    main()
