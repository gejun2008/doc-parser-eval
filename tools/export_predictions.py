#!/usr/bin/env python3
"""
把本仓库历史 run 的模型输出导出成 benchmark-kit 要求的 predictions 目录，供 ocr-benchmark skill 判分。

只读旧 run，不改任何文件。调用失败（ok=false）的页不写文件，判分时记为 missing（= 失败），与旧口径一致。

用法（公司电脑，在旧评测仓库目录执行，--out 指向数据集仓库里的 predictions 目录）:
  python tools/export_predictions.py --out <DS>/predictions/inf-flash --model Infinity-Parser2-Flash \
      --financial runs/<金融 run> --perturbed runs/<扰动 run> \
      --olmocr runs/<olmOCR run> --parsebench runs/<ParseBench INF run>
各集合都可省略，只导出给了 run 的那几个。
"""
import argparse
import json
from pathlib import Path


def prediction_rel(collection, rec):
    pdf = rec["pdf"].replace("\\", "/").removeprefix("data/")
    stem = pdf.rsplit(".", 1)[0]
    if collection == "financial":
        return f"{stem}_p{rec['page']}.md"
    if collection == "olmocr":
        return f"olmocr_bench/bench_data/pdfs/{stem}.md"
    return f"{stem}.md"


def export(run, collection, pred):
    """run_dir 里某个集合的输出 -> pred 目录。返回写出的文件数。"""
    run, pred, n = Path(run), Path(pred), 0
    if collection == "parsebench":
        # ParseBench run 落盘的是官方 *.result.json，取官方 normalize 后的 markdown
        for f in sorted((run / "parsebench").rglob("*.result.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            p = pred / f"parsebench/subset/docs/{r['request']['example_id']}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text((r.get("output") or {}).get("markdown") or "", encoding="utf-8")
            n += 1
        return n
    for f in sorted((run / "raw").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if not r.get("ok"):
            continue
        p = pred / prediction_rel(collection, r)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(r.get("content") or "", encoding="utf-8")
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="predictions/<model> 目录")
    ap.add_argument("--model", required=True)
    ap.add_argument("--version", default="")
    for c in ("financial", "perturbed", "olmocr", "parsebench"):
        ap.add_argument(f"--{c}", metavar="RUN_DIR")
    a = ap.parse_args()
    out = Path(a.out)
    for c in ("financial", "perturbed", "olmocr", "parsebench"):
        run = getattr(a, c)
        if run:
            print(f"{c}: {export(run, c, out)} 个文件 <- {run}")
    # 历史 run 都是图片输入、300 DPI（runner.py / parsebench_runner.py 的固定口径）
    (out / "run_card.yaml").write_text(
        f"model: {a.model}\nversion: \"{a.version}\"\ninput_mode: image\ndpi: 300\n"
        "output_format: markdown\nnotes: exported from historical doc-parser-eval runs\n",
        encoding="utf-8")
    print(f"-> {out}（run_card.yaml 已写，按需补 version）")


if __name__ == "__main__":
    main()
