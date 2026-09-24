"""
生成 docs/briefing-deck.pptx：briefing-deck.html 的 PPTX 版本。
内容与 HTML 版一致，全部为可编辑的原生形状与表格，字体微软雅黑。

改数字时两边都要改：本脚本与 docs/briefing-deck.html。

依赖 python-pptx（不在 requirements.txt 里，只有生成幻灯片时需要）:
  uv pip install python-pptx
用法:
  python tools/make_briefing_pptx.py docs/briefing-deck.pptx
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

FONT = "Microsoft YaHei"
C = {k: RGBColor.from_string(v) for k, v in dict(
    ink="1B2430", muted="5B6675", line="DDE3EA", navy="16324F", paper="FFFFFF",
    go="1F7A4D", go_bg="E4F4EA", no="B3261E", no_bg="FBE7E5", warn="9A6700",
    warn_bg="FFF4D6", gray_bg="EEF0F3", lede_bg="F5F8FB", th_bg="F7F9FB",
    inf="3D6FB6", az="8A94A3", track="F0F2F5", alert_bg="FFFAFA").items()}

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
L, R = 0.55, 13.333 - 0.55
W = R - L


def set_font(run, size, color="ink", bold=False):
    f = run.font
    f.size, f.bold, f.name = Pt(size), bold, FONT
    f.color.rgb = C[color]
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", FONT)


def fill_tf(tf, paras, size, color="ink", align=None, spacing=None):
    """paras: list of paragraphs; each paragraph is str or list of (text, bold[, color[, url]])."""
    tf.word_wrap = True
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            para.alignment = align
        if spacing:
            para.space_after = Pt(spacing)
        for seg in ([(p, False)] if isinstance(p, str) else p):
            r = para.add_run()
            r.text = seg[0]
            set_font(r, size, seg[2] if len(seg) > 2 else color, seg[1])
            if len(seg) > 3:
                r.hyperlink.address = seg[3]
                set_font(r, size, seg[2], seg[1])  # hyperlink 会重置颜色，重设一次


def text(slide, x, y, w, h, paras, size, color="ink", align=None, anchor=MSO_ANCHOR.TOP,
         spacing=None, margin=0.0):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor
    fill_tf(tf, paras, size, color, align, spacing)
    return tb


def rect(slide, x, y, w, h, fill=None, line=None, lw=0.75, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.04
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = C[fill]
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = C[line]
        s.line.width = Pt(lw)
    s.shadow.inherit = False
    return s


def card(slide, x, y, w, h, line="line", fill="paper", lw=0.75):
    return rect(slide, x, y, w, h, fill, line, lw, MSO_SHAPE.ROUNDED_RECTANGLE)


def table(slide, x, y, widths, rows, size=11, head_size=10, row_h=0.36, fills=None, colors=None, bolds=None):
    """rows[0] 为表头。fills/colors/bolds: {(r,c): key}"""
    fills, colors, bolds = fills or {}, colors or {}, bolds or {}
    shp = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y),
                                 Inches(sum(widths)), Inches(row_h * len(rows)))
    tbl = shp.table
    tblPr = tbl._tbl.tblPr
    for attr in ("bandRow", "firstRow"):
        tblPr.set(attr, "0")
    style = tblPr.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # No Style, Table Grid
    for ci, w in enumerate(widths):
        tbl.columns[ci].width = Inches(w)
    for ri, row in enumerate(rows):
        tbl.rows[ri].height = Inches(row_h)
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            key = fills.get((ri, ci), "th_bg" if ri == 0 else "paper")
            cell.fill.solid()
            cell.fill.fore_color.rgb = C[key]
            tf = cell.text_frame
            tf.text = ""
            is_head = ri == 0
            fill_tf(tf, [val], head_size if is_head else size,
                    colors.get((ri, ci), "muted" if is_head else "ink"))
            if is_head or bolds.get((ri, ci)):
                for p in tf.paragraphs:
                    for r in p.runs:
                        r.font.bold = True
            set_borders(cell)
    return shp


def set_borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln = tcPr.find(qn(tag))
        if ln is not None:
            tcPr.remove(ln)
        ln = tcPr.makeelement(qn(tag), {"w": "0" if tag in ("a:lnL", "a:lnR") else "9525"})
        if tag in ("a:lnL", "a:lnR"):
            ln.append(ln.makeelement(qn("a:noFill"), {}))
        else:
            sf = ln.makeelement(qn("a:solidFill"), {})
            clr = sf.makeelement(qn("a:srgbClr"), {"val": "DDE3EA"})
            sf.append(clr)
            ln.append(sf)
        tcPr.append(ln)


def header(slide, kicker, title, page):
    text(slide, L, 0.32, W, 0.3, [kicker], 11, "muted")
    text(slide, L, 0.58, W, 0.6, [[(title, True, "navy")]], 26)
    text(slide, L, 7.08, W - 1, 0.3, [FOOT[page]], 9, "muted")
    text(slide, R - 1, 7.08, 1, 0.3, [f"{page} / 4"], 9, "muted", align=PP_ALIGN.RIGHT)


# 每页只引用一个出处文件：测试数据看 test-results.md，分析看 evaluation-report.md
DOCS = "https://github.com/gejun2008/doc-parser-eval/blob/v1.0-report/docs/"
TR = ("test-results.md", False, "inf", DOCS + "test-results.md")
ER = ("evaluation-report.md", False, "inf", DOCS + "evaluation-report.md")
FOOT = {
    1: [("样本：53 份公开披露文档 → 210 页 → 1,229 条断言；配对页 191 页（Azure 19 页因网关超时失败）　·　出处：", False), ER],
    2: [("检验方法：McNemar 配对检验；不合成总分；n < 30 的分层不下结论　·　出处：", False), TR],
    3: [("出处：", False), ER],
    4: [("出处：", False), TR, ("　·　", False), ER],
}

# ---------------- 第 1 页 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "INFINITY-PARSER2 vs AZURE DOCUMENT INTELLIGENCE · 技术评估简报 · 2026-09-24",
       "文档类型适用性对比：Azure DI vs Infinity-Parser2", 1)
rect(s, L, 1.22, W, 0.78, "lede_bg")
rect(s, L, 1.22, 0.06, 0.78, "navy")
text(s, L + 0.2, 1.27, W - 0.3, 0.7, [[
    ("一句话：解析质量上 Azure 每项都持平或更好", True),
    ("。港股披露文件、A 股公告的关键字段没看到差异，可以进 POC；但 A 股年报、中报「页首是续表」的页，Infinity 会", False),
    ("静默丢掉整段表格", True), ("。它还", False), ("不提供置信度", True), ("、", False), ("只收 PDF 和图片", True),
    ("。替代理由只能来自成本或私有化部署。", False)]], 13, anchor=MSO_ANCHOR.MIDDLE)

text(s, L, 2.12, 4, 0.3, [[("支持的文件格式", True, "navy")]], 13)
Y, G, N = "✓", "go", "no"
table(s, L, 2.45, [2.0, 1.1, 4.2, 2.0, 1.1, 1.83], [
    ["", "PDF", "图片", "Office（Word / Excel / PPT）", "HTML", "备注"],
    ["Azure DI", "✓", "✓  JPG · PNG · BMP · TIFF · HEIF", "✓", "✓", ""],
    ["Infinity-Parser2", "✓", "✓  PNG · JPG · BMP · TIFF · WEBP", "✗", "✗", "Office 须先转 PDF / 图片"],
], size=11, head_size=10, row_h=0.32,
    fills={(1, 1): G + "_bg", (1, 2): G + "_bg", (1, 3): G + "_bg", (1, 4): G + "_bg",
           (2, 1): G + "_bg", (2, 2): G + "_bg", (2, 3): N + "_bg", (2, 4): N + "_bg"},
    colors={(1, 1): G, (1, 2): G, (1, 3): G, (1, 4): G, (2, 1): G, (2, 2): G, (2, 3): N, (2, 4): N,
            (2, 5): "muted"},
    bolds={(1, 0): True, (2, 0): True})

status = [
    ("港股年报 / 中报 / 招股书", "可替代候选 · 进 POC", "go", "金额、科目归属断言两边都没有失败；分族的正文完整性待第三轮"),
    ("A 股临时公告", "可替代候选 · 进 POC", "go", "金额断言两边都没有失败；第一轮 Infinity 的领先已查明是标点造成的"),
    ("A 股年报 / 中报（报表附注页）", "现阶段不可替代", "no", "Infinity 3 页确定性丢表（共 27 个金额），都在页首续表页，没有报错；Azure 也缺了 6 个，原因待查"),
    ("需要按置信度分流复核的流程", "不可替代（结构性）", "no", "API 不返回任何置信度，请求 logprobs 会被静默忽略"),
    ("港股 KYC 类文件", "证据不足", "warn", "只有 39 条正文完整性断言，没有金额断言"),
    ("扫描件 / 倾斜件", "未与 Azure 对照", "warn", "仅测了 Infinity：倾斜 2° 的页出现无限复读，打满 32k token，输出作废"),
    ("贸易金融单证", "未覆盖", "gray", "没有合规的公开样本，现有结论不能外推"),
]
rows = [["文档类型（PDF）", "判断", "依据（同一批页配对比较）"]]
fills, colors = {}, {}
for i, (a, b, k, c) in enumerate(status, 1):
    rows.append([a, b, c])
    fills[(i, 1)] = k + "_bg" if k != "gray" else "gray_bg"
    colors[(i, 1)] = k if k != "gray" else "muted"
table(s, L, 3.78, [3.0, 2.2, W - 5.2], rows, size=11.5, head_size=10, row_h=0.38,
      fills=fills, colors=colors, bolds={(i, 1): True for i in range(1, 8)})

# ---------------- 第 2 页 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "Azure 在各项指标上持平或更好 · 同一批 191 页、同一套断言配对比较",
       "解析质量对比：Azure DI vs Infinity-Parser2", 2)
LW = 6.75
text(s, L, 1.2, 3, 0.3, [[("断言通过率", True, "navy")]], 13)
rect(s, L + 1.35, 1.3, 0.13, 0.13, "inf"); text(s, L + 1.52, 1.23, 1, 0.3, ["Infinity"], 10, "muted")
rect(s, L + 2.3, 1.3, 0.13, 0.13, "az"); text(s, L + 2.47, 1.23, 1, 0.3, ["Azure DI"], 10, "muted")

metrics = [
    ("金额", "数值是否原样出现、出现次数是否正确 · n = 486", 97.5, 100.0,
     [("差异显著（0 : 12，p = 0.0005）。Infinity 的 12 条失败逐条核对后：", False, "muted"),
      ("8 条是真实遗漏", True, "ink"), ("，另外 4 条只是减号字形不同。", False, "muted")]),
    ("正文完整性", "每页抽 3 行正文，查是否原样输出 · n = 448", 93.1, 97.1,
     [("差异显著（2 : 20，p = 0.0001）。", False, "muted"),
      ("第一轮的 91.3% 对 72.5% 作废", True, "ink"), ("：那是 Azure 把全角标点转成半角造成的。", False, "muted")]),
    ("单位与币种", "表头「单位：元」等是否保留 · n = 93", 98.9, 100.0,
     [("未观察到显著差异（0 : 1）。金额与科目同行（n = 76）：Infinity 100%，Azure 98.7%，同样未观察到显著差异。", False, "muted")]),
]
y = 1.62
for name, sub, a, b, note in metrics:
    h = 1.72
    card(s, L, y, LW, h)
    text(s, L + 0.18, y + 0.1, LW - 0.3, 0.3, [[(name, True), ("  · " + sub, False, "muted")]], 11.5)
    for j, (lab, v, key) in enumerate((("Infinity", a, "inf"), ("Azure DI", b, "az"))):
        by = y + 0.5 + j * 0.34
        text(s, L + 0.18, by - 0.05, 1.3, 0.28, [lab], 11)
        bx, bw = L + 1.4, LW - 2.45
        rect(s, bx, by, bw, 0.17, "track")
        rect(s, bx, by, bw * v / 100, 0.17, key)
        text(s, bx + bw + 0.1, by - 0.05, 0.8, 0.28, [f"{v:g}%"], 11)
    text(s, L + 0.18, y + 1.18, LW - 0.36, 0.5, [note], 10)
    y += h + 0.13

RX = L + LW + 0.35
RW = R - RX
card(s, RX, 1.2, RW, 2.72, "no", "alert_bg", 1.5)
text(s, RX + 0.2, 1.3, RW - 0.4, 0.3, [[("全量金额扫描：两边都会缺，性质不同", True, "no")]], 13)
text(s, RX + 0.2, 1.62, RW - 0.4, 0.25, ["配对 54 页 A 股金额页，1,544 个金额"], 9.5, "muted")
for i, (big, small, col) in enumerate((("11 个", "Infinity 缺失 · 2 页", "no"), ("6 个", "Azure 缺失 · 2 页", "ink"))):
    bx = RX + 0.2 + i * 2.0
    text(s, bx, 1.85, 1.9, 0.5, [[(big, True, col)]], 28)
    text(s, bx, 2.38, 1.9, 0.3, [small], 9.5, "muted")
text(s, RX + 0.2, 2.72, RW - 0.4, 1.2, [
    [("• ", False), ("Infinity 已查实", True), ("：页首续表整段没输出；调用照常正常结束，重复 3 次缺的完全一样", False)],
    [("• 配对集外还有一页：", False), ("整张 16 个金额的表", True), ("不见了（Azure 该页网关失败）", False)],
    "• Azure 缺的 6 个原因待查（第三轮）；页级比较未观察到显著差异",
], 10.5, spacing=2)

card(s, RX, 4.07, RW, 2.9)
text(s, RX + 0.2, 4.15, RW - 0.4, 0.3, [[("服务与成本", True, "navy"), ("（只作参考，两边口径不同，不比优劣）", False, "muted")]], 12)
table(s, RX + 0.2, 4.52, [1.0, 2.0, RW - 0.4 - 3.0], [
    ["", "Infinity（测试端点）", "Azure DI（公司网关）"],
    ["成功率", "210 / 210", "191 / 210"],
    ["延迟 P50", "22.5 s（并发 2）", "17 s（并发 4，含轮询）"],
    ["吞吐", "1.6–5.6 页/分，并发无效", "—"],
    ["价格", "未报价", "牌价 $10 / 千页"],
], size=10, head_size=9.5, row_h=0.3)
text(s, RX + 0.2, 6.3, RW - 0.4, 0.6, [[
    ("每页约 9.6k token。若按 token 计费，输入单价要低于 ", False, "muted"),
    ("≈ $1.13 / 百万 token", True), (" 才能与 Azure 牌价持平。", False, "muted")]], 10)

# ---------------- 第 3 页 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "OCR 出错时会报不确定，VLM 出错时照常交付 · 下一步：POC 范围与退出标准", "技术路线对比：Azure DI（OCR 流水线）vs Infinity-Parser2（VLM）", 3)
cmp_rows = [
    ["", "Infinity-Parser2", "Azure DI（prebuilt-layout）"],
    ["技术路线", "视觉语言模型（VLM），一次生成整页 markdown", "OCR + 版面分析流水线"],
    ["支持格式", "仅 PDF 与图片", "PDF、图片、Office、HTML"],
    ["输入", "整页渲染成 300 DPI 图像，逐页独立处理", "PDF（本次为单页 PDF）"],
    ["置信度", "无", "每个文本片段都有"],
    ["确定性", "同一页调用 3 次，99.0% 逐字相同（金额零变化）", "确定性"],
    ["标点", "保留原文全角", "全角转半角，下游需要归一化"],
    ["认不出时", "可能漏掉或生成内容，调用照常正常结束", "给低置信度或留空"],
    ["特有失败", "无限复读、打满 token 上限（观测到 2 次）", "—"],
    ["坐标框", "由模型生成", "几何检测得出"],
    ["版本", "只看得到别名 inf-mllm，型号与版本不可知", "有 API 版本号，可指定"],
    ["模型", "开源权重（Apache-2.0）；自称基于 Qwen3.5（待证实）", "闭源托管服务"],
]
TW = 7.35
table(s, L, 1.3, [1.25, 3.55, TW - 4.8], cmp_rows, size=11, head_size=10, row_h=0.44,
      fills={(4, 1): "no_bg", (4, 2): "go_bg", (2, 1): "no_bg", (2, 2): "go_bg"},
      colors={(4, 1): "no", (4, 2): "go", (2, 1): "no", (2, 2): "go"},
      bolds={(4, 1): True, (4, 2): True, (2, 1): True, (2, 2): True})

RX = L + TW + 0.35
RW = R - RX
card(s, RX, 1.3, RW, 3.2)
text(s, RX + 0.2, 1.4, RW - 0.4, 0.3, [[("POC 建议范围", True, "navy")]], 13)
text(s, RX + 0.2, 1.75, RW - 0.4, 2.7, [
    [("• ", False), ("先决条件：有成本或私有化部署上的动因", True), ("，解析质量本身不构成动因", False)],
    "• 港股年报、中报、招股书 + A 股公告，只用电子版 PDF，每族 ≥ 300 页",
    [("• ", False), ("定向测试 ≥ 50 页「页首续表」", True), ("，测丢表的发生频率", False)],
    "• 强制护栏：金额与 PDF 文本层逐个对账；finish_reason=length 一律转人工",
    "• 开测前厂商须答复：型号与版本锁定、计费方式、置信度、生产 SLA",
], 11.5, spacing=5)
card(s, RX, 4.65, RW, 2.25)
text(s, RX + 0.2, 4.75, RW - 0.4, 0.3, [[("退出标准（任一触发即停）", True, "navy")]], 13)
text(s, RX + 0.2, 5.12, RW - 0.4, 1.75, [
    "• 丢失或替换金额的页，显著多于 Azure",
    "• 不能锁定版本，也不承诺变更前通知",
    "• 按合同价计入人工复核后，单页成本高于 Azure",
    "• 生产吞吐达不到业务峰值；复读退化率超过阈值",
], 11.5, spacing=5)

# ---------------- 第 4 页：总结 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "结论 · 详细 · 方法 · 数据集", "评测总结", 4)
summary = [
    ["", ""],
    ["结论", [("Azure 在", False), ("金额", True), ("、", False), ("正文完整性", True), ("两项上显著更好，", False),
             ("单位币种", True), ("、", False), ("金额科目归属", True), ("两项差异不显著，没有一项 Infinity 更好。"
             "Infinity 另有两个结构性缺陷：", False), ("不返回置信度", True), ("；页首是续表的页会", False), ("静默丢表", True), ("。", False)]],
    ["详细", "测试结果数据：参考 test-results.md；分析报告查询信息：参考 evaluation-report.md"],
    ["方法", "两边都通过调用 API 解析同一批页，各自输出 markdown，我方不做转换；输出与同一套 GT（断言）逐条比对，"
             "只比两边都成功的页，用配对检验判断差异是否显著，不合成总分。"],
    ["数据集", "自建金融集：53 份公开披露文档（巨潮资讯网、HKEX 披露易）→ 210 页 → 1,229 条断言，配对 191 页。"
               "GT 以 PDF 文本层自动提取为主，76 条科目归属人工逐条确认。公共基准 olmOCR-Bench：跑了 41 页。"],
]
shp = table(s, L, 1.3, [1.3, W - 1.3], summary, size=13, head_size=6, row_h=0.9,
            fills={(i, 0): "lede_bg" for i in range(1, 5)}, colors={(i, 0): "navy" for i in range(1, 5)},
            bolds={(i, 0): True for i in range(1, 5)})
tbl = shp.table._tbl
tbl.remove(tbl.tr_lst[0])  # table() 默认首行是表头，这一页不需要
heights = (0.95, 0.6, 0.95, 0.95)
for i, h in enumerate(heights):
    shp.table.rows[i].height = Inches(h)
shp.height = Inches(sum(heights))
for i, (doc, desc) in enumerate((
        (TR, "测试集与测试结果：测试集构成、GT 来源、各项指标与逐条失败明细、服务数据、数字出处"),
        (ER, "分析报告：结论与依据、按文档类型的判断、结构性差异、POC 范围与退出标准、评测方法（附录 C）"))):
    cx = L + i * (W / 2 + 0.1)
    card(s, cx, 5.2, W / 2 - 0.1, 1.1)
    text(s, cx + 0.2, 5.3, W / 2 - 0.5, 0.3, [[(doc[0], True, "inf", doc[3])]], 13)
    text(s, cx + 0.2, 5.68, W / 2 - 0.5, 0.55, [desc], 10.5, "muted")

prs.save(sys.argv[1])
print("saved", sys.argv[1])
