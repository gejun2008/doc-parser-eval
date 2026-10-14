"""Side-by-side view of several scored models: one table per collection, models as columns.

    python -m eval table                      # every folder under results/ that has a summary.json
    python -m eval table results/a results/b  # chosen models

Descriptive only: no overall score, no ranking, no significance. Use `python -m eval compare A B`
for a paired test between two models.
"""
import json
from pathlib import Path

import yaml

from .common import MIN_N, ROOT

# (collection, title, stratum key in summary.json, metric)
SECTIONS = [
    ("financial", "Financial disclosures — pass rate by assertion type", "test_type", "rate"),
    ("financial", "Financial disclosures — pass rate by document family", "family", "rate"),
    ("olmocr", "olmOCR-Bench subset — pass rate by subset", "subset", "rate"),
    ("perturbed", "Perturbation — pass rate by variant", "variant", "rate"),
    ("parsebench", "ParseBench subset — mean score by dimension", "test_type", "mean"),
]
CARD_KEYS = ["version", "input_mode", "dpi", "dataset_commit", "eval_version", "olmocr_math", "scored_utc"]


def _load(d):
    d = Path(d)
    return {"name": d.name,
            "card": yaml.safe_load((d / "run_card.yaml").read_text(encoding="utf-8")) or {},
            "summary": json.loads((d / "summary.json").read_text(encoding="utf-8"))}


def _cell(s, metric):
    if s is None:
        return "–"
    v = s.get(metric)
    if s["n"] == 0 or v is None:
        return "N/A"
    shown = f"{v:.1%}" if metric == "rate" else f"{v:.3f}"
    miss = f", {s['missing']} missing" if s.get("missing") else ""
    if not s["sufficient"]:
        return f"({shown}, n={s['n']}{miss}) ⚠"
    return f"{shown} (n={s['n']}{miss})"


def side_by_side(dirs=None):
    if not dirs:
        base = ROOT / "results"
        dirs = sorted(p for p in base.iterdir() if (p / "summary.json").is_file()) if base.is_dir() else []
    models = [_load(d) for d in dirs]
    if not models:
        raise SystemExit("No scored results found (results/<model>/summary.json). Run `python -m eval score` first.")
    names = [m["name"] for m in models]
    head = "| | " + " | ".join(names) + " |"
    sep = "|---|" + "---|" * len(names)

    out = ["# Models side by side", "",
           "Descriptive only: **no overall score, no ranking.** Differences here are not tested; use "
           "`python -m eval compare <a> <b>` for a paired test. ⚠ = fewer than "
           f"{MIN_N} scored items: not interpretable on its own.", "",
           "## Runs", "", head, sep]
    out += [f"| {k} | " + " | ".join(str(m["card"].get(k, "")) for m in models) + " |" for k in CARD_KEYS]
    out += ["| endpoint model | " + " | ".join(str((m["card"].get("endpoint") or {}).get("model", "—"))
                                               for m in models) + " |", ""]
    for k in ("dataset_commit", "input_mode", "dpi", "eval_version"):
        if len({str(m["card"].get(k)) for m in models}) > 1:
            out += [f"> **WARNING:** `{k}` differs between runs; those columns are not directly comparable.", ""]

    for coll, title, key, metric in SECTIONS:
        present = [m for m in models if coll in m["summary"]]
        if not present:
            continue
        strata = []
        for m in models:
            for s in (m["summary"].get(coll) or {}).get("strata", {}).get(key, []):
                if s["stratum"] not in strata:
                    strata.append(s["stratum"])
        out += [f"## {title}", "", head, sep]
        for st in strata:
            cells = []
            for m in models:
                rows = (m["summary"].get(coll) or {}).get("strata", {}).get(key, [])
                cells.append(_cell(next((s for s in rows if s["stratum"] == st), None), metric))
            out.append(f"| {st} | " + " | ".join(cells) + " |")
        cov = [(m["summary"].get(coll) or {}).get("coverage") for m in models]
        out.append("| *coverage* | " + " | ".join(
            "–" if c is None else ", ".join(f"{k} {v}" for k, v in c.items()) for c in cov) + " |")
        if coll == "perturbed":
            drops = [(m["summary"].get(coll) or {}).get("drop_vs_clean") or {} for m in models]
            for v in sorted({v for d in drops for v in d}):
                out.append(f"| *drop vs clean: {v}* | " + " | ".join(
                    f"{d[v]['drop']:.1%} (n={d[v]['n']})" if v in d else "–" for d in drops) + " |")
        out.append("")
    out.append("Missing predictions count as failures (ParseBench: empty documents). "
               "Columns with a different dataset commit or input mode measure different things.")
    return "\n".join(out)
