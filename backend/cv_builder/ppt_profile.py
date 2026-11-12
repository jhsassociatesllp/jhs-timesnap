# backend/cv_builder/ppt_profile.py
"""
One-slide JHS profile built from templates/CV builder format.pptx.

The template is a sample (a partner's profile). Every shape is found by its id
and rewritten with the employee's details, keeping the template's fonts and
colours; shapes the profile has no data for are removed and the rest closes
up. Sections the user switched off (or left empty) are simply not drawn.
"""

import base64
import copy
import ipaddress
import os
import re
import socket
import urllib.request
from io import BytesIO
from urllib.parse import urlparse

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

from backend.cv_builder.context import build_context

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "CV builder format.pptx")

NAVY = RGBColor(0x1F, 0x38, 0x64)
RED = RGBColor(0xC8, 0x10, 0x2E)

# shape ids in the template
ID_TITLE, ID_PHOTO, ID_ROLE, ID_FIRM, ID_POSITIONING = 2, 4, 5, 10, 11
QUAL_IDS = (6, 7, 8, 9)
ID_SECTOR_HEAD = 12
SECTOR_FIRST_ID, SECTOR_SLOTS, SECTOR_COLS = 13, 8, 4        # card, title, description per sector
PILLAR_FIRST_ID, PILLAR_SLOTS = 37, 4                        # panel, icon, title, text per pillar
ID_FRAME_LABEL, CHIP_FIRST_ID, CHIP_COUNT = 53, 54, 9

MAX_PHOTO_BYTES = 5 * 1024 * 1024


# ── small helpers ─────────────────────────────────────────────────────────────
def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" .,;:") + "…"


def _remove(shape):
    shape._element.getparent().remove(shape._element)


def _set_paragraphs(shape, paragraphs, head_rest=False):
    """paragraphs: list of [(text, RGBColor|None), ...] runs. The shape's existing
    paragraphs are the formatting prototypes: the first for every line, or - with
    head_rest - the first for line 1 and the second for the lines after it."""
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    tf = shape.text_frame
    protos = [copy.deepcopy(p._p) for p in tf.paragraphs]
    for p in tf._txBody.findall(ns + "p"):
        tf._txBody.remove(p)
    for i, runs in enumerate(paragraphs):
        p = copy.deepcopy(protos[min(1, i, len(protos) - 1)] if head_rest else protos[0])
        rs = p.findall(ns + "r")
        for r in rs[1:]:
            p.remove(r)
        for end in p.findall(ns + "endParaRPr"):
            p.remove(end)
        tf._txBody.append(p)
        last = rs[0]
        for j, (text, _) in enumerate(runs):
            r = rs[0] if j == 0 else copy.deepcopy(rs[0])
            if j:
                last.addnext(r)
            last = r
            r.find(ns + "t").text = text
    for para, runs in zip(tf.paragraphs, paragraphs):
        for run, (_, color) in zip(para.runs, runs):
            if color is not None:
                run.font.color.rgb = color


def _set_text(shape, text, size=None):
    _set_paragraphs(shape, [[(text, None)]])
    if size:
        for r in shape.text_frame.paragraphs[0].runs:
            r.font.size = size


def _pack_lines(items, per_line=38, max_lines=3):
    """Join short items with ', ' into at most max_lines lines."""
    lines, cur = [], ""
    for it in items:
        it = clip(it, per_line)
        if not cur:
            cur = it
        elif len(cur) + 2 + len(it) <= per_line:
            cur += ", " + it
        else:
            lines.append(cur)
            cur = it
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


