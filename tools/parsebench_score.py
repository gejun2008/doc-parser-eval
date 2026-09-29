#!/usr/bin/env python3
"""
ParseBench 判分（research-plan.md §3.2 第二层）

**判分逻辑不自己写**：normalize 用官方 provider 的 normalize()，判分用官方
`parse-bench run <pipeline> --skip_inference`（run-llama/ParseBench@3295d7f，
克隆在 tools/vendor/parsebench_src，不入库）。本脚本只做三件事：

  1. <run>/parsebench/<pipeline>/**/*.raw.json -> *.result.json
     调官方 provider 的 normalize()，但**不实例化 provider**：
     infinity_parser2 的 __init__ 会去连 vLLM 服务、azure 的 __init__ 要读 SDK 凭证，
     而 normalize() 不依赖任何实例字段（已核对）
  2. 调用失败 / 输出为空的文件，写一个空 markdown 的 result.json。
     官方判分器对缺失的结果文件**不计入分母**，不补的话失败页凭空消失、分数虚高。
     这些文件单列在 summary 的 empty_output_files
  3. 跑官方判分，然后把逐文件结果按 manifest 的维度 / 分层 / 领域猜测汇总，
     每层给 n 和 bootstrap 95% CI，不合成加权总分（CLAUDE.md 约定 5）

必须在 parse-bench 的独立环境里运行（Python ≥3.12）:
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run_id>
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run_id> --pipeline azure_di_layout

环境准备见 docs/working/parsebench-method.md。
"""

import argparse
import csv
import json
import os
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS = ["table", "chart", "text_content", "text_formatting", "layout"]
# 维度 -> manifest 里的 dimension（text 两个维度共用一批文件）
DIM_OF = {"table": "table", "chart": "chart", "layout": "layout",
          "text_content": "text", "text_formatting": "text"}


def provider_for(pipeline_name):
    import importlib

    from parse_bench.inference.pipelines import get_pipeline
    from parse_bench.inference.providers.registry import _PROVIDER_REGISTRY
    spec = get_pipeline(pipeline_name)
    if spec.provider_name not in _PROVIDER_REGISTRY:
        # 注册靠 import 触发；模块名与注册名一致（infinity_parser2 / azure_document_intelligence）
        importlib.import_module(f"parse_bench.inference.providers.parse.{spec.provider_name}")
    cls = _PROVIDER_REGISTRY[spec.provider_name]
    return spec, cls.__new__(cls)          # 不跑 __init__，见文件头第 1 条


def empty_result(raw):
    from parse_bench.schemas.parse_output import ParseOutput
    from parse_bench.schemas.pipeline_io import InferenceResult
    return InferenceResult(
        request=raw.request, pipeline_name=raw.pipeline_name, product_type=raw.product_type,
        raw_output=raw.raw_output,
        output=ParseOutput(task_type="parse", example_id=raw.request.example_id,
                           pipeline_name=raw.pipeline_name, pages=[], layout_pages=[],
                           markdown=""),
        started_at=raw.started_at, completed_at=raw.completed_at,
        latency_in_ms=raw.latency_in_ms)


def normalize_all(pb_dir, pipeline_name):
    from parse_bench.schemas.pipeline_io import RawInferenceResult
    _, prov = provider_for(pipeline_name)
    empty, errors, n = [], [], 0
    for f in sorted(pb_dir.rglob("*.raw.json")):
        raw = RawInferenceResult.model_validate(json.loads(f.read_text(encoding="utf-8")))
        try:
            res = prov.normalize(raw)
            if not (res.output.markdown or "").strip():
                empty.append(raw.request.example_id)
        except Exception as e:  # noqa: BLE001  provider 对空结果会抛 ProviderPermanentError
            res = empty_result(raw)
            empty.append(raw.request.example_id)
            errors.append({"example_id": raw.request.example_id,
                           "error": f"{type(e).__name__}: {e}"[:300]})
        out = f.with_name(f.name.replace(".raw.json", ".result.json"))
        out.write_text(res.model_dump_json(), encoding="utf-8")
        n += 1
    return n, empty, errors


def run_official(pipeline_name, input_dir, out_dir):
    exe = Path(sys.executable).with_name("parse-bench")
    if not exe.exists():                       # Windows: Scripts\parse-bench.exe
        exe = exe.with_suffix(".exe")
    cmd = [str(exe), "run", pipeline_name, "--input_dir", str(input_dir),
           "--output_dir", str(out_dir), "--skip_inference", "--open_report", "False"]
    print("$", " ".join(cmd))
    # Windows 控制台默认编码不是 UTF-8，官方判分器打印 emoji 会崩，强制 UTF-8
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    (out_dir / "_official_stdout.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr,
                                                   encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"官方判分失败，见 {out_dir / '_official_stdout.log'}")


# 每个维度的官方主指标 = parse_bench/analysis/aggregation_report.py 的 _DEFAULT_METRICS，
# leaderboard 的维度分就是这一列的逐文件均值
MAIN_METRIC = {
    "table": "grits_trm_composite",
    "chart": "rule_pass_rate",
    "text_content": "content_faithfulness",
    "text_formatting": "semantic_formatting",
    "layout": "layout_element_rule_pass_rate",
}


