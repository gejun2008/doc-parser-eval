"""Financial disclosures and perturbation collections: assertion scoring.

Ported from doc-parser-eval tools/check.py. Rules:
- Only assertions with status auto / auto_textlayer / confirmed are scored.
  draft and rejected are counted but never scored.
- Text is compared after removing all whitespace: models merge the PDF's hard line breaks,
  while anchors come from physical text-layer lines. This loosens the check: spacing and
  line breaks are not verified.
- A page with no prediction file fails every assertion on it (outcome "missing").
- The perturbation collection reuses the assertions of the page each image was made from.
"""
import re
from collections import defaultdict
from pathlib import Path

import yaml

from .common import (DATA, FAIL, MISSING, NOT_SCORED, PASS, data_relative, prediction_path,
                     read_csv, read_prediction, strip_fences)

SCORED_STATUS = {"auto", "auto_textlayer", "confirmed"}


def norm(s):
    return re.sub(r"\s+", "", s or "")


def judge(a, content_n):
    """(True | False | None, detail). content_n is whitespace-normalised. None = not scorable."""
    t = a.get("target")
    if t is None:
        return None, "assertion_missing_target"
    tn = norm(str(t))
    if not tn:
        return None, "assertion_empty_target"
    cnt = content_n.count(tn)
    rule = a.get("rule", "exactly_once")

    if rule == "exactly_once" and cnt != 1:
        return False, f"expected exactly once, found {cnt}"
    if rule == "at_least_once" and cnt < 1:
        return False, "not found"
    if rule == "exactly_n":
        # Expected count comes from the PDF text layer: the same amount legitimately
        # appears in both the current and prior-period columns.
        want = a.get("n")
        if want is None:
            return None, "assertion_missing_n"
        if cnt != want:
            return False, f"expected {want}, found {cnt}"
    if rule == "label_proximity":
        # The amount must still sit next to its row label. Text proximity only,
        # not proof of the correct table row/column.
        ln = norm(str(a.get("label") or ""))
        if not ln:
            return None, "assertion_missing_label"
        gap = a.get("max_gap", 120)
        if cnt < 1:
            return False, "amount not found"
        if ln not in content_n:
            return False, f"label not found: {a.get('label')}"
        best, li = None, -1
        while True:
            li = content_n.find(ln, li + 1)
            if li < 0:
                break
            ai = -1
            while True:
                ai = content_n.find(tn, ai + 1)
                if ai < 0:
                    break
                d = ai - (li + len(ln)) if ai > li else li - (ai + len(tn))
                best = d if best is None else min(best, d)
        if best is None or best > gap:
            return False, f"label-amount gap {best} > {gap}"
        return True, f"label-amount gap {best}"

    for f in (a.get("forbid") or []):
        fn = norm(str(f))
        if fn and fn != tn and fn in content_n:
            return False, f"forbidden form present: {f}"
    return True, f"found x{cnt}"


def load_assertions(data=DATA):
    """[(document record, assertion), ...] for every assertion in data/assertions."""
    out = []
    for yf in sorted((data / "assertions").glob("*.yaml")):
        d = yaml.safe_load(yf.read_text(encoding="utf-8"))
        for a in d.get("assertions") or []:
            out.append((d, a))
    return out


def _score_page(doc, assertions, text, base):
    rows = []
    content_n = None if text is None else norm(strip_fences(text))
    for a in assertions:
        st = a.get("status", "draft")
        row = dict(base, doc_id=doc["doc_id"], family=doc.get("family", ""),
                   window=doc.get("window", ""), page=a["page"], test_id=a["id"],
                   test_type=a.get("type", ""), status=st)
        if st not in SCORED_STATUS:
            row.update(outcome=NOT_SCORED, detail=f"status={st}")
        elif a.get("eval_on", "md") != "md":
            row.update(outcome=NOT_SCORED, detail=f"eval_on={a.get('eval_on')} unsupported")
        elif content_n is None:
            row.update(outcome=MISSING, detail="no prediction file")
        else:
            ok, why = judge(a, content_n)
            row.update(outcome=NOT_SCORED if ok is None else (PASS if ok else FAIL), detail=why)
        rows.append(row)
    return rows


def _by_page(data):
    pages = defaultdict(list)
    docs = {}
    for d, a in load_assertions(data):
        pages[(d["doc_id"], int(a["page"]))].append(a)
        docs[d["doc_id"]] = d
    return pages, docs


def financial_inputs(data=DATA):
    """Every selected page (data/corpus/run_manifest.csv), with or without assertions."""
    out = []
    for r in read_csv(data / "corpus" / "run_manifest.csv"):
        out.append({"input_path": "data/" + data_relative(r["pdf"]), "page": int(r["page"]),
                    "prediction_path": prediction_path(r["pdf"], int(r["page"]))})
    return out


def perturbed_inputs(data=DATA):
    out = []
    for r in read_csv(data / "perturbed" / "manifest.csv"):
        out.append({"input_path": "data/" + data_relative(r["path"]), "page": "",
                    "prediction_path": prediction_path(r["path"])})
    return out


def score_financial(pred_root, data=DATA):
    pages, docs = _by_page(data)
    rows = []
    for (doc_id, page), assertions in sorted(pages.items()):
        doc = docs[doc_id]
        rel = prediction_path(doc["local_path"], page)
        rows += _score_page(doc, assertions, read_prediction(pred_root, rel),
                            {"collection": "financial", "variant": "original", "item": rel})
    inputs = financial_inputs(data)
    coverage = {"pages_selected": len(inputs),
                "pages_with_prediction": sum((Path(pred_root) / i["prediction_path"]).is_file()
                                             for i in inputs),
                "pages_with_assertions": len(pages)}
    return rows, coverage


def score_perturbed(pred_root, data=DATA):
    pages, docs = _by_page(data)
    rows, unmapped = [], 0
    manifest = read_csv(data / "perturbed" / "manifest.csv")
    for r in manifest:
        key = (r["doc_id"], int(r["page"]))
        if key not in pages:
            unmapped += 1
            continue
        rel = prediction_path(r["path"])
        rows += _score_page(docs[r["doc_id"]], pages[key], read_prediction(pred_root, rel),
                            {"collection": "perturbed", "variant": r["variant"], "item": rel})
    coverage = {"images": len(manifest),
                "images_with_prediction": sum((Path(pred_root) / prediction_path(r["path"])).is_file()
                                              for r in manifest),
                "images_without_assertions": unmapped}
    return rows, coverage
