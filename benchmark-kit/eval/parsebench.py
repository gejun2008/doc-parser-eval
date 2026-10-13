"""ParseBench subset: official ParseBench evaluator (run-llama/ParseBench @ 3295d7f, vendored in
eval/vendor/parsebench_src and installed with eval/requirements-parsebench.txt).

- One Markdown prediction per input file: data/parsebench/subset/docs/<group>/<x>.<ext>
  -> parsebench/subset/docs/<group>/<x>.md
- Each prediction is wrapped as an official ParseOutput (markdown + one page) and scored by the
  official EvaluationCLI, one dimension at a time. Nothing in the scoring is reimplemented.
- Score per file = the official headline metric of the dimension (same column the leaderboard averages).
- A missing prediction is scored as an empty document (the official evaluator would otherwise drop it
  from the denominator and inflate the mean); its outcome is "missing".
- Visual Grounding (layout) needs element bounding boxes. Markdown has none, so layout is "not_scored"
  (N/A), never 0.
"""
import contextlib
import csv
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .common import DATA, MISSING, NOT_SCORED, prediction_path, read_csv, read_prediction, strip_fences

BENCH = "parsebench/subset"
DIMENSIONS = ["table", "chart", "text_content", "text_formatting", "layout"]
MAIN_METRIC = {  # parse_bench/analysis/aggregation_report.py _DEFAULT_METRICS
    "table": "grits_trm_composite",
    "chart": "rule_pass_rate",
    "text_content": "content_faithfulness",
    "text_formatting": "semantic_formatting",
    "layout": "layout_element_rule_pass_rate",
}
DIM_NAME = {"table": "Tables", "chart": "Charts", "text_content": "Content Faithfulness",
            "text_formatting": "Semantic Formatting", "layout": "Visual Grounding"}
SCORED = "scored"
PIPELINE = "submitted"


def _files_by_dimension(data):
    """{dimension: [pdf path relative to subset, ...]} from the rule files."""
    out = {}
    for dim in DIMENSIONS:
        f = data / BENCH / f"{dim}.jsonl"
        if not f.exists():
            continue
        seen = []
        for line in f.open(encoding="utf-8"):
            if line.strip():
                pdf = json.loads(line)["pdf"]
                if pdf not in seen:
                    seen.append(pdf)
        out[dim] = seen
    return out


def parsebench_inputs(data=DATA):
    files = sorted({p for v in _files_by_dimension(data).values() for p in v})
    return [{"input_path": f"data/{BENCH}/{p}", "page": "",
             "prediction_path": prediction_path(f"{BENCH}/{p}")} for p in files]


def _example_id(pdf):
    """'docs/table/x.pdf' -> 'table/x' (ParseBench's example id)."""
    return pdf.removeprefix("docs/").rsplit(".", 1)[0]


def _write_result(pipe_dir, pdf, markdown, data):
    from parse_bench.schemas.parse_output import PageIR, ParseOutput
    from parse_bench.schemas.pipeline_io import InferenceRequest, InferenceResult
    ex = _example_id(pdf)
    now = datetime.now()
    req = InferenceRequest(example_id=ex, source_file_path=str(data / BENCH / pdf), product_type="parse")
    out = ParseOutput(example_id=ex, pipeline_name=PIPELINE, markdown=markdown,
                      pages=[PageIR(page_index=0, markdown=markdown)])
    res = InferenceResult(request=req, pipeline_name=PIPELINE, product_type="parse", raw_output={},
                          output=out, started_at=now, completed_at=now, latency_in_ms=0)
    p = pipe_dir / f"{ex}.result.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(res.model_dump_json(), encoding="utf-8")


def score_parsebench(pred_root, data=DATA, keep_official=None):
    try:
        from parse_bench.evaluation.cli import EvaluationCLI
    except ImportError as e:
        raise SystemExit("ParseBench evaluator not installed: "
                         "python -m pip install -r eval/requirements-parsebench.txt") from e

    by_dim = _files_by_dimension(data)
    manifest = {}
    mf = data / "parsebench" / "manifest.csv"
    if mf.exists():
        manifest = {r["pdf"]: r for r in read_csv(mf)}

    tmp = Path(tempfile.mkdtemp(prefix="ocrbench_parsebench_"))
    pipe_dir = tmp / PIPELINE
    present = {}
    try:
        for pdf in sorted({p for v in by_dim.values() for p in v}):
            text = read_prediction(pred_root, prediction_path(f"{BENCH}/{pdf}"))
            present[pdf] = text is not None
            _write_result(pipe_dir, pdf, "" if text is None else strip_fences(text), data)

        rows = []
        log = tmp / "official_evaluator.log"
        for dim, pdfs in by_dim.items():
            base = lambda pdf: {"collection": "parsebench", "item": prediction_path(f"{BENCH}/{pdf}"),  # noqa: E731
                                "page": "", "variant": "original", "subset": dim, "test_type": dim,
                                "test_id": _example_id(pdf), "stratum": manifest.get(pdf, {}).get("stratum", "")}
            if dim == "layout":
                rows += [dict(base(p), outcome=NOT_SCORED, score="",
                              detail="Visual Grounding needs bounding boxes; markdown has none")
                         for p in pdfs]
                continue
            report_dir = tmp / "eval" / dim
            with open(log, "a", encoding="utf-8") as fh, contextlib.redirect_stdout(fh), \
                    contextlib.redirect_stderr(fh):
                rc = EvaluationCLI().run(output_dir=pipe_dir, test_cases_dir=data / BENCH, group=dim,
                                         report_dir=str(report_dir), export_html=False,
                                         export_markdown=False, export_rule_csv=False)
            if rc != 0:
                tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
                raise SystemExit(f"Official ParseBench evaluator failed on {dim}. Last log lines:\n{tail}")
            col = MAIN_METRIC[dim]
            with open(report_dir / "_evaluation_results.csv", encoding="utf-8") as fh:
                got = {r["example_id"]: r for r in csv.DictReader(fh)}
            for pdf in pdfs:
                r = got.get(_example_id(pdf))
                score = None
                if r is not None and r.get(col) not in ("", None):
                    score = float(r[col])
                if score is None:
                    rows.append(dict(base(pdf), outcome=NOT_SCORED, score="",
                                     detail=f"official evaluator returned no {col}"
                                     + (f": {r.get('error')}" if r and r.get("error") else "")))
                else:
                    rows.append(dict(base(pdf), outcome=SCORED if present[pdf] else MISSING,
                                     score=round(score, 6),
                                     detail="" if present[pdf] else "no prediction file; scored as empty"))
        if keep_official:
            dst = Path(keep_official)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(tmp / "eval", dst)
            shutil.copy(log, dst / "official_evaluator.log")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    coverage = {"files": len(present), "files_with_prediction": sum(present.values()),
                "visual_grounding": "N/A (markdown only)"}
    return rows, coverage
