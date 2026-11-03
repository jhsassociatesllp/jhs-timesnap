# backend/buddy_referral/router.py
"""
Buddy Referral module.

  1. Existing employee referral - an employee records which colleague (picked
     via a JHS-code / name search) refer someone, for a position.
  2. Referral - an employee submits a role plus the candidate's resume
     (.pdf / .docx only), stored in MongoDB GridFS.

Admin endpoints (control panel "Buddy Referral" card) show the submitting
employee's code, name, date of joining, manager and partner (looked up live
from Employee_details) and export the history to Excel.
"""

import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

import gridfs
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from gridfs.errors import NoFile
from pydantic import BaseModel

from backend.access_manager.router import is_referral_admin, require_referral_admin
from backend.auth import get_current_user
from backend.buddy_referral.notify import send_referral_email
from backend.database import referral_db, employee_details_collection, timesheets_collection

router = APIRouter(prefix="/buddy-referral", tags=["Buddy Referral"])

existing_referrals = referral_db["buddy_existing_referrals"]
resume_referrals = referral_db["buddy_referrals"]
_fs = gridfs.GridFS(referral_db, collection="buddy_referral_resumes")

MAX_RESUME_BYTES = 10 * 1024 * 1024
_ALLOWED = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04"),
}
_IST = timedelta(hours=5, minutes=30)


# ── helpers ───────────────────────────────────────────────────────────────────
def _name(emp: dict, fallback: str = "") -> str:
    return (emp or {}).get("Emp Name") or (emp or {}).get("EmployeeName") or (emp or {}).get("Name") or fallback


def _emp(empid: str) -> Optional[dict]:
    return employee_details_collection.find_one({"EmpID": (empid or "").strip().upper()})


def _profile(emp: Optional[dict], empid: str) -> dict:
    """The employee facts the screens need (DOJ, manager, partner)."""
    emp = emp or {}
    return {
        "empid": empid, "name": _name(emp, empid),
        "date_of_joining": emp.get("Date of Joining") or "",
        "manager": emp.get("ReportingEmpName") or "",
        "partner": emp.get("Partner") or "",
        "designation": emp.get("Designation Name") or emp.get("Designation") or "",
        "branch": emp.get("Branch Name") or "",
    }


def _profiles_for(empids) -> dict:
    ids = sorted({(e or "").strip().upper() for e in empids if e})
    found = {(d.get("EmpID") or "").strip().upper(): d
             for d in employee_details_collection.find({"EmpID": {"$in": ids}})} if ids else {}
    return {e: _profile(found.get(e), e) for e in ids}


def _iso(dt):
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return dt


def _ist_text(dt) -> str:
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + _IST).strftime("%d/%m/%Y %H:%M")


# ── Signed-in employee + employee search (type-ahead) ─────────────────────────
@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    return _profile(_emp(empid), empid)


@router.get("/employees/search")
def search_employees(q: str = "", current_user: str = Depends(get_current_user)):
    q = (q or "").strip()
    if len(q) < 1:
        return {"results": []}
    rx = {"$regex": re.escape(q), "$options": "i"}
    cur = employee_details_collection.find(
        {"$or": [{"EmpID": rx}, {"Emp Name": rx}, {"EmployeeName": rx}, {"Name": rx}]}
    ).limit(40)
    out = []
    for e in cur:
        empid = (e.get("EmpID") or "").strip().upper()
        if not empid:
            continue
        out.append({
            "empid": empid, "name": _name(e, empid),
            "designation": e.get("Designation Name") or e.get("Designation") or "",
            "department": e.get("Branch Name") or e.get("Department") or "",
        })
    ql = q.lower()
    out.sort(key=lambda r: (not (r["empid"].lower().startswith(ql) or r["name"].lower().startswith(ql)), r["name"].lower()))
    return {"results": out[:10]}


# ── 1. Existing employee referral ─────────────────────────────────────────────
class ExistingReferralBody(BaseModel):
    referral_from: str          # JHS code of the referring employee (selected from search)
    position: str


