#!/usr/bin/env python3
"""
断言人工审核页生成器 (T3 后半段)

生成**本地** HTML 审核页：左边页面图，右边草稿断言，逐条通过/改/删。
不联网、不上传，图与断言都内嵌在文件里，双击即可在浏览器打开。

为什么必须对着页面图核对：PDF 文本层的数字不等于版面上的数字——
可能顺序错乱、跨列拼接、两栏数字被连在一起。脚本抽错而人没看出来，
错的就是 GT 本身。所以 draft 断言一律要人眼过。

审核结果存在浏览器 localStorage，点「导出 JSON」下载，然后：
  python tools/apply_review.py ~/Downloads/review_<doc_id>.json

用法:
  python tools/review_assertions.py              # 全部文档
  python tools/review_assertions.py --doc-id x   # 单份
  python tools/review_assertions.py --dpi 140    # 图更清晰但文件更大
"""

import argparse
import base64
import html
import io
import json
from pathlib import Path

import pymupdf
import yaml

ASSERT_DIR = Path("data/assertions")
OUT = Path("review")

PAGE_TPL = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>断言审核 · {doc_id}</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --mut:#666; --line:#e0e0e0; --accent:#2563eb;
         --ok:#15803d; --no:#b91c1c; --draft:#b45309; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#141414; --fg:#eee; --mut:#999; --line:#333; --accent:#60a5fa;
  --ok:#4ade80; --no:#f87171; --draft:#fbbf24; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.6 -apple-system,
        "PingFang SC","Microsoft YaHei",sans-serif; }}