# ── photo ─────────────────────────────────────────────────────────────────────
def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _load_photo(value: str):
    """Bytes of the profile photo (data: URL or public http(s) URL), or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        if value.startswith("data:image/"):
            raw = base64.b64decode(value.split(",", 1)[1], validate=False)
        else:
            u = urlparse(value)
            if u.scheme not in ("http", "https") or not u.hostname or not _public_host(u.hostname):
                return None
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(urllib.request.Request(value, headers={"User-Agent": "JHS-CV"}), timeout=6) as r:
                raw = r.read(MAX_PHOTO_BYTES + 1)
        if not raw or len(raw) > MAX_PHOTO_BYTES:
            return None
        from PIL import Image
        img = Image.open(BytesIO(raw))
        img.load()
        return img
    except Exception:
        return None


def _fill_photo(slide, shape, img, name=""):
    """Swap the sample photo for `img`, centre-cropped to the frame's shape.
    Without a photo the frame shows the employee's initials."""
    left, top, w, h = shape.left, shape.top, shape.width, shape.height
    _remove(shape)
    if img is None:
        initials = "".join(x[0] for x in name.split()[:2]).upper() or "?"
        d = min(w, h) * 6 // 10
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, left + (w - d) // 2, top + (h - d) // 2, d, d)
        circle.name = "Photo"
        circle.fill.solid()
        circle.fill.fore_color.rgb = RGBColor(0x2F, 0x55, 0x97)
        circle.line.fill.background()
        circle.shadow.inherit = False
        tf = circle.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.text = initials
        run = tf.paragraphs[0].runs[0]
        run.font.size, run.font.bold, run.font.name = Pt(40), True, "Arial"
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        return
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (int(w / 9525 * 2), int(h / 9525 * 2)), centering=(0.5, 0.25))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=88)
    buf.seek(0)
    pic = slide.shapes.add_picture(buf, left, top, w, h)
    pic.name = "Photo"


