"""Regression tests on synthetic fixtures. Run: python -m eval.tests

Every expected outcome below was worked out by hand from the fixture files. If a scorer
change alters any of them, the change alters scores: bump eval.__version__ and say why.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
os.environ["OCRBENCH_DATA"] = str(FIX / "data")

from eval.__main__ import main  # noqa: E402
from eval.common import prediction_path, read_csv  # noqa: E402
from eval.financial import score_financial, score_perturbed  # noqa: E402
from eval.olmocr import math_available, score_olmocr  # noqa: E402
from eval.report import perturbation_drop  # noqa: E402

HAVE_PARSEBENCH = importlib.util.find_spec("parse_bench") is not None
HAVE_PYMUPDF = importlib.util.find_spec("pymupdf") is not None

PRED = FIX / "predictions" / "demo"
DATA = FIX / "data"


def outcomes(rows, key=lambda r: r["test_id"]):
    return {key(r): r["outcome"] for r in rows}


class Naming(unittest.TestCase):
    def test_prediction_path(self):
        self.assertEqual(prediction_path("data/corpus/hk/x.pdf", 3), "corpus/hk/x_p3.md")
        self.assertEqual(prediction_path("data\\perturbed\\dpi100\\y.png"), "perturbed/dpi100/y.md")
        self.assertEqual(prediction_path("olmocr_bench/bench_data/pdfs/t/z.pdf"),
                         "olmocr_bench/bench_data/pdfs/t/z.md")


class Financial(unittest.TestCase):
    def test_outcomes(self):
        rows, cov = score_financial(PRED, DATA)
        self.assertEqual(outcomes(rows), {
            "demo_p1_pi01": "pass",        # anchor split across lines: whitespace is ignored
            "demo_p1_am01": "pass",        # exactly_n = 2, found twice
            "demo_p1_am02": "fail",        # forbidden form 1234 present
            "demo_p1_al01": "pass",        # label next to amount
            "demo_p1_dr01": "not_scored",  # draft is never scored
            "demo_p2_pi01": "missing",     # no prediction for page 2
        })
        self.assertEqual(cov, {"pages_selected": 2, "pages_with_prediction": 1,
                               "pages_with_assertions": 2})

    def test_perturbed_and_drop(self):
        rows, cov = score_perturbed(PRED, DATA)
        got = outcomes(rows, key=lambda r: (r["variant"], r["test_id"]))
        self.assertEqual(got[("dpi100", "demo_p1_am02")], "fail")
        self.assertEqual(got[("jpeg30", "demo_p1_pi01")], "missing")
        self.assertEqual(cov["images_with_prediction"], 1)
        drop = perturbation_drop(rows, score_financial(PRED, DATA)[0])
        self.assertEqual(drop["dpi100"]["drop"], 0.0)
        self.assertEqual(drop["jpeg30"]["drop"], 0.75)


class OlmOCR(unittest.TestCase):
    def test_without_math(self):
        rows, cov = score_olmocr(PRED, DATA, with_math=False)
        self.assertEqual(outcomes(rows), {
            "doc_a_present_01": "pass",
            "doc_a_absent_01": "fail",      # text that must be absent is present
            "doc_a_order_01": "pass",
            "doc_a_table_01": "pass",
            "doc_a_math_01": "not_scored",  # math skipped by default
            "doc_b_present_01": "missing",
        })
        self.assertEqual(cov["pdfs_with_prediction"], 1)

    @unittest.skipUnless(os.environ.get("OCRBENCH_TEST_MATH") and math_available(),
                         "set OCRBENCH_TEST_MATH=1 with Playwright + Chromium installed")
    def test_with_math(self):
        rows, _ = score_olmocr(PRED, DATA, with_math=True)
        self.assertEqual(outcomes(rows)["doc_a_math_01"], "pass")


@unittest.skipUnless(HAVE_PARSEBENCH, "pip install -r eval/requirements-parsebench.txt")
class ParseBench(unittest.TestCase):
    def test_outcomes(self):
        from eval.parsebench import score_parsebench
        rows, cov = score_parsebench(PRED, DATA)
        got = {r["test_id"]: (r["outcome"], r["score"]) for r in rows}
        self.assertEqual(got["table/t1"], ("scored", 1.0))      # prediction equals the expected table
        self.assertEqual(got["table/t2"], ("missing", 0.0))     # no file: scored as an empty document
        self.assertEqual(got["layout/l1"][0], "not_scored")     # Visual Grounding is N/A for markdown
        self.assertEqual(cov["files_with_prediction"], 1)


class _MockOpenAI:
    """Minimal OpenAI-compatible /chat/completions server. `script` is a list of responses
    handed out in order (then the last one repeats): ("ok"|"length"|500, content)."""

    def __init__(self, script):
        import http.server
        import threading
        self.script, self.requests = list(script), []
        mock = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                mock.requests.append({"auth": self.headers.get("Authorization"), "body": body})
                kind, content = mock.script.pop(0) if len(mock.script) > 1 else mock.script[0]
                if kind == 500:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"boom")
                    return
                out = {"model": "mock-ocr", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                       "choices": [{"index": 0, "finish_reason": "stop" if kind == "ok" else "length",
                                    "message": {"role": "assistant", "content": content}}]}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _make_inputs(data):
    """Create the PDFs and images the fixture manifests point to (not stored in git)."""
    import pymupdf
    pdfs = {"corpus/demo/demo_doc.pdf": 2, "olmocr_bench/bench_data/pdfs/demo_subset/doc_a.pdf": 1,
            "olmocr_bench/bench_data/pdfs/demo_subset/doc_b.pdf": 1,
            "parsebench/subset/docs/table/t1.pdf": 1, "parsebench/subset/docs/table/t2.pdf": 1}
    for rel, pages in pdfs.items():
        doc = pymupdf.open()
        for i in range(pages):
            doc.new_page().insert_text((72, 72), f"{rel} page {i + 1}")
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        doc.save(data / rel)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(200)
    for rel in ("perturbed/dpi100/demo_doc_p1_dpi100.png", "parsebench/subset/docs/layout/l1.png"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        pix.save(data / rel)
    (data / "perturbed/jpeg30").mkdir(parents=True, exist_ok=True)
    (data / "perturbed/jpeg30/demo_doc_p1_jpeg30.jpg").write_bytes(pix.tobytes("jpg"))


@unittest.skipUnless(HAVE_PYMUPDF, "pip install -r eval/requirements-run.txt")
class RunOpenAI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        shutil.copytree(DATA, self.data)
        _make_inputs(self.data)
        self.pred = self.tmp / "predictions" / "mock"
        self.pred.mkdir(parents=True)
        os.environ["OCRBENCH_TEST_KEY"] = "sk-test-secret"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _items(self):
        from eval.financial import financial_inputs, perturbed_inputs
        from eval.olmocr import olmocr_inputs
        from eval.parsebench import parsebench_inputs
        fns = {"financial": financial_inputs, "perturbed": perturbed_inputs,
               "olmocr": olmocr_inputs, "parsebench": parsebench_inputs}
        return [dict(r, collection=c) for c, fn in fns.items() for r in fn(self.data)]

    def _card(self, url):
        return {"model": "mock", "input_mode": "image", "dpi": 72,
                "endpoint": {"url": url, "model": "mock-ocr", "api_key_env": "OCRBENCH_TEST_KEY",
                             "concurrency": 2, "retries": 2}}

    def test_smoke_then_resume(self):
        from eval.run import run
        srv = _MockOpenAI([("ok", "# page\n\nTotal revenue for the year")])
        try:
            items = self._items()
            self.assertEqual(len(items), 2 + 2 + 2 + 3)
            s1 = run(self.pred, self._card(srv.url), items, limit=1, data=self.data, log=lambda *_: None)
            self.assertEqual((s1["called"], s1["ok"]), (4, 4))          # one per collection
            s2 = run(self.pred, self._card(srv.url), items, data=self.data, log=lambda *_: None)
            self.assertEqual((s2["called"], s2["ok"], s2["remaining_without_prediction"]), (5, 5, 0))
        finally:
            srv.close()
        self.assertEqual(srv.requests[0]["auth"], "Bearer sk-test-secret")
        img = srv.requests[0]["body"]["messages"][0]["content"][0]["image_url"]["url"]
        self.assertTrue(img.startswith("data:image/"))
        self.assertTrue((self.pred / "corpus/demo/demo_doc_p2.md").is_file())
        raw = (self.pred / "_raw/corpus/demo/demo_doc_p1.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-test-secret", raw)                          # the key is never written
        self.assertNotIn("base64", raw)                                  # nor the image
        self.assertEqual(json.loads(raw)["finish_reason"], "stop")

    def test_truncated_and_retry(self):
        from eval.run import run
        item = [i for i in self._items() if i["prediction_path"] == "corpus/demo/demo_doc_p1.md"]
        srv = _MockOpenAI([("length", "partial")])
        try:
            s = run(self.pred, self._card(srv.url), item, data=self.data, log=lambda *_: None)
        finally:
            srv.close()
        self.assertEqual((s["ok"], s["fail"]), (0, 1))                   # truncated output is a failure
        self.assertFalse((self.pred / "corpus/demo/demo_doc_p1.md").exists())
        srv = _MockOpenAI([(500, ""), ("ok", "recovered")])
        try:
            s = run(self.pred, self._card(srv.url), item, data=self.data, log=lambda *_: None)
        finally:
            srv.close()
        self.assertEqual(s["ok"], 1)                                     # 500 retried, then success
        raw = json.loads((self.pred / "_raw/corpus/demo/demo_doc_p1.json").read_text(encoding="utf-8"))
        self.assertEqual([a["status"] for a in raw["attempts"]], [500, 200])


class EndToEnd(unittest.TestCase):
    def test_score_and_compare(self):
        out = Path(tempfile.mkdtemp())
        try:
            colls = ["financial", "olmocr", "perturbed"] + (["parsebench"] if HAVE_PARSEBENCH else [])
            for side in ("a", "b"):
                self.assertEqual(main(["score", str(PRED), "--collections", *colls,
                                       "--out", str(out / side)]), 0)
            for f in ("financial.md", "olmocr.md", "perturbed.md", "run_card.yaml", "summary.json"):
                self.assertTrue((out / "a" / f).is_file(), f)
            self.assertEqual(len(read_csv(out / "a" / "olmocr.csv")), 6)
            self.assertEqual(main(["compare", str(out / "a"), str(out / "b"),
                                   "--out", str(out / "cmp.md")]), 0)
            self.assertIn("Only A", (out / "cmp.md").read_text(encoding="utf-8"))
            self.assertEqual(main(["table", str(out / "a"), str(out / "b"), "--out", str(out / "t.md")]), 0)
            table = (out / "t.md").read_text(encoding="utf-8")
            self.assertIn("| page_integrity |", table)        # one row per stratum, one column per model
            self.assertIn("no overall score", table)
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    sys.exit(unittest.main(module=__name__, verbosity=2).result.wasSuccessful() is False)