def score_column(dim, rows):
    col = MAIN_METRIC[dim]
    if rows and col not in rows[0]:
        sys.exit(f"{dim} 的结果里没有官方主指标列 {col}，判分器版本可能变了")
    return col


def boot_ci(xs, n_boot=2000, seed=0):
    if len(xs) < 2:
        return [None, None]
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n_boot))
    return [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot) - 1], 4)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--pipeline", default="infinity_parser2_flash")
    ap.add_argument("--input-dir", default="data/parsebench/subset")
    ap.add_argument("--manifest", default="data/parsebench/manifest.csv")
    ap.add_argument("--skip-official", action="store_true", help="只重做汇总")
    a = ap.parse_args()

    run_dir = Path(a.run_dir)
    out_dir = run_dir / "parsebench"
    pb_dir = out_dir / a.pipeline
    if not pb_dir.is_dir():
        sys.exit(f"{pb_dir} 不存在")

    if not a.skip_official:
        n, empty, errors = normalize_all(pb_dir, a.pipeline)
        print(f"normalize {n} 个文件，空输出 {len(empty)} 个")
        (out_dir / "_normalize_log.json").write_text(json.dumps(
            {"n": n, "empty_output_files": empty, "errors": errors},
            ensure_ascii=False, indent=2), encoding="utf-8")
        run_official(a.pipeline, Path(a.input_dir), out_dir)
    norm_log = json.loads((out_dir / "_normalize_log.json").read_text(encoding="utf-8"))

    manifest = {r["pdf"]: r for r in csv.DictReader(open(a.manifest, encoding="utf-8"))}
    by_example = {}
    for pdf, r in manifest.items():
        group, fname = pdf.split("/")[1], pdf.rsplit("/", 1)[1]
        by_example[f"{group}/{fname.rsplit('.', 1)[0]}"] = r

    summary = {"run_id": run_dir.name, "pipeline": a.pipeline,
               "scored_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "scorer": {"source": "run-llama/ParseBench", "commit": "3295d7f",
                          "normalize": "官方 provider.normalize()", "reimplemented": False},
               "empty_output_files": norm_log["empty_output_files"],
               "caveats": [
                   "500 份分层子集，非全量 2,078 页，不能直接与厂商 72.2 / 73.25 或 leaderboard 比大小",
                   "按维度、分层出数，不合成加权总分",
                   "调用失败 / 空输出的文件按空 markdown 计分（官方判分器默认会把缺失文件排除出分母）",
                   "domain_guess 是文件名启发式标签，只看覆盖面，不作领域结论",
               ],
               "dimensions": {}}
    per_file_rows = []
    for dim in DIMENSIONS:
        rep = out_dir / a.pipeline / dim / "_evaluation_report.json"
        res_csv = out_dir / a.pipeline / dim / "_evaluation_results.csv"
        if not rep.exists():
            summary["dimensions"][dim] = {"status": "no_report"}
            continue
        report = json.loads(rep.read_text(encoding="utf-8"))
        rows = list(csv.DictReader(open(res_csv, encoding="utf-8"))) if res_csv.exists() else []
        col = score_column(dim, rows)
        strata, doms = defaultdict(list), defaultdict(list)
        for r in rows:
            ex = r.get("example_id") or r.get("test_id") or ""
            m = by_example.get(ex) or by_example.get(ex.split("::")[0])
            try:
                s = float(r[col]) if col and r.get(col) not in ("", None) else None
            except ValueError:
                s = None
            if m is None or s is None:
                continue
            strata[m["stratum"]].append(s)
            doms[m["domain_guess"]].append(s)
            per_file_rows.append({"dimension": dim, "example_id": ex, "stratum": m["stratum"],
                                  "domain_guess": m["domain_guess"], "score": s,
                                  "empty_output": ex in norm_log["empty_output_files"]})

        def layer(g):
            return {k: {"n": len(v), "mean": round(statistics.fmean(v), 4), "ci95": boot_ci(v)}
                    for k, v in sorted(g.items())}
        allv = [x for v in strata.values() for x in v]
        summary["dimensions"][dim] = {
            "official_report_file": str(rep), "score_column": col,
            "official_headline": {k: v for k, v in report.items()
                                  if isinstance(v, (int, float, str)) and not isinstance(v, bool)},
            "n_files_scored": len(allv),
            "mean": round(statistics.fmean(allv), 4) if allv else None,
            "ci95": boot_ci(allv),
            "by_stratum": layer(strata), "by_domain_guess": layer(doms),
        }

    (run_dir / "parsebench_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (run_dir / "parsebench_per_file.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["dimension", "example_id", "stratum",
                                           "domain_guess", "score", "empty_output"])
        w.writeheader()
        w.writerows(per_file_rows)

    print(f"\n{'维度':16} {'n':>4} {'均值':>7}  95% CI")
    for dim, v in summary["dimensions"].items():
        if "mean" in v and v["mean"] is not None:
            print(f"{dim:16} {v['n_files_scored']:4} {v['mean']:7.3f}  {v['ci95']}")
        else:
            print(f"{dim:16} {v.get('status', '-')}")
    print(f"空输出 {len(summary['empty_output_files'])} 个")
    print(f"-> {run_dir / 'parsebench_summary.json'}\n-> {run_dir / 'parsebench_per_file.csv'}")


if __name__ == "__main__":
    main()
