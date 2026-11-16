# backend/access_manager/router.py
"""
Control-panel access manager: lets a small, fixed set of employees grant or
revoke the admin modules shown in the Control Panel for other employees.

  timesheet, quality_audit, kra, chatbot, cv  -> module_admin_access collection
  declaration                                 -> Employee Declaration admins collection
"""

import re
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import db, employee_details_collection, module_admin_collection
from backend.employee_declaration.db import admins as declaration_admins

router = APIRouter(prefix="/access-manager", tags=["Access Manager"])

# Only these employee codes may open the access manager.
ACCESS_MANAGERS = ["JHS1485", "JHS1191", "JHS1283"]

MODULES = {
    "timesheet":     "Timesheet",
    "quality_audit": "Quality Audit",
    "kra":           "KRA",
    "chatbot":       "JHS Chatbot",
    "cv":            "CV Builder",
    "buddy_referral": "Buddy Referral",
    "compliance_calendar": "Compliance Calendar",
    "employee_form": "Employee Application Form",
    "declaration":   "Employee Declaration",
}
_COLLECTION_MODULES = [m for m in MODULES if m != "declaration"]

audit_collection = db["access_manager_audit"]


def is_access_manager(empid: str) -> bool:
    return (empid or "").strip().upper() in ACCESS_MANAGERS


_CORE_ADMIN_MODULES = {"timesheet", "quality_audit", "kra"}


def has_admin_module(empid: str, key: str) -> bool:
    """Access managers and super admins (all three core modules) get every
    optional admin screen; everyone else needs `key` in module_admin_access."""
    empid = (empid or "").strip().upper()
    if empid in ACCESS_MANAGERS:
        return True
    doc = module_admin_collection.find_one({"empid": empid})
    mods = set(doc.get("modules", []) if doc else [])
    return key in mods or _CORE_ADMIN_MODULES.issubset(mods)


def is_cv_admin(empid: str) -> bool:
    return has_admin_module(empid, "cv")


def is_referral_admin(empid: str) -> bool:
    return has_admin_module(empid, "buddy_referral")


def is_employee_form_admin(empid: str) -> bool:
    return has_admin_module(empid, "employee_form")


def is_compliance_admin(empid: str) -> bool:
    """Explicit grant only (via Manage Module Access): access managers and super admins
    do NOT get the Compliance Calendar admin automatically."""
    doc = module_admin_collection.find_one({"empid": (empid or "").strip().upper()})
    return "compliance_calendar" in (doc.get("modules", []) if doc else [])


COMPLIANCE_FIRST_ADMIN = "JHS1485"


def seed_compliance_admin() -> None:
    """One-time: give COMPLIANCE_FIRST_ADMIN the module on first start. A marker stops it
    re-granting later, so revoking in Manage Module Access sticks."""
    try:
        flags = db["app_flags"]
        if flags.find_one({"_id": "compliance_calendar_admin_seeded"}):
            return
        module_admin_collection.update_one(
            {"empid": COMPLIANCE_FIRST_ADMIN},
            {"$set": {"empid": COMPLIANCE_FIRST_ADMIN}, "$addToSet": {"modules": "compliance_calendar"}},
            upsert=True)
        flags.insert_one({"_id": "compliance_calendar_admin_seeded"})
    except Exception:
        pass   # never block start-up; grant it from Manage Module Access instead


def require_compliance_admin(current_user: str = Depends(get_current_user)) -> str:
    if not is_compliance_admin(current_user):
        raise HTTPException(403, "Compliance Calendar admin access required")
    return current_user


def require_employee_form_admin(current_user: str = Depends(get_current_user)) -> str:
    if not is_employee_form_admin(current_user):
        raise HTTPException(403, "Employee Application Form admin access required")
    return current_user


def require_cv_admin(current_user: str = Depends(get_current_user)) -> str:
    if not is_cv_admin(current_user):
        raise HTTPException(403, "CV admin access required")
    return current_user


def require_referral_admin(current_user: str = Depends(get_current_user)) -> str:
    if not is_referral_admin(current_user):
        raise HTTPException(403, "Buddy Referral admin access required")
    return current_user


def require_manager(current_user: str = Depends(get_current_user)) -> str:
    if not is_access_manager(current_user):
        raise HTTPException(403, "You are not allowed to manage access")
    return current_user.strip().upper()


def _emp(empid: str):
    return employee_details_collection.find_one({"EmpID": (empid or "").strip().upper()})


