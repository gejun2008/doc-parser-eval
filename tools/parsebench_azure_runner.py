#!/usr/bin/env python3
"""
ParseBench runner：Azure Document Intelligence 基线（在公司电脑上跑）

与 INF 侧（tools/parsebench_runner.py）跑同一批 500 份文件，产物交给同一个判分脚本。
对应官方 pipeline `azure_di_layout`：prebuilt-layout，outputContentFormat=markdown。

## 转换不由我们做

网关返回的 analyzeResult（REST，camelCase）先用 Azure SDK 的模型类
`azure.ai.documentintelligence.models.AnalyzeResult(<dict>)` 包起来，
再交给**官方 provider 自己的** `_convert_result_to_dict()` 生成 raw_output。
版面到 markdown 的转换由微软做（content 字段），官方 normalize 只读这个结构——
我们一行转换规则都不写（与 azure_di_runner.py 同一原则：不栽赃对手）。
已用构造的 REST 样例核对过：表格、段落角色、figure、bbox 都能完整走到 normalize。

## 公司网关

`analyze()` 是唯一需要按公司网关改的函数。默认实现是 Azure 官方 REST
（POST :analyze -> 202 + Operation-Location -> 轮询），凭证从环境变量读。
如果公司网关的 URL / 认证 / 同步异步不同，**只改 analyze()**，返回值保持为
analyzeResult 字典（即 REST 响应里 "analyzeResult" 那一层）。

整份文件原样发送（ParseBench 的文件本身就是单页），不加 pages 参数、不转图片。
JPG/PNG 按图片 content-type 发送（Azure DI 原生支持）。

必须在 parse-bench 的独立环境里运行（需要 parse_bench 与 azure-ai-documentintelligence）:
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --dry-run
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --limit 1
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --concurrency 4
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py --resume runs/<run_id>
之后:
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run_id> --pipeline azure_di_layout

产物:
  runs/<run_id>/raw/<slug>.json          网关原始响应（响应头已脱敏）
  runs/<run_id>/parsebench/azure_di_layout/<group>/<stem>.raw.json   官方格式
"""

import argparse
import csv
import hashlib
import importlib
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

PIPELINE = "azure_di_layout"
API_VERSION = "2024-11-30"
MODEL_ID = "prebuilt-layout"
CONTENT_TYPE = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".tif": "image/tiff", ".tiff": "image/tiff",
                ".bmp": "image/bmp"}
SENSITIVE = re.compile(r"auth|cookie|key|token|secret|signature", re.I)

_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def slug(rel):
    return re.sub(r"[^A-Za-z0-9_.-]", "__", str(rel).rsplit(".", 1)[0])


def redact(headers):
    return {k: ("<redacted>" if SENSITIVE.search(k) else v) for k, v in (headers or {}).items()}


# ---------------------------------------------------------------------------
# 唯一按公司网关改的地方
# ---------------------------------------------------------------------------

