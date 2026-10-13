"""Regression tests on synthetic fixtures. Run: python -m eval.tests

Every expected outcome below was worked out by hand from the fixture files. If a scorer
change alters any of them, the change alters scores: bump eval.__version__ and say why.
"""
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


class EndToEnd(unittest.TestCase):
    def test_score_and_compare(self):
        out = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(main(["score", str(PRED), "--out", str(out / "a")]), 0)
            self.assertEqual(main(["score", str(PRED), "--out", str(out / "b")]), 0)
            for f in ("financial.md", "olmocr.md", "perturbed.md", "run_card.yaml", "summary.json"):
                self.assertTrue((out / "a" / f).is_file(), f)
            self.assertEqual(len(read_csv(out / "a" / "olmocr.csv")), 6)
            self.assertEqual(main(["compare", str(out / "a"), str(out / "b"),
                                   "--out", str(out / "cmp.md")]), 0)
            self.assertIn("Only A", (out / "cmp.md").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    sys.exit(unittest.main(module=__name__, verbosity=2).result.wasSuccessful() is False)