def _name(emp, fallback=""):
    return (emp or {}).get("Emp Name") or (emp or {}).get("EmployeeName") or (emp or {}).get("Name") or fallback


def _current_modules(empid: str) -> List[str]:
    doc = module_admin_collection.find_one({"empid": empid})
    mods = [m for m in (doc.get("modules", []) if doc else []) if m in _COLLECTION_MODULES]
    if declaration_admins.find_one({"empid": empid}):
        mods.append("declaration")
    return mods


def has_control_panel(empid: str) -> bool:
    """True when the employee has at least one Control Panel module (or manages access), so the
    Control Panel button shows on the modules page as soon as any module is granted."""
    empid = (empid or "").strip().upper()
    if is_access_manager(empid):
        return True
    doc = module_admin_collection.find_one({"empid": empid}) or module_admin_collection.find_one(
        {"empid": {"$regex": f"^{re.escape(empid)}$", "$options": "i"}})
    if any(m != "resume_ranker" for m in (doc.get("modules", []) if doc else [])):
        return True
    return declaration_admins.find_one({"empid": empid}) is not None


@router.get("/check")
def check(current_user: str = Depends(get_current_user)):
    return {"is_manager": is_access_manager(current_user), "modules": MODULES,
            "has_control_panel": has_control_panel(current_user)}


@router.get("/user/{empid}")
def get_user(empid: str, _: str = Depends(require_manager)):
    empid = empid.strip().upper()
    emp = _emp(empid)
    if not emp:
        raise HTTPException(404, "Employee not found")
    return {"empid": empid, "name": _name(emp, empid), "modules": _current_modules(empid)}


@router.get("/list")
def list_access(_: str = Depends(require_manager)):
    """Everyone who currently has at least one control-panel module."""
    holders = {}
    for d in module_admin_collection.find({}):
        mods = [m for m in d.get("modules", []) if m in _COLLECTION_MODULES]
        if mods and d.get("empid"):
            holders[d["empid"].strip().upper()] = mods
    for d in declaration_admins.find({}):
        e = (d.get("empid") or "").strip().upper()
        if e:
            holders.setdefault(e, []).append("declaration")
    rows = []
    for empid, mods in sorted(holders.items()):
        rows.append({"empid": empid, "name": _name(_emp(empid), empid), "modules": mods,
                     "is_manager": empid in ACCESS_MANAGERS})
    return {"rows": rows}


class SetAccessBody(BaseModel):
    empid: str
    modules: List[str]          # the full set the employee should have; [] revokes everything


@router.post("/set")
def set_access(body: SetAccessBody, manager: str = Depends(require_manager)):
    empid = body.empid.strip().upper()
    emp = _emp(empid)
    if not emp:
        raise HTTPException(404, "Employee not found")
    wanted = [m for m in dict.fromkeys(body.modules) if m in MODULES]
    if len(wanted) != len(set(body.modules)):
        raise HTTPException(400, "Unknown module in request")

    before = _current_modules(empid)
    coll_mods = [m for m in wanted if m in _COLLECTION_MODULES]
    existing = module_admin_collection.find_one({"empid": empid}) or {}
    legacy = [m for m in existing.get("modules", []) if m not in _COLLECTION_MODULES]   # keep unknown/other keys untouched
    final = coll_mods + legacy
    if final:
        module_admin_collection.update_one(
            {"empid": empid}, {"$set": {"empid": empid, "modules": final}}, upsert=True)
    else:
        module_admin_collection.delete_one({"empid": empid})
    if "declaration" in wanted:
        declaration_admins.update_one({"empid": empid}, {"$setOnInsert": {"empid": empid}}, upsert=True)
    else:
        declaration_admins.delete_one({"empid": empid})

    audit_collection.insert_one({
        "changed_by": manager, "target": empid, "target_name": _name(emp, empid),
        "before": before, "after": wanted, "at": datetime.now(timezone.utc),
    })
    return {"success": True, "empid": empid, "name": _name(emp, empid), "modules": wanted}


# ── Main-page module visibility ───────────────────────────────────────────────
# Which module cards show on the main (modules) page. Only the owners below can change it.
#   mode "all"        the card shows for everyone (subject to the module's own access rules)
#   mode "restricted" the card is hidden for everyone (the owners included) except the employees granted here
# Visibility only, except HR Policy Quiz where a grant also makes the employee an HR quiz admin.
# Other modules (Quality Audit, Resume Ranker...) keep their own access rules.
VISIBILITY_ADMINS = ["JHS1191", "JHS1485"]

