# backend/exit_management/pdf_export.py
"""Exit Form PDF for the employee, available only when the whole exit process is complete (Form Complete approved).

Sections, in this order, one per page group:
    1) Employee Exit Form   2) Project Details   3) IT Clearance   4) HR Clearance
Every signature is drawn as the actual image (never a "view" link): files stored in GridFS (PNG / JPEG, or the first page of a PDF)
are read back and embedded. The PDF is built on the fly from the employee's own `exist_form` document and returned as a download.
"""
import io
import logging
from datetime import datetime

from fastapi import HTTPException
from fpdf import FPDF
from PIL import Image
from pymongo.errors import PyMongoError

from backend.exit_management import repository as repo
from backend.exit_management.service import COMPANY_LABELS, MANAGER_LABELS
from backend.exit_management.utils import aware

log = logging.getLogger("exit_management")

NAVY = (44, 62, 80)
BLUE = (102, 126, 234)
GREY = (110, 120, 130)
LIGHT = (244, 246, 250)
QUESTIONS = [
    ("would_rejoin", "17. Would you rejoin JHS any time in future?"),
    ("systems_and_processes", "18. Were you comfortable with all systems and processes used by your team? Suggest any changes that would have improved your efficiency."),
    ("team_experience", "19. Did you feel comfortable working in your team? What would you miss the most about your department?"),
    ("resignation_reason", "20. What is the reason for your resignation?"),
    ("better_prospect", "21. Are you leaving because of a better prospect?"),
    ("new_employer", "    Name of the new employer"),
    ("pull_factors", "22. What are the pull factors of your new employer?"),
    ("recommend_company", "23. Would you recommend the company to a friend as a good organisation to work for?"),
    ("recommend_reason", "    Reason for not recommending the company"),
    ("jhs_memories", "24. List three things you would remember most about being a part of the JHS family."),
    ("improvements", "25. List three things that would have made your life better at JHS."),
    ("employee_benefits", "26. Do you think the employee benefits provided by the company were sufficient? (If not, do you have any suggestions?)"),
    ("departure_prevention", "27. What circumstances would have prevented your departure?"),
]
DECLARATION = ("I hereby declare that I haven't joined any of JHS Client OR I have informed the HR Department "
               "on the Client I would be joining.")


def T(value) -> str:
    """Text safe for the built-in PDF fonts (Latin-1): anything else becomes '?'."""
    return ("" if value is None else str(value)).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"') \
        .replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")


def _date(value) -> str:
    if not value:
        return "-"
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return T(value)


def _stamp(value) -> str:
    iso = aware(value) if isinstance(value, datetime) else value
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return T(iso)


# ── signature images ─────────────────────────────────────────────────────────
def signature_png(ref):
    """The stored signature file as (png bytes, (w, h)), or None. A PDF signature is shown as its first page."""
    if not ref or not ref.get("gridfs_file_id"):
        return None
    try:
        stream = repo.signature_bucket.open_download_stream(ref["gridfs_file_id"])
        data = stream.read()
        stream.close()
    except Exception:                                              # file missing / database trouble: the PDF is still produced
        log.warning("signature file %s could not be read for the PDF", ref.get("gridfs_file_id"))
        return None
    try:
        if data[:4] == b"%PDF":
            import pypdfium2 as pdfium
            img = pdfium.PdfDocument(data)[0].render(scale=1.4).to_pil()
        else:
            img = Image.open(io.BytesIO(data))
            img.load()
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        img = img.convert("RGB")
        img.thumbnail((600, 300))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue(), img.size
    except Exception:
        log.warning("signature file %s could not be converted for the PDF", ref.get("gridfs_file_id"))
        return None


class _Pdf(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.doc_title = title
        self.set_margins(14, 16, 14)
        self.set_auto_page_break(True, 16)

    def header(self):
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, T(self.doc_title), align="L")
        self.ln(7)
        self.set_draw_color(220, 224, 230)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"Page {self.page_no()} / {{nb}}", align="C")


