# backend/access_manager/router.py
"""
Control-panel access manager: lets a small, fixed set of employees grant or
revoke the admin modules shown in the Control Panel for other employees.

  timesheet, quality_audit, kra, chatbot, cv  -> module_admin_access collection
  declaration                                 -> Employee Declaration admins collection
"""

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


@router.get("/check")
def check(current_user: str = Depends(get_current_user)):
    return {"is_manager": is_access_manager(current_user), "modules": MODULES}


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