# ── slide ─────────────────────────────────────────────────────────────────────
def build_profile_ppt(profile: dict, emp_name: str = "") -> bytes:
    c = build_context(profile, emp_name)

    prs = Presentation(TEMPLATE)
    slide = prs.slides[0]
    S = {sh.shape_id: sh for sh in slide.shapes}

    # ── title bar ─────────────────────────────────────────────────────────────
    codes = ", ".join(q["code"] for q in c["quals"][:3])
    title = " ".join(x for x in (codes, c["name"]) if x)
    if c["designation"]:
        title += f" - {c['designation']}"
    _set_text(S[ID_TITLE], title)
    if len(title) > 40:
        sz = 2400 if len(title) <= 55 else 2000
        for r in S[ID_TITLE].text_frame.paragraphs[0].runs:
            r.font.size = Emu(sz * 127)          # hundredths of a point -> EMU

    # ── left panel ────────────────────────────────────────────────────────────
    _fill_photo(slide, S[ID_PHOTO], _load_photo(profile.get("professional_photo")), c["name"])

    role = [[(t, None)] for t in (c["designation"], c["department"]) if t]
    if role:
        _set_paragraphs(S[ID_ROLE], role, head_rest=True)      # bold role line, lighter description line
    else:
        _remove(S[ID_ROLE])

    chips = [(f"{q['code']}, {q['institute']}" if q["institute"] else q["code"]) for q in c["quals"]]
    chips += c["mems"]
    for i, sid in enumerate(QUAL_IDS):
        if i < len(chips):
            _set_text(S[sid], clip(chips[i], 26))
        else:
            _remove(S[sid])

    contact = [t for t in (c["email"], c["phone"], c["location"]) if t]
    firm = [[("JHS & Associates LLP", None)]] + [[(clip(t, 34), None)] for t in contact]
    _set_paragraphs(S[ID_FIRM], firm, head_rest=True)

    # ── positioning line ──────────────────────────────────────────────────────
    summary = c["summary"].replace("\n", " ").strip()
    if summary:
        summary = clip(summary, 190)
        parts = re.split(r"(?<=[.!?])\s+", summary)
        if len(parts) > 1:
            runs = [(" ".join(parts[:-1]) + " ", NAVY), (parts[-1], RED)]
        else:
            runs = [(summary, NAVY)]
        _set_paragraphs(S[ID_POSITIONING], [runs])
    else:
        _remove(S[ID_POSITIONING])

    # ── sector experience ─────────────────────────────────────────────────────
    durations = {}
    for s in profile.get("sector_experience") or []:
        if isinstance(s, dict) and s.get("sector"):
            durations[s["sector"]] = (s.get("duration") or "").strip()
    sectors = c["sectors"][:SECTOR_SLOTS]
    for i in range(SECTOR_SLOTS):
        card, ttl, desc = (S[SECTOR_FIRST_ID + 3 * i + k] for k in range(3))
        if i < len(sectors):
            _set_text(ttl, clip(sectors[i], 24))
            d = durations.get(sectors[i], "")
            if d:
                _set_text(desc, clip(d, 70))
            else:
                _remove(desc)
        else:
            _remove(card), _remove(ttl), _remove(desc)
    rows_used = -(-len(sectors) // SECTOR_COLS)
    row_pitch = S[SECTOR_FIRST_ID + 3 * SECTOR_COLS].top - S[SECTOR_FIRST_ID].top
    lift = 0
    if not sectors:
        _remove(S[ID_SECTOR_HEAD])
        lift = S[PILLAR_FIRST_ID].top - S[ID_SECTOR_HEAD].top
    else:
        _set_text(S[ID_SECTOR_HEAD], "Sector experience")
        lift = (2 - rows_used) * row_pitch

    # ── areas of expertise: heading + up to 3 detail lines each ─────────────────
    cands = [(a["area"], [clip(x, 38) for x in a["details"]], True) for a in c["areas"]]
    cands = cands[:PILLAR_SLOTS]

    panels = []
    for i in range(PILLAR_SLOTS):
        panels.append([S[PILLAR_FIRST_ID + 4 * i + k] for k in range(4)])
    grid = _PanelGrid(panels, lift)
    for i, (panel, icon, ttl, txt) in enumerate(panels):
        if i < len(cands):
            label, lines, bullets = cands[i]
            _set_text(ttl, label)
            _set_text(icon, label[:1].upper())
            if lines:
                _set_paragraphs(txt, [[(("•  " if bullets else "") + ln, None)] for ln in lines])
            else:
                _remove(txt)
        else:
            for sh in (panel, icon, ttl, txt):
                _remove(sh)
    grid.place(panels[:len(cands)])

    # ── frameworks (other skills & tools) ─────────────────────────────────────
    skills = c["frameworks"]
    chip_shapes = [S[CHIP_FIRST_ID + i] for i in range(CHIP_COUNT)]
    label = S[ID_FRAME_LABEL]
    if skills:
        _set_text(label, "Frameworks")
        left = chip_shapes[0].left
        right_edge = 11887200
        gap = 73152
        proto = chip_shapes[0]
        placed = 0
        for i, name in enumerate(skills):
            text = clip(name, 22)
            w = 183000 + 66000 * len(text)
            if left + w > right_edge:
                break
            if placed < CHIP_COUNT:
                shp = chip_shapes[placed]
            else:
                el = copy.deepcopy(proto._element)
                slide.shapes._spTree.append(el)
                shp = slide.shapes[-1]
            _set_text(shp, text)
            shp.left, shp.width = Emu(left), Emu(w)
            left += w + gap
            placed += 1
        for shp in chip_shapes[placed:]:
            _remove(shp)
    else:
        _remove(label)
        for shp in chip_shapes:
            _remove(shp)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


class _PanelGrid:
    """The template's 2x2 panel grid. place() lays n panels out in the same area: rows share the
    height, and a lone last panel spans the full width, so a profile with few panels still looks full."""

    def __init__(self, panels, lift):
        p0, p1, p2 = panels[0][0], panels[1][0], panels[2][0]
        self.x0, self.x1 = p0.left, p1.left
        self.w, self.h = p0.width, p0.height
        self.top = p0.top - lift
        self.bottom = p2.top + p2.height                       # bottom edge of the template's second row
        self.gap = p2.top - (p0.top + p0.height)
        # inner shapes (icon, title, text) relative to their panel
        self.rel = [[(sh.left - pn[0].left, sh.top - pn[0].top, sh.width) for sh in pn[1:]] for pn in panels]

    def place(self, panels):
        n = len(panels)
        if not n:
            return
        rows = -(-n // 2)
        row_h = min((self.bottom - self.top - self.gap * (rows - 1)) // rows, int(self.h * 1.5))
        full = self.x1 + self.w - self.x0
        for i, shapes in enumerate(panels):
            row, col = divmod(i, 2)
            span = n % 2 == 1 and i == n - 1
            panel = shapes[0]
            panel.left = self.x0 + (self.x1 - self.x0 if col and not span else 0)
            panel.top = self.top + row * (row_h + self.gap)
            panel.width = full if span else self.w
            panel.height = row_h
            for sh, (dx, dy, w) in zip(shapes[1:], self.rel[i]):
                sh.left, sh.top = panel.left + dx, panel.top + dy
                if sh is shapes[3]:
                    sh.width = w + (full - self.w if span else 0)
