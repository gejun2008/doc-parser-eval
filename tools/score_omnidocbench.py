#!/usr/bin/env python3
"""
OmniDocBench 金融切片判分（research-plan.md §3.2 第二层）

**判分逻辑不自己写**：调用官方 opendatalab/OmniDocBench 评测代码（end2end + quick_match），
钉在 commit PINNED，放在 tools/vendor/omnidocbench_src/（不入库，见 setup 命令）。
本脚本只做四件事：
  1. 读 runner 落盘，套 SDK 后处理（与 score_olmocr.py 同一个函数）
  2. 按官方命名写每页 md（<图片名去扩展名>.md）
  3. 调官方 pdf_validation.py，产物收进 runs/<run_id>/omnidoc_result/
  4. 按子集分层汇总，每层给 n 与 bootstrap 95% CI，不合成总分

指标方向：Edit_dist 越低越好（0 = 完全一致），TEDS 越高越好（1 = 完全一致）。
按 CLAUDE.md，这些学术指标只进附录，用于与厂商口径对齐，不进正文。

调用失败页（ok=false，含 finish_reason=length）写空 md 参与判分——
等于该页全错，与 score_olmocr.py「失败页上的测试判 fail」同一口径，另在 failed_pages 单列。

环境（官方要求 Python 3.10–3.11，与主 venv 分开）:
  git clone https://github.com/opendatalab/OmniDocBench.git tools/vendor/omnidocbench_src
  git -C tools/vendor/omnidocbench_src checkout <PINNED>
  uv venv --python 3.11 tools/vendor/.venv-omnidoc
  uv pip install --python tools/vendor/.venv-omnidoc/bin/python -e tools/vendor/omnidocbench_src

用法:
  python tools/score_omnidocbench.py runs/<run_id>
"""

import argparse
import csv
import json
import random
import re
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score_olmocr import postprocess_doc2md  # noqa: E402  同一个后处理，不重复实现

PINNED = "f133a71e9e91c3621c7ce8994200a7b394a06eb3"
SRC = Path("tools/vendor/omnidocbench_src").resolve()
PY = Path("tools/vendor/.venv-omnidoc/bin/python").absolute()  # 不能 resolve：venv 的 python 是软链
DATA = Path("data/omnidocbench")
GT = DATA / "gt_research_report.json"
SAVE_NAME = "omnidoc_pred_quick_match"  # 官方按「预测目录名_匹配方法」命名


def bootstrap_ci(xs, n_boot=2000, seed=20260929):
    """页（或表）为重抽样单位的均值 95% CI。种子固定，可复现。"""
    if len(xs) < 2:
        return [None, None]
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n_boot))
    return [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot) - 1], 4)]