@router.post("/existing")
def submit_existing(body: ExistingReferralBody, current_user: str = Depends(get_current_user)):
    position = body.position.strip()
    if not position:
        raise HTTPException(400, "Position is required")
    ref = _emp(body.referral_from)
    if not ref:
        raise HTTPException(400, "Please select the referring employee from the suggestions")
    me_ = _profile(_emp(current_user), current_user.strip().upper())
    ref_id = (ref.get("EmpID") or "").strip().upper()
    existing_referrals.insert_one({
        "submitted_by": me_["empid"], "submitted_by_name": me_["name"],
        "date_of_joining": me_["date_of_joining"],
        "referral_from": ref_id, "referral_from_name": _name(ref, ref_id),
        "position": position,
        "submitted_at": datetime.now(timezone.utc),
    })
    # No HR mail for this one: only "Referred Someone" (a candidate + resume) notifies HR.
    return {"success": True}


# ── 2. Referral with resume ───────────────────────────────────────────────────
@router.post("/referral")
async def submit_referral(
    background: BackgroundTasks,
    role: str = Form(...),
    resume: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
):
    role = role.strip()
    if not role:
        raise HTTPException(400, "Role is required")
    filename = (resume.filename or "").strip()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in _ALLOWED:
        raise HTTPException(400, "Only .pdf and .docx files are allowed")
    data = await resume.read(MAX_RESUME_BYTES + 1)
    if not data:
        raise HTTPException(400, "The uploaded file is empty")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(400, "Resume must be 10 MB or smaller")
    mime, magic = _ALLOWED[ext]
    if not data.startswith(magic):
        raise HTTPException(400, f"The file content is not a valid {ext[1:].upper()} file")
    safe_name = re.sub(r"[^\w.\- ]", "_", filename)[:120]
    file_id = _fs.put(data, filename=safe_name, content_type=mime)
    me_ = _profile(_emp(current_user), current_user.strip().upper())
    resume_referrals.insert_one({
        "submitted_by": me_["empid"], "submitted_by_name": me_["name"],
        "date_of_joining": me_["date_of_joining"],
        "role": role, "resume_file_id": file_id, "resume_filename": safe_name,
        "resume_size": len(data), "submitted_at": datetime.now(timezone.utc),
    })
    background.add_task(send_referral_email, me_["empid"], me_["name"], "referral", role)   # HR acknowledgement mail (only "Referred Someone" sends one)
    return {"success": True}


