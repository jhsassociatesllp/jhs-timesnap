# backend/employee_declaration/router.py
"""
Employee Declaration Form - every employee reads the fixed declaration
document and signs it once; two allowlisted employee codes (see db.py's
`admins` collection) get a read-only admin roster + Excel export.

Uses the platform's normal get_current_user - unlike HR Policy Quiz there's
no separate non-employee login to bridge from, so no extra JWT domain here.
"""
from datetime import datetime, timezone
from io import BytesIO

import pytz
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import employee_details_collection
from backend.employee_declaration.db import submissions, admins
from backend.employee_declaration.html_render import DECLARATION_HTML
from backend.employee_declaration.pdf_render import generate_declaration_pdf

router = APIRouter(prefix="/employee-declaration", tags=["Employee Declaration"])

IST = pytz.timezone("Asia/Kolkata")


def now():
    return datetime.now(timezone.utc)


def _aware_utc(dt):
    """pymongo hands datetimes back tz-naive (value is still UTC). Returning
    those straight to the frontend serializes without a timezone marker, so
    the browser's `new Date(...)` parses it as local time instead of UTC and
    silently drops the IST offset. Reattach UTC tzinfo before it goes out
    over JSON so the ISO string carries an explicit offset."""
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _format_ist(dt) -> str:
    """submitted_at is stored as UTC (pymongo hands it back tz-naive) - the
    admin table/JS side convert to the browser's local time automatically,
    but the PDF/Excel exports are rendered server-side, so they need an
    explicit UTC -> IST conversion instead of just formatting the raw UTC
    value as if it were already local."""
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")


def _employee_name(empid: str) -> str:
    emp = employee_details_collection.find_one({"EmpID": empid})
    if not emp:
        return empid
    return emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or empid


def _is_admin_empid(empid: str) -> bool:
    empid = empid.strip().upper()
    if admins.find_one({"empid": empid}):
        return True
    # Case-insensitive fallback, in case someone inserts a code manually
    # from Compass in lowercase or mixed case.
    return admins.find_one({"empid": {"$regex": f"^{empid}$", "$options": "i"}}) is not None


