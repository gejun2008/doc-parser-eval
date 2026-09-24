"""
Generate docs/en/briefing-deck.pptx: the English version of docs/en/briefing-deck.html.
Same layout helpers as tools/make_briefing_pptx.py (Chinese version); only the text differs.

When numbers change, update both languages: tools/make_briefing_pptx.py, this script,
docs/briefing-deck.html and docs/en/briefing-deck.html.

Requires python-pptx (not in requirements.txt; only needed to build the slides):
  uv pip install python-pptx
Usage:
  python tools/make_briefing_pptx_en.py docs/en/briefing-deck.pptx
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

FONT = "Calibri"
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


# One source file per slide: test-results.md for data, evaluation-report.md for analysis
DOCS = "https://github.com/gejun2008/doc-parser-eval/blob/v1.1-report/docs/en/"
TR = ("test-results.md", False, "inf", DOCS + "test-results.md")
ER = ("evaluation-report.md", False, "inf", DOCS + "evaluation-report.md")
FOOT = {
    1: [("Sample: 53 public disclosure documents → 210 pages → 1,229 assertions; 191 paired pages "
         "(19 Azure pages failed on gateway timeouts)  ·  Source: ", False), ER],
    2: [("Test: McNemar paired test; no composite score; no conclusion for strata with n < 30  ·  Source: ", False), TR],
    3: [("Source: ", False), ER],
    4: [("Sources: ", False), TR, ("  ·  ", False), ER],
}

# ---------------- Slide 1 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "INFINITY-PARSER2 vs AZURE DOCUMENT INTELLIGENCE · TECHNICAL EVALUATION BRIEF · 2026-09-24",
       "Document Type Suitability: Azure DI vs Infinity-Parser2", 1)
rect(s, L, 1.22, W, 0.78, "lede_bg")
rect(s, L, 1.22, 0.06, 0.78, "navy")
text(s, L + 0.2, 1.25, W - 0.3, 0.74, [[
    ("In one sentence: on parsing quality Azure is equal or better on every metric.", True),
    (" No difference on key fields in HK disclosures and A-share announcements, so these can enter a POC; "
     "but on A-share annual / interim pages that start with a continuation table, Infinity ", False),
    ("silently drops the whole table segment", True), (". It also ", False), ("provides no confidence", True),
    (" and ", False), ("accepts only PDF and images", True),
    (". A reason to switch can only come from cost or on-premise deployment.", False)]], 12, anchor=MSO_ANCHOR.MIDDLE)

text(s, L, 2.12, 4, 0.3, [[("Supported file formats", True, "navy")]], 13)
G, N = "go", "no"
table(s, L, 2.45, [2.0, 1.0, 4.1, 2.1, 1.0, 2.03], [
    ["", "PDF", "Images", "Office (Word / Excel / PPT)", "HTML", "Note"],
    ["Azure DI", "✓", "✓  JPG · PNG · BMP · TIFF · HEIF", "✓", "✓", ""],
    ["Infinity-Parser2", "✓", "✓  PNG · JPG · BMP · TIFF · WEBP", "✗", "✗", "Office → PDF / image first"],
], size=11, head_size=10, row_h=0.32,
    fills={(1, 1): G + "_bg", (1, 2): G + "_bg", (1, 3): G + "_bg", (1, 4): G + "_bg",
           (2, 1): G + "_bg", (2, 2): G + "_bg", (2, 3): N + "_bg", (2, 4): N + "_bg"},
    colors={(1, 1): G, (1, 2): G, (1, 3): G, (1, 4): G, (2, 1): G, (2, 2): G, (2, 3): N, (2, 4): N,
            (2, 5): "muted"},
    bolds={(1, 0): True, (2, 0): True})

status = [
    ("HK annual / interim reports / prospectuses", "Candidate · enter POC", "go",
     "Neither system failed any amount or label assertion; per-family text completeness awaits round 3"),
    ("A-share ad-hoc announcements", "Candidate · enter POC", "go",
     "Neither system failed any amount assertion; Infinity's round-1 lead was traced to punctuation"),
    ("A-share annual / interim (statements & notes)", "Not replaceable yet", "no",
     "Infinity dropped tables on 3 pages (27 amounts), all continuation pages, no error; Azure also missed 6, cause unknown"),
    ("Workflows routing review by confidence", "Not replaceable (structural)", "no",
     "The API returns no confidence; a logprobs request is silently ignored"),
    ("HK KYC-type documents", "Insufficient evidence", "warn", "Only 39 text-completeness assertions, no amount assertions"),
    ("Scanned / skewed pages", "Not compared with Azure", "warn",
     "Infinity only: a page skewed by 2° fell into endless repetition, hit 32k tokens, output unusable"),
    ("Trade-finance documents", "Not covered", "gray", "No compliant public samples; conclusions cannot be extrapolated"),
]
rows = [["Document type (PDF)", "Judgement", "Evidence (same pages, paired comparison)"]]
fills, colors = {}, {}
for i, (a, b, k, c) in enumerate(status, 1):
    rows.append([a, b, c])
    fills[(i, 1)] = k + "_bg" if k != "gray" else "gray_bg"
    colors[(i, 1)] = k if k != "gray" else "muted"
table(s, L, 3.78, [3.3, 2.3, W - 5.6], rows, size=10.5, head_size=10, row_h=0.38,
      fills=fills, colors=colors, bolds={(i, 1): True for i in range(1, 8)})

# ---------------- Slide 2 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "Azure is equal or better on every metric · same 191 pages, same assertions, paired comparison",
       "Parsing Quality: Azure DI vs Infinity-Parser2", 2)
LW = 6.75
text(s, L, 1.2, 3, 0.3, [[("Assertion pass rate", True, "navy")]], 13)
rect(s, L + 2.0, 1.3, 0.13, 0.13, "inf"); text(s, L + 2.17, 1.23, 1, 0.3, ["Infinity"], 10, "muted")
rect(s, L + 2.95, 1.3, 0.13, 0.13, "az"); text(s, L + 3.12, 1.23, 1, 0.3, ["Azure DI"], 10, "muted")

metrics = [
    ("Amounts", "value appears verbatim, the correct number of times · n = 486", 97.5, 100.0,
     [("Significant (0 : 12, p = 0.0005). Of Infinity's 12 failures, checked one by one: ", False, "muted"),
      ("8 are real omissions", True, "ink"), ("; the other 4 differ only in the minus-sign glyph.", False, "muted")]),
    ("Text completeness", "3 text lines per page must appear verbatim · n = 448", 93.1, 97.1,
     [("Significant (2 : 20, p = 0.0001). ", False, "muted"),
      ("Round 1's 91.3% vs 72.5% is void", True, "ink"),
      (": it came from Azure converting full-width punctuation to half-width.", False, "muted")]),
    ("Unit & currency", "headers such as \"unit: yuan\" are kept · n = 93", 98.9, 100.0,
     [("No significant difference (0 : 1). Amount next to its label (n = 76): Infinity 100%, Azure 98.7%, "
       "also no significant difference.", False, "muted")]),
]
y = 1.62
for name, sub, a, b, note in metrics:
    h = 1.72
    card(s, L, y, LW, h)
    text(s, L + 0.18, y + 0.1, LW - 0.3, 0.3, [[(name, True), ("  · " + sub, False, "muted")]], 11)
    for j, (lab, v, key) in enumerate((("Infinity", a, "inf"), ("Azure DI", b, "az"))):
        by = y + 0.5 + j * 0.34
        text(s, L + 0.18, by - 0.05, 1.3, 0.28, [lab], 11)
        bx, bw = L + 1.4, LW - 2.45
        rect(s, bx, by, bw, 0.17, "track")
        rect(s, bx, by, bw * v / 100, 0.17, key)
        text(s, bx + bw + 0.1, by - 0.05, 0.8, 0.28, [f"{v:g}%"], 11)
    text(s, L + 0.18, y + 1.18, LW - 0.36, 0.5, [note], 9.5)
    y += h + 0.13

RX = L + LW + 0.35
RW = R - RX
card(s, RX, 1.2, RW, 2.72, "no", "alert_bg", 1.5)
text(s, RX + 0.2, 1.3, RW - 0.4, 0.3, [[("Full amount scan: both miss, for different reasons", True, "no")]], 13)
text(s, RX + 0.2, 1.62, RW - 0.4, 0.25, ["54 paired A-share pages with amounts, 1,544 amounts"], 9.5, "muted")
for i, (big, small, col) in enumerate((("11", "missed by Infinity · 2 pages", "no"), ("6", "missed by Azure · 2 pages", "ink"))):
    bx = RX + 0.2 + i * 2.2
    text(s, bx, 1.85, 2.1, 0.5, [[(big, True, col)]], 28)
    text(s, bx, 2.38, 2.1, 0.3, [small], 9.5, "muted")
text(s, RX + 0.2, 2.68, RW - 0.4, 1.2, [
    [("• ", False), ("Infinity, confirmed", True),
     (": continuation table at page top not output; the call still ended normally; 3 repeats missed the same", False)],
    [("• One more page outside the paired set: ", False), ("a whole table of 16 amounts", True),
     (" vanished (Azure failed at the gateway there)", False)],
    "• Cause of Azure's 6 misses to be investigated (round 3); no significant difference at page level",
], 9.5, spacing=2)

card(s, RX, 4.07, RW, 2.9)
text(s, RX + 0.2, 4.15, RW - 0.4, 0.3, [[("Service & cost", True, "navy"),
                                        ("  (reference only; bases differ, not ranked)", False, "muted")]], 12)
table(s, RX + 0.2, 4.52, [1.1, 2.0, RW - 0.4 - 3.1], [
    ["", "Infinity (test endpoint)", "Azure DI (gateway)"],
    ["Success rate", "210 / 210", "191 / 210"],
    ["Latency P50", "22.5 s (concurrency 2)", "17 s (concurrency 4, polling)"],
    ["Throughput", "1.6–5.6 pages/min, flat", "—"],
    ["Price", "Not quoted", "List $10 / 1,000 pages"],
], size=9.5, head_size=9, row_h=0.3)
text(s, RX + 0.2, 6.3, RW - 0.4, 0.6, [[
    ("About 9.6k tokens per page. If billed per token, the input price must be below ", False, "muted"),
    ("≈ $1.13 / million tokens", True), (" to match Azure's list price.", False, "muted")]], 9.5)

# ---------------- Slide 3 ----------------
s = prs.slides.add_slide(BLANK)
header(s, "When OCR fails it reports uncertainty; when a VLM fails it delivers anyway · next: POC scope and exit criteria",
       "Technical Approach: Azure DI (OCR Pipeline) vs Infinity-Parser2 (VLM)", 3)
cmp_rows = [
    ["", "Infinity-Parser2", "Azure DI (prebuilt-layout)"],
    ["Approach", "Vision-language model (VLM), whole page to markdown in one pass", "OCR + layout-analysis pipeline"],
    ["Formats", "PDF and images only", "PDF, images, Office, HTML"],
    ["Input", "Each page rendered to a 300 DPI image, processed independently", "PDF (single-page PDFs in this test)"],
    ["Confidence", "None", "For every text span"],
    ["Determinism", "Same page 3 times: 99.0% character-identical (amounts unchanged)", "Deterministic"],
    ["Punctuation", "Keeps original full-width", "Full-width → half-width; normalise downstream"],
    ["When unsure", "May omit or generate content; the call still ends normally", "Low confidence or left blank"],
    ["Unique failure", "Endless repetition hitting the token limit (seen twice)", "—"],
    ["Bounding boxes", "Generated by the model", "Geometric detection"],
    ["Version", "Only the alias inf-mllm; model and version unknown", "API version, can be pinned"],
    ["Model", "Open weights (Apache-2.0); claims Qwen3.5 base (unverified)", "Closed, hosted service"],
]
TW = 7.35
table(s, L, 1.3, [1.35, 3.5, TW - 4.85], cmp_rows, size=10, head_size=10, row_h=0.44,
      fills={(4, 1): "no_bg", (4, 2): "go_bg", (2, 1): "no_bg", (2, 2): "go_bg"},
      colors={(4, 1): "no", (4, 2): "go", (2, 1): "no", (2, 2): "go"},
      bolds={(4, 1): True, (4, 2): True, (2, 1): True, (2, 2): True})

RX = L + TW + 0.35
RW = R - RX
card(s, RX, 1.3, RW, 3.2)
text(s, RX + 0.2, 1.4, RW - 0.4, 0.3, [[("Recommended POC scope", True, "navy")]], 13)
text(s, RX + 0.2, 1.75, RW - 0.4, 2.7, [
    [("• ", False), ("Precondition: a cost or on-premise reason", True), ("; parsing quality alone is not a reason", False)],
    "• HK annual / interim reports and prospectuses + A-share announcements, electronic PDFs only, ≥ 300 pages per family",
    [("• ", False), ("Targeted test on ≥ 50 \"continuation table at page top\" pages", True), (" to measure how often tables drop", False)],
    "• Guardrails: reconcile every amount against the PDF text layer; route every finish_reason=length to a human",
    "• Vendor must answer first: model and version locking, billing, confidence, production SLA",
], 10.5, spacing=4)
card(s, RX, 4.65, RW, 2.25)
text(s, RX + 0.2, 4.75, RW - 0.4, 0.3, [[("Exit criteria (stop if any is triggered)", True, "navy")]], 13)
text(s, RX + 0.2, 5.12, RW - 0.4, 1.75, [
    "• Significantly more pages with missing or substituted amounts than Azure",
    "• No version locking and no advance notice of changes",
    "• Per-page cost above Azure at contract price, including human review",
    "• Production throughput below business peak; repetition-degeneration rate above threshold",
], 10.5, spacing=4)

# ---------------- Slide 4: summary ----------------
s = prs.slides.add_slide(BLANK)
header(s, "Conclusion · Details · Method · Data sets", "Evaluation Summary", 4)
summary = [
    ["", ""],
    ["Conclusion", [("Azure is significantly better on ", False), ("amounts", True), (" and ", False),
                    ("text completeness", True), ("; on ", False), ("unit & currency", True), (" and ", False),
                    ("amount–label pairing", True), (" there is no significant difference; Infinity is better on none. "
                    "Infinity also has two structural gaps: it ", False), ("returns no confidence", True),
                    (", and on pages starting with a continuation table it ", False), ("silently drops the table", True), (".", False)]],
    ["Details", "Test result data: see test-results.md; analysis and findings: see evaluation-report.md"],
    ["Method", "Both systems parse the same pages through their APIs and output markdown, with no conversion on our side; "
               "outputs are checked assertion by assertion against the same GT, only pages where both succeeded are compared, "
               "a paired test decides significance, and no composite score is computed."],
    ["Data sets", "Self-built financial set: 53 public disclosure documents (CNINFO, HKEXnews) → 210 pages → 1,229 assertions, "
                  "191 paired pages. GT is mainly extracted automatically from the PDF text layer; 76 label pairings were "
                  "confirmed by a human one by one. Public benchmark olmOCR-Bench: 41 pages run."],
]
shp = table(s, L, 1.3, [1.5, W - 1.5], summary, size=12, head_size=6, row_h=0.9,
            fills={(i, 0): "lede_bg" for i in range(1, 5)}, colors={(i, 0): "navy" for i in range(1, 5)},
            bolds={(i, 0): True for i in range(1, 5)})
tbl = shp.table._tbl
tbl.remove(tbl.tr_lst[0])  # table() treats row 0 as a header; this slide has none
heights = (0.95, 0.6, 0.95, 0.95)
for i, h in enumerate(heights):
    shp.table.rows[i].height = Inches(h)
shp.height = Inches(sum(heights))
for i, (doc, desc) in enumerate((
        (TR, "Test sets and results: composition, GT sources, every metric and failure detail, service data, sources of numbers"),
        (ER, "Analysis report: conclusions and evidence, judgement by document type, structural differences, "
             "POC scope and exit criteria, method (Appendix C)"))):
    cx = L + i * (W / 2 + 0.1)
    card(s, cx, 5.2, W / 2 - 0.1, 1.1)
    text(s, cx + 0.2, 5.3, W / 2 - 0.5, 0.3, [[(doc[0], True, "inf", doc[3])]], 13)
    text(s, cx + 0.2, 5.68, W / 2 - 0.5, 0.55, [desc], 10, "muted")

prs.save(sys.argv[1])
print("saved", sys.argv[1])