PAGE_MODULES = {
    "timesheet":      "Timesheet",
    "chatbot":        "JHS Chatbot",
    "kra":            "KRA",
    "quality_audit":  "Quality Audit",
    "hr_quiz":        "HR Policy Quiz",
    "declaration":    "Employee Declaration",
    "resume_ranker":  "Resume Ranker",
    "cv":             "CV Builder",
    "buddy_referral": "Buddy Referral",
}

visibility_collection = db["module_visibility"]


def is_visibility_admin(empid: str) -> bool:
    return (empid or "").strip().upper() in VISIBILITY_ADMINS


def require_visibility_admin(current_user: str = Depends(get_current_user)) -> str:
    if not is_visibility_admin(current_user):
        raise HTTPException(403, "Only JHS1191 and JHS1485 can manage module access")
    return current_user.strip().upper()


def _visibility_docs() -> dict:
    return {d["_id"]: d for d in visibility_collection.find({}) if d.get("_id") in PAGE_MODULES}


def _hidden_for(empid: str) -> List[str]:
    empid = (empid or "").strip().upper()
    out = []
    for key, d in _visibility_docs().items():
        if d.get("mode") == "restricted" and empid not in [e.upper() for e in d.get("empids", [])]:
            out.append(key)
    return out


@router.get("/visibility/me")
def my_visibility(current_user: str = Depends(get_current_user)):
    """Modules hidden for the signed-in employee, and whether they may manage visibility."""
    return {"hidden": _hidden_for(current_user), "can_manage": is_visibility_admin(current_user)}


@router.get("/visibility")
def get_visibility(_: str = Depends(require_visibility_admin)):
    docs = _visibility_docs()
    rows = []
    for key, label in PAGE_MODULES.items():
        d = docs.get(key) or {}
        empids = sorted({e.strip().upper() for e in d.get("empids", []) if e})
        rows.append({"key": key, "label": label,
                     "mode": "restricted" if d.get("mode") == "restricted" else "all",
                     "employees": [{"empid": e, "name": _name(_emp(e), e)} for e in empids]})
    return {"rows": rows}


class VisibilityModeBody(BaseModel):
    module: str
    mode: str                    # "all" | "restricted"


@router.post("/visibility/mode")
def set_visibility_mode(body: VisibilityModeBody, who: str = Depends(require_visibility_admin)):
    if body.module not in PAGE_MODULES:
        raise HTTPException(400, "Unknown module")
    if body.mode not in ("all", "restricted"):
        raise HTTPException(400, "Mode must be 'all' or 'restricted'")
    visibility_collection.update_one({"_id": body.module}, {"$set": {"mode": body.mode}}, upsert=True)
    audit_collection.insert_one({"changed_by": who, "target": body.module, "kind": "visibility_mode",
                                 "after": body.mode, "at": datetime.now(timezone.utc)})
    return {"success": True}


class VisibilityGrantBody(BaseModel):
    module: str
    empid: str
    grant: bool                  # True = give access, False = revoke


@router.post("/visibility/grant")
def set_visibility_grant(body: VisibilityGrantBody, who: str = Depends(require_visibility_admin)):
    if body.module not in PAGE_MODULES:
        raise HTTPException(400, "Unknown module")
    empid = body.empid.strip().upper()
    emp = _emp(empid)
    if not emp:
        raise HTTPException(404, "Employee not found")
    op = {"$addToSet": {"empids": empid}} if body.grant else {"$pull": {"empids": empid}}
    visibility_collection.update_one({"_id": body.module}, op, upsert=True)
    if body.module == "hr_quiz":
        _sync_hr_quiz_admin(empid, body.grant)
    audit_collection.insert_one({"changed_by": who, "target": empid, "kind": "visibility_grant",
                                 "module": body.module, "after": "granted" if body.grant else "revoked",
                                 "at": datetime.now(timezone.utc)})
    return {"success": True, "empid": empid, "name": _name(emp, empid)}


def _sync_hr_quiz_admin(empid: str, grant: bool) -> None:
    """The HR Policy Quiz card also needs the employee to be an HR quiz admin, so a grant here adds them
    to that list and a revoke removes them again - but only if this panel added them (people who were
    admins before are never removed)."""
    from backend.hr_policy_quiz.db import hr_quiz_admins     # lazy: needs the HR_QUIZ_* settings
    if grant:
        if not hr_quiz_admins.find_one({"empid": empid}):
            hr_quiz_admins.insert_one({"empid": empid, "granted_via": "module_access"})
    else:
        hr_quiz_admins.delete_one({"empid": empid, "granted_via": "module_access"})