def _require_admin(current_user: str) -> str:
    empid = current_user.strip().upper()
    if not _is_admin_empid(empid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for the Employee Declaration Admin dashboard")
    return empid


# ---------------------------------------------------------------------------
# Employee: view + sign + submit
# ---------------------------------------------------------------------------

@router.get("/document")
def get_document(current_user: str = Depends(get_current_user)):
    return {"html": DECLARATION_HTML}


@router.get("/status")
def get_status(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    record = submissions.find_one({"empid": empid})
    if not record:
        return {"submitted": False, "submitted_at": None, "employee_name": _employee_name(empid), "signature": None}
    return {
        "submitted": True,
        "submitted_at": _aware_utc(record.get("submitted_at")),
        "employee_name": record.get("employee_name") or _employee_name(empid),
        "signature": record.get("signature"),
    }


class SubmitDeclarationRequest(BaseModel):
    signature: str


@router.post("/submit")
def submit_declaration(body: SubmitDeclarationRequest, current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()

    if not body.signature or not body.signature.startswith("data:image"):
        raise HTTPException(status_code=422, detail="A signature is required before you can submit")

    if submissions.find_one({"empid": empid}):
        raise HTTPException(status_code=409, detail="You have already submitted this declaration")

    employee_name = _employee_name(empid)
    submitted_at = now()
    submissions.insert_one(
        {
            "empid": empid,
            "employee_name": employee_name,
            "signature": body.signature,
            "submitted_at": submitted_at,
        }
    )
    return {"success": True, "submitted_at": submitted_at, "employee_name": employee_name}


# ---------------------------------------------------------------------------
# Admin: full roster + export
# ---------------------------------------------------------------------------

@router.get("/admin/access-check")
def admin_access_check(current_user: str = Depends(get_current_user)):
    return {"is_admin": _is_admin_empid(current_user)}


def _display_name(emp: dict, empid: str) -> str:
    return emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or empid


def _gather_roster() -> list[dict]:
    submitted_by_empid = {s["empid"]: s for s in submissions.find({})}
    rows = []
    for emp in employee_details_collection.find({}, {"EmpID": 1, "Emp Name": 1, "EmployeeName": 1, "Name": 1}):
        empid = (emp.get("EmpID") or "").strip().upper()
        if not empid:
            continue
        record = submitted_by_empid.get(empid)
        rows.append(
            {
                "empid": empid,
                "name": _display_name(emp, empid),
                "submitted": record is not None,
                "submitted_at": _aware_utc(record.get("submitted_at")) if record else None,
                "signature": record.get("signature") if record else None,
            }
        )
    rows.sort(key=lambda r: (not r["submitted"], r["empid"]))
    return rows


@router.get("/admin/submissions")
def admin_submissions(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    return {"rows": _gather_roster()}


def _generate_declaration_pdf(empid: str, name: str, submitted_at, signature: str | None) -> bytes:
    date_str = _format_ist(submitted_at).split(",")[0] if submitted_at else ""
    return generate_declaration_pdf(name, signature, date_str)


def _pdf_response(pdf_bytes: bytes, filename: str, inline: bool) -> Response:
    disposition = "inline" if inline else "attachment"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/my-pdf")
def my_declaration_pdf(download: bool = False, current_user: str = Depends(get_current_user)):
    """The signed declaration of the logged-in employee (view inline or download)."""
    empid = current_user.strip().upper()
    record = submissions.find_one({"empid": empid})
    if not record:
        raise HTTPException(status_code=404, detail="You have not submitted the declaration yet")
    name = record.get("employee_name") or _employee_name(empid)
    pdf_bytes = _generate_declaration_pdf(empid, name, record.get("submitted_at"), record.get("signature"))
    return _pdf_response(pdf_bytes, f"declaration-{empid}.pdf", inline=not download)


class PreviewRequest(BaseModel):
    signature: str | None = None


@router.post("/preview-pdf")
def preview_declaration_pdf(body: PreviewRequest, current_user: str = Depends(get_current_user)):
    """How the PDF will look with the employee's name, today's date and the
    signature they have drawn/typed/uploaded - nothing is saved."""
    empid = current_user.strip().upper()
    sig = body.signature if body.signature and body.signature.startswith("data:image") else None
    pdf_bytes = _generate_declaration_pdf(empid, _employee_name(empid), now(), sig)
    return _pdf_response(pdf_bytes, f"declaration-preview-{empid}.pdf", inline=True)


@router.get("/admin/submissions/{empid}/pdf")
def admin_submission_pdf(empid: str, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    empid = empid.strip().upper()

    record = submissions.find_one({"empid": empid})
    if not record:
        raise HTTPException(status_code=404, detail="No submission found for this employee")

    name = record.get("employee_name") or _employee_name(empid)
    try:
        pdf_bytes = _generate_declaration_pdf(empid, name, record.get("submitted_at"), record.get("signature"))
    except Exception as e:
        print(f"[DeclarationPDF] Failed to generate PDF for {empid}: {e}")
        raise HTTPException(status_code=500, detail="Could not generate the declaration PDF")

    return _pdf_response(pdf_bytes, f"declaration-{empid}.pdf", inline=False)


@router.get("/admin/export.xlsx")
def admin_export_xlsx(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)

    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows = _gather_roster()

    wb = Workbook()
    sheet = wb.active
    sheet.title = "Declarations"
    bold = Font(bold=True)

    sheet.append(["Employee ID", "Name", "Submitted", "Submitted At"])
    for cell in sheet[1]:
        cell.font = bold

    for r in rows:
        sheet.append([r["empid"], r["name"], "Yes" if r["submitted"] else "No", _format_ist(r["submitted_at"])])

    for col in sheet.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        sheet.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)

    buf = BytesIO()
    wb.save(buf)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=employee-declaration-report.xlsx"},
    )
