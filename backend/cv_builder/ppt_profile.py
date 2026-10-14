# backend/cv_builder/ppt_profile.py
"""
One-slide "team profile" PowerPoint for employees whose profile is marked
"PPT Profile Required = Yes". Red & white design. Sections the user switched
off (or left empty) are simply not drawn, same as the CV.
"""

import math
import re
import threading
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from backend.cv_builder.docx_fill import build_context

RED = RGBColor(0xC8, 0x10, 0x2E)
DARK_RED = RGBColor(0x9E, 0x0C, 0x24)
BLUSH = RGBColor(0xFD, 0xEC, 0xEE)
PINK_TEXT = RGBColor(0xFA, 0xD5, 0xDA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x2B, 0x2B, 0x2B)
GREY = RGBColor(0x6B, 0x6B, 0x6B)
FONT = "Calibri"

SLIDE_W, SLIDE_H = 13.333, 7.5
PANEL_W = 4.3
RX, RW = 4.85, 7.95          # right column x / width
BOTTOM = 6.95                # nothing is drawn below this line
_tls = threading.local()      # right-column scale; the left panel always uses 1.0


def _fs() -> float:
    return getattr(_tls, "fs", 1.0)


# ── drawing helpers ───────────────────────────────────────────────────────────
def _rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE, line=None, line_w=0.75):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_w)
    s.shadow.inherit = False
    return s


def _text(slide, x, y, w, h, text, size=11, bold=False, color=INK, align=PP_ALIGN.LEFT,
          spacing=None, anchor=MSO_ANCHOR.TOP, italic=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = text if isinstance(text, list) else [text]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size * _fs())
        r.font.bold = bold
        r.font.italic = italic
        r.font.name = FONT
        r.font.color.rgb = color
        if spacing:
            r.font._element.set("spc", str(spacing))
    return tb


def _bullets(slide, x, y, w, items, size=10, color=INK, gap=0.04):
    """Bulleted list; returns the y after the last item."""
    sz = size * _fs()
    cpl = max(10, int((w - 0.17) / (sz * 0.0068)))    # approx characters per line
    for it in items:
        lines = max(1, math.ceil(len(it) / cpl))
        h = lines * sz * 0.0175 + gap * _fs()
        _rect(slide, x, y + 0.075 * _fs(), 0.06 * _fs(), 0.06 * _fs(), RED, MSO_SHAPE.OVAL)
        _text(slide, x + 0.17, y, w - 0.17, h, it, size=size, color=color)
        y += h
    return y


def _heading(slide, x, y, w, label):
    _text(slide, x, y, w, 0.25 * _fs(), label.upper(), size=10.5, bold=True, color=RED, spacing=150)
    _rect(slide, x, y + 0.27 * _fs(), w, 0.02, RED)
    return y + 0.4 * _fs()


def _chip_w(text, sz):
    return len(text) * sz * 0.0078 + 0.34


def _chips(slide, x, y, w, items, filled=False, size=10):
    """Rounded 'pill' chips that wrap onto new rows. Returns y after the last row."""
    sz, cx, row_h = size * _fs(), x, 0.34 * _fs()
    for it in items:
        cw = min(_chip_w(it, sz), w)
        if cx + cw > x + w + 0.001 and cx > x:
            cx = x
            y += row_h + 0.08
        chip = _rect(slide, cx, y, cw, row_h, BLUSH if filled else WHITE, MSO_SHAPE.ROUNDED_RECTANGLE,
                     line=None if filled else RED, line_w=1)
        chip.adjustments[0] = 0.5
        tf = chip.text_frame
        tf.margin_left = tf.margin_right = Inches(0.08)
        tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = False
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = it
        r.font.size = Pt(sz)
        r.font.name = FONT
        r.font.bold = filled
        r.font.color.rgb = DARK_RED if filled else RED
        cx += cw + 0.1
    return y + row_h + 0.14