# ── The signed-in employee's own referrals ───────────────────────────────────
@router.get("/mine")
def my_referrals(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    docs = list(existing_referrals.find({"submitted_by": empid}).sort("submitted_at", -1))
    to_prof = _profiles_for(d.get("referral_from") for d in docs)
    active = _active_ids(d.get("referral_from") for d in docs)
    existing = []
    for d in docs:
        to_id = (d.get("referral_from") or "").strip().upper()
        t = to_prof.get(to_id) or _profile(None, to_id)
        existing.append({
            "empid": to_id, "name": t["name"] or d.get("referral_from_name"), "position": d.get("position"),
            "date_of_joining": t["date_of_joining"], "duration": _duration(t["date_of_joining"])["text"],
            "status": "Active" if to_id in active else "Inactive", "submitted_at": _iso(d.get("submitted_at")),
        })
    referrals = [{"role": d.get("role"), "resume_filename": d.get("resume_filename"),
                  "submitted_at": _iso(d.get("submitted_at"))}
                 for d in resume_referrals.find({"submitted_by": empid}).sort("submitted_at", -1)]
    return {"existing": existing, "referrals": referrals}


# ── Admin (control panel: Buddy Referral) ─────────────────────────────────────
@router.get("/admin/access-check")
def admin_access_check(current_user: str = Depends(get_current_user)):
    return {"is_admin": is_referral_admin(current_user)}


def _parse_date(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    s = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            pass
    return None


def _duration(doj) -> dict:
    """Months + days since joining; 'buddy' once 6 months are completed."""
    start = _parse_date(doj)
    if not start:
        return {"text": "", "months": None, "buddy": False}
    today = (datetime.now(timezone.utc) + _IST).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    if start > today:
        return {"text": "Not joined yet", "months": 0, "buddy": False}
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    y, m = divmod(start.month - 1 + months, 12)
    anchor = start.replace(year=start.year + y, month=m + 1, day=1)
    # clamp the day to the length of that month
    nxt = anchor.replace(year=anchor.year + (anchor.month == 12), month=anchor.month % 12 + 1)
    anchor = anchor.replace(day=min(start.day, (nxt - anchor).days))
    days = (today - anchor).days
    return {"text": f"{months} month{'s' if months != 1 else ''} {days} day{'s' if days != 1 else ''}",
            "months": months, "buddy": months >= 6}


def _active_ids(empids) -> set:
    ids = sorted({(e or "").strip().upper() for e in empids if e})
    if not ids:
        return set()
    return {(x or "").strip().upper()
            for x in timesheets_collection.distinct("employeeId", {"employeeId": {"$in": ids}})}


def _contacted(d: dict) -> str:
    return "Yes" if d.get("contacted") == "Yes" else "No"


def _yes_no(d: dict, field: str) -> str:
    """'Yes' / 'No' once the admin has decided, '' while it is still open."""
    return d.get(field) if d.get(field) in ("Yes", "No") else ""


def _existing_rows():
    docs = list(existing_referrals.find({}).sort("submitted_at", -1))
    prof = _profiles_for(d.get("submitted_by") for d in docs)
    to_prof = _profiles_for(d.get("referral_from") for d in docs)
    active = _active_ids(d.get("referral_from") for d in docs)
    rows = []
    for d in docs:
        p = prof.get((d.get("submitted_by") or "").strip().upper()) or _profile(None, d.get("submitted_by") or "")
        to_id = (d.get("referral_from") or "").strip().upper()
        t = to_prof.get(to_id) or _profile(None, to_id)
        dur = _duration(t["date_of_joining"])
        rows.append({
            "id": str(d["_id"]),
            "empid": d.get("submitted_by"), "name": p["name"] or d.get("submitted_by_name"),
            "manager": p["manager"], "partner": p["partner"],
            "referred_to_name": t["name"] or d.get("referral_from_name"),
            "referred_to_position": t["designation"],
            "referred_emp": to_id,
            "referred_doj": t["date_of_joining"],
            "duration": dur["text"], "buddy": dur["buddy"],
            "status": "Active" if to_id in active else "Inactive",
            "contacted": _contacted(d),
            "paid": _yes_no(d, "paid"), "paid_remark": d.get("paid_remark") or "",
            "position": d.get("position"), "submitted_at": d.get("submitted_at"),
        })
    return rows


def _referral_rows():
    docs = list(resume_referrals.find({}).sort("submitted_at", -1))
    prof = _profiles_for(d.get("submitted_by") for d in docs)
    rows = []
    for d in docs:
        p = prof.get((d.get("submitted_by") or "").strip().upper()) or _profile(None, d.get("submitted_by") or "")
        rows.append({
            "id": str(d["_id"]),
            "empid": d.get("submitted_by"), "name": p["name"] or d.get("submitted_by_name"),
            "date_of_joining": p["date_of_joining"] or d.get("date_of_joining") or "",
            "manager": p["manager"], "partner": p["partner"],
            "contacted": _contacted(d),
            "shortlisted": _yes_no(d, "shortlisted"), "shortlisted_remark": d.get("shortlisted_remark") or "",
            "role": d.get("role"), "resume_filename": d.get("resume_filename"),
            "resume_size": d.get("resume_size"), "submitted_at": d.get("submitted_at"),
        })
    return rows


@router.get("/admin/existing")
def admin_existing(_: str = Depends(require_referral_admin)):
    rows = _existing_rows()
    for r in rows:
        r["submitted_at"] = _iso(r["submitted_at"])
    return {"rows": rows}


@router.get("/admin/referrals")
def admin_referrals(_: str = Depends(require_referral_admin)):
    rows = _referral_rows()
    for r in rows:
        r["submitted_at"] = _iso(r["submitted_at"])
    return {"rows": rows}


@router.get("/admin/referrals/{referral_id}/resume")
def admin_resume(referral_id: str, inline: int = 0, _: str = Depends(require_referral_admin)):
    """Resume bytes. inline=1 -> for viewing in the browser, else a download."""
    try:
        doc = resume_referrals.find_one({"_id": ObjectId(referral_id)})
    except (InvalidId, TypeError):
        raise HTTPException(404, "Referral not found")
    if not doc:
        raise HTTPException(404, "Referral not found")
    try:
        f = _fs.get(doc["resume_file_id"])
    except NoFile:
        raise HTTPException(404, "Resume file is missing")
    name = doc.get("resume_filename") or "resume"
    return Response(
        content=f.read(), media_type=getattr(f, "content_type", None) or "application/octet-stream",
        headers={"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{name}"'},
    )


def _xlsx(title: str, headers, rows) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2C3E50")
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([("" if v is None else v) for v in r])
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None] or [10])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(width + 2, 12), 45)
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Column order shared by the per-tab exports and the dashboard export. The last
# column (Submitted On) is dropped from the dashboard sheets, which lead with it.
_EX_HEAD = ["Emp Code", "Emp Name", "Position (Referred Emp)", "Manager", "Partner", "Referred Emp Code", "Referred Emp Name",
            "Joining Date (Referred Emp)", "Duration (Referred Emp)", "Buddy Referral", "Referred Emp Status",
            "Contacted", "Paid", "Paid Remark", "Submitted On"]
