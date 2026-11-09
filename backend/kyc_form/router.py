# backend/kyc_form/router.py
"""
KYC Details Form module — a copy of the Microsoft Form "KYC Details Form" (38 questions, all required):
26 answers (branch, personal, bank, contact, address, Aadhaar / PAN, referral) and 12 document uploads.

Works like the other employee forms (Employee Application Form, Undertaking): the employee fills it in,
can save a draft any number of times (uploaded files are kept as they go), submits once (after that only HR
can reopen it).

Storage policy: KYC data is saved ONLY to SharePoint (KYC DETAILS / <year> / <dd-mm-yyyy> / <Name (EmpID)> /).
MongoDB is used only as a staging area for drafts and in-progress uploads.  After a successful SharePoint
push the sensitive form answers and uploaded files are wiped from MongoDB; only a minimal tracking record
(empid, status, submitted_at, sharepoint path/status) is kept so the employee cannot re-submit and HR can
see which employees have completed the form.

Validation notes:
  - spouse_name:  optional when marital_status is "Unmarried" or "Divorce"
  - alt_mobile:   optional (many employees do not have an alternate number)
  - up_experience / up_offer_letter / up_salary_slips / up_ca_marksheet: optional for fresher / first-job
"""
import os
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

import gridfs
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from backend.access_manager.router import is_employee_form_admin, require_employee_form_admin
from backend.auth import get_current_user
from backend.database import employee_details_collection, employee_form_db
# Same sign-in as the other employee forms: a normal employee token OR a new-joiner token (personal e-mail login)
from backend.employee_form.router import current_form_user, is_joiner, joiners
from backend import date_range
from backend.kyc_form import details_pdf, sharepoint

router = APIRouter(prefix="/kyc-form", tags=["KYC Details Form"])

kyc = employee_form_db["kyc_forms"]
_fs = gridfs.GridFS(employee_form_db, collection="kyc_files")

# ── The questions (same order and wording as the Microsoft Form) ─────────────
# (key, label, type, extra)   type: text | textarea | date | radio | tel | email     — every question is required
PARTNERS = ["Huzefa Kaka", "Huzefa Unwala", "Amit More", "Taher Pepermintwala", "Jamal Chatriwala", "Sahil Shah",
            "Disha Shah", "Tausif Shaikh", "Samad Dhanani"]
ANSWERS = [
    ("branch", "Branch", "radio", {"options": ["Mumbai", "Masjid", "Kalyan"]}),
    ("full_name", "Employee Name ( Full name as per Aadhar)", "text", {}),
    ("father_name", "Father Name", "text", {}),
    ("blood_group", "Blood Group", "text", {}),
    ("marital_status", "Marital Status", "radio", {"options": ["Married", "Unmarried", "Widow / Widower", "Divorce"]}),
    ("spouse_name", "Husband / Wife Name", "text", {}),
    ("gender", "Gender", "radio", {"options": ["Male", "Female"]}),
    ("date_of_joining", "Date of Joining ( dd/mm/yyyy )", "date", {}),
    ("reporting_partner", "Reporting Partner", "radio", {"options": PARTNERS}),
    ("reporting_manager", "Reporting Manager", "text", {}),
    ("module", "Module", "radio", {"options": ["MT", "MAT", "Employee", "Article", "Retainer"]}),
    ("designation", "Designation", "text", {}),
    ("bank_holder", "Name as per Bank", "text", {}),
    ("bank_name", "Bank Name", "text", {}),
    ("account_no", "Bank Account Number", "text", {"check": "account"}),
    ("ifsc", "IFSC Code", "text", {"check": "ifsc", "upper": True}),
    ("dob", "Date of Birth ( dd/mm/yyyy )", "date", {}),
    ("personal_email", "Personal Email Id", "email", {"check": "email"}),
    ("mobile", "Personal Contact Number", "tel", {"check": "mobile"}),
    ("alt_mobile", "Alternate Contact Number", "tel", {"check": "mobile"}),
    ("education", "Educational Qualification", "text", {}),
    ("current_address", "Current Address with LandMark", "textarea", {}),
    ("permanent_address", "Permanent Address", "textarea", {}),
    ("aadhaar", "Aadhar Card Number", "text", {"check": "aadhaar"}),
    ("pan", "Pan Card Number", "text", {"check": "pan", "upper": True}),
    ("referred_by", "Referred by whom", "text", {}),
]
# (key, label) — one file each, up to 10 MB: Word, Excel, PPT, PDF, image, video or audio
UPLOADS = [
    ("up_aadhaar", "Aadhar Card"),
    ("up_pan", "PAN Card"),
    ("up_address_proof", "Address proof (Rent Document/Electricity Bill)"),
    ("up_marksheets", "Education Marksheets (10th Marksheet,12th Marksheet, Sem 6 Marksheet)"),
    ("up_degree", "Education Certificate(Degree Certificate)"),
    ("up_cheque", "Cancelled Cheque"),
    ("up_photo", "Passport Size Photograph 2 Nos"),
    ("up_experience", "Experience Letter of previous organizations"),
    ("up_offer_letter", "Previous Company Offer/Appointment letter"),
    ("up_salary_slips", "Latest 3 months’ Salary slips/ Bank Statements"),
    ("up_resume", "Updated Resume"),
    ("up_ca_marksheet", "CA/CMA Marksheet (Foundation/Intermediate group 1-2/ Final)"),
]
OPTIONAL_UPLOADS = {"up_experience", "up_offer_letter", "up_salary_slips", "up_ca_marksheet"}

MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXT = {
    # Word, Excel, PPT, PDF
    "doc", "docx", "dot", "dotx", "rtf", "txt", "xls", "xlsx", "xlsm", "csv", "ppt", "pptx", "pdf",
    # image (no svg: it can carry script)
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic", "heif",
    # video
    "mp4", "mov", "avi", "mkv", "webm", "wmv", "m4v", "3gp",
    # audio
    "mp3", "wav", "m4a", "aac", "ogg", "wma", "flac",
}

CHECKS = {
    "mobile": (re.compile(r"^[6-9]\d{9}$"), "must be a 10-digit mobile number"),
    "email": (re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$"), "must be a valid e-mail"),
    "pan": (re.compile(r"^[A-Z]{5}\d{4}[A-Z]$"), "must look like ABCDE1234F"),
    "aadhaar": (re.compile(r"^\d{12}$"), "must be 12 digits"),
    "account": (re.compile(r"^\d{9,18}$"), "must be 9 to 18 digits"),
    "ifsc": (re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$"), "must look like HDFC0001234"),
}
SENSITIVE = {"pan", "aadhaar", "account_no"}   # masked in the HR list

FIELDS = {a[0]: a for a in ANSWERS}
UPLOAD_KEYS = {u[0]: u[1] for u in UPLOADS}
MAX_LEN = 500


def _clean(data: dict) -> dict:
    """Keep only the known questions, as trimmed strings; upper-case where asked."""
    out = {}
    for key, (_k, _label, _t, extra) in FIELDS.items():
        v = (data or {}).get(key)
        v = ("" if v is None else str(v)).strip()[:MAX_LEN]
        out[key] = v.upper() if extra.get("upper") else v
    return out


def _problems(data: dict, files: dict) -> list:
    """Validate required answers, conditional fields, format checks, required uploads."""
    bad = []
    marital = data.get("marital_status", "")
    for key, label, ftype, extra in ANSWERS:
        v = data.get(key)
        # spouse_name is only required when married or widowed
        if key == "spouse_name" and marital in ("Unmarried", "Divorce"):
            continue
        # alt_mobile is optional — skip if blank, but validate format if provided
        if key == "alt_mobile":
            if v and not CHECKS["mobile"][0].match(v):
                bad.append(f"{label} must be a 10-digit mobile number")
            continue
        if not v:
            bad.append(f"{label} is required")
        elif extra.get("check") and not CHECKS[extra["check"]][0].match(v):
            bad.append(f"{label} {CHECKS[extra['check']][1]}")
        elif ftype == "radio" and v not in extra["options"]:
            bad.append(f"{label}: choose one of the listed options")
    for key, label in UPLOADS:
        if key not in files and key not in OPTIONAL_UPLOADS:
            bad.append(f"Upload: {label} is required")
    return bad


def _empid(user: str) -> str:
    return (user or "").strip().upper()


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


def _emp(empid: str) -> dict:
    return employee_details_collection.find_one({"EmpID": empid}) or {}


def _emp_name(empid: str) -> str:
    e = _emp(empid)
    return e.get("Emp Name") or e.get("EmployeeName") or e.get("Name") or ""


def _file_meta(f: dict) -> dict:
    return {"name": f.get("name"), "size": f.get("size"), "uploaded_at": _iso(f.get("uploaded_at"))}


def _file_meta_sp(f: dict) -> dict:
    """File metadata for SharePoint-sourced files (no GridFS id, has sp_web_url)."""
    return {"name": f.get("name"), "size": f.get("size"), "uploaded_at": None,
            "sp_web_url": f.get("sp_web_url", ""), "sp_download_url": f.get("sp_download_url", "")}


def _public(doc: Optional[dict]) -> dict:
    if not doc:
        return {"status": "none", "data": {}, "files": {}}
    return {"status": doc.get("status", "draft"), "data": doc.get("data", {}),
            "files": {k: _file_meta(v) for k, v in (doc.get("files") or {}).items()},
            "updated_at": _iso(doc.get("updated_at")), "submitted_at": _iso(doc.get("submitted_at"))}


# ── Employee ─────────────────────────────────────────────────────────────────
@router.get("/spec")
def spec(_: str = Depends(current_form_user)):
    """The questions, so the page can draw itself."""
    return {
        "answers": [{"key": k, "label": label, "type": t, "required": True, **extra} for k, label, t, extra in ANSWERS],
        "uploads": [{"key": k, "label": label, "optional": k in OPTIONAL_UPLOADS} for k, label in UPLOADS],
        "max_mb": MAX_FILE_BYTES // (1024 * 1024),
        "allowed": "Word, Excel, PPT, PDF, Image, Video, Audio",
        "allowed_ext": sorted(ALLOWED_EXT),
    }


@router.get("/me")
def me(current_user: str = Depends(current_form_user)):
    """Known details of the signed-in employee, used to prefill an empty form."""
    empid = _empid(current_user)
    if is_joiner(empid):                                   # new joiner: only the e-mail HR created the login with is known
        j = joiners.find_one({"empid": empid}) or {}
        return {"empid": empid, "name": "", "personal_email": j.get("email", ""), "mobile": "", "joiner": True}
    e = _emp(empid)
    return {"empid": empid, "name": e.get("Emp Name") or e.get("EmployeeName") or e.get("Name") or "",
            "designation": e.get("Designation Name") or "", "personal_email": e.get("Personal EMail") or "",
            "mobile": str(e.get("Mobile") or "")}


@router.get("/my")
def my_form(current_user: str = Depends(current_form_user)):
    return _public(kyc.find_one({"empid": _empid(current_user)}))


def _locked(existing: Optional[dict]):
    if existing and existing.get("status") == "submitted":
        raise HTTPException(409, "This form has already been submitted. Please contact HR if it needs to be changed.")


@router.put("/draft")
def save_draft(payload: dict = Body(...), current_user: str = Depends(current_form_user)):
    empid = _empid(current_user)
    _locked(kyc.find_one({"empid": empid}))
    now = datetime.now(timezone.utc)
    kyc.update_one({"empid": empid},
                   {"$set": {"empid": empid, "data": _clean(payload), "updated_at": now},
                    "$setOnInsert": {"status": "draft", "created_at": now}}, upsert=True)
    return {"success": True, "updated_at": now.isoformat()}


def _person_name(empid: str, data: dict) -> str:
    return (data or {}).get("full_name") or _emp_name(empid) or empid


def _push_to_sharepoint(empid: str) -> dict:
    """Save one submitted KYC form to SharePoint, then wipe sensitive data from MongoDB."""
    doc = kyc.find_one({"empid": empid})
    if not doc or doc.get("status") != "submitted":
        return {"status": "skipped"}
    try:
        out = sharepoint.save_submission(doc, _person_name(empid, doc.get("data")), ANSWERS, UPLOADS,
                                         lambda fid: _fs.get(fid).read())
    except Exception as exc:                                  # never let this surface to the employee
        out = {"status": "failed", "error": str(exc)[:300], "at": datetime.now(timezone.utc)}
        sharepoint.log.warning("KYC of %s was not saved to SharePoint: %s", empid, out["error"])
        kyc.update_one({"empid": empid}, {"$set": {"sharepoint": out}})
        return out
    # SharePoint upload succeeded — wipe sensitive answers + GridFS files from MongoDB.
    # Only a minimal tracking record (empid, status, submitted_at, sharepoint metadata) is kept.
    for field_meta in (doc.get("files") or {}).values():
        fid = field_meta.get("file_id")
        if fid:
            try:
                _fs.delete(fid)
            except Exception:
                pass
    kyc.update_one({"empid": empid}, {
        "$set": {"sharepoint": out},
        "$unset": {"data": "", "files": ""}
    })
    return out


@router.post("/submit")
def submit(payload: dict = Body(...), current_user: str = Depends(current_form_user)):
    empid = _empid(current_user)
    existing = kyc.find_one({"empid": empid})
    _locked(existing)
    data = _clean(payload)
    bad = _problems(data, (existing or {}).get("files") or {})
    if bad:
        raise HTTPException(422, "; ".join(bad[:6]) + (f" (+{len(bad) - 6} more)" if len(bad) > 6 else ""))
    now = datetime.now(timezone.utc)
    kyc.update_one({"empid": empid},
                   {"$set": {"empid": empid, "data": data, "status": "submitted", "updated_at": now, "submitted_at": now},
                    "$setOnInsert": {"created_at": now}}, upsert=True)
    # Push to SharePoint synchronously — on success, sensitive data is wiped from MongoDB.
    if sharepoint.is_configured():
        kyc.update_one({"empid": empid}, {"$set": {"sharepoint": {"status": "pending", "at": now}}})
        out = _push_to_sharepoint(empid)
        if out.get("status") == "failed":
            sharepoint.log.warning("KYC submit SP push failed for %s: %s", empid, out.get("error"))
    else:
        kyc.update_one({"empid": empid}, {"$set": {"sharepoint": {"status": "not_configured", "at": now}}})
    return {"success": True, "submitted_at": now.isoformat()}


# ── Uploaded documents ───────────────────────────────────────────────────────
@router.post("/upload/{field}")
async def upload(field: str, file: UploadFile = File(...), current_user: str = Depends(current_form_user)):
    """Store (or replace) one document. Saved straight away, so it survives a draft that is never submitted."""
    if field not in UPLOAD_KEYS:
        raise HTTPException(404, "Unknown upload")
    empid = _empid(current_user)
    existing = kyc.find_one({"empid": empid})
    _locked(existing)
    name = os.path.basename(file.filename or "file").strip()[:150] or "file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, "File type not allowed. Allowed: Word, Excel, PPT, PDF, Image, Video, Audio.")
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    fid = _fs.put(data, filename=name, empid=empid, field=field, content_type=file.content_type or "application/octet-stream")
    old = ((existing or {}).get("files") or {}).get(field)
    now = datetime.now(timezone.utc)
    meta = {"file_id": fid, "name": name, "size": len(data), "uploaded_at": now}
    kyc.update_one({"empid": empid},
                   {"$set": {"empid": empid, f"files.{field}": meta, "updated_at": now},
                    "$setOnInsert": {"status": "draft", "created_at": now, "data": {}}}, upsert=True)
    if old and old.get("file_id"):                         # the replaced file is removed so nothing is left behind
        try:
            _fs.delete(old["file_id"])
        except Exception:
            pass
    return {"success": True, "field": field, **_file_meta(meta)}


@router.delete("/upload/{field}")
def remove_upload(field: str, current_user: str = Depends(current_form_user)):
    if field not in UPLOAD_KEYS:
        raise HTTPException(404, "Unknown upload")
    empid = _empid(current_user)
    existing = kyc.find_one({"empid": empid})
    _locked(existing)
    old = ((existing or {}).get("files") or {}).get(field)
    if old:
        kyc.update_one({"empid": empid}, {"$unset": {f"files.{field}": ""}, "$set": {"updated_at": datetime.now(timezone.utc)}})
        try:
            _fs.delete(old["file_id"])
        except Exception:
            pass
    return {"success": True}


def _send(doc: Optional[dict], field: str) -> Response:
    meta = ((doc or {}).get("files") or {}).get(field)
    if not meta:
        raise HTTPException(404, "File not found")
    try:
        gf = _fs.get(meta["file_id"])
    except gridfs.errors.NoFile:
        raise HTTPException(404, "File is missing from the database")
    safe = re.sub(r'[^A-Za-z0-9._ -]', "_", meta.get("name") or "file")
    # always a download, never rendered by the browser, and never sniffed into something executable
    return Response(content=gf.read(), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.get("/file/{field}")
def my_file(field: str, current_user: str = Depends(current_form_user)):
    return _send(kyc.find_one({"empid": _empid(current_user)}), field)


# ── HR admin ─────────────────────────────────────────────────────────────────
def _mask(key: str, v) -> str:
    v = str(v or "")
    return ("•" * max(len(v) - 4, 0) + v[-4:]) if key in SENSITIVE and len(v) > 4 else v


@router.get("/admin/access-check")
def admin_access_check(current_user: str = Depends(current_form_user)):
    return {"is_admin": is_employee_form_admin(current_user)}


@router.get("/admin/list")
def admin_list(_: str = Depends(require_employee_form_admin)):
    rows = []
    for d in kyc.find({}).sort("updated_at", -1):
        x = d.get("data", {})
        rows.append({"empid": d.get("empid"), "name": _emp_name(d.get("empid")) or x.get("full_name", ""),
                     "status": d.get("status", "draft"), "branch": x.get("branch", ""), "mobile": x.get("mobile", ""),
                     "pan": _mask("pan", x.get("pan")), "aadhaar": _mask("aadhaar", x.get("aadhaar")),
                     "files": len(d.get("files") or {}), "files_total": len(UPLOADS),
                     "submitted_at": _iso(d.get("submitted_at")), "updated_at": _iso(d.get("updated_at"))})
    return {"rows": rows}


@router.get("/admin/export")
def admin_export(date_from: str = "", date_to: str = "", by: str = "updated_at",
                 _: str = Depends(require_employee_form_admin)):
    """Excel of the KYC responses. Optional date range (IST days) on `by`: updated_at | submitted_at."""
    lo, hi = date_range.bounds(date_from, date_to)
    by = by if by in ("updated_at", "submitted_at") else "updated_at"
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    heads = ["Emp Code", "Emp Name", "Status"] + [a[1] for a in ANSWERS] + [u[1] for u in UPLOADS] + \
            ["Submitted On (UTC)", "Last Updated (UTC)"]
    wb = Workbook()
    ws = wb.active
    ws.title = "KYC Details"
    ws.append(heads)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2C3E50")
    stamp = lambda dt: dt.strftime("%d/%m/%Y %H:%M") if isinstance(dt, datetime) else ""
    for d in kyc.find({}).sort("empid", 1):
        if not date_range.within(d.get(by), lo, hi):
            continue
        x, files = d.get("data", {}), d.get("files") or {}
        ws.append([d.get("empid"), _emp_name(d.get("empid")), d.get("status", "draft")] +
                  [x.get(a[0], "") for a in ANSWERS] +
                  [(files[u[0]]["name"] if u[0] in files else "Not uploaded") for u in UPLOADS] +
                  [stamp(d.get("submitted_at")), stamp(d.get("updated_at"))])
    for i, h in enumerate(heads, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(len(h) + 2, 16), 40)
    ws.freeze_panes = "D2"
    buf = BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=KYC_Details.xlsx"})


@router.get("/admin/{empid}")
def admin_get(empid: str, _: str = Depends(require_employee_form_admin)):
    d = kyc.find_one({"empid": _empid(empid)})
    if not d:
        raise HTTPException(404, "No KYC form for this employee")
    sp = d.get("sharepoint") or {}
    pub = _public(d)
    # If data was wiped (submitted + SharePoint saved), read it back from SharePoint
    if d.get("status") == "submitted" and not d.get("data") and sp.get("status") == "saved":
        try:
            restored = sharepoint.read_from_sharepoint(sp, ANSWERS, UPLOADS)
            pub["data"] = restored["data"]
            pub["files"] = {k: _file_meta_sp(v) for k, v in restored["files"].items()}
            pub["source"] = "sharepoint"
        except Exception as exc:
            pub["source_error"] = str(exc)[:200]
    return {**pub, "empid": d["empid"], "name": _emp_name(d["empid"]) or pub["data"].get("full_name", ""),
            "sharepoint": {**sp, "at": _iso(sp.get("at"))} if sp else None}


@router.post("/admin/{empid}/sharepoint")
def admin_resave(empid: str, _: str = Depends(require_employee_form_admin)):
    """Save (or save again) one submitted KYC form to SharePoint, e.g. after a failure."""
    d = kyc.find_one({"empid": _empid(empid)})
    if not d:
        raise HTTPException(404, "No KYC form for this employee")
    if d.get("status") != "submitted":
        raise HTTPException(409, "Only a submitted KYC form is saved to SharePoint")
    out = _push_to_sharepoint(d["empid"])
    return {**out, "at": _iso(out.get("at"))}


@router.get("/admin/{empid}/file/{field}")
def admin_file(empid: str, field: str, _: str = Depends(require_employee_form_admin)):
    return _send(kyc.find_one({"empid": _empid(empid)}), field)


def _details_doc(empid: str) -> dict:
    d = kyc.find_one({"empid": _empid(empid)})
    if not d:
        raise HTTPException(404, "No KYC form for this employee")
    return d


def _download_name(d: dict, ext: str) -> str:
    label = sharepoint.safe_name(f"KYC Details - {_person_name(d['empid'], d.get('data'))} ({d['empid']})", 120)
    return f'attachment; filename="{label.encode("ascii", "replace").decode()}.{ext}"'


@router.get("/admin/{empid}/details.xlsx")
def admin_details_xlsx(empid: str, _: str = Depends(require_employee_form_admin)):
    """One person's KYC answers (and the list of their documents) as an Excel file."""
    d = _details_doc(empid)
    content = sharepoint.build_excel(_person_name(d["empid"], d.get("data")), d["empid"], d.get("data") or {},
                                     d.get("files") or {}, ANSWERS, UPLOADS)
    return Response(content=content, headers={"Content-Disposition": _download_name(d, "xlsx")},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/admin/{empid}/details.pdf")
def admin_details_pdf(empid: str, _: str = Depends(require_employee_form_admin)):
    """One person's KYC answers (and the list of their documents) as a PDF."""
    d = _details_doc(empid)
    content = details_pdf.build_pdf(_person_name(d["empid"], d.get("data")), d["empid"], d.get("status", "draft"),
                                    d.get("submitted_at"), d.get("updated_at"), d.get("data") or {}, d.get("files") or {},
                                    ANSWERS, UPLOADS)
    return Response(content=content, headers={"Content-Disposition": _download_name(d, "pdf")}, media_type="application/pdf")


@router.post("/admin/{empid}/reopen")
def admin_reopen(empid: str, admin: str = Depends(require_employee_form_admin)):
    """Let the employee edit and submit again (e.g. they entered a wrong number or a wrong document)."""
    r = kyc.update_one({"empid": _empid(empid)},
                       {"$set": {"status": "draft", "reopened_by": admin, "updated_at": datetime.now(timezone.utc)}})
    if not r.matched_count:
        raise HTTPException(404, "No KYC form for this employee")
    return {"success": True}
