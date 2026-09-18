"""
Shared admin gate for the JHS Chatbot admin hub (HR Policy / RCM / JHS
Library knowledge-base management) — one "chatbot" module-access check
reused by all three bots' admin endpoints, instead of each bot re-checking
the same thing on its own.

Same pattern as backend/timesheet/timesheet_admin.py's _require_admin_access:
whoever has "chatbot" in their module_admin_access doc (granted via the
Control Panel's /set-module-access) gets access, with a fallback to legacy
admin_details_collection users.
"""
from fastapi import Depends, HTTPException

from backend.auth import get_current_user
from backend.database import admin_details_collection, module_admin_collection

MODULE_KEY = "chatbot"


def require_chatbot_admin(empid: str = Depends(get_current_user)) -> str:
    normalized = empid.strip().upper()
    doc = module_admin_collection.find_one({"empid": normalized})
    if not doc:
        doc = module_admin_collection.find_one({"empid": {"$regex": f"^{normalized}$", "$options": "i"}})
    if not doc or MODULE_KEY not in doc.get("modules", []):
        legacy = admin_details_collection.find_one({"userid": normalized})
        if not legacy:
            raise HTTPException(status_code=403, detail="Admin access required")
    return empid
