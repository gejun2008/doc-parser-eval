#!/usr/bin/env python3
"""
ParseBench 结果文档生成（INF vs Azure DI）

只读已落盘的产物，不重新判分、不改任何数字:
  <inf_run>/   run_meta.json, run_summary.json, parsebench_summary.json, parsebench_per_file.csv
  <azure_run>/ 同上 + parsebench_compare.json（parsebench_compare.py 产出）
  tools/vendor/parsebench_src/leaderboard.csv   官方全量 leaderboard，只作参照并列，不加评论

输出一份 markdown（默认 docs/working/parsebench-results.md）。
写法遵守 CLAUDE.md：不合成总分；分层样本不足写「样本不足，不下结论」；
p ≥ 0.05 写「未观察到显著差异」；厂商数字与我们的数字并列成表，不加评论。

用法:
  python tools/parsebench_report.py runs/<inf_run> runs/<azure_run>
  python tools/parsebench_report.py runs/<inf_run>                  # 只有 INF 单边
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

DIM_NAME = {"table": "Tables", "chart": "Charts", "text_content": "Content Faithfulness",
            "text_formatting": "Semantic Formatting", "layout": "Visual Grounding"}
LB_COL = {"table": "Tables", "chart": "Charts", "text_content": "Content_Faithfulness",
          "text_formatting": "Semantic_Formatting", "layout": "Visual_Grounding"}
LB_ROWS = ["Infinity-Parser2-Flash", "Infinity-Parser2-Pro", "Azure Document Intelligence (Layout)"]


def jload(p):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x):
    return "—" if x is None else f"{x * 100:.1f}"


def ci(c):
    lo, hi = c or (None, None)
    return "—" if lo is None else f"[{lo * 100:.1f}, {hi * 100:.1f}]"


def leaderboard():
    p = Path("tools/vendor/parsebench_src/leaderboard.csv")
    if not p.exists():
        return {}
    return {r["Provider"]: r for r in csv.DictReader(open(p, encoding="utf-8"))
            if r["Provider"] in LB_ROWS}


def sys_block(name, run):
    meta, summ = jload(run / "run_meta.json") or {}, jload(run / "run_summary.json") or {}
    ps = jload(run / "parsebench_summary.json") or {}
    return name, meta, summ, ps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inf_run")
    ap.add_argument("azure_run", nargs="?")
    ap.add_argument("--out", default="docs/working/parsebench-results.md")
    a = ap.parse_args()

    inf = Path(a.inf_run)
    az = Path(a.azure_run) if a.azure_run else None
    _, im, isumm, ips = sys_block("INF", inf)
    am, asumm, aps, cmp_ = {}, {}, {}, None
    if az:
        _, am, asumm, aps = sys_block("Azure", az)
        cmp_ = jload(az / "parsebench_compare.json")
    subset = jload("data/parsebench/subset_meta.json") or {}

    L = []
    w = L.append
    w("# ParseBench 500 份分层子集：Infinity-Parser2 与 Azure DI")
    w("")
    w(f"> 由 `tools/parsebench_report.py` 于 {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC 从落盘结果生成，"
      "数字一律来自下列文件，未手工改动。口径见 `docs/working/parsebench-method.md`。")
    w("")
    w("**这一层是中立公开基准（准入门槛），不是结论依据。** 厂商在 ParseBench 上自报过分数，"
      "泄漏风险无法排除；决定性证据仍在自建金融场景集。")
    w("")
    w("## 1. 运行信息")
    w("")
    w("| 项 | Infinity-Parser2 | Azure DI |")
    w("|---|---|---|")
    w(f"| run_id | `{im.get('run_id', '—')}` | `{am.get('run_id', '—')}` |")
    w(f"| 开始时间 (UTC) | {im.get('started_utc', '—')} | {am.get('started_utc', '—')} |")
    w(f"| 调用口径 | 裸 HTTP，doc2json + deep parsing（= 官方 `infinity_parser2_flash`） | "
      f"prebuilt-layout，markdown（= 官方 `azure_di_layout`），经公司网关 |")
    w(f"| 服务端回显模型 | {', '.join(isumm.get('served_models', [])) or '—'} | "
      f"{', '.join(asumm.get('served_models', [])) or '—'} |")
    w(f"| 并发 | {im.get('concurrency', '—')} | {am.get('concurrency', '—')} |")
    w(f"| 文件数（落盘 / 成功） | {isumm.get('n_files_on_disk', '—')} / {isumm.get('n_files_ok', '—')} | "
      f"{asumm.get('n_files_on_disk', '—')} / {asumm.get('n_files_ok', '—')} |")
    w(f"| 空输出（按 0 分计） | {len(ips.get('empty_output_files', []))} | "
      f"{len(aps.get('empty_output_files', [])) if aps else '—'} |")
    w(f"| 判分器 | run-llama/ParseBench `{ips.get('scorer', {}).get('commit', '—')}`，官方 normalize + 官方指标 | 同左 |")
    w("")
    w(f"数据集 `llamaindex/ParseBench` revision `{subset.get('hf_revision', '—')[:12]}`，"
      f"seed `{subset.get('seed', '—')}`，{subset.get('n_files', '—')} 份文件；"
      f"规则数 {subset.get('n_rules', {})}。")
    w("")

    # 2. 主结果
    w("## 2. 按维度（官方主指标，满分 100）")
    w("")
    if cmp_:
        for view, title in (("both_output", "主口径：只比两边都有输出的文件"),
                            ("all", "参照口径：全部文件，失败 / 空输出按 0 分")):
            w(f"### {title}")
            w("")
            w("| 维度 | n | Infinity | Azure | 差 (I−A) | 差的 95% CI | I 高 | A 高 | 平 | 符号检验 p | 结论 |")
            w("|---|---|---|---|---|---|---|---|---|---|---|")
            for dim in DIM_NAME:
                c = (cmp_["views"].get(view, {}).get(dim) or {}).get("overall")
                if not c or not c.get("n"):
                    continue
                verdict = {"A 更高": "Infinity 更高", "B 更高": "Azure 更高"}.get(c["verdict"], c["verdict"])
                w(f"| {DIM_NAME[dim]} | {c['n']} | {pct(c['mean_a'])} | {pct(c['mean_b'])} | "
                  f"{c['diff'] * 100:+.1f} | {ci(c['diff_ci95'])} | {c['a_better']} | {c['b_better']} | "
                  f"{c['tie']} | {c['sign_p']:.4f} | {verdict} |")
            w("")
    else:
        w("| 维度 | n | Infinity | 95% CI |")
        w("|---|---|---|---|")
        for dim in DIM_NAME:
            d = ips.get("dimensions", {}).get(dim) or {}
            if d.get("mean") is not None:
                w(f"| {DIM_NAME[dim]} | {d['n_files_scored']} | {pct(d['mean'])} | {ci(d['ci95'])} |")
        w("")
        w("Azure 侧尚未运行，本节只有单边结果，按约定不解读绝对分数。")
        w("")

    # 3. 分层
    w("## 3. 按分层（主口径）")
    w("")
    w("分层键见 `data/parsebench/manifest.csv` 的 `stratum` 列。配对数不足的分层只列数字，结论写「样本不足」。")
    w("")
    for dim in DIM_NAME:
        if cmp_:
            strata = (cmp_["views"]["both_output"].get(dim) or {}).get("by_stratum") or {}
            if not strata:
                continue
            w(f"**{DIM_NAME[dim]}**")
            w("")
            w("| 分层 | n | Infinity | Azure | 差 (I−A) | 95% CI | p | 结论 |")
            w("|---|---|---|---|---|---|---|---|")
            for s, c in strata.items():
                if not c.get("n"):
                    continue
                verdict = {"A 更高": "Infinity 更高", "B 更高": "Azure 更高"}.get(c["verdict"], c["verdict"])
                w(f"| {s} | {c['n']} | {pct(c['mean_a'])} | {pct(c['mean_b'])} | {c['diff'] * 100:+.1f} | "
                  f"{ci(c['diff_ci95'])} | {c['sign_p']:.4f} | {verdict} |")
            w("")
        else:
            st = (ips.get("dimensions", {}).get(dim) or {}).get("by_stratum") or {}
            if not st:
                continue
            w(f"**{DIM_NAME[dim]}**（仅 Infinity）")
            w("")
            w("| 分层 | n | Infinity | 95% CI |")
            w("|---|---|---|---|")
            for s, c in st.items():
                w(f"| {s} | {c['n']} | {pct(c['mean'])} | {ci(c['ci95'])} |")
            w("")

    # 4. 领域猜测
    w("## 4. 按领域猜测（启发式，只看覆盖面）")
    w("")
    w("`domain_guess` 由文件名关键词推断，数据集本身没有领域字段。**不作领域结论。**"
      "`text_suite` 是文本维度的人工构造集，`unknown` 是文件名为哈希、看不出领域的文件。")
    w("")
    w(f"覆盖：{subset.get('domain_guess', {})}")
    w("")
    if cmp_:
        w("| 维度 | 领域猜测 | n | Infinity | Azure | 差 (I−A) | 结论 |")
        w("|---|---|---|---|---|---|---|")
        for dim in DIM_NAME:
            for d, c in ((cmp_["views"]["both_output"].get(dim) or {}).get("by_domain_guess") or {}).items():
                if c.get("n"):
                    verdict = {"A 更高": "Infinity 更高", "B 更高": "Azure 更高"}.get(c["verdict"], c["verdict"])
                    w(f"| {DIM_NAME[dim]} | {d} | {c['n']} | {pct(c['mean_a'])} | {pct(c['mean_b'])} | "
                      f"{c['diff'] * 100:+.1f} | {verdict} |")
        w("")

    # 5. 参照数字
    w("## 5. 参照数字（并列，不加评论）")
    w("")
    w("下表前两行来自本次 500 份子集；其余来自厂商自报或官方全量 leaderboard（2,078 页）。"
      "样本与构成不同，**不能直接比大小**。")
    w("")
    w("| 来源 | 样本 | " + " | ".join(DIM_NAME.values()) + " | Overall |")
    w("|---|---|" + "---|" * (len(DIM_NAME) + 1))
    for label, ps in (("本次 · Infinity-Parser2 (Flash 2.1，厂商答复)", ips),
                      ("本次 · Azure DI (Layout)", aps)):
        if not ps:
            continue
        vals = [pct((ps.get("dimensions", {}).get(d) or {}).get("mean")) for d in DIM_NAME]
        w(f"| {label} | 500 份子集，全部文件 | " + " | ".join(vals) + " | 不合成 |")
    for name, r in leaderboard().items():
        w(f"| 官方 leaderboard · {name} | 全量 | " + " | ".join(r.get(LB_COL[d], "—") for d in DIM_NAME)
          + f" | {r.get('Overall', '—')} |")
    w("| FinIE 站点 · Infinity-Parser2-Flash | 未说明 | — | — | — | — | — | 72.2 |")
    w("| FinIE 站点 / 技术报告 · Infinity-Parser2-Pro | 未说明 | — | — | — | — | — | 74.3 |")
    w("")

    # 6. 工程观察
    w("## 6. 调用层观察")
    w("")
    w("| 项 | Infinity-Parser2 | Azure DI |")
    w("|---|---|---|")
    w(f"| 调用失败文件 | {len(isumm.get('failed_files', []))} | {len(asumm.get('failed_files', []))} |")
    w(f"| 主调用 finish_reason=length（截断内容仍交判分，与厂商口径一致） | "
      f"{len(isumm.get('length_truncated_files', []))} | 不适用 |")
    w(f"| deep parsing 退回 shallow 的文件 | {len(isumm.get('deep_parsing_fallbacks', []))} | 不适用 |")
    w(f"| 调用次数（按类型） | {isumm.get('n_calls_by_kind', '—')} | 每份 1 次 |")
    w(f"| token（输入 / 输出） | {isumm.get('tokens', {}).get('prompt_tokens', '—')} / "
      f"{isumm.get('tokens', {}).get('completion_tokens', '—')} | 不适用（按页计费，{asumm.get('pages_billed', '—')} 页） |")
    lat = isumm.get("call_latency_s", {})
    w(f"| 单次调用耗时中位数 / P95（秒） | {lat.get('median', '—')} / {lat.get('p95', '—')}（并发 {im.get('concurrency', '—')}） | 见 run 目录 |")
    w("")
    if isumm.get("failed_files") or asumm.get("failed_files"):
        w("失败文件明细见两边 `run_summary.json` 的 `failed_files`。")
        w("")

    w("## 7. 口径声明")
    w("")
    for c in (ips.get("caveats") or []):
        w(f"- {c}")
    w("- Infinity 用 doc2json + deep parsing（厂商 ParseBench 自报分的配置），**不是产品默认的 doc2md**")
    w("- Infinity 的 PDF 用 PyMuPDF 300 DPI 渲染（与 INF SDK 一致），官方 provider 用 pdf2image；像素尺寸可能差 1px")
    w("- Azure 收到原始文件（PDF 保留文本层），Infinity 收到渲染图；若 GT 取自文本层，这一点可能对 Azure 有利")
    w("- Visual Grounding 依赖 bbox：Infinity 的 bbox 是模型生成的坐标 token，Azure 是几何检测")
    w("")
    w("## 8. 复现")
    w("")
    w("```")
    w("python tools/fetch_parsebench.py                     # 同 seed、同 revision 必得同一批 500 份")
    w("python tools/parsebench_runner.py --concurrency 8    # INF")
    w("tools/vendor/.venv-parsebench/bin/python tools/parsebench_azure_runner.py   # Azure（公司电脑）")
    w("tools/vendor/.venv-parsebench/bin/python tools/parsebench_score.py runs/<run> [--pipeline azure_di_layout]")
    w("python tools/parsebench_compare.py <inf>/parsebench_per_file.csv <azure>/parsebench_per_file.csv")
    w("python tools/parsebench_report.py runs/<inf_run> runs/<azure_run>")
    w("```")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
