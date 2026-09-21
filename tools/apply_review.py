#!/usr/bin/env python3
"""
把审核页导出的 JSON 合并回断言 YAML (T3 收尾)

审核页（tools/review_assertions.py）导出的 JSON 形如：
  {"doc_id": ..., "reviewed_at": ..., "decisions": {"<assertion_id>": {"status": ..., "target": ...}}}

合并规则：
  confirmed  status 改为 confirmed；若人工改过 target 则采用新值，
             并把原值记在 original_target 里（**不覆盖证据链**）
  rejected   status 改为 rejected，保留在文件里但判定器会跳过
             （删掉会让「为什么这条没测」无从追溯）

status=auto 的 page_integrity 不受影响。

用法:
  python tools/apply_review.py ~/Downloads/review_<doc_id>.json
  python tools/apply_review.py ~/Downloads/review_*.json
  python tools/apply_review.py --status          # 只看各文档的审核进度
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ASSERT_DIR = Path("data/assertions")


def show_status():
    tot = Counter()
    print(f"{'文档':46} {'auto':>5} {'draft':>6} {'confirmed':>10} {'rejected':>9}")
    for f in sorted(ASSERT_DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        c = Counter(i.get("status", "draft") for i in d["assertions"])
        tot.update(c)
        print(f"{d['doc_id'][:46]:46} {c['auto']:5} {c['draft']:6} "
              f"{c['confirmed']:10} {c['rejected']:9}")
    print(f"\n合计 auto {tot['auto']}  draft {tot['draft']}  "
          f"confirmed {tot['confirmed']}  rejected {tot['rejected']}")
    if tot["draft"]:
        print(f"！还有 {tot['draft']} 条草稿未审核，判定器会跳过它们")


def apply_one(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    doc_id = data["doc_id"]
    yml = ASSERT_DIR / f"{doc_id}.yaml"
    if not yml.exists():
        print(f"！找不到 {yml}")
        return Counter()
    d = yaml.safe_load(yml.read_text(encoding="utf-8"))
    decisions = data.get("decisions") or {}
    c = Counter()
    for it in d["assertions"]:
        dec = decisions.get(it["id"])
        if not dec:
            continue
        if it.get("status") == "auto":
            continue  # page_integrity 锚点为纯自动类，不接受人工改动
        # auto_textlayer 可以被审计推翻：人工发现文本层 GT 错了就标 rejected
        new_status = dec.get("status")
        if new_status not in ("confirmed", "rejected"):
            continue
        new_target = dec.get("target")
        if (new_status == "confirmed" and new_target
                and new_target != str(it.get("target"))):
            it["original_target"] = it.get("target")
            it["target"] = new_target
            c["edited"] += 1
        it["status"] = new_status
        c[new_status] += 1
    d.setdefault("review", {})
    d["review"]["reviewed_at"] = data.get("reviewed_at")
    d["review"]["applied_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    d["review"]["source"] = str(path)
    yml.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=100),
                   encoding="utf-8")
    print(f"{doc_id}: confirmed {c['confirmed']}  rejected {c['rejected']}  "
          f"人工改值 {c['edited']}")
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_files", nargs="*")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status or not a.json_files:
        show_status()
        return
    tot = Counter()
    for p in a.json_files:
        tot.update(apply_one(p))
    print(f"\n合计 confirmed {tot['confirmed']}  rejected {tot['rejected']}  "
          f"人工改值 {tot['edited']}")


if __name__ == "__main__":
    main()