def stat(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if not xs:
        return {"n": 0}
    out = {"n": len(xs), "mean": round(statistics.fmean(xs), 4),
           "median": round(statistics.median(xs), 4), "ci95": bootstrap_ci(xs)}
    if len(xs) < 30:
        out["note"] = "样本不足，不下结论"
    return out


def check_src():
    if not SRC.exists() or not PY.exists():
        sys.exit("官方评测代码或其 venv 不存在，按文件头的 setup 命令安装")
    head = subprocess.run(["git", "-C", str(SRC), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != PINNED:
        sys.exit(f"官方评测代码 commit {head[:8]} ≠ 钉定的 {PINNED[:8]}，口径会漂")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    check_src()

    run_dir = Path(a.run_dir).resolve()
    manifest = {r["pdf"]: r for r in csv.DictReader(open(DATA / "manifest.csv", encoding="utf-8"))}
    gt_pages = {p["page_info"]["image_path"]: p
                for p in json.loads(GT.read_text(encoding="utf-8"))}

    pred_dir = run_dir / "omnidoc_pred"
    shutil.rmtree(pred_dir, ignore_errors=True)
    pred_dir.mkdir()
    raws, failed = {}, []
    for f in sorted((run_dir / "raw").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        raws[r["pdf"]] = r
    missing = sorted(set(gt_pages) - set(raws))
    if missing:
        sys.exit(f"{len(missing)} 页没有 runner 落盘，先跑完再判分，例如 {missing[:3]}")

    for name, r in raws.items():
        md = postprocess_doc2md(r.get("content") or "") if r.get("ok") else ""
        if not r.get("ok"):
            failed.append({"image": name, "status": r.get("status"),
                           "finish_reason": r.get("finish_reason")})
        (pred_dir / (name[:-4] + ".md")).write_text(md, encoding="utf-8")

    # 官方代码把产物写到 cwd/result/，所以在 run 目录下的工作目录里跑
    work = run_dir / "omnidoc_eval"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    cfg = f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: {a.workers}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: {GT.resolve()}
    prediction:
      data_path: {pred_dir}
    match_method: quick_match
    match_workers: {a.workers}
"""
    (work / "config.yaml").write_text(cfg, encoding="utf-8")
    log = work / "eval.log"
    with open(log, "w", encoding="utf-8") as lf:
        rc = subprocess.run([str(PY), str(SRC / "pdf_validation.py"), "--config", "config.yaml"],
                            cwd=work, stdout=lf, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        sys.exit(f"官方评测退出码 {rc}，见 {log}")
    res = work / "result"
    official = json.loads((res / f"{SAVE_NAME}_metric_result.json").read_text(encoding="utf-8"))

    def per_page(element):
        p = res / f"{SAVE_NAME}_{element}_per_page_edit.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    text_pp, table_pp, order_pp = per_page("text_block"), per_page("table"), per_page("reading_order")
    teds_pt = json.loads((res / f"{SAVE_NAME}_table_per_table_TEDS.json").read_text(encoding="utf-8"))

    # 表格拍平率：GT 有表、产品输出里一张 <table> 都没有（olmOCR-Bench 发现 1 的同口径复核）
    def has_table(name):
        return "<table" in (pred_dir / (name[:-4] + ".md")).read_text(encoding="utf-8").lower()

    groups = defaultdict(list)
    for name in gt_pages:
        groups["all"].append(name)
        groups[f"subset={manifest[name]['subset']}"].append(name)
        groups[f"language={manifest[name]['language']}"].append(name)

    def table_scores(names, key):
        names = set(names)
        return [v[key] for k, v in teds_pt.items()
                if any(k.startswith(n) for n in names)]

    strata = {}
    for g, names in sorted(groups.items()):
        table_pages = [n for n in names if int(manifest[n]["n_tables"]) > 0]
        flat = [n for n in table_pages if not has_table(n)]
        strata[g] = {
            "n_pages": len(names),
            "text_edit_dist_per_page": stat([text_pp.get(n) for n in names]),
            "reading_order_edit_dist_per_page": stat([order_pp.get(n) for n in names]),
            "table_edit_dist_per_page": stat([table_pp.get(n) for n in names]),
            "table_TEDS_per_table": stat(table_scores(names, "TEDS")),
            "table_TEDS_structure_only_per_table": stat(table_scores(names, "TEDS_structure_only")),
            "table_flattened": {"pages_with_gt_table": len(table_pages),
                                "pages_without_any_pred_table": len(flat),
                                "rate": round(len(flat) / len(table_pages), 4) if table_pages else None},
        }

    lats = [r["latency_s"] for r in raws.values() if r.get("ok")]
    summary = {
        "run_id": run_dir.name,
        "scored_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scorer": {"source": "opendatalab/OmniDocBench", "pinned_commit": PINNED[:8],
                   "method": "end2end, quick_match", "reimplemented": False},
        "dataset": json.loads((DATA / "slice_meta.json").read_text(encoding="utf-8")),
        "postprocess": "infinity_parser2 v0.4.0 postprocess_doc2md_result（逐字复制，只剥 ``` 围栏）",
        "direction": "Edit_dist 越低越好；TEDS 越高越好",
        "caveats": [
            "学术指标，只进附录用于与厂商口径对齐，不进正文",
            "按子集与语言分层，不合成加权总分；n<30 的分层不下结论",
            "调用失败页写空 md 参与判分，另见 failed_pages",
            "输入是数据集自带 PNG（约 200 DPI），走 SDK 图片路径，不是 300 DPI PDF 栅格化",
            "OmniDocBench 是公开基准，无法排除进过训练集；研报页多为 2024 年前材料",
        ],
        "n_pages": len(raws), "n_failed_pages": len(failed), "failed_pages": failed,
        "page_latency_s": {"n": len(lats),
                           "median": round(statistics.median(lats), 1) if lats else None},
        "strata": strata,
        "official_metric_result": official,
    }
    shutil.copytree(res, run_dir / "omnidoc_result", dirs_exist_ok=True)
    (run_dir / "omnidoc_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'分层':<32}{'页':>4}  {'正文ED↓':>16}  {'阅读序ED↓':>16}  {'表TEDS↑(n表)':>20}  拍平")
    for g, s in strata.items():
        def fmt(x):
            return f"{x['mean']:.3f} {x['ci95']}" if x.get("n") and x.get("ci95")[0] is not None else "-"
        t = s["table_TEDS_per_table"]
        print(f"{g:<32}{s['n_pages']:>4}  {fmt(s['text_edit_dist_per_page']):>16}  "
              f"{fmt(s['reading_order_edit_dist_per_page']):>16}  "
              f"{fmt(t):>14}({t.get('n', 0)})  "
              f"{s['table_flattened']['pages_without_any_pred_table']}/{s['table_flattened']['pages_with_gt_table']}")
    print(f"\n失败页 {len(failed)}  -> {run_dir / 'omnidoc_summary.json'}")


if __name__ == "__main__":
    main()