_RR_HEAD = ["Emp Code", "Emp Name", "Date of Joining", "Manager", "Partner", "Role", "Resume File",
            "Contacted", "Shortlisted", "Shortlisted Remark", "Submitted On"]


def _ex_line(r):
    return [r["empid"], r["name"], r["referred_to_position"] or r["position"], r["manager"], r["partner"],
            r["referred_emp"], r["referred_to_name"], r["referred_doj"], r["duration"], "Buddy Referral" if r["buddy"] else "",
            r["status"], r["contacted"], r["paid"], r["paid_remark"], _ist_text(r["submitted_at"])]


def _rr_line(r):
    return [r["empid"], r["name"], r["date_of_joining"], r["manager"], r["partner"], r["role"],
            r["resume_filename"], r["contacted"], r["shortlisted"], r["shortlisted_remark"], _ist_text(r["submitted_at"])]


@router.get("/admin/existing/export")
def export_existing(_: str = Depends(require_referral_admin)):
    rows = _existing_rows()
    data = _xlsx("Referred by a JHS Employee", _EX_HEAD, [_ex_line(r) for r in rows])
    return Response(content=data, media_type=_XLSX,
                    headers={"Content-Disposition": "attachment; filename=Referred_by_JHS_Employee.xlsx"})


@router.get("/admin/referrals/export")
def export_referrals(_: str = Depends(require_referral_admin)):
    rows = _referral_rows()
    data = _xlsx("Referred Someone",
                 _RR_HEAD, [_rr_line(r) for r in rows])
    return Response(content=data, media_type=_XLSX,
                    headers={"Content-Disposition": "attachment; filename=Referred_Someone.xlsx"})


# ── Contacted flag (Yes / No, set manually by the admin) ─────────────────────
class ContactedBody(BaseModel):
    contacted: str


