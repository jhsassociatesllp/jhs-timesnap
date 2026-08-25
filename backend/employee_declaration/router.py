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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import employee_details_collection
from backend.employee_declaration.db import submissions, admins
from backend.employee_declaration.html_render import DECLARATION_HTML

router = APIRouter(prefix="/employee-declaration", tags=["Employee Declaration"])


def now():
    return datetime.now(timezone.utc)


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
        "submitted_at": record.get("submitted_at"),
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
                "submitted_at": record.get("submitted_at") if record else None,
                "signature": record.get("signature") if record else None,
            }
        )
    rows.sort(key=lambda r: (not r["submitted"], r["empid"]))
    return rows


@router.get("/admin/submissions")
def admin_submissions(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    return {"rows": _gather_roster()}


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
        submitted_at = r["submitted_at"].strftime("%d %b %Y, %I:%M %p") if r["submitted_at"] else "-"
        sheet.append([r["empid"], r["name"], "Yes" if r["submitted"] else "No", submitted_at])

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
