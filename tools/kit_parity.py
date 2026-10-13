#!/usr/bin/env python3
"""
新判分器（benchmark-kit 的 python -m eval）与旧判分器的逐条一致性检查。

把旧 run 的原始响应（runs/<run_id>/raw/*.json）转成 predictions 目录，用新判分器打分，
再与旧 run 落盘的逐条结果逐条比对。只读旧 run，不改任何文件；临时文件写在系统临时目录。

用法（在公司电脑上，dataset 仓库已放入 benchmark-kit 的 eval/）:
  python tools/kit_parity.py runs/<金融 run>   --collection financial --dataset <ocr-benchmark-dataset 路径>
  python tools/kit_parity.py runs/<扰动 run>   --collection perturbed --dataset <...>
  python tools/kit_parity.py runs/<olmOCR run> --collection olmocr    --dataset <...> [--with-math]
  python tools/kit_parity.py runs/<ParseBench run> --collection parsebench --dataset <...>

比对口径:
  - 旧结果里 pass 为空（当时未执行，例如 draft）的条目不比
  - 金融与扰动：旧 target 与新 GT 的 target 前 80 字不同的条目不比（GT 在 9/23 复核时改过 2 条）
  - olmOCR 不带 --with-math 时，math 类不比
  - ParseBench：预测取旧 run 的 *.result.json 里官方 normalize 后的 markdown；只比 layout 以外四个维度，
    逐文件分数差 < 1e-6 算一致。已知 1 处差异：整段输出被 ```markdown 围栏包住的文件，
    新口径先剥掉外层围栏再判（INF 官方流程不剥）
本仓库已用历史 INF 数据核对：金融 1,153/1,153、扰动 500/500、ParseBench 512/513 一致；
olmOCR 需在公司电脑上跑。
"""
import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def prediction_rel(collection, rec):
    pdf = rec["pdf"].replace("\\", "/").removeprefix("data/")
    stem = pdf.rsplit(".", 1)[0]
    if collection == "financial":
        return f"{stem}_p{rec['page']}.md"
    if collection == "olmocr":
        return f"olmocr_bench/bench_data/pdfs/{stem}.md"
    return f"{stem}.md"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--collection", required=True, choices=["financial", "perturbed", "olmocr", "parsebench"])
    ap.add_argument("--dataset", required=True, help="ocr-benchmark-dataset 仓库根目录")
    ap.add_argument("--with-math", action="store_true")
    a = ap.parse_args()
    run, ds = Path(a.run_dir), Path(a.dataset).resolve()

    tmp = Path(tempfile.mkdtemp(prefix="kit_parity_"))
    pred = tmp / "predictions" / "parity"
    n = 0
    if a.collection == "parsebench":
        for f in sorted((run / "parsebench").rglob("*.result.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            ex = r["request"]["example_id"]
            p = pred / f"parsebench/subset/docs/{ex}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text((r.get("output") or {}).get("markdown") or "", encoding="utf-8")
            n += 1
    for f in sorted((run / "raw").glob("*.json")) if a.collection != "parsebench" else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        if not r.get("ok"):
            continue                      # 旧口径：调用失败判 fail；新口径：无文件 = missing = fail
        p = pred / prediction_rel(a.collection, r)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(r.get("content") or "", encoding="utf-8")
        n += 1
    (pred / "run_card.yaml").write_text("model: parity\ninput_mode: image\ndpi: 300\n", encoding="utf-8")
    print(f"{n} 条原始响应 -> {pred}")

    out = tmp / "results"
    cmd = [sys.executable, "-m", "eval", "score", str(pred), "--collections", a.collection, "--out", str(out)]
    if a.with_math:
        cmd.append("--with-math")
    subprocess.run(cmd, cwd=ds, check=True)
    new = list(csv.DictReader(open(out / f"{a.collection}.csv", encoding="utf-8")))

    if a.collection == "parsebench":
        old = {(r["dimension"], r["example_id"]): float(r["score"])
               for r in csv.DictReader(open(run / "parsebench_per_file.csv", encoding="utf-8"))}
        new_by = {(r["test_type"], r["test_id"]): r for r in new if r["outcome"] in ("scored", "missing")}
        diff = [(k, v, new_by[k]["score"]) for k, v in old.items()
                if k in new_by and abs(v - float(new_by[k]["score"])) >= 1e-6]
        n_cmp = sum(k in new_by for k in old)
        print(f"\n比对 {n_cmp} 个文件×维度（旧结果共 {len(old)} 个，layout 不比），"
              f"一致 {n_cmp - len(diff)}，不一致 {len(diff)}")
        for d in diff[:20]:
            print("  ", d)
        print(f"\n临时目录 {tmp}（可删除）")
        return 1 if diff else 0

    if a.collection == "olmocr":
        old = {r["test_id"]: r for r in csv.DictReader(open(run / "olmocr_results.csv", encoding="utf-8"))}
        new_by = {r["test_id"]: r for r in new}
        keyed = [(k, o["pass"], new_by.get(k)) for k, o in old.items()
                 if o["pass"] != "" and (a.with_math or o["type"] != "math")]
    else:
        old = {(r["assertion_id"], r["variant"]): r
               for r in csv.DictReader(open(run / "results.csv", encoding="utf-8"))}
        gt = {}
        for y in (ds / "data" / "assertions").glob("*.yaml"):
            import yaml
            for it in yaml.safe_load(y.read_text(encoding="utf-8"))["assertions"]:
                gt[it["id"]] = str(it.get("target"))[:80]
        new_by = {(r["test_id"], r["variant"]): r for r in new}
        keyed = [(k, o["pass"], new_by.get(k)) for k, o in old.items()
                 if o["pass"] != "" and gt.get(k[0]) == o["target"]]

    diff = []
    for k, old_pass, nr in keyed:
        new_pass = None if nr is None else ("1" if nr["outcome"] == "pass" else
                                            "0" if nr["outcome"] in ("fail", "missing") else "")
        if new_pass != old_pass:
            diff.append((k, old_pass, nr["outcome"] if nr else "absent", (nr or {}).get("detail", "")[:100]))
    print(f"\n比对 {len(keyed)} 条（旧结果共 {len(old)} 条），一致 {len(keyed) - len(diff)}，不一致 {len(diff)}")
    for d in diff[:20]:
        print("  ", d)
    print(f"\n临时目录 {tmp}（可删除）")
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
