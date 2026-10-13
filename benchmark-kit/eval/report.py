"""Markdown reports. One report per collection, each in its own metric. No overall score."""
from collections import Counter, defaultdict

from .common import MIN_N, PASS, aggregate

CAVEATS = {
    "financial": [
        "Only assertions with status auto / auto_textlayer / confirmed are scored.",
        "Text is compared with all whitespace removed: spacing and line breaks are not checked.",
        "amount_label checks text proximity, not correct table row/column.",
        "Assertions on one page are correlated; read page-level coverage alongside assertion counts.",
    ],
    "olmocr": [
        "Subset of olmOCR-Bench (120 of 1,403 PDFs, quotas weighted toward financial relevance): "
        "not comparable with the official leaderboard.",
        "headers_footers tests are all 'absent' checks: dropping headers/footers passes them "
        "regardless of parsing quality.",
        "Public benchmark: may be in the training data of the model under test.",
    ],
    "perturbed": [
        "Reuses the financial assertions of the source page. Read the drop vs. the clean page, "
        "not the absolute rate.",
        "Images were rebuilt offline from fixed recipes and seeds; they are not byte-identical to "
        "historical test inputs.",
    ],
}

STRATA = {
    "financial": [("By assertion type", ("test_type",)), ("By document family", ("family",)),
                  ("By family × window", ("family", "window"))],
    "olmocr": [("By subset", ("subset",)), ("By test type", ("test_type",))],
    "perturbed": [("By variant", ("variant",)), ("By variant × assertion type", ("variant", "test_type"))],
}

TITLES = {"financial": "Financial disclosures", "olmocr": "olmOCR-Bench subset",
          "perturbed": "Perturbation"}


def _pct(x):
    return "–" if x is None else f"{x:.1%}"


def _table(agg):
    lines = ["| Stratum | n | Pass | Missing | Pass rate | 95% CI |", "|---|---:|---:|---:|---:|---|"]
    for a in agg:
        if not a["sufficient"]:
            rate, ci = f"insufficient sample ({_pct(a['rate'])})", "–"
        else:
            rate, ci = _pct(a["rate"]), f"{_pct(a['ci95'][0])} – {_pct(a['ci95'][1])}"
        lines.append(f"| {a['stratum']} | {a['n']} | {a['pass']} | {a['missing']} | {rate} | {ci} |")
    return lines


def perturbation_drop(pert_rows, fin_rows):
    """Per variant: pass rate on clean pages vs. the same assertions on perturbed images."""
    clean = {r["test_id"]: r["outcome"] == PASS for r in fin_rows if r["outcome"] in ("pass", "fail", "missing")}
    by_var = defaultdict(lambda: [0, 0, 0])  # n, clean pass, perturbed pass
    for r in pert_rows:
        if r["outcome"] in ("pass", "fail", "missing") and r["test_id"] in clean:
            v = by_var[r["variant"]]
            v[0] += 1
            v[1] += clean[r["test_id"]]
            v[2] += r["outcome"] == PASS
    return {k: {"n": n, "clean_rate": round(c / n, 4), "perturbed_rate": round(p / n, 4),
                "drop": round((c - p) / n, 4)} for k, (n, c, p) in sorted(by_var.items()) if n}


def render(collection, rows, coverage, card, drop=None):
    out = [f"# {TITLES[collection]}", ""]
    out += [f"- **Model:** {card.get('model')} {card.get('version') or ''}".rstrip(),
            f"- **Input mode:** {card.get('input_mode')}"
            + (f" @ {card.get('dpi')} DPI" if card.get("dpi") else ""),
            f"- **Dataset commit:** {card.get('dataset_commit') or 'unknown'}",
            f"- **Scorer:** eval {card.get('eval_version')}, scored {card.get('scored_utc')}", ""]
    out += ["## Coverage", ""] + [f"- {k}: {v}" for k, v in coverage.items()] + [""]
    outcomes = Counter(r["outcome"] for r in rows)
    out += ["Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())),
            "", f"Missing predictions count as failures. Strata with n < {MIN_N} are not given a rate.", ""]
    for title, keys in STRATA[collection]:
        out += [f"## {title}", ""] + _table(aggregate(rows, *keys)) + [""]
    if drop:
        out += ["## Drop vs. clean page (same assertions, same model)", "",
                "| Variant | n | Clean | Perturbed | Drop |", "|---|---:|---:|---:|---:|"]
        out += [f"| {k} | {v['n']} | {_pct(v['clean_rate'])} | {_pct(v['perturbed_rate'])} | {_pct(v['drop'])} |"
                for k, v in drop.items()] + [""]
    not_scored = Counter(r["detail"].split(":")[0] for r in rows if r["outcome"] == "not_scored")
    if not_scored:
        out += ["## Not scored", ""] + [f"- {k}: {v}" for k, v in not_scored.most_common()] + [""]
    out += ["## Read with care", ""] + [f"- {c}" for c in CAVEATS[collection]] + [""]
    return "\n".join(out)
