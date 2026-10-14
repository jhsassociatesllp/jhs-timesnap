# backend/compliance_calendar/router.py
"""
Compliance Calendar: statutory due dates shown on the platform calendar, in the
modules-page marquee and in the login "due this week" popup.

  * seed.json     - dates imported from the Excel workbooks (build_seed.py)
  * Mongo         - dates admins add manually from the Control Panel
"""
import json
import os
from datetime import date, datetime, timezone
from typing import List

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.access_manager.router import is_compliance_admin, require_compliance_admin
from backend.auth import get_current_user
from backend.compliance_calendar.build_seed import group_key
from backend.database import compliance_db

router = APIRouter(prefix="/compliance-calendar", tags=["Compliance Calendar"])

custom_items = compliance_db["compliance_calendar_items"]

_SEED_PATH = os.path.join(os.path.dirname(__file__), "seed.json")
with open(_SEED_PATH, encoding="utf-8") as _fh:
    _SEED = [{**r, "id": f"s{i}", "source": "excel"} for i, r in enumerate(json.load(_fh))]


def _custom_row(d: dict) -> dict:
    return {"id": str(d["_id"]), "law": d["law"], "compliance": d["compliance"], "date": d["date"],
            "group": d.get("group") or group_key(d["law"], d["compliance"]), "source": "manual"}


@router.get("/items")
def list_items(_: str = Depends(get_current_user)):
    rows = _SEED + [_custom_row(d) for d in custom_items.find({})]
    rows.sort(key=lambda r: (r["date"], r["law"], r["compliance"]))
    return {"items": rows}


@router.get("/admin/access-check")
def admin_access_check(current_user: str = Depends(get_current_user)):
    return {"is_admin": is_compliance_admin(current_user)}


@router.get("/admin/items")
def admin_items(_: str = Depends(require_compliance_admin)):
    rows = [dict(_custom_row(d), added_by=d.get("added_by", ""),
                 created_at=d["created_at"].isoformat() if d.get("created_at") else "")
            for d in custom_items.find({}).sort("date", 1)]
    laws = sorted({r["law"] for r in _SEED} | {r["law"] for r in rows})
    return {"items": rows, "laws": laws}


class ItemBody(BaseModel):
    law: str = Field(min_length=1, max_length=60)
    compliance: str = Field(min_length=1, max_length=500)
    date: str   # YYYY-MM-DD


@router.post("/admin/items")
def add_item(body: ItemBody, admin: str = Depends(require_compliance_admin)):
    law, comp = body.law.strip(), " ".join(body.compliance.split())
    if not law or not comp:
        raise HTTPException(400, "Law and compliance are required")
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Due date must be a valid date (YYYY-MM-DD)")
    iso = d.isoformat()
    if custom_items.find_one({"law": law, "compliance": comp, "date": iso}):
        raise HTTPException(409, "This due date has already been added")
    doc = {"law": law, "compliance": comp, "date": iso, "group": group_key(law, comp),
           "added_by": admin.strip().upper(), "created_at": datetime.now(timezone.utc)}
    doc["_id"] = custom_items.insert_one(doc).inserted_id
    return {"success": True, "item": _custom_row(doc)}


@router.delete("/admin/items/{item_id}")
def delete_item(item_id: str, _: str = Depends(require_compliance_admin)):
    try:
        oid = ObjectId(item_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Item not found")
    if not custom_items.delete_one({"_id": oid}).deleted_count:
        raise HTTPException(404, "Item not found")
    return {"success": True}