def _chip_height(items, w, size=10):
    sz, row_h = size * _fs(), 0.34 * _fs()
    rows, cx = 1, 0.0
    for it in items:
        cw = min(_chip_w(it, sz), w)
        if cx + cw > w + 0.001 and cx > 0:
            rows += 1
            cx = 0.0
        cx += cw + 0.1
    return rows * row_h + (rows - 1) * 0.08 + 0.14


def _bullets_height(items, w, size=10, gap=0.04):
    sz = size * _fs()
    cpl = max(10, int((w - 0.17) / (sz * 0.0068)))
    return sum(max(1, math.ceil(len(i) / cpl)) * sz * 0.0175 + gap * _fs() for i in items)


def clip_text(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip(" .,;:") + "…"


# ── slide ─────────────────────────────────────────────────────────────────────
def build_profile_ppt(profile: dict, emp_name: str = "", template_id: str = "1") -> bytes:
    _tls.fs = 1.0
    c = build_context(profile, [], emp_name, template_id)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    slide = prs.slides.add_slide(prs.slide_layouts[6])            # blank
    T = lambda key, default: c["titles"].get(key) or default

    # ── left red panel ────────────────────────────────────────────────────────
    _rect(slide, 0, 0, PANEL_W, SLIDE_H, RED)
    _rect(slide, PANEL_W - 0.09, 0, 0.09, SLIDE_H, DARK_RED)
    px, pw = 0.5, PANEL_W - 1.0
    y = 0.55
    name_lines = 2 if len(c["name"]) > 18 else 1
    _text(slide, px, y, pw, 0.5 * name_lines, c["name"], size=26 if name_lines == 1 else 24, bold=True, color=WHITE)
    y += 0.5 * name_lines + 0.08
    if c["designation"]:
        _text(slide, px, y, pw, 0.3, c["designation"], size=13, color=WHITE)
        y += 0.3
    if c["department"]:
        _text(slide, px, y, pw, 0.3, c["department"], size=11, color=PINK_TEXT)
        y += 0.3
    y += 0.1
    _rect(slide, px, y, 0.9, 0.04, WHITE)
    y += 0.22

    exp = c["exp_total"].strip()
    if exp:
        if re.fullmatch(r"\d{1,2}(\.\d+)?", exp):                 # a plain number of years: big figure + caption
            _text(slide, px, y, 1.6, 0.6, exp, size=34, bold=True, color=WHITE)
            _text(slide, px + 0.25 + len(exp) * 0.27, y + 0.16, pw, 0.4, ["YEARS OF", "EXPERIENCE"],
                  size=9, bold=True, color=PINK_TEXT, spacing=100)
            y += 0.8
        else:                                                         # free text such as "6 month": compact line + caption
            _text(slide, px, y, pw, 0.4, clip_text(exp, 22), size=22, bold=True, color=WHITE)
            _text(slide, px, y + 0.42, pw, 0.2, "EXPERIENCE", size=9, bold=True, color=PINK_TEXT, spacing=100)
            y += 0.85

    contact = [t for t in (c["email"], c["phone"], c["location"],
                           f"LinkedIn: {c['linkedin']}" if c["linkedin"] else "",
                           f"Portfolio: {c['portfolio']}" if c["portfolio"] else "") if t]
    for line in contact:
        h = 0.2 * max(1, math.ceil(len(line) / 38))
        _text(slide, px, y, pw, h, line, size=10, color=WHITE)
        y += h + 0.04
    if contact:
        y += 0.12

    def panel_block(label, entries):
        nonlocal y
        if not entries or y > BOTTOM - 0.6:
            return
        _text(slide, px, y, pw, 0.22, label.upper(), size=9.5, bold=True, color=PINK_TEXT, spacing=150)
        _rect(slide, px, y + 0.25, pw, 0.012, PINK_TEXT)
        y += 0.36
        for main, sub in entries:
            if y > BOTTOM - 0.25:
                break
            h = 0.2 * max(1, math.ceil(len(main) / 36))
            _text(slide, px, y, pw, h, main, size=10.5, bold=True, color=WHITE)
            y += h
            if sub:
                _text(slide, px, y, pw, 0.18, sub, size=9, color=PINK_TEXT)
                y += 0.19
            y += 0.06
        y += 0.1

    panel_block(T("education", "Qualifications"),
                [(q["name"], ", ".join(x for x in (q["institute"], q["year"]) if x)) for q in c["quals"][:5]])
    panel_block(T("memberships", "Memberships"),
                [(" — ".join(x for x in (m["name"], m["level"]) if x), m["number"]) for m in c["mems"][:4]])

    # brand block anchoring the bottom of the red panel (only when the panel has room for it)
    if y <= 6.2:
        _rect(slide, px, 6.42, 0.9, 0.04, WHITE)
        _text(slide, px, 6.55, pw, 0.25, "JHS & ASSOCIATES LLP", size=12, bold=True, color=WHITE, spacing=200)
        _text(slide, px, 6.85, pw, 0.2, "Team Profile", size=9.5, color=PINK_TEXT, spacing=100)

    # ── right column ──────────────────────────────────────────────────────────
    _text(slide, RX, 0.4, RW, 0.22, "JHS & ASSOCIATES LLP   |   TEAM PROFILE", size=9, bold=True, color=GREY,
          align=PP_ALIGN.RIGHT, spacing=200)
    top, avail = 0.85, BOTTOM - 0.85

    def clip(text, n):
        return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0].rstrip(" .,;:") + "…"

    # Richest layout that fits: each tier trims list lengths / drops the least important blocks.
    TIERS = [  # summary chars, expertise, sectors, certs/achievements, assignments, show other-skills, custom
        (520, 12, 10, 5, 4, True, 2),
        (380, 9, 8, 4, 3, True, 1),
        (300, 7, 6, 3, 3, False, 0),
        (220, 6, 5, 3, 2, False, 0),
    ]

    def plan(tier):
        sm, ne, ns, nc, na, other, ncu = tier
        fs = _fs()
        blocks = []
        if c["summary"]:
            t = clip(c["summary"], sm)
            blocks.append(("summary", T("summary", "Profile"), t, 0.4 * fs + math.ceil(len(t) / int(RW / (11 * fs * 0.0068))) * 0.2 * fs + 0.15))
        if c["key_skills"]:
            it = c["key_skills"][:ne]
            blocks.append(("expertise", T("expertise", "Key Expertise"), it, 0.4 * fs + _chip_height(it, RW)))
        if c["sectors"]:
            it = c["sectors"][:ns]
            blocks.append(("sectors", T("sectors", "Sector Experience"), it, 0.4 * fs + _chip_height(it, RW)))
        if other and c["all_other"]:
            t = clip("  •  ".join(c["all_other"][:14]), 260)
            blocks.append(("other", T("other_skills", "Other Skills & Tools"), t,
                           0.4 * fs + math.ceil(len(t) / int(RW / (10 * fs * 0.0068))) * 0.19 * fs + 0.15))
        if c["certs"] or c["achievements"]:
            colw = (RW - 0.4) / 2
            ce, ac = c["certs"][:nc], c["achievements"][:nc]
            blocks.append(("ca", None, (ce, ac), 0.4 * fs + max(_bullets_height(ce, colw), _bullets_height(ac, colw)) + 0.15))
        for sec in c["custom"][:ncu]:
            ln = sec["lines"][:4]
            if ln:
                blocks.append(("custom", sec["title"], ln, 0.4 * fs + _bullets_height(ln, RW) + 0.15))
        if c["assignments"]:
            rows = c["assignments"][:na]
            blocks.append(("assign", T("assignments", "Key Assignments"), rows, 0.4 * fs + 0.3 * fs * (len(rows) + 1) + 0.1))
        return blocks

    _tls.fs = 1.0
    chosen = None
    for tier in TIERS:
        blocks = plan(tier)
        if sum(b[3] for b in blocks) <= avail:
            chosen = blocks
            break
    if chosen is None:                                       # still too much: drop from the bottom
        chosen = plan(TIERS[-1])
        while chosen and sum(b[3] for b in chosen) > avail:
            chosen.pop()
    # Sparse slide: scale text and spacing up so it does not look empty
    used = sum(b[3] for b in chosen)
    if chosen and used < 0.62 * avail:
        for fs in (1.3, 1.2, 1.1):
            _tls.fs = fs
            bigger = plan(TIERS[0])
            if sum(b[3] for b in bigger) <= avail * 0.92:
                chosen = bigger
                break
            _tls.fs = 1.0
    used = sum(b[3] for b in chosen)
    gap = min(0.42, max(0.0, (avail - used) / (len(chosen) + 1))) if chosen else 0.0   # spread what is left

    y = top + gap * 0.5
    for kind, label, data, h in chosen:
        if kind == "summary":
            y = _heading(slide, RX, y, RW, label)
            _text(slide, RX, y, RW, h - 0.4 * _fs(), data, size=11, color=INK)
            y += h - 0.4 * _fs()
        elif kind in ("expertise", "sectors"):
            y = _heading(slide, RX, y, RW, label)
            y = _chips(slide, RX, y, RW, data, filled=(kind == "sectors"))
        elif kind == "other":
            y = _heading(slide, RX, y, RW, label)
            _text(slide, RX, y, RW, h - 0.4 * _fs(), data, size=10, color=INK)
            y += h - 0.4 * _fs()
        elif kind == "ca":
            certs, achs = data
            colw = (RW - 0.4) / 2
            start = y
            if certs:
                y1 = _heading(slide, RX, start, colw if achs else RW, T("certifications", "Certifications"))
                _bullets(slide, RX, y1, colw if achs else RW, certs)
            if achs:
                ax = RX + (colw + 0.4 if certs else 0)
                y2 = _heading(slide, ax, start, colw if certs else RW, T("achievements", "Achievements & Awards"))
                _bullets(slide, ax, y2, colw if certs else RW, achs)
            y = start + h
        elif kind == "custom":
            y = _heading(slide, RX, y, RW, label)
            y = _bullets(slide, RX, y, RW, data) + 0.15
        elif kind == "assign":
            rows = data
            y = _heading(slide, RX, y, RW, label)
            cols = [("Assignment", "assignment", 2.4), ("Client / Scope", "client", 3.35), ("Sector", "sector", 2.2)]
            rh = 0.3 * _fs()
            tbl_shape = slide.shapes.add_table(len(rows) + 1, len(cols), Inches(RX), Inches(y), Inches(RW),
                                               Inches(rh * (len(rows) + 1)))
            tbl = tbl_shape.table
            for ci, (_, _, w_in) in enumerate(cols):
                tbl.columns[ci].width = Inches(w_in)
            for ri in range(len(rows) + 1):
                tbl.rows[ri].height = Inches(rh)
                for ci, (label_, key, _) in enumerate(cols):
                    cell = tbl.cell(ri, ci)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RED if ri == 0 else (BLUSH if ri % 2 == 0 else WHITE)
                    cell.margin_left = Inches(0.1)
                    cell.margin_top = cell.margin_bottom = Inches(0.03)
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    tf = cell.text_frame
                    tf.word_wrap = True
                    r = tf.paragraphs[0].add_run()
                    r.text = label_ if ri == 0 else clip(rows[ri - 1].get(key) or "", 48)
                    r.font.size = Pt(10 * _fs())
                    r.font.name = FONT
                    r.font.bold = ri == 0
                    r.font.color.rgb = WHITE if ri == 0 else INK
            y += rh * (len(rows) + 1) + 0.1

        y += gap

    _tls.fs = 1.0
    if not chosen:
        _text(slide, RX, 3.2, RW, 0.4, "Add a summary, skills or sectors to your CV profile to fill this slide.",
              size=13, color=GREY, align=PP_ALIGN.CENTER, italic=True)

    # ── footer ────────────────────────────────────────────────────────────────
    _rect(slide, RX, 7.08, RW, 0.015, RED)
    _text(slide, RX, 7.14, RW, 0.2, "JHS & Associates LLP  |  Confidential – Proposal Use", size=8, color=GREY)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
