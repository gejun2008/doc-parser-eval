"""python -m eval {verify,inputs,score,compare}"""
import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import __version__
from .common import ROOT, aggregate, dump_json, git_commit, read_csv, write_csv

COLLECTIONS = ["financial", "olmocr", "perturbed"]
# Directory under predictions/<model>/ whose presence marks a collection as submitted.
PREFIX = {"financial": "corpus", "olmocr": "olmocr_bench", "perturbed": "perturbed"}
FIELDS = ["collection", "item", "page", "variant", "test_id", "test_type", "subset",
          "doc_id", "family", "window", "status", "outcome", "detail"]
REQUIRED_CARD = ["model", "input_mode"]


def cmd_verify(a):
    rows = read_csv(ROOT / "metadata" / "checksums.csv")
    bad = {"missing": [], "lfs_pointer": [], "size": [], "sha256": []}
    for r in rows:
        p = ROOT / r["path"]
        if not p.is_file():
            bad["missing"].append(r["path"])
            continue
        with open(p, "rb") as f:
            if f.read(40).startswith(b"version https://git-lfs"):
                bad["lfs_pointer"].append(r["path"])
                continue
        if r.get("bytes") and p.stat().st_size != int(r["bytes"]):
            bad["size"].append(r["path"])
            continue
        if not a.quick:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != r["sha256"].lower():
                bad["sha256"].append(r["path"])
    n_bad = sum(map(len, bad.values()))
    print(f"{len(rows)} files checked ({'size only' if a.quick else 'size + sha256'}), {n_bad} problems")
    for k, v in bad.items():
        if v:
            print(f"  {k}: {len(v)}  e.g. {v[0]}")
    if bad["lfs_pointer"]:
        print("  -> run `git lfs pull`")
    return 1 if n_bad else 0


def _inputs(coll):
    if coll == "financial":
        from .financial import financial_inputs
        return financial_inputs()
    if coll == "perturbed":
        from .financial import perturbed_inputs
        return perturbed_inputs()
    from .olmocr import olmocr_inputs
    return olmocr_inputs()


def cmd_inputs(a):
    rows = [dict(r, collection=c) for c in a.collections for r in _inputs(c)]
    out = Path(a.out)
    write_csv(out, rows, ["collection", "input_path", "page", "prediction_path"])
    print(f"{len(rows)} inputs -> {out}")
    print("Write each prediction to predictions/<model>/<prediction_path>. "
          "For the financial collection, parse only the listed page of the PDF.")
    return 0


def _load_card(pred_root):
    p = pred_root / "run_card.yaml"
    if not p.exists():
        sys.exit(f"{p} not found. Create it first (see README: Run card).")
    card = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED_CARD if not card.get(k)]
    if missing:
        sys.exit(f"run_card.yaml is missing: {', '.join(missing)}")
    if card.get("input_mode") == "image" and not card.get("dpi"):
        sys.exit("run_card.yaml: input_mode is image, so dpi is required")
    return card


def cmd_score(a):
    pred_root = Path(a.predictions)
    card = _load_card(pred_root)
    colls = a.collections or [c for c in COLLECTIONS if (pred_root / PREFIX[c]).is_dir()]
    if not colls:
        sys.exit(f"No collection folders ({', '.join(PREFIX.values())}) under {pred_root}")

    with_math = False
    if "olmocr" in colls and a.with_math:
        from .olmocr import math_available
        with_math = math_available()
        if not with_math:
            print("! --with-math given but Playwright/Chromium cannot start: math tests stay unscored")

    out = Path(a.out or ROOT / "results" / pred_root.name)
    card = dict(card, dataset_commit=git_commit(), eval_version=__version__,
                scored_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                collections=colls, olmocr_math="scored" if with_math else "skipped")

    from .report import perturbation_drop, render
    results, summary = {}, {"run_card": card}
    for c in colls:
        print(f"[{c}] scoring ...")
        if c == "financial":
            from .financial import score_financial
            rows, cov = score_financial(pred_root)
        elif c == "perturbed":
            from .financial import score_perturbed
            rows, cov = score_perturbed(pred_root)
        else:
            from .olmocr import score_olmocr
            rows, cov = score_olmocr(pred_root, with_math=with_math)
        results[c] = (rows, cov)

    for c, (rows, cov) in results.items():
        drop = (perturbation_drop(rows, results["financial"][0])
                if c == "perturbed" and "financial" in results else None)
        write_csv(out / f"{c}.csv", rows, FIELDS)
        (out / f"{c}.md").write_text(render(c, rows, cov, card, drop), encoding="utf-8")
        summary[c] = {"coverage": cov, "drop_vs_clean": drop,
                      "strata": {k: aggregate(rows, k) for k in ("test_type", "family", "subset", "variant")
                                 if any(r.get(k) for r in rows)}}
        n = sum(r["outcome"] in ("pass", "fail", "missing") for r in rows)
        print(f"  {c}: {n} scored, {sum(r['outcome'] == 'pass' for r in rows)} pass, "
              f"{sum(r['outcome'] == 'missing' for r in rows)} missing -> {out / (c + '.md')}")

    (out / "run_card.yaml").write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False),
                                       encoding="utf-8")
    dump_json(out / "summary.json", summary)
    print(f"Done. Reports in {out}. There is no overall score: read each collection on its own.")
    return 0


def cmd_compare(a):
    from .compare import compare
    text = compare(a.a, a.b)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"-> {a.out}")
    else:
        print(text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="check data files against metadata/checksums.csv")
    v.add_argument("--quick", action="store_true", help="size only, skip sha256")
    v.set_defaults(fn=cmd_verify)

    i = sub.add_parser("inputs", help="list inputs and the prediction file expected for each")
    i.add_argument("--collections", nargs="+", choices=COLLECTIONS, default=COLLECTIONS)
    i.add_argument("--out", default="inputs.csv")
    i.set_defaults(fn=cmd_inputs)

    s = sub.add_parser("score", help="score predictions/<model>")
    s.add_argument("predictions")
    s.add_argument("--collections", nargs="+", choices=COLLECTIONS,
                   help="default: every collection folder present in the predictions directory")
    s.add_argument("--with-math", action="store_true",
                   help="score olmOCR math tests (needs Playwright + Chromium)")
    s.add_argument("--out", help="default: results/<model folder name>")
    s.set_defaults(fn=cmd_score)

    c = sub.add_parser("compare", help="paired comparison of two results folders")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out")
    c.set_defaults(fn=cmd_compare)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
