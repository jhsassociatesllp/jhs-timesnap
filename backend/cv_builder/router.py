# backend/cv_builder/router.py
"""
CV Builder Module
Employees fill in their profile (dropdowns come from dropdown_masters.json,
generated from Profile_Builder_Excel.xlsx, plus values employees added
themselves) and download their profile as a one-slide PowerPoint built from
templates/CV builder format.pptx (see ppt_profile.py).
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import employee_details_collection, cv_db
from backend.cv_builder import storage
from backend.cv_builder.convert import pptx_to_pdf
from backend.cv_builder.ppt_profile import build_profile_ppt
from backend.cv_builder.resume_parser import extract_texts, parse_resume_texts

router = APIRouter(prefix="/cv-builder", tags=["CV Builder"])

cv_profiles_collection   = cv_db["cv_profiles"]
cv_options_collection    = cv_db["cv_custom_options"]     # values employees added to the dropdowns

_HERE = os.path.dirname(os.path.abspath(__file__))
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


class AreaItem(BaseModel):
    area: str
    details: Optional[List[str]] = []


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
    sector_experience: Optional[List[SectorItem]] = []
    skills_expertise: Optional[List[str]] = []          # framework / tool chips
    expertise_areas: Optional[List[AreaItem]] = []
    next_review_date: Optional[str] = ""
    profile_status: Optional[str] = "Draft"
    ppt_required: Optional[str] = ""


_PROFILE_DEFAULTS: Dict[str, Any] = {
    "professional_photo": "", "email": "", "phone": "", "location": "", "summary": "",
    "qualification": [], "qualification_details": {}, "membership": [], "membership_details": {},
    "membership_id": "", "sector_experience": [], "skills_expertise": [], "expertise_areas": [],
    "next_review_date": "", "profile_status": "Draft", "ppt_required": "",
    "updated_at": None,
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
    return _expose_photo(doc)


_PHOTO_IN_GRIDFS = "gridfs"          # marker kept in the profile; the image itself is in GridFS
_PHOTO_KEEP = "__keep__"             # sent by the form when the photo is unchanged


def _expose_photo(doc: dict) -> dict:
    """What the browser gets: a URL for a GridFS photo (legacy inline images are passed through)."""
    if doc.get("professional_photo") == _PHOTO_IN_GRIDFS:
        ts = doc.get("updated_at")
        stamp = int(ts.replace(tzinfo=timezone.utc).timestamp()) if isinstance(ts, datetime) else 0
        doc["professional_photo"] = f"/cv-builder/photo?v={stamp}"
    return doc


@router.get("/photo")
def get_photo(current_user: str = Depends(get_current_user)):
    data = storage.get_photo(current_user.strip().upper())
    if not data:
        raise HTTPException(404, "No photo")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/profile")
def save_profile(body: CVProfileModel, current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    emp_info = _employee_info(empid)
    now = datetime.now(timezone.utc)
    data = body.dict()
    data["expertise_areas"] = [{"area": a["area"].strip()[:26], "details": [d.strip()[:38] for d in a.get("details") or [] if d.strip()][:3]}
                               for a in data.get("expertise_areas") or [] if (a.get("area") or "").strip()][:4]
    data["designation"] = body.designation or emp_info["designation"]
    data["department"] = body.department or emp_info["department"]
    data["profile_status"] = "Filled"
    who = empid
    data["qualification"] = _canonical_list("qualification", body.qualification, who)
    data["membership"] = _canonical_list("membership", body.membership, who)
    data["skills_expertise"] = _canonical_list("skills", body.skills_expertise, who)
    secs = _canonical_list("sector", [x.sector for x in body.sector_experience or []], who)
    dur = {x.sector.strip().lower(): (x.duration or "") for x in body.sector_experience or []}
    data["sector_experience"] = [{"sector": x, "duration": dur.get(x.lower(), "")} for x in secs]
    existing = cv_profiles_collection.find_one({"empid": empid})
    data["professional_photo"] = _store_photo(empid, body.professional_photo, existing)
    payload = {"empid": empid, "employee_name": emp_info["name"], **data, "updated_at": now}
    payload["created_at"] = existing.get("created_at", now) if existing else now
    if existing:
        cv_profiles_collection.replace_one({"empid": empid}, payload)
    else:
        cv_profiles_collection.insert_one(payload)
    payload.pop("_id", None)
    return {"success": True, "profile": _expose_photo(payload)}


def _store_photo(empid: str, value: Optional[str], existing: Optional[dict]) -> str:
    """Put a newly chosen photo in GridFS; returns the value to keep in the profile."""
    value = (value or "").strip()
    had = (existing or {}).get("professional_photo")
    if value.startswith("data:image/"):
        try:
            storage.save_photo(empid, storage.normalize_photo(value))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _PHOTO_IN_GRIDFS
    if value == _PHOTO_KEEP or value.startswith("/cv-builder/photo"):
        if had == _PHOTO_IN_GRIDFS:
            return _PHOTO_IN_GRIDFS
        if had and had.startswith("data:image/"):                 # profile saved before GridFS: move it over now
            try:
                storage.save_photo(empid, storage.normalize_photo(had))
                return _PHOTO_IN_GRIDFS
            except ValueError:
                return ""
        return ""
    storage.delete_photo(empid)                                   # empty = photo removed
    return ""


@router.delete("/profile")
def clear_profile(current_user: str = Depends(get_current_user)):
    """Delete the signed-in employee's saved CV profile so they can start again.
    Only their own record is touched; shared dropdown suggestions are left alone."""
    empid = current_user.strip().upper()
    result = cv_profiles_collection.delete_one({"empid": empid})
    storage.delete_all(empid)                                    # photo and stored slide
    return {"success": True, "deleted": result.deleted_count}


# ── Downloads ─────────────────────────────────────────────────────────────────
def _stored_profile(empid: str) -> dict:
    profile = cv_profiles_collection.find_one({"empid": empid})
    if not profile:
        raise HTTPException(404, "Profile not found. Please save your profile first.")
    profile.pop("_id", None)
    return profile


_PPT_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _slide_bytes(profile: dict, empid: str) -> bytes:
    """The profile slide, from GridFS when it was built from the current profile, else built and stored."""
    version = str(profile.get("updated_at") or "")
    stem = "Profile_" + re.sub(r"[^\w\-]", "_", (profile.get("employee_name") or empid).strip())
    if version:
        stored = storage.get_cv(empid, version)
        if stored:
            return stored
    build_from = dict(profile)
    if build_from.get("professional_photo") == _PHOTO_IN_GRIDFS:
        jpeg = storage.get_photo(empid)
        build_from["professional_photo"] = ("data:image/jpeg;base64," + base64.b64encode(jpeg).decode()) if jpeg else ""
    data = build_profile_ppt(build_from, profile.get("employee_name") or empid)
    if version:
        storage.save_cv(empid, version, data, f"{stem}.pptx")
    return data


def _ppt_response(profile: dict, empid: str):
    try:
        data = _slide_bytes(profile, empid)
    except Exception as e:
        raise HTTPException(500, f"Profile PPT generation failed: {e}")
    stem = "Profile_" + re.sub(r"[^\w\-]", "_", (profile.get("employee_name") or empid).strip())
    return Response(content=data, media_type=_PPT_MIME,
                    headers={"Content-Disposition": f"attachment; filename={stem}.pptx"})


def _view_response(profile: dict, empid: str):
    """The slide as an inline PDF, for viewing in the browser."""
    try:
        pdf = pptx_to_pdf(_slide_bytes(profile, empid))
    except RuntimeError as e:
        raise HTTPException(501 if "not available" in str(e) else 500, str(e))
    except Exception as e:
        raise HTTPException(500, f"Profile view failed: {e}")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=profile.pdf", "Cache-Control": "no-store"})


@router.get("/view")
def view_profile(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    return _view_response(_stored_profile(empid), empid)


@router.get("/download/ppt")
def download_profile_ppt(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    profile = _stored_profile(empid)
    return _ppt_response(profile, empid)


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
            "updated_at": (pr or {}).get("updated_at"),
        })
    for empid, pr in profiles.items():          # profiles of ids missing from the roster
        if empid not in seen:
            rows.append({"empid": empid, "name": pr.get("employee_name") or empid, "manager": "", "partner": "",
                         "filled": True, "profile_status": pr.get("profile_status", ""),
                         "updated_at": pr.get("updated_at")})
    rows.sort(key=lambda r: (not r["filled"], r["empid"]))
    return {"total": len(rows), "filled": sum(1 for r in rows if r["filled"]), "rows": rows}


@router.get("/admin/view/{empid}")
def cv_admin_view(empid: str, _: str = Depends(require_cv_admin)):
    empid = empid.strip().upper()
    return _view_response(_stored_profile(empid), empid)


@router.get("/admin/ppt/{empid}")
def cv_admin_ppt(empid: str, _: str = Depends(require_cv_admin)):
    empid = empid.strip().upper()
    return _ppt_response(_stored_profile(empid), empid)
