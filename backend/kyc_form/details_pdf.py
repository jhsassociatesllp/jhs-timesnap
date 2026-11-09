# backend/kyc_form/details_pdf.py
"""
PDF of one person's KYC details (the 26 answers + the list of uploaded documents), for HR to download or print.
Built with fpdf2's standard fonts, which cover Latin text: any character outside it (e.g. Devanagari) is shown as "?"
in the PDF. The Excel download has the full text.
"""
from datetime import datetime, timedelta, timezone

from fpdf import FPDF
from fpdf.enums import XPos, YPos

IST = timedelta(hours=5, minutes=30)


def _t(value) -> str:
    """Text the built-in PDF fonts can draw."""
    return str("" if value is None else value).encode("latin-1", "replace").decode("latin-1")


def _ist(dt) -> str:
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) + IST).strftime("%d %b %Y, %I:%M %p IST")


def build_pdf(name: str, empid: str, status: str, submitted_at, updated_at, data: dict, files: dict,
              answers: list, uploads: list) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_t(f"KYC Details - {name} ({empid})"))
    pdf.add_page()

    # title bar
    pdf.set_fill_color(44, 62, 80)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "  KYC Details Form", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(31, 41, 55)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _t(f"{name}  ({empid})"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(107, 114, 128)
    when = _ist(submitted_at) if status == "submitted" else _ist(updated_at)
    pdf.cell(0, 6, _t(("Submitted " if status == "submitted" else "Draft, last saved ") + when), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(31, 41, 55)
    pdf.ln(3)

    def section(title: str) -> None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(102, 126, 234)
        pdf.cell(0, 8, _t(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(31, 41, 55)

    def table(rows: list, widths=(72, 118)) -> None:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_draw_color(225, 232, 237)
        with pdf.table(col_widths=widths, text_align="LEFT", line_height=6, borders_layout="HORIZONTAL_LINES",
                       first_row_as_headings=False) as t:
            for label, value in rows:
                r = t.row()
                pdf.set_text_color(107, 114, 128)
                r.cell(_t(label))
                pdf.set_text_color(31, 41, 55)
                r.cell(_t(value if value not in (None, "") else "-"))

    section("Employee details")
    table([(f"{i}. {label}", data.get(key, "")) for i, (key, label, _ty, _x) in enumerate(answers, start=1)])
    pdf.ln(3)
    section("Documents")
    n = len(answers)
    rows = []
    for i, (key, label) in enumerate(uploads, start=1):
        f = files.get(key)
        rows.append((f"{n + i}. {label}", f"{f['name']} ({max(1, round(f['size'] / 1024))} KB)" if f else "Not uploaded"))
    table(rows)

    pdf.set_y(-14)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(156, 163, 175)
    pdf.cell(0, 6, _t(f"Generated {_ist(datetime.now(timezone.utc))} - JHS Associates"), align="C")
    return bytes(pdf.output())
