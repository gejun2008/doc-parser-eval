"""Shared helpers: paths, prediction lookup, text normalisation, statistics, output."""
import csv
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# OCRBENCH_DATA overrides the data root (used by the fixture tests).
DATA = Path(os.environ.get("OCRBENCH_DATA") or ROOT / "data")

# A stratum with fewer scored items than this is reported as "insufficient sample".
MIN_N = 20

PASS, FAIL, MISSING, NOT_SCORED = "pass", "fail", "missing", "not_scored"


def data_relative(input_path):
    """'data/corpus/x.pdf', 'corpus/x.pdf' or 'C:\\...\\data\\corpus\\x.pdf' -> 'corpus/x.pdf'."""
    s = str(input_path).replace("\\", "/")
    if "/data/" in s:
        s = s.rsplit("/data/", 1)[1]
    return s.removeprefix("data/")


def prediction_path(input_path, page=None):
    """Prediction file for an input, relative to predictions/<model>/.

    Rule: drop 'data/', swap the extension for '.md'; inputs that are multi-page
    PDFs (the financial collection) get '_p<page>' because only some pages are scored.
    """
    stem = data_relative(input_path).rsplit(".", 1)[0]
    if page is not None:
        stem += f"_p{page}"
    return stem + ".md"


def read_prediction(pred_root, rel):
    """Text of a prediction, or None if the file does not exist (scored as a failure)."""
    p = Path(pred_root) / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_fences(text):
    """Remove a ```markdown fence wrapping the whole output. Content is not touched."""
    text = (text or "").strip()
    text = re.sub(r"^```markdown\s*\n?", "", text)
    text = re.sub(r"^```\s*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def aggregate(rows, *keys):
    """Pass rate by stratum. Missing predictions count as failures; not_scored rows are excluded."""
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(str(r[k]) for k in keys)].append(r)
    out = []
    for k, rs in sorted(groups.items()):
        scored = [r for r in rs if r["outcome"] in (PASS, FAIL, MISSING)]
        n_pass = sum(r["outcome"] == PASS for r in scored)
        lo, hi = wilson(n_pass, len(scored))
        out.append({
            "stratum": " / ".join(k), "n": len(scored), "pass": n_pass,
            "missing": sum(r["outcome"] == MISSING for r in scored),
            "not_scored": len(rs) - len(scored),
            "rate": round(n_pass / len(scored), 4) if scored else None,
            "ci95": [lo, hi], "sufficient": len(scored) >= MIN_N,
        })
    return out


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def git_commit(root=ROOT):
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "data"], cwd=root,
                               capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            return out.stdout.strip() + ("+modified-data" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def dump_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
