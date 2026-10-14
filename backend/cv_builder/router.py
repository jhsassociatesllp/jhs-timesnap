# backend/cv_builder/router.py
"""
CV Builder Module
Employees fill in their profile (dropdowns come from dropdown_masters.json,
generated from Profile_Builder_Excel.xlsx, plus values employees added
themselves) and download their CV as Word or PDF in one of five templates
(see docx_fill.py / templates/). Profiles marked "PPT Profile Required" can also
download a red & white profile slide (ppt_profile.py).
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import employee_details_collection, cv_db
from backend.cv_builder.convert import docx_to_pdf, pdf_available
from backend.cv_builder.docx_fill import SECTIONS, render_docx, section_spec
from backend.cv_builder.ppt_profile import build_profile_ppt
from backend.cv_builder.resume_parser import extract_texts, parse_resume_texts

router = APIRouter(prefix="/cv-builder", tags=["CV Builder"])

cv_profiles_collection   = cv_db["cv_profiles"]
cv_options_collection    = cv_db["cv_custom_options"]     # values employees added to the dropdowns

_HERE = os.path.dirname(os.path.abspath(__file__))
# Template preview images (rendered from the Word templates)
_TPL_DIR = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "static", "cv_builder")
_TPL_IDS = ("1", "2", "3", "4", "5")
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

with open(os.path.join(_HERE, "dropdown_masters.json"), encoding="utf-8") as _f:
    DROPDOWN_MASTERS = json.load(_f)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _employee_info(empid: str) -> dict:
    emp = employee_details_collection.find_one({"EmpID": empid})
    if not emp:
        return {"name": empid, "designation": "", "department": "", "email": ""}
    return {
        "name": emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or empid,
        "designation": emp.get("Designation Name") or emp.get("Designation") or "",
        "department": emp.get("Department") or emp.get("Branch Name") or "",
        "email": emp.get("EMail") or emp.get("Email") or emp.get("Personal EMail") or "",
    }


from backend.access_manager.router import is_cv_admin, require_cv_admin  # noqa: E402


# ── Custom dropdown values (qualification / skills / sector / membership) ─────
# Employees may type a value that is not in the list. It is stored once,
# compared case-insensitively, and suggested to everyone from then on.
_OPTION_LISTS = {
    "qualification": "qualifications",
    "skills": "skills_expertise",
    "sector": "sector_experience",
    "membership": "memberships",
}
_VALUE_RE = re.compile(r"^[\w][\w .,&()/+'#:\-]{0,78}[\w).+#]$|^[\w]$")


def _clean_option(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _master_lookup(field: str) -> Dict[str, str]:
    return {v.lower(): v for v in DROPDOWN_MASTERS.get(_OPTION_LISTS[field], [])}


def _register_option(field: str, value: str, who: str = "") -> str:
    """Canonical spelling for `value`; stores it first if it is new.
    Case-insensitive: 'ind as' and 'IND AS' both resolve to the stored 'Ind AS'."""
    v = _clean_option(value)
    if not v:
        return ""
    key = v.lower()
    master = _master_lookup(field)
    if key in master:
        return master[key]
    doc = cv_options_collection.find_one({"field": field, "key": key})
    if doc:
        return doc["value"]
    if len(v) > 80 or not _VALUE_RE.match(v):
        raise HTTPException(400, "Please use letters, numbers and simple punctuation (max 80 characters)")
    cv_options_collection.update_one(
        {"field": field, "key": key},
        {"$setOnInsert": {"field": field, "key": key, "value": v, "created_by": who,
                          "created_at": datetime.now(timezone.utc)}},
        upsert=True)
    doc = cv_options_collection.find_one({"field": field, "key": key})     # a concurrent insert may have won
    return (doc or {}).get("value", v)


def _canonical_list(field: str, values, who: str) -> List[str]:
    out, seen = [], set()
    for v in values or []:
        try:
            cv = _register_option(field, v, who)
        except HTTPException:
            continue
        if cv and cv.lower() not in seen:
            seen.add(cv.lower())
            out.append(cv)
    return out


# ── Pydantic Models ───────────────────────────────────────────────────────────
class SectorItem(BaseModel):
    sector: str
    duration: Optional[str] = ""


class AssignmentItem(BaseModel):
    assignment: Optional[str] = ""
    client: Optional[str] = ""
    sector: Optional[str] = ""
    role: Optional[str] = ""


class CustomSection(BaseModel):
    id: Optional[str] = ""
    title: Optional[str] = ""
    text: Optional[str] = ""          # one bullet per line
    visible: Optional[bool] = True


class SectionConfig(BaseModel):
    hidden: Optional[List[str]] = []                 # section keys removed from the CV
    titles: Optional[Dict[str, str]] = {}            # section key -> custom heading
    custom: Optional[List[CustomSection]] = []       # user-added sections


class CVProfileModel(BaseModel):
    designation: Optional[str] = ""
    department: Optional[str] = ""
    professional_photo: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    location: Optional[str] = ""
    summary: Optional[str] = ""
    qualification: Optional[List[str]] = []
    # {"CA": {"institute": "...", "year": "2017"}}
    qualification_details: Optional[Dict[str, Dict[str, str]]] = {}
    membership: Optional[List[str]] = []
    # {"ICAI": {"level": "Associate Member (ACA)", "number": "M.No. 123"}}
    membership_details: Optional[Dict[str, Dict[str, str]]] = {}
    membership_id: Optional[str] = ""
    total_experience: Optional[str] = ""
    sector_experience: Optional[List[SectorItem]] = []
    skills_expertise: Optional[List[str]] = []
    key_skills: Optional[List[str]] = []
    skills_highlighted: Optional[str] = ""
    achievements: Optional[str] = ""
    certifications: Optional[str] = ""
    key_assignments: Optional[List[AssignmentItem]] = []
    linkedin: Optional[str] = ""
    portfolio: Optional[str] = ""
    page_layout: Optional[str] = "2"          # "1" = single page, "2" = two pages
    next_review_date: Optional[str] = ""
    profile_status: Optional[str] = "Draft"
    ppt_required: Optional[str] = ""
    selected_template: Optional[str] = "1"
    section_config: Optional[SectionConfig] = SectionConfig()


_PROFILE_DEFAULTS: Dict[str, Any] = {
    "professional_photo": "", "email": "", "phone": "", "location": "", "summary": "",
    "qualification": [], "qualification_details": {}, "membership": [], "membership_details": {},
    "membership_id": "", "total_experience": "", "sector_experience": [],
    "skills_expertise": [], "key_skills": [], "skills_highlighted": "", "achievements": "",
    "certifications": "", "key_assignments": [], "linkedin": "", "portfolio": "", "page_layout": "2",
    "next_review_date": "", "profile_status": "Draft", "ppt_required": "", "selected_template": "1",
    "section_config": {"hidden": [], "titles": {}, "custom": []}, "updated_at": None,
}


# ── API Routes ────────────────────────────────────────────────────────────────
@router.get("/dropdowns")
def get_dropdowns():
    """Excel masters plus the values employees have added (shared suggestions)."""
    out = {k: list(v) for k, v in DROPDOWN_MASTERS.items()}
    for field, list_key in _OPTION_LISTS.items():
        have = {v.lower() for v in out.get(list_key, [])}
        extra = sorted((d["value"] for d in cv_options_collection.find({"field": field})),
                       key=lambda x: x.lower())
        out.setdefault(list_key, []).extend(v for v in extra if v.lower() not in have)
    return out


class OptionBody(BaseModel):
    field: str            # qualification | skills | sector | membership
    value: str


@router.post("/options")
def add_option(body: OptionBody, current_user: str = Depends(get_current_user)):
    if body.field not in _OPTION_LISTS:
        raise HTTPException(400, "Unknown field")
    value = _register_option(body.field, body.value, current_user.strip().upper())
    if not value:
        raise HTTPException(400, "Please enter a value")
    return {"field": body.field, "value": value}


# ── Auto-fill from an old resume ──────────────────────────────────────────────
_RESUME_MAX = 5 * 1024 * 1024
_RESUME_MAGIC = {".pdf": b"%PDF", ".docx": b"PK"}


@router.post("/parse-resume")
async def parse_resume_upload(request: Request, name: str = "", current_user: str = Depends(get_current_user)):
    """
    Suggest profile values from an uploaded resume. The file arrives as the raw
    request body and is only ever held in memory: it is not written to disk or
    the database, not logged, and dropped when this request ends. Nothing is
    saved - the browser fills the form and the employee decides what to keep.
    """
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in _RESUME_MAGIC:
        raise HTTPException(400, "Only .pdf and .docx resumes are supported")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _RESUME_MAX:
        raise HTTPException(413, "Resume must be 5 MB or smaller")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > _RESUME_MAX:
            raise HTTPException(413, "Resume must be 5 MB or smaller")
    data = bytes(buf)
    if not data:
        raise HTTPException(400, "The file is empty")
    if not data.startswith(_RESUME_MAGIC[ext]):
        raise HTTPException(400, f"That does not look like a valid {ext[1:].upper()} file")
    try:
        texts = extract_texts(data, ext)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not read that file. Try saving it again as PDF or DOCX.")
    finally:
        del data, buf
    if max(len(t.strip()) for t in texts) < 40:
        raise HTTPException(422, "No readable text found (a scanned image?). Please upload a text-based PDF or a Word file.")
    result = parse_resume_texts(texts, get_dropdowns())
    del texts
    if not result["fields"]:
        raise HTTPException(422, "Could not find any details in that resume. Please fill the form manually.")
    return result


@router.get("/capabilities")
def get_capabilities():
    return {"docx": True, "pdf": pdf_available(), "ppt": True}


@router.get("/sections/{template_id}")
def get_sections(template_id: str):
    """Sections of a template the user can show / hide / rename."""
    if template_id not in SECTIONS:
        raise HTTPException(404, "Template not found")
    return {"template": template_id, "sections": section_spec(template_id)}


@router.get("/template-preview/{tpl_id}")
def get_template_preview(tpl_id: str):
    """Serve the preview image of a Word template."""
    if tpl_id not in _TPL_IDS:
        raise HTTPException(404, "Template not found")
    path = os.path.join(_TPL_DIR, f"tpl{tpl_id}.png")
    if not os.path.exists(path):
        raise HTTPException(404, "Template image file not found")
    return FileResponse(path, media_type="image/png")


@router.get("/profile")
def get_profile(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    emp_info = _employee_info(empid)
    doc = cv_profiles_collection.find_one({"empid": empid})
    if not doc:
        return {
            **_PROFILE_DEFAULTS,
            "empid": empid, "employee_name": emp_info["name"],
            "designation": emp_info["designation"], "department": emp_info["department"],
            # email is left blank on purpose: the employee types it themselves
        }
    doc.pop("_id", None)
    for k, v in _PROFILE_DEFAULTS.items():
        doc.setdefault(k, v)
    return doc


@router.post("/profile")
def save_profile(body: CVProfileModel, current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    emp_info = _employee_info(empid)
    now = datetime.now(timezone.utc)
    data = body.dict()
    data["key_assignments"] = [a for a in data.get("key_assignments") or []
                               if any((a.get(k) or "").strip() for k in ("assignment", "client", "sector", "role"))]
    data["designation"] = body.designation or emp_info["designation"]
    data["department"] = body.department or emp_info["department"]
    data["profile_status"] = body.profile_status or "Draft"
    data["selected_template"] = body.selected_template if body.selected_template in _TPL_IDS else "1"
    data["page_layout"] = "1" if str(body.page_layout) == "1" else "2"
    who = empid
    data["qualification"] = _canonical_list("qualification", body.qualification, who)
    data["membership"] = _canonical_list("membership", body.membership, who)
    data["skills_expertise"] = _canonical_list("skills", body.skills_expertise, who)
    data["key_skills"] = [k for k in _canonical_list("skills", body.key_skills, who) if k in data["skills_expertise"]]
    secs = _canonical_list("sector", [x.sector for x in body.sector_experience or []], who)
    dur = {x.sector.strip().lower(): (x.duration or "") for x in body.sector_experience or []}
    data["sector_experience"] = [{"sector": x, "duration": dur.get(x.lower(), "")} for x in secs]
    payload = {"empid": empid, "employee_name": emp_info["name"], **data, "updated_at": now}
    existing = cv_profiles_collection.find_one({"empid": empid})
    payload["created_at"] = existing.get("created_at", now) if existing else now
    if existing:
        cv_profiles_collection.replace_one({"empid": empid}, payload)
    else:
        cv_profiles_collection.insert_one(payload)
    payload.pop("_id", None)
    return {"success": True, "profile": payload}


@router.delete("/profile")
def clear_profile(current_user: str = Depends(get_current_user)):
    """Delete the signed-in employee's saved CV profile so they can start again.
    Only their own record is touched; shared dropdown suggestions are left alone."""
    empid = current_user.strip().upper()
    result = cv_profiles_collection.delete_one({"empid": empid})
    return {"success": True, "deleted": result.deleted_count}


# ── Downloads ─────────────────────────────────────────────────────────────────
def _stored_profile(empid: str) -> dict:
    profile = cv_profiles_collection.find_one({"empid": empid})
    if not profile:
        raise HTTPException(404, "Profile not found. Please save your profile first.")
    profile.pop("_id", None)
    return profile


def _file_stem(profile: dict, empid: str, template_id: str) -> str:
    return "CV_" + re.sub(r"[^\w\-]", "_", (profile.get("employee_name") or empid).strip()) + f"_T{template_id}"


def _build(template_id: str, empid: str):
    if template_id not in _TPL_IDS:
        raise HTTPException(400, "Invalid template ID (must be 1-5)")
    profile = _stored_profile(empid)
    try:
        data = render_docx(template_id, profile, [], profile.get("employee_name") or empid)
    except Exception as e:
        raise HTTPException(500, f"CV generation failed: {e}")
    return data, _file_stem(profile, empid, template_id)


def _pdf_response(data: bytes, stem: str):
    try:
        pdf = docx_to_pdf(data, "cv")
    except RuntimeError as e:
        raise HTTPException(501 if "not available" in str(e) else 500, str(e))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={stem}.pdf"})


@router.get("/download/docx/{template_id}")
def download_cv_docx(template_id: str, current_user: str = Depends(get_current_user)):
    data, fname = _build(template_id, current_user.strip().upper())
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": f"attachment; filename={fname}.docx"})


@router.get("/download/pdf/{template_id}")
def download_cv_pdf(template_id: str, current_user: str = Depends(get_current_user)):
    data, fname = _build(template_id, current_user.strip().upper())
    return _pdf_response(data, fname)


_PPT_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _ppt_response(profile: dict, empid: str):
    try:
        data = build_profile_ppt(profile, profile.get("employee_name") or empid,
                                 profile.get("selected_template") or "1")
    except Exception as e:
        raise HTTPException(500, f"Profile PPT generation failed: {e}")
    stem = "Profile_" + re.sub(r"[^\w\-]", "_", (profile.get("employee_name") or empid).strip())
    return Response(content=data, media_type=_PPT_MIME,
                    headers={"Content-Disposition": f"attachment; filename={stem}.pptx"})


@router.get("/download/ppt")
def download_profile_ppt(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    profile = _stored_profile(empid)
    if (profile.get("ppt_required") or "").strip().lower() != "yes":
        raise HTTPException(400, 'Set "PPT Profile Required" to Yes and save your profile first.')
    return _ppt_response(profile, empid)


# ── Live preview (unsaved form data) ──────────────────────────────────────────
@router.post("/preview/docx/{template_id}")
def preview_cv_docx(template_id: str, body: CVProfileModel, current_user: str = Depends(get_current_user)):
    """Render the CV from the form as currently filled in (not yet saved)."""
    if template_id not in _TPL_IDS:
        raise HTTPException(400, "Invalid template ID (must be 1-5)")
    empid = current_user.strip().upper()
    emp_info = _employee_info(empid)
    profile = body.dict()
    profile["empid"] = empid
    profile["employee_name"] = emp_info["name"]
    profile["designation"] = profile.get("designation") or emp_info["designation"]
    profile["department"] = profile.get("department") or emp_info["department"]
    try:
        data = render_docx(template_id, profile, [], emp_info["name"])
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")
    return Response(content=data, media_type=_DOCX_MIME, headers={"Cache-Control": "no-store"})


# ── Admin (control panel) ─────────────────────────────────────────────────────
@router.get("/admin/access-check")
def cv_admin_access_check(current_user: str = Depends(get_current_user)):
    return {"is_admin": is_cv_admin(current_user)}


@router.get("/admin/status")
def cv_admin_status(_: str = Depends(require_cv_admin)):
    """Every employee with whether they have filled in their CV profile,
    plus their manager and partner."""
    profiles = {p["empid"]: p for p in cv_profiles_collection.find({}, {"_id": 0})}
    rows, seen = [], set()
    for emp in employee_details_collection.find({}):
        empid = (emp.get("EmpID") or "").strip().upper()
        if not empid or empid in seen:
            continue
        seen.add(empid)
        pr = profiles.get(empid)
        rows.append({
            "empid": empid,
            "name": emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or empid,
            "manager": emp.get("ReportingEmpName") or "",
            "partner": emp.get("Partner") or "",
            "filled": pr is not None,
            "profile_status": (pr or {}).get("profile_status", ""),
            "template": (pr or {}).get("selected_template", ""),
            "ppt": ((pr or {}).get("ppt_required") or "").strip().lower() == "yes",
            "updated_at": (pr or {}).get("updated_at"),
        })
    for empid, pr in profiles.items():          # profiles of ids missing from the roster
        if empid not in seen:
            rows.append({"empid": empid, "name": pr.get("employee_name") or empid, "manager": "", "partner": "",
                         "filled": True, "profile_status": pr.get("profile_status", ""),
                         "template": pr.get("selected_template", ""),
                         "ppt": (pr.get("ppt_required") or "").strip().lower() == "yes",
                         "updated_at": pr.get("updated_at")})
    rows.sort(key=lambda r: (not r["filled"], r["empid"]))
    return {"total": len(rows), "filled": sum(1 for r in rows if r["filled"]), "rows": rows}


@router.get("/admin/download/{empid}/{template_id}")
def cv_admin_download(empid: str, template_id: str, fmt: str = "docx", _: str = Depends(require_cv_admin)):
    """An employee's CV as saved (also used by the admin preview). fmt = docx | pdf"""
    data, fname = _build(template_id, empid.strip().upper())
    if fmt == "pdf":
        return _pdf_response(data, fname)
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": f"attachment; filename={fname}.docx"})


@router.get("/admin/ppt/{empid}")
def cv_admin_ppt(empid: str, _: str = Depends(require_cv_admin)):
    empid = empid.strip().upper()
    return _ppt_response(_stored_profile(empid), empid)