def analyze(path, timeout=180, poll_s=2.0, max_poll=150):
    """发送整份文件，返回 (analyzeResult 字典或 None, 调用记录)。

    默认实现 = Azure 官方 REST。公司网关不同就改这里，保持返回结构不变。
    调用记录里不能出现 key / token。
    """
    ep = (os.environ.get("AZURE_DI_ENDPOINT") or "").rstrip("/")
    key = os.environ.get("AZURE_DI_KEY") or ""
    url = (f"{ep}/documentintelligence/documentModels/{MODEL_ID}:analyze"
           f"?api-version={API_VERSION}&outputContentFormat=markdown")
    ctype = CONTENT_TYPE.get(path.suffix.lower(), "application/octet-stream")
    ts, t0 = now(), time.perf_counter()
    rec = {"ts_utc": ts, "content_type": ctype, "n_polls": 0}
    try:
        r = requests.post(url, timeout=timeout, data=path.read_bytes(),
                          headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": ctype})
        rec.update(status=r.status_code, response_headers=redact(dict(r.headers)))
        if r.status_code != 202:
            rec["error_body"] = r.text[:4000]
            return None, rec
        op = r.headers.get("Operation-Location")
        for i in range(max_poll):
            time.sleep(poll_s)
            pr = requests.get(op, timeout=timeout, headers={"Ocp-Apim-Subscription-Key": key})
            body = pr.json()
            rec.update(n_polls=i + 1, status=pr.status_code, op_status=body.get("status"),
                       response_headers=redact(dict(pr.headers)))
            if body.get("status") == "succeeded":
                return body.get("analyzeResult"), rec
            if body.get("status") == "failed":
                rec["error_body"] = json.dumps(body.get("error"))[:4000]
                return None, rec
        rec.update(status=-2, error_body="poll timeout")
        return None, rec
    except (requests.RequestException, ValueError) as e:
        rec.update(status=-1, error_body=repr(e)[:4000])
        return None, rec
    finally:
        rec["latency_s"] = round(time.perf_counter() - t0, 3)


# ---------------------------------------------------------------------------

def to_raw_output(analyze_result):
    """REST analyzeResult -> 官方 provider._convert_result_to_dict()（不实例化 provider）。"""
    from azure.ai.documentintelligence.models import AnalyzeResult
    m = importlib.import_module("parse_bench.inference.providers.parse.azure_document_intelligence")
    prov = m.AzureDocumentIntelligenceProvider.__new__(m.AzureDocumentIntelligenceProvider)
    d = prov._convert_result_to_dict(AnalyzeResult(analyze_result))
    d["_config"] = {"model_id": MODEL_ID, "output_content_format": "markdown"}
    return d


def pipeline_spec():
    from parse_bench.inference.pipelines import get_pipeline
    return json.loads(get_pipeline(PIPELINE).model_dump_json())


def process(row, cfg):
    rel = row["pdf"]
    group = rel.split("/")[1]
    stem = rel.rsplit("/", 1)[1].rsplit(".", 1)[0]
    ours = cfg["raw_dir"] / f"{slug(rel)}.json"
    pb = cfg["pb_dir"] / group / f"{stem}.raw.json"
    if ours.exists():
        prev = json.loads(ours.read_text(encoding="utf-8"))
        if prev.get("ok"):
            return "cached", prev

    path = cfg["root"] / rel
    started = datetime.now()
    attempts, ar = [], None
    for i in range(cfg["retries"] + 1):
        ar, rec = analyze(path, timeout=cfg["timeout"])
        attempts.append(rec)
        if ar is not None:
            break
        if i < cfg["retries"]:
            time.sleep(cfg["backoff"] * (2 ** i))
    completed = datetime.now()
    content = (ar or {}).get("content") or ""
    ok = ar is not None and bool(content)
    out = {
        "schema": "inf-eval/raw/1", "run_id": cfg["run_id"], "pdf": rel,
        "dimension": row["dimension"], "stratum": row["stratum"],
        "system": "azure_di", "model_id": MODEL_ID, "api_version": API_VERSION,
        "request": {"outputContentFormat": "markdown", "whole_file": True,
                    "conversion_by_us": False},
        "n_attempts": len(attempts), "attempts": attempts,
        "served_model": (ar or {}).get("modelId"),
        "n_pages_billed": len((ar or {}).get("pages") or []),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "analyze_result": ar,
        "latency_s": attempts[-1].get("latency_s"), "ok": ok,
    }
    ours.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    raw_output = to_raw_output(ar) if ar is not None else {}
    pb.parent.mkdir(parents=True, exist_ok=True)
    pb.write_text(json.dumps({
        "request": {"example_id": f"{group}/{stem}", "source_file_path": str(path.resolve()),
                    "product_type": "parse", "schema_override": None, "config_override": None},
        "pipeline": cfg["spec"], "pipeline_name": PIPELINE, "product_type": "parse",
        "raw_output": raw_output,
        "started_at": started.isoformat(), "completed_at": completed.isoformat(),
        "latency_in_ms": int((completed - started).total_seconds() * 1000),
    }, ensure_ascii=False, default=str), encoding="utf-8")
    return ("ok" if ok else "fail"), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/parsebench/manifest.csv")
    ap.add_argument("--root", default="data/parsebench/subset")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--backoff", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=0, help="每个维度各取前 N 份，验证管道用")
    ap.add_argument("--resume", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.manifest, encoding="utf-8")))
    missing = [r["pdf"] for r in rows if not (Path(a.root) / r["pdf"]).exists()]
    if missing:
        sys.exit(f"{len(missing)} 份文件不存在，例如 {missing[:3]}")
    if a.limit:
        per, picked = Counter(), []
        for r in rows:
            if per[r["dimension"]] < a.limit:
                picked.append(r)
                per[r["dimension"]] += 1
        rows = picked
    print(f"文件 {len(rows)} 份  " + "  ".join(
        f"{k}={v}" for k, v in sorted(Counter(r["dimension"] for r in rows).items())))
    print(f"预估成本约 ${len(rows) / 1000 * 10:.2f}（牌价 $10/1000 页，按合同价为准）")
    if a.dry_run:
        print("凭证:", "已配置" if os.environ.get("AZURE_DI_ENDPOINT") else "未配置（按网关方式改 analyze()）")
        return

    run_dir = Path(a.resume) if a.resume else Path("runs") / (
        f"parsebench_azure_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    raw_dir, pb_dir = run_dir / "raw", run_dir / "parsebench" / PIPELINE
    raw_dir.mkdir(parents=True, exist_ok=True)
    pb_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"run_id": run_dir.name, "raw_dir": raw_dir, "pb_dir": pb_dir,
           "root": Path(a.root), "timeout": a.timeout, "retries": a.retries,
           "backoff": a.backoff, "spec": pipeline_spec()}
    meta = run_dir / "run_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({
            "run_id": run_dir.name, "started_utc": now(), "system": "azure_di",
            "pipeline_equivalent": PIPELINE, "model_id": MODEL_ID, "api_version": API_VERSION,
            "output_content_format": "markdown", "conversion_by_us": False,
            "manifest": a.manifest, "n_files": len(rows), "concurrency": a.concurrency,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    counts, done, t0 = Counter(), [0], time.perf_counter()

    def work(row):
        try:
            state, out = process(row, cfg)
        except Exception as e:  # noqa: BLE001
            state, out = "error", {"error": repr(e)}
        with _lock:
            counts[state] += 1
            done[0] += 1
            print(f"{'  ' if state in ('ok', 'cached') else '！'}[{done[0]:3}/{len(rows)}] "
                  f"{row['dimension']:6} {row['pdf'][5:60]:55} {out.get('latency_s') or 0:6.1f}s "
                  f"{state} {out.get('error', '')}", flush=True)

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        list(ex.map(work, rows))

    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw_dir.glob("*.json"))]
    fails = [r for r in recs if not r["ok"]]
    (run_dir / "run_summary.json").write_text(json.dumps({
        "run_id": run_dir.name, "finished_utc": now(),
        "wall_s_this_session": round(time.perf_counter() - t0, 1),
        "counts_this_session": dict(counts), "n_files_on_disk": len(recs),
        "n_files_ok": len(recs) - len(fails),
        "failed_files": [{"pdf": r["pdf"], "status": r["attempts"][-1].get("status"),
                          "error": (r["attempts"][-1].get("error_body") or "")[:300]}
                         for r in fails],
        "pages_billed": sum(r["n_pages_billed"] for r in recs),
        "served_models": sorted({r["served_model"] for r in recs if r.get("served_model")}),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {dict(counts)} -> {run_dir}")
    print(f"判分: tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py {run_dir} "
          f"--pipeline {PIPELINE}")


if __name__ == "__main__":
    main()