@router.put("/admin/{kind}/{referral_id}/contacted")
def set_contacted(kind: str, referral_id: str, body: ContactedBody, _: str = Depends(require_referral_admin)):
    coll = {"existing": existing_referrals, "referrals": resume_referrals}.get(kind)
    if coll is None:
        raise HTTPException(404, "Unknown referral type")
    value = (body.contacted or "").strip().capitalize()
    if value not in ("Yes", "No"):
        raise HTTPException(400, "Contacted must be Yes or No")
    try:
        res = coll.update_one({"_id": ObjectId(referral_id)}, {"$set": {"contacted": value}})
    except (InvalidId, TypeError):
        raise HTTPException(404, "Referral not found")
    if not res.matched_count:
        raise HTTPException(404, "Referral not found")
    return {"success": True, "contacted": value}


# ── Paid (Referred by a JHS Employee) / Shortlisted (Referred Someone): Yes / No + remark ──
_DECISIONS = {"existing": ("paid", existing_referrals, "paid_remark"),
              "referrals": ("shortlisted", resume_referrals, "shortlisted_remark")}


class DecisionBody(BaseModel):
    value: str
    remark: Optional[str] = ""


@router.put("/admin/{kind}/{referral_id}/decision")
def set_decision(kind: str, referral_id: str, body: DecisionBody, _: str = Depends(require_referral_admin)):
    if kind not in _DECISIONS:
        raise HTTPException(404, "Unknown referral type")
    field, coll, remark_field = _DECISIONS[kind]
    value = (body.value or "").strip().capitalize()
    if value not in ("Yes", "No"):
        raise HTTPException(400, "Value must be Yes or No")
    remark = (body.remark or "").strip()[:300]
    if value == "No" and not remark:
        raise HTTPException(400, "A remark is required when the answer is No")
    try:
        res = coll.update_one({"_id": ObjectId(referral_id)},
                              {"$set": {field: value, remark_field: remark if value == "No" else ""}})
    except (InvalidId, TypeError):
        raise HTTPException(404, "Referral not found")
    if not res.matched_count:
        raise HTTPException(404, "Referral not found")
    return {"success": True, "value": value, "remark": remark if value == "No" else ""}


# ── Dashboard ────────────────────────────────────────────────────────────────
def _in_range(dt, d_from: Optional[datetime], d_to: Optional[datetime]) -> bool:
    if not isinstance(dt, datetime):
        return not (d_from or d_to)
    local = ((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) + _IST).replace(tzinfo=None)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (not d_from or day >= d_from) and (not d_to or day <= d_to)


def _range(date_from: str, date_to: str):
    f, t = _parse_date(date_from), _parse_date(date_to)
    if f and t and f > t:
        raise HTTPException(400, "'From' date is after 'To' date")
    return f, t


def _dashboard_data(date_from: str, date_to: str) -> dict:
    f, t = _range(date_from, date_to)
    ex = [r for r in _existing_rows() if _in_range(r["submitted_at"], f, t)]
    rr = [r for r in _referral_rows() if _in_range(r["submitted_at"], f, t)]

    people = {}
    def person(code, name):
        return people.setdefault(code, {"empid": code, "name": name, "count": 0, "referred_to": [], "referred_someone": []})
    for r in ex:
        p = person(r["empid"], r["name"])
        p["count"] += 1
        p["referred_to"].append({
            "name": r["referred_to_name"], "empid": r["referred_emp"], "position": r["position"],
            "doj": r["referred_doj"], "duration": r["duration"], "status": r["status"],
            "contacted": r["contacted"], "paid": r["paid"], "paid_remark": r["paid_remark"],
            "submitted_at": _iso(r["submitted_at"]),
        })
    for r in rr:
        p = person(r["empid"], r["name"])
        p["count"] += 1
        p["referred_someone"].append({
            "role": r["role"], "resume_filename": r["resume_filename"],
            "contacted": r["contacted"], "shortlisted": r["shortlisted"], "shortlisted_remark": r["shortlisted_remark"],
            "submitted_at": _iso(r["submitted_at"]),
        })
    top = sorted(people.values(), key=lambda p: (-p["count"], p["name"] or ""))[:10]
    contacted = sum(1 for r in ex + rr if r["contacted"] == "Yes")
    paid_yes = sum(1 for r in ex if r["paid"] == "Yes")
    paid_no = sum(1 for r in ex if r["paid"] == "No")
    short_yes = sum(1 for r in rr if r["shortlisted"] == "Yes")
    short_no = sum(1 for r in rr if r["shortlisted"] == "No")
    return {
        "employees_referred": len(people),
        "total_referrals": len(ex) + len(rr),
        "referred_to_count": len(ex),
        "referred_someone_count": len(rr),
        "contacted": contacted, "pending": len(ex) + len(rr) - contacted,
        "buddy_given": paid_yes, "buddy_not_given": paid_no, "buddy_awaiting": len(ex) - paid_yes - paid_no,
        "shortlisted": short_yes, "rejected": short_no, "shortlist_awaiting": len(rr) - short_yes - short_no,
        "top": top, "_ex": ex, "_rr": rr,
    }


