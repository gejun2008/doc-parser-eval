"""olmOCR-Bench subset: runs the upstream olmOCR test classes unchanged (eval/vendor/olmocr).

- One prediction per PDF: data/olmocr_bench/bench_data/pdfs/<subset>/<x>.pdf
  -> olmocr_bench/bench_data/pdfs/<subset>/<x>.md
- Math tests need Playwright + Chromium to render KaTeX. They are skipped unless
  --with-math is given; skipped tests are "not_scored", never failures.
- A checker exception is "not_scored" with the error in detail, not a model failure.
- headers_footers tests are all "absent" checks: a parser that drops headers and footers
  passes them regardless of parsing quality. Read that subset with this in mind.
"""
import importlib
import json
import sys
import types
from pathlib import Path

from .common import DATA, FAIL, MISSING, NOT_SCORED, PASS, prediction_path, read_prediction, strip_fences

VENDOR = Path(__file__).resolve().parent / "vendor"
BENCH = "olmocr_bench/bench_data"


def _import_tests(with_math):
    """Import the upstream test module. Without math, stub the KaTeX renderer so that
    Playwright is not imported at all (upstream imports it at module load)."""
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    loaded = sys.modules.get("olmocr.bench.katex.render")
    if with_math and getattr(loaded, "_ocrbench_stub", False):
        for m in ("olmocr.bench.katex.render", "olmocr.bench.katex", "olmocr.bench.tests"):
            sys.modules.pop(m, None)
    if not with_math and loaded is None:
        stub = types.ModuleType("olmocr.bench.katex.render")
        stub._ocrbench_stub = True

        def _disabled(*_a, **_k):
            raise RuntimeError("math rendering disabled; run with --with-math")
        stub.render_equation = stub.compare_rendered_equations = _disabled
        sys.modules["olmocr.bench.katex.render"] = stub
    return importlib.import_module("olmocr.bench.tests")


def math_available():
    """True if Playwright and its Chromium can actually start."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001  any failure means math cannot be scored
        return False


def _test_files(data):
    return sorted((data / BENCH).glob("*.jsonl"))


def olmocr_inputs(data=DATA):
    seen, out = set(), []
    for jf in _test_files(data):
        for line in jf.open(encoding="utf-8"):
            if line.strip():
                pdf = json.loads(line)["pdf"]
                if pdf not in seen:
                    seen.add(pdf)
                    inp = f"{BENCH}/pdfs/{pdf}"
                    out.append({"input_path": "data/" + inp, "page": "", "prediction_path": prediction_path(inp)})
    return out


def score_olmocr(pred_root, data=DATA, with_math=False):
    tests = _import_tests(with_math)
    rows, cache = [], {}
    for jf in _test_files(data):
        subset = jf.stem
        for line in jf.open(encoding="utf-8"):
            if not line.strip():
                continue
            raw = json.loads(line)
            rel = prediction_path(f"{BENCH}/pdfs/{raw['pdf']}")
            row = {"collection": "olmocr", "subset": subset, "item": rel, "page": raw.get("page", ""),
                   "variant": "original", "test_id": raw["id"], "test_type": raw["type"]}
            if raw["type"] == "math" and not with_math:
                rows.append(dict(row, outcome=NOT_SCORED, detail="math skipped (no --with-math)"))
                continue
            if rel not in cache:
                text = read_prediction(pred_root, rel)
                cache[rel] = None if text is None else strip_fences(text)
            content = cache[rel]
            if content is None:
                rows.append(dict(row, outcome=MISSING, detail="no prediction file"))
                continue
            try:
                t = tests.load_single_test(line)
                passed, expl = t.run(content)
                rows.append(dict(row, outcome=PASS if passed else FAIL, detail=(expl or "")[:300]))
            except Exception as e:  # noqa: BLE001  checker problem, not a model failure
                rows.append(dict(row, outcome=NOT_SCORED,
                                 detail=f"checker_error: {type(e).__name__}: {e}"[:300]))
    pdfs = {r["item"] for r in rows}
    coverage = {"pdfs": len(pdfs),
                "pdfs_with_prediction": sum(1 for p in pdfs if cache.get(p) is not None
                                            or (Path(pred_root) / p).is_file()),
                "math": "scored" if with_math else "skipped"}
    return rows, coverage
