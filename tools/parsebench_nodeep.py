#!/usr/bin/env python3
"""
ParseBench deep parsing 消融：去掉 deep parsing 后 Infinity 的分数

官方 infinity_parser2_flash pipeline 在模型输出后多做一步 deep parsing
（每个 figure 裁图再调一次模型转表格）。这一步在评测框架的 provider 里，
**不在 INF SDK 默认流程里**，客户按默认参数拿不到。

本脚本**不调用 API**：从 INF run 的 raw/ 里取每份文件主调用（doc2json）的原始输出，
按与 parsebench_runner.py 相同的后处理还原成 shallow 结果，写成新 run 目录，
再交给 parsebench_score.py 用官方判分器重判。与原 run 的唯一差别就是没有 deep parsing。

用法（在 parse-bench 独立环境里）:
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_nodeep.py runs/parsebench_inf_<ts>
  tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/parsebench_inf_<ts>_nodeep
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from PIL import Image

# parsebench_runner 经 probe.py 导入时会检查 INF 凭证；本脚本不发请求，给占位值即可
os.environ.setdefault("INFINITY_PARSER2_API_URL", "unused://no-api-call")
os.environ.setdefault("INFINITY_PARSER2_API_KEY", "unused")
sys.path.insert(0, str(Path(__file__).parent))
import parsebench_runner as R  # noqa: E402  复用同一套后处理，保证口径一致

PIPELINE = "infinity_parser2_flash"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inf_run")
    a = ap.parse_args()

    src = Path(a.inf_run)
    dst = src.with_name(src.name + "_nodeep")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in ("run_meta.json", "run_summary.json"):
        if (src / name).exists():
            shutil.copy(src / name, dst / name)

    # pdf（不含扩展名）-> 我们的原始记录
    ours = {}
    for p in (src / "raw").glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        ours[rec["pdf"].rsplit(".", 1)[0]] = rec

    pb_src = src / "parsebench" / PIPELINE
    n = 0
    for f in sorted(pb_src.rglob("*.raw.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rec = ours["docs/" + d["request"]["example_id"]]
        pages = []
        for c in rec["calls"]:
            if c["kind"] != "doc2json":
                continue
            fin = c["attempts"][-1]
            content = (R.choice(fin).get("message") or {}).get("content") if fin["status"] == 200 else None
            if content is None:
                pages.append({"result": "", "_config": {}})
                continue
            w, h = c["image"]["orig_w"], c["image"]["orig_h"]
            # 后处理只用到图像宽高，用同尺寸空白图代替原图
            result, _ = R.postprocess_doc2json(content, Image.new("RGB", (w, h)))
            cfg = dict(d["raw_output"].get("_config") or {}) or {
                "page_width": float(w), "page_height": float(h)}
            pages.append({"result": result, "_config": cfg})
        raw_output = dict(pages[0]) if pages else {"result": "", "_config": {}}
        if len(pages) > 1:
            raw_output["page_results"] = pages
        d["raw_output"] = raw_output
        out = dst / "parsebench" / PIPELINE / f.relative_to(pb_src)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        n += 1

    (dst / "ABLATION.txt").write_text(
        f"由 tools/parsebench_nodeep.py 从 {src.name} 生成：主调用输出不变，去掉 deep parsing。"
        f"未调用 API。文件数 {n}。\n", encoding="utf-8")
    print(f"重建 {n} 份 shallow 结果 -> {dst}")
    print(f"下一步: tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py {dst}")


if __name__ == "__main__":
    main()
