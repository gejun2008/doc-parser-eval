#!/usr/bin/env python3
"""
低质扫描扰动组生成 (T2)

research-plan.md §3.3 第 8 类。真实银行文档大量是传真件与多代影印件，
**扰动组的衰减幅度比原始分数更接近生产表现**。

零标注成本：扰动页的内容与原页完全相同，直接复用原页的断言文件。

## 必须避开的口径陷阱（sdk-findings.md §6）

把源 PDF 降到 150 DPI 再送**没有用**——客户端一律按 300 DPI 重新栅格化，
降了等于白降。要真正测低分辨率输入，必须**直接送图片**，
让 SDK 的 `encode_image_to_base64` 走 `smart_resize(min_pixels=2048,
max_pixels=16777216)` 这条路：150 DPI 的 A4 约 2.1M 像素，落在区间内会原样送出。

所以本脚本产出的是**图片文件**，runner 用图片路径调用，不经过 PDF 栅格化。

## 对照组

不另外生成。原始 300 DPI 的那次 run 就是对照组
（`runs/inf-mllm_doc2md_20260921T013924Z`），同一批页、同一批断言。
**只有衰减幅度有意义，扰动组的绝对分数没有独立含义。**

用法:
  python tools/perturb.py --per-family 6      # 每族抽 6 页做扰动
  python tools/perturb.py --variant dpi150    # 只生成某一种
"""

import argparse
import csv
import io
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter

OUT = Path("data/perturbed")
SEED = 20260921

VARIANTS = {
    "dpi150":    "150 DPI 栅格化。普通扫描仪常见设置",
    "dpi100":    "100 DPI 栅格化。传真件量级",
    "jpeg30":    "300 DPI 后 JPEG 质量 30。邮件转发反复压缩的效果",
    "rot2":      "300 DPI 后旋转 ±2°。走纸歪斜",
    "photocopy": "150 DPI + 灰度 + 对比度拉伸 + 高斯噪声 + 轻微模糊 + 旋转 1°。多代影印",
}


def render(pdf, page_no, dpi):
    pix = pymupdf.open(pdf)[page_no - 1].get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def add_noise(img, sigma=12, seed=0):
    """加高斯噪声。用固定 seed 保证可复现。"""
    import numpy as np
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.int16)
    arr = arr + rng.normal(0, sigma, arr.shape).astype(np.int16)
    return Image.fromarray(arr.clip(0, 255).astype("uint8"))


def make(variant, pdf, page_no, seed):
    """返回 (PIL 图, 保存格式, 后缀)。所有随机性由 seed 决定。"""
    if variant == "dpi150":
        return render(pdf, page_no, 150), "PNG", ".png"
    if variant == "dpi100":
        return render(pdf, page_no, 100), "PNG", ".png"
    if variant == "jpeg30":
        img = render(pdf, page_no, 300)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=30)
        buf.seek(0)
        return Image.open(buf).convert("RGB"), "JPEG", ".jpg"
    if variant == "rot2":
        img = render(pdf, page_no, 300)
        angle = 2.0 if seed % 2 == 0 else -2.0   # 确定性地交替正负
        return img.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255)), "PNG", ".png"
    if variant == "photocopy":
        img = render(pdf, page_no, 150).convert("L")
        img = ImageEnhance.Contrast(img).enhance(1.6)
        img = img.convert("RGB")
        img = add_noise(img, sigma=14, seed=seed)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        img = img.rotate(1.0, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
        return img, "PNG", ".png"
    raise ValueError(variant)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=6)
    ap.add_argument("--variant", action="append", choices=list(VARIANTS))
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    variants = a.variant or list(VARIANTS)

    rows = list(csv.DictReader(open("data/corpus/pages.csv", encoding="utf-8")))
    by_fam = defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r)

    # 分层抽样，固定 seed，报告附录要能复现选了哪些页
    picked = []
    for fam, rs in sorted(by_fam.items()):
        rs = sorted(rs, key=lambda r: (r["doc_id"], int(r["page"])))
        n = min(a.per_family, len(rs))
        picked += random.Random(f"{a.seed}:{fam}").sample(rs, n)
    picked.sort(key=lambda r: (r["family"], r["doc_id"], int(r["page"])))
    print(f"抽样 {len(picked)} 页 × {len(variants)} 个扰动 = {len(picked)*len(variants)} 次调用")

    man = []
    for i, r in enumerate(picked):
        for v in variants:
            d = OUT / v
            d.mkdir(parents=True, exist_ok=True)
            img, fmt, ext = make(v, r["local_path"], int(r["page"]), a.seed + i)
            dst = d / f"{r['doc_id']}_p{r['page']}{ext}"
            img.save(dst, format=fmt, **({"quality": 30} if fmt == "JPEG" else {}))
            man.append({"variant": v, "path": str(dst), "doc_id": r["doc_id"],
                        "page": r["page"], "family": r["family"], "window": r["window"],
                        "width": img.size[0], "height": img.size[1],
                        "pixels": img.size[0] * img.size[1],
                        "bytes": dst.stat().st_size,
                        "source_pdf": r["local_path"]})
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(picked)} 页")

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(man[0].keys()))
        w.writeheader()
        w.writerows(man)
    (OUT / "perturb_meta.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": a.seed, "per_family": a.per_family,
        "variants": {v: VARIANTS[v] for v in variants},
        "n_pages": len(picked), "n_images": len(man),
        "control": "原始 300 DPI run 即对照组，不另生成",
        "trap_note": ("必须以图片送入，不能降源 PDF 的 DPI——"
                      "客户端一律按 300 DPI 重栅格化（sdk-findings.md §6）"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'扰动':12} {'张数':>4} {'中位像素':>10} {'中位KB':>8}")
    for v in variants:
        g = [m for m in man if m["variant"] == v]
        px = sorted(m["pixels"] for m in g)[len(g)//2]
        kb = sorted(m["bytes"] for m in g)[len(g)//2] / 1024
        print(f"{v:12} {len(g):4} {px:10,} {kb:8.0f}")
    print(f"\n-> {OUT}/manifest.csv")


if __name__ == "__main__":
    main()