@router.get("/admin/dashboard")
def admin_dashboard(date_from: str = "", date_to: str = "", _: str = Depends(require_referral_admin)):
    d = _dashboard_data(date_from, date_to)
    d.pop("_ex"); d.pop("_rr")
    return d


@router.get("/admin/dashboard/export")
def export_dashboard(date_from: str = "", date_to: str = "", _: str = Depends(require_referral_admin)):
    from openpyxl import load_workbook
    d = _dashboard_data(date_from, date_to)
    ex = sorted(d["_ex"], key=lambda r: r["submitted_at"] or datetime.min)
    rr = sorted(d["_rr"], key=lambda r: r["submitted_at"] or datetime.min)
    summary = [
        ["From", date_from or "All"], ["To", date_to or "All"],
        ["Employees who referred someone (unique)", d["employees_referred"]],
        ["Total referrals", d["total_referrals"]],
        ["Referral To (JHS employee)", d["referred_to_count"]],
        ["Referred Someone (resume)", d["referred_someone_count"]],
        ["Contacted", d["contacted"]], ["Pending", d["pending"]],
        ["Buddy referral given", d["buddy_given"]], ["Buddy referral not given", d["buddy_not_given"]],
        ["Buddy referral awaiting", d["buddy_awaiting"]],
        ["Shortlisted", d["shortlisted"]], ["Rejected", d["rejected"]], ["Shortlisting awaiting", d["shortlist_awaiting"]],
    ]
    top = [[i + 1, p["empid"], p["name"], p["count"], len(p["referred_to"]), len(p["referred_someone"])]
           for i, p in enumerate(d["top"])]
    wb = load_workbook(BytesIO(_xlsx("Summary", ["Metric", "Value"], summary)))
    for title, head, rows in (
        ("Top 10 Referrers", ["Rank", "Emp Code", "Emp Name", "Total Referrals", "Referral To", "Referred Someone"], top),
        ("Referral To", ["Submitted On"] + _EX_HEAD[:-1], [[_ist_text(r["submitted_at"])] + _ex_line(r)[:-1] for r in ex]),
        ("Referred Someone", ["Submitted On"] + _RR_HEAD[:-1], [[_ist_text(r["submitted_at"])] + _rr_line(r)[:-1] for r in rr]),
    ):
        src = load_workbook(BytesIO(_xlsx(title, head, rows))).active
        ws = wb.create_sheet(title)
        for row in src.iter_rows():
            for c in row:
                n = ws.cell(row=c.row, column=c.column, value=c.value)
                if c.has_style:
                    n.font, n.fill, n.alignment = c.font.copy(), c.fill.copy(), c.alignment.copy()
        for k, dim in src.column_dimensions.items():
            ws.column_dimensions[k].width = dim.width
        ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    fname = f"Buddy_Referral_Dashboard_{date_from or 'all'}_to_{date_to or 'all'}.xlsx"
    return Response(content=buf.getvalue(), media_type=_XLSX,
                    headers={"Content-Disposition": f"attachment; filename={fname}"})