header {{ position:sticky; top:0; z-index:5; background:var(--bg);
          border-bottom:1px solid var(--line); padding:10px 16px;
          display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
h1 {{ font-size:15px; margin:0; font-weight:600; }}
.meta {{ color:var(--mut); font-size:12px; }}
button {{ font:inherit; padding:4px 10px; border:1px solid var(--line);
          background:transparent; color:var(--fg); border-radius:5px; cursor:pointer; }}
button:hover {{ border-color:var(--accent); }}
button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
.page {{ display:grid; grid-template-columns: minmax(0,1.1fr) minmax(0,1fr);
         gap:16px; padding:16px; border-bottom:2px solid var(--line); }}
@media (max-width: 900px) {{ .page {{ grid-template-columns:1fr; }} }}
.page img {{ width:100%; border:1px solid var(--line); border-radius:4px; }}
.sticky {{ position:sticky; top:52px; align-self:start; }}
.a {{ border:1px solid var(--line); border-left-width:4px; border-radius:5px;
      padding:8px 10px; margin-bottom:8px; }}
.a.draft {{ border-left-color:var(--draft); }}
.a.auto  {{ border-left-color:var(--mut); opacity:.65; }}
.a.confirmed {{ border-left-color:var(--ok); }}
.a.rejected  {{ border-left-color:var(--no); opacity:.45; }}
.t {{ font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; word-break:break-all; }}
.ctx {{ color:var(--mut); font-size:12px; margin-top:3px; }}
.row {{ display:flex; gap:6px; margin-top:6px; align-items:center; flex-wrap:wrap; }}
input[type=text] {{ font:13px ui-monospace,Menlo,monospace; padding:3px 6px; flex:1;
   min-width:140px; background:transparent; color:var(--fg);
   border:1px solid var(--line); border-radius:4px; }}
.tag {{ font-size:11px; color:var(--mut); border:1px solid var(--line);
        border-radius:3px; padding:0 5px; }}
#bar {{ font-size:12px; color:var(--mut); }}
</style></head><body>
<header>
  <h1>{doc_id}</h1>
  <span class="meta">{family} · {window} · 披露 {disclosed_at}</span>
  <span id="bar"></span>
  <button class="primary" onclick="exportAll()">导出全部</button>
  <button onclick="exportJSON()">仅导出本篇</button>
  <button onclick="confirmAllVisible()">全部通过</button>
  <span class="meta">仅 draft 需要处理；auto 类为自动生成，只读</span>
</header>
{pages}
<script>
const DOC_ID = {doc_id_json};
const KEY = "review:" + DOC_ID;

// file:// 下部分浏览器（Safari 尤其）会拒绝 localStorage 并抛异常。
// 不兜住的话整页按钮全失效，所以失败时退回内存态并提示——
// 内存态关页面就丢，必须当场导出。
let LS_OK = true;
function lsGet(k) {{ try {{ return localStorage.getItem(k); }} catch (e) {{ LS_OK = false; return null; }} }}
function lsSet(k, v) {{ try {{ localStorage.setItem(k, v); }} catch (e) {{ LS_OK = false; }} }}
function lsKeys() {{ try {{ return Object.keys(localStorage); }} catch (e) {{ LS_OK = false; return []; }} }}

let state = JSON.parse(lsGet(KEY) || "{{}}");

function render(id) {{
  const el = document.getElementById("a_" + id);
  if (!el) return;
  const s = state[id];
  el.classList.remove("confirmed", "rejected");
  if (s && s.status) el.classList.add(s.status);
}}
function setStatus(id, status) {{
  const inp = document.getElementById("t_" + id);
  state[id] = {{status: status, target: inp ? inp.value : null}};
  lsSet(KEY, JSON.stringify(state));
  render(id); bar();
}}
function confirmAllVisible() {{
  if (!confirm("把本页所有未处理的 draft 标为通过？请确认你已逐条看过。")) return;
  document.querySelectorAll(".a.draft").forEach(el => {{
    const id = el.dataset.id;
    if (!state[id]) setStatus(id, "confirmed");
  }});
}}
function bar() {{
  const total = document.querySelectorAll(".a.draft").length;
  const done = Object.keys(state).length;
  document.getElementById("bar").textContent =
    "草稿 " + total + " 条，已处理 " + done + " 条";
}}
function download(name, obj) {{
  const blob = new Blob([JSON.stringify(obj, null, 1)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
}}
function exportJSON() {{
  download("review_" + DOC_ID + ".json",
           {{doc_id: DOC_ID, reviewed_at: new Date().toISOString(), decisions: state}});
}}
function exportAll() {{
  // 把所有已审文档汇成一个文件，省掉 53 次下载。
  // 同源前提：全部页面都用 file:// 打开，或都用同一个本地服务打开，不要混用。
  const docs = {{}};
  lsKeys().filter(k => k.indexOf("review:") === 0).forEach(k => {{
    try {{ docs[k.slice(7)] = JSON.parse(lsGet(k) || "{{}}"); }} catch (e) {{}}
  }});
  docs[DOC_ID] = state;
  const n = Object.values(docs).reduce((a, d) => a + Object.keys(d).length, 0);
  if (!confirm("导出 " + Object.keys(docs).length + " 份文档、共 " + n + " 条决定？")) return;
  download("review_all.json", {{reviewed_at: new Date().toISOString(), docs: docs}});
}}
Object.keys(state).forEach(render); bar();
if (!LS_OK) {{
  const w = document.createElement("div");
  w.style.cssText = "background:#b45309;color:#fff;padding:6px 16px;font-size:13px";
  w.textContent = "浏览器拒绝了本地存储：审核结果只存在内存里，关闭页面即丢失。"
    + "请在离开本页前点「仅导出本篇」，或改用 Chrome，或用本地服务打开"
    + "（python -m http.server 8765）。";
  document.body.insertBefore(w, document.body.firstChild);
}}
</script></body></html>"""


def render_assertion(a):
    aid = a["id"]
    status = a.get("status", "draft")
    esc = html.escape
    if status == "auto" or (status == "auto_textlayer" and not a.get("_audit")):
        return (f'<div class="a auto" data-id="{esc(aid)}">'
                f'<span class="tag">{esc(a["type"])}</span> '
                f'<span class="tag">自动</span>'
                f'<div class="t">{esc(str(a.get("target", "")))}</div></div>')
    ctx = a.get("context")
    forbid = a.get("forbid") or []
    audit = status == "auto_textlayer"
    return (
        f'<div class="a draft" id="a_{esc(aid)}" data-id="{esc(aid)}">'
        f'<span class="tag">{esc(a["type"])}</span> '
        f'<span class="tag">{esc(a.get("severity", ""))}</span>'
        + ('<span class="tag">审计抽样</span>' if audit else "")
        + (f'<div class="ctx">科目：<b>{esc(str(a["label"]))}</b>'
           f'　要求与金额同行（间距 ≤ {a.get("max_gap", 120)}）</div>'
           if a.get("label") else "")
        + f'<div class="row"><input type="text" id="t_{esc(aid)}" '
          f'value="{esc(str(a.get("target", "")))}"></div>'
        + (f'<div class="ctx">上下文：{esc(ctx)}</div>' if ctx else "")
        + (f'<div class="ctx">禁止串：{esc(", ".join(forbid))}</div>' if forbid else "")
        + f'<div class="row">'
          f'<button onclick="setStatus(\'{esc(aid)}\',\'confirmed\')">通过</button>'
          f'<button onclick="setStatus(\'{esc(aid)}\',\'rejected\')">删除</button>'
          f'</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", action="append")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--audit", type=int, default=0,
                    help="额外抽 N 条 auto_textlayer 断言进审核页，用于估计文本层 GT 的错误率")
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    files = sorted(ASSERT_DIR.glob("*.yaml"))

    # 审计抽样：文本层派生的 GT 也可能错，抽一小批人工复核以给出错误率上界。
    # 固定 seed，报告附录要能复现抽了哪些。
    audit_ids = set()
    if a.audit:
        import random
        pool = []
        for f in files:
            d0 = yaml.safe_load(f.read_text(encoding="utf-8"))
            pool += [i["id"] for i in d0["assertions"]
                     if i.get("status") == "auto_textlayer"]
        audit_ids = set(random.Random(20260921).sample(pool, min(a.audit, len(pool))))
        print(f"审计抽样 {len(audit_ids)} 条（从 {len(pool)} 条文本层派生断言中）")
    index = []
    for f in files:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        if a.doc_id and d["doc_id"] not in a.doc_id:
            continue
        doc = pymupdf.open(d["local_path"])
        by_page = {}
        for it in d["assertions"]:
            if it["id"] in audit_ids:
                it["_audit"] = True
            by_page.setdefault(it["page"], []).append(it)

        blocks = []
        for page_no in sorted(by_page):
            pix = doc[page_no - 1].get_pixmap(dpi=a.dpi)
            b64 = base64.b64encode(pix.tobytes("png")).decode()
            items = sorted(by_page[page_no],
                           key=lambda x: (not (x.get("status") == "draft"
                                               or x.get("_audit")), x["type"]))
            blocks.append(
                f'<section class="page"><div><div class="meta">第 {page_no} 页</div>'
                f'<img src="data:image/png;base64,{b64}" alt="第 {page_no} 页"></div>'
                f'<div class="sticky">' + "".join(render_assertion(i) for i in items)
                + "</div></section>")
        doc.close()

        out = OUT / f"{d['doc_id']}.html"
        out.write_text(PAGE_TPL.format(
            doc_id=html.escape(d["doc_id"]), doc_id_json=json.dumps(d["doc_id"]),
            family=html.escape(d["family"]), window=html.escape(d["window"]),
            disclosed_at=html.escape(str(d["disclosed_at"])),
            pages="".join(blocks)), encoding="utf-8")
        n_draft = sum(1 for i in d["assertions"]
                      if i.get("status") == "draft" or i.get("_audit"))
        index.append((d["doc_id"], d["family"], d["window"], n_draft,
                      len(d["assertions"]), out.name, out.stat().st_size))
        print(f"  {d['doc_id']:44} draft {n_draft:3} / {len(d['assertions']):3} "
              f"{out.stat().st_size/1e6:5.1f}MB")

    rows = "".join(
        f'<tr><td><a href="{html.escape(fn)}">{html.escape(did)}</a></td>'
        f"<td>{html.escape(fam)}</td><td>{html.escape(win)}</td>"
        f"<td style='text-align:right'>{nd}</td>"
        f"<td style='text-align:right'>{na}</td></tr>"
        for did, fam, win, nd, na, fn, _ in sorted(index))
    (OUT / "index.html").write_text(
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<title>断言审核索引</title><style>"
        "body{font:14px/1.6 -apple-system,'PingFang SC',sans-serif;max-width:900px;"
        "margin:40px auto;padding:0 16px;}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left}"
        "@media(prefers-color-scheme:dark){body{background:#141414;color:#eee}"
        "td,th{border-color:#333}a{color:#60a5fa}}</style></head><body>"
        f"<h1>断言审核</h1><p>共 {len(index)} 份文档，"
        f"待核对草稿 {sum(r[3] for r in index)} 条。"
        "逐份打开、逐条核对、导出 JSON，然后 <code>python tools/apply_review.py &lt;json&gt;</code></p>"
        "<table><tr><th>文档</th><th>族</th><th>窗口</th><th>草稿</th><th>总断言</th></tr>"
        + rows + "</table></body></html>", encoding="utf-8")
    print(f"\n-> {OUT}/index.html  （{len(index)} 份，草稿 {sum(r[3] for r in index)} 条）")


if __name__ == "__main__":
    main()
