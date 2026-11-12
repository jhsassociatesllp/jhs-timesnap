# backend/employee_declaration/pdf_render.py
"""
Renders the Employee Declaration as a PDF laid out like the original
JHS_Employee_Declaration.pdf: red "JHS" mark top-right on every page, centred
bold title, bold numbered section headings with an underline rule, hanging-
indent clauses, "Page x of y" footer, and the Employee Name / Signature /
Date block at the end - filled in with the employee's details.
"""
import base64
import html as html_lib
import re
from io import BytesIO

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from backend.employee_declaration.html_render import DECLARATION_HTML

_SECTION_RE = re.compile(r"^\d{1,2}\.\s+\S")
_CLAUSE_RE = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(.*)$", re.S)

_REPLACEMENTS = {
    "‘": "'", "’": "'", "‚": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ", "•": "-", "\t": " ",
}


def _safe(text: str) -> str:
    """Core PDF fonts are Latin-1 only; map smart punctuation, drop the rest."""
    for uni, ascii_ in _REPLACEMENTS.items():
        text = text.replace(uni, ascii_)
    return text.encode("latin-1", "replace").decode("latin-1")


def _blocks() -> list[tuple[str, str]]:
    """Split the mammoth HTML into (kind, text) blocks.
    kinds: title, subtitle, section, clause:<no>, para. The trailing
    'Employee Name / Date / SIGNATURE' placeholder lines are dropped - the PDF
    draws its own filled-in signature block instead."""
    text = re.sub(r"</(p|h\d|li|tr|div)>", "\n", DECLARATION_HTML, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in html_lib.unescape(text).split("\n")]
    lines = [ln for ln in lines if ln]

    out: list[tuple[str, str]] = []
    for ln in lines:
        low = ln.lower().rstrip(": ").strip()
        if low in ("employee name", "date", "signature") or ln.startswith("Employee Name:") or ln.startswith("Date:"):
            continue
        if not out:
            out.append(("title", ln))
        elif len(out) == 1:
            out.append(("subtitle", ln))
        elif _SECTION_RE.match(ln) and not _CLAUSE_RE.match(ln):
            out.append(("section", ln))
        else:
            m = _CLAUSE_RE.match(ln)
            out.append((f"clause:{m.group(1)}", m.group(2)) if m else ("para", ln))
    return out


class _DeclarationPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "", 22)
        self.set_text_color(200, 16, 46)
        self.set_xy(self.w - self.r_margin - 30, 9)
        self.cell(30, 10, "JHS", align="R")
        self.set_text_color(0, 0, 0)
        self.set_xy(self.l_margin, self.t_margin)

    def footer(self):
        self.set_y(-14)
        self.set_font("Times", "", 9)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="C")


def generate_declaration_pdf(name: str = "", signature: str | None = None, date_str: str = "") -> bytes:
    """name/signature/date_str may be blank, which leaves those lines empty
    like the blank form."""
    pdf = _DeclarationPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.alias_nb_pages()
    pdf.add_page()

    body_w = pdf.w - pdf.l_margin - pdf.r_margin
    indent = 11

    for kind, text in _blocks():
        text = _safe(text)
        if kind == "title":
            pdf.set_font("Times", "B", 15)
            pdf.cell(0, 8, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        elif kind == "subtitle":
            pdf.set_font("Times", "I", 9.5)
            pdf.cell(0, 6, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(4)
        elif kind == "section":
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.ln(1.5)
            pdf.set_font("Times", "B", 11.5)
            pdf.cell(0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            y = pdf.get_y() + 0.3
            pdf.set_draw_color(0, 0, 0)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, y, pdf.l_margin + body_w, y)
            pdf.ln(1.8)
        elif kind.startswith("clause:"):
            no = kind.split(":", 1)[1]
            y0 = pdf.get_y()
            pdf.set_font("Times", "", 9.5)
            pdf.set_x(pdf.l_margin)
            pdf.cell(indent, 4.2, no)
            pdf.set_xy(pdf.l_margin + indent, y0)
            pdf.multi_cell(body_w - indent, 4.2, text, align="J", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1.3)
        else:
            pdf.set_font("Times", "", 9.5)
            pdf.multi_cell(0, 4.2, text, align="J", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2.5)

    # Signature block - same three lines, same order as the original form.
    if pdf.get_y() > pdf.h - 70:
        pdf.add_page()
    pdf.ln(8)
    line_w = 62
    pdf.set_font("Times", "", 10)
    pdf.set_line_width(0.2)

    def field(label: str, value: str):
        pdf.set_x(pdf.l_margin)
        pdf.cell(30, 7, label)
        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(line_w, 7, _safe(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.line(x, y + 6.6, x + line_w, y + 6.6)

    field("Employee Name:", name)

    pdf.set_x(pdf.l_margin)
    pdf.cell(30, 14, "Signature:")
    sx, sy = pdf.get_x(), pdf.get_y()
    pdf.ln(14)
    pdf.line(sx, sy + 13.6, sx + line_w, sy + 13.6)
    if signature and signature.startswith("data:image"):
        try:
            img = base64.b64decode(signature.split(",", 1)[1])
            pdf.image(BytesIO(img), x=sx + 1, y=sy + 0.5, w=line_w - 2, h=12.5, keep_aspect_ratio=True)
        except Exception:
            pass
    pdf.set_xy(pdf.l_margin, sy + 14)

    field("Date:", date_str)

    return bytes(pdf.output())