# ── drawing helpers ──────────────────────────────────────────────────────────
def _section(pdf: _Pdf, number: int, title: str, subtitle: str = ""):
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 11, T(f"  {number}. {title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        pdf.set_text_color(*GREY)
        pdf.set_font("Helvetica", "", 9)
        pdf.ln(1.5)
        pdf.multi_cell(0, 5, T(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_text_color(0, 0, 0)


def _heading(pdf: _Pdf, text: str):
    if pdf.get_y() > pdf.page_break_trigger - 25:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, T(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*BLUE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 30, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(0, 0, 0)


def _pairs(pdf: _Pdf, pairs):
    """Label / value boxes, three per row."""
    col = (pdf.w - pdf.l_margin - pdf.r_margin) / 3
    for i in range(0, len(pairs), 3):
        if pdf.get_y() > pdf.page_break_trigger - 16:
            pdf.add_page()
        y = pdf.get_y()
        for j, (label, value) in enumerate(pairs[i:i + 3]):
            x = pdf.l_margin + j * col
            pdf.set_xy(x, y)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*GREY)
            pdf.cell(col - 2, 4, T(label).upper())
            pdf.set_xy(x, y + 4.5)
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(col - 2, 6, T(value)[:38])
        pdf.set_y(y + 13)


def _table(pdf: _Pdf, widths, header, rows, img_h=13):
    """Bordered table. A cell is text, or an (png_bytes, (w, h)) tuple that is drawn as an image."""
    def draw_header():
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8.5)
        for w, h in zip(widths, header):
            pdf.cell(w, 8, T(h), border=1, fill=True, align="C" if len(str(h)) < 11 else "L")
        pdf.ln(8)
        pdf.set_text_color(0, 0, 0)

    pdf.set_draw_color(190, 196, 206)
    draw_header()
    for row in rows:
        pdf.set_font("Helvetica", "", 9)
        heights = []
        for w, cell in zip(widths, row):
            if isinstance(cell, tuple):
                heights.append(img_h + 4)
            else:
                heights.append(max(1, len(pdf.multi_cell(w - 3, 4.6, T(cell), align="L", split_only=True))) * 4.6 + 4)
        rh = max(8, *heights)
        if pdf.get_y() + rh > pdf.page_break_trigger:
            pdf.add_page()
            draw_header()
            pdf.set_font("Helvetica", "", 9)
        x0, y0 = pdf.l_margin, pdf.get_y()
        x = x0
        for w, cell in zip(widths, row):
            pdf.rect(x, y0, w, rh)
            if isinstance(cell, tuple):
                png, (iw, ih) = cell
                scale = min((w - 4) / iw, (rh - 4) / ih)
                pw, ph = iw * scale, ih * scale
                pdf.image(io.BytesIO(png), x=x + (w - pw) / 2, y=y0 + (rh - ph) / 2, w=pw, h=ph)
            else:
                pdf.set_xy(x + 1.5, y0 + 2)
                pdf.multi_cell(w - 3, 4.6, T(cell), align="L", new_x="LEFT", new_y="TOP")
            x += w
        pdf.set_xy(x0, y0 + rh)


def _signature_box(pdf: _Pdf, label: str, ref, filename_fallback="Signature not available"):
    """A labelled box with the actual signature drawn in it."""
    if pdf.get_y() > pdf.page_break_trigger - 42:
        pdf.add_page()
    _heading(pdf, label)
    y = pdf.get_y()
    pdf.set_draw_color(200, 205, 215)
    pdf.rect(pdf.l_margin, y, 80, 32)
    got = signature_png(ref)
    if got:
        png, (iw, ih) = got
        scale = min(76 / iw, 28 / ih)
        pdf.image(io.BytesIO(png), x=pdf.l_margin + (80 - iw * scale) / 2, y=y + (32 - ih * scale) / 2, w=iw * scale, h=ih * scale)
    else:
        pdf.set_xy(pdf.l_margin + 2, y + 12)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*GREY)
        pdf.cell(76, 5, T(filename_fallback), align="C")
        pdf.set_text_color(0, 0, 0)
    pdf.set_y(y + 36)


def _signature_pair(pdf: _Pdf, left_label, left_ref, right_label, right_ref):
    """Two labelled signature boxes side by side (keeps the HR page on one sheet)."""
    if pdf.get_y() > pdf.page_break_trigger - 46:
        pdf.add_page()
    pdf.ln(2)
    y = pdf.get_y()
    for i, (label, ref) in enumerate(((left_label, left_ref), (right_label, right_ref))):
        x = pdf.l_margin + i * 92
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*NAVY)
        pdf.cell(88, 7, T(label))
        pdf.set_draw_color(200, 205, 215)
        pdf.rect(x, y + 8, 88, 30)
        got = signature_png(ref)
        if got:
            png, (iw, ih) = got
            scale = min(84 / iw, 26 / ih)
            pdf.image(io.BytesIO(png), x=x + (88 - iw * scale) / 2, y=y + 8 + (30 - ih * scale) / 2, w=iw * scale, h=ih * scale)
        else:
            pdf.set_xy(x, y + 20)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*GREY)
            pdf.cell(88, 5, "Signature not available", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(y + 42)


def _ratings(pdf: _Pdf, title: str, labels: dict, data: dict):
    _heading(pdf, title)
    _table(pdf, [130, 52], ["Particulars", "Rating"], [[label, (data or {}).get(key) or "-"] for key, label in labels.items()])


def _approved_line(pdf: _Pdf, label: str, stage: dict):
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*GREY)
    who = (stage or {}).get("approver_name") or (stage or {}).get("approver_code") or "-"
    pdf.cell(0, 6, T(f"{label}: {who}  -  {_stamp((stage or {}).get('approved_at'))}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


# ── the four sections ────────────────────────────────────────────────────────
def _exit_form(pdf: _Pdf, doc: dict):
    det = doc.get("employee_details") or {}
    _section(pdf, 1, "Employee Exit Form", f"Submitted on {_stamp(doc.get('submitted_at'))}")
    _heading(pdf, "Employee / Article Details")
    _pairs(pdf, [("Full name", doc.get("employee_name")), ("Code", doc.get("employee_id")), ("Designation", det.get("designation")),
                 ("Joining date", _date(det.get("joining_date"))), ("Reporting to", det.get("reporting_to")),
                 ("Resignation date", _date(det.get("resignation_date"))), ("Last working date", _date(det.get("last_working_date")))])
    _ratings(pdf, "About Reporting Manager", MANAGER_LABELS, doc.get("manager_feedback"))
    _ratings(pdf, "About JHS", COMPANY_LABELS, doc.get("company_feedback"))
    _heading(pdf, "Exit Interview")
    ei = doc.get("exit_interview") or {}
    for key, question in QUESTIONS:
        if key in ("new_employer", "pull_factors") and ei.get("better_prospect") != "Yes":
            continue
        if key == "recommend_reason" and ei.get("recommend_company") != "No":
            continue
        if pdf.get_y() > pdf.page_break_trigger - 22:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.multi_cell(0, 5, T(question), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(60, 70, 85)
        pdf.multi_cell(0, 5, T(ei.get(key) or "-"), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
    _signature_box(pdf, "Employee Signature", doc.get("signature_file"))


def _project_details(pdf: _Pdf, doc: dict):
    ph = doc.get("project_handover") or {}
    rm = (doc.get("approval") or {}).get("reporting_manager") or {}
    _section(pdf, 2, "Project Details")
    rows, first = [], None
    for it in ph.get("items", []):
        first = first or it.get("signature_file")
        rows.append([it.get("particular"), it.get("option") or "-", it.get("remarks") or "-", "Signed" if it.get("signature_file") else "-"])
    _table(pdf, [66, 20, 44, 52], ["Particulars", "Option", "Remarks", "Signature"], rows)
    _signature_box(pdf, "Reporting Manager Signature", first)
    _approved_line(pdf, "Reporting Manager stage approved by", rm)


def _it_clearance(pdf: _Pdf, doc: dict):
    ic = doc.get("it_clearance") or {}
    it = (doc.get("approval") or {}).get("it") or {}
    _section(pdf, 3, "IT Clearance")
    rows, first = [], None
    for i, item in enumerate(ic.get("items", []), 1):
        first = first or item.get("signature_file")
        rows.append([f"{i}. {item.get('particular')}", item.get("option") or "-", item.get("remarks") or "-", "Signed" if item.get("signature_file") else "-"])
    _table(pdf, [74, 16, 40, 52], ["Particulars", "Status", "Remarks", "Signature"], rows)
    _approved_line(pdf, "IT Clearance approved by", it)
    _signature_box(pdf, "IT Representative Signature", first)                    # the actual signature image, below the approval line


def _hr_clearance(pdf: _Pdf, doc: dict):
    hc = doc.get("hr_clearance") or {}
    hr = (doc.get("approval") or {}).get("hr") or {}
    _section(pdf, 4, "HR Clearance")
    rows = []
    for item in hc.get("items", []):
        rows.append([item.get("particular"), item.get("option") or "-", item.get("remarks") or "-", "Signed" if item.get("signature_file") else "-"])
    _table(pdf, [66, 20, 44, 52], ["Particulars", "Option", "Remarks", "Signature"], rows)
    _heading(pdf, "Declaration")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, T(DECLARATION), align="L", new_x="LMARGIN", new_y="NEXT")
    _heading(pdf, "HR Comments")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, T(hc.get("hr_comments") or "-"), align="L", new_x="LMARGIN", new_y="NEXT")
    _signature_pair(pdf, "Employee Signature", doc.get("signature_file"), "HR Signature", hc.get("hr_signature_file"))
    _approved_line(pdf, "HR Clearance approved by", hr)


def _is_complete(doc) -> bool:
    approval = (doc or {}).get("approval") or {}
    return approval.get("current_stage") == "complete" and (approval.get("form_complete") or {}).get("status") == "approved"


def _render(doc: dict):
    """-> (pdf bytes, file name): the ONE PDF format used by the employee and by the HR representative."""
    pdf = _Pdf(f"JHS Employee Exit Form - {doc.get('employee_name')} ({doc.get('employee_id')})")
    pdf.alias_nb_pages()
    pdf.set_title(T(f"Employee Exit Form - {doc.get('employee_id')}"))
    _exit_form(pdf, doc)
    _project_details(pdf, doc)
    _it_clearance(pdf, doc)
    _hr_clearance(pdf, doc)
    return bytes(pdf.output()), f"Employee_Exit_Form_{doc.get('employee_id')}.pdf"


def build(empid: str):
    """-> (pdf bytes, file name) for this employee's COMPLETED exit form."""
    try:
        doc = repo.find_form(empid)
    except PyMongoError:
        log.exception("pdf export lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if not doc or doc.get("status") != "submitted":
        raise HTTPException(404, "You have not submitted an exit form yet.")
    if not _is_complete(doc):
        raise HTTPException(409, "The PDF is available once the exit process is complete (all approvals done).")
    return _render(doc)


def build_for_hr(me: str, form_id: str):
    """-> (pdf bytes, file name) of a COMPLETED exit form, for an HR representative (never for their own form)."""
    from backend.exit_management import approvals
    doc = approvals.load_form(form_id)
    if me == doc.get("employee_id") or me not in approvals.scoped_hr_approvers(doc.get("employee_id")):
        raise HTTPException(403, "You are not the HR representative for this employee.")
    if not _is_complete(doc):
        raise HTTPException(409, "The PDF is available once the exit process is complete (all approvals done).")
    return _render(doc)
