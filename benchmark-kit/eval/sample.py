"""Fixed, stratified sample of benchmark inputs, for quick multi-model comparisons.

    python -m eval sample --name quick100                         # default quotas, 100 inputs
    python -m eval sample --name q --quota financial=60 parsebench=40 --seed 7

Writes samples/<name>.csv. Run and score every model with `--inputs samples/<name>.csv` so that all of them
see exactly the same inputs. Commit the file if other people should use the same sample.

Within each collection inputs are spread over its strata in proportion to stratum size (at least one per stratum
while the quota allows), chosen at random with a fixed seed: same seed + same dataset = same sample.
Strata: financial = document family, olmOCR = subset, perturbation = variant, ParseBench = file group.
"""
import hashlib
import random
from pathlib import Path

from .common import ROOT, read_csv, write_csv

DEFAULT_QUOTA = {"financial": 40, "parsebench": 30, "olmocr": 20, "perturbed": 10}
DEFAULT_SEED = 20261020
FIELDS = ["collection", "stratum", "input_path", "page", "prediction_path"]


def stratum_of(collection, prediction_path):
    """The path component that names the stratum: corpus/<family>/, perturbed/<variant>/,
    olmocr_bench/bench_data/pdfs/<subset>/, parsebench/subset/docs/<group>/."""
    parts = prediction_path.split("/")
    idx = {"financial": 1, "perturbed": 1, "olmocr": 3, "parsebench": 3}[collection]
    return parts[idx] if len(parts) > idx + 1 else ""


def _allocate(sizes, quota):
    """Largest-remainder allocation of `quota` over strata, at least 1 each while quota allows."""
    total = sum(sizes.values())
    quota = min(quota, total)
    keys = sorted(sizes)
    alloc = {k: 0 for k in keys}
    if quota >= len(keys):
        for k in keys:
            alloc[k] = 1
    left = quota - sum(alloc.values())
    if left > 0:
        cap = {k: sizes[k] - alloc[k] for k in keys}
        share = {k: left * cap[k] / max(1, sum(cap.values())) for k in keys}
        for k in keys:
            alloc[k] += min(cap[k], int(share[k]))
        rest = quota - sum(alloc.values())
        for k in sorted(keys, key=lambda k: share[k] - int(share[k]), reverse=True):
            if rest <= 0:
                break
            if alloc[k] < sizes[k]:
                alloc[k] += 1
                rest -= 1
    return alloc


def build_sample(items, quota=None, seed=DEFAULT_SEED):
    """items: [{collection, input_path, page, prediction_path}]. Returns the sampled rows."""
    quota = quota or DEFAULT_QUOTA
    out = []
    for coll, q in quota.items():
        pool = [dict(it, stratum=stratum_of(coll, it["prediction_path"])) for it in items if it["collection"] == coll]
        by = {}
        for it in pool:
            by.setdefault(it["stratum"], []).append(it)
        alloc = _allocate({k: len(v) for k, v in by.items()}, q)
        rng = random.Random(f"{seed}:{coll}")
        for k in sorted(by):
            ordered = sorted(by[k], key=lambda it: it["prediction_path"])
            out += sorted(rng.sample(ordered, alloc[k]), key=lambda it: it["prediction_path"])
    return out


def write_sample(rows, name):
    path = ROOT / "samples" / f"{name}.csv"
    write_csv(path, rows, FIELDS)
    return path


def load_sample(path):
    """(set of prediction paths, description) for --inputs."""
    p = Path(path)
    rows = read_csv(p)
    if not rows or "prediction_path" not in rows[0]:
        raise SystemExit(f"{p} is not a sample file (needs a prediction_path column)")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return {r["prediction_path"] for r in rows}, {"file": p.name, "n": len(rows), "sha256_16": digest}
