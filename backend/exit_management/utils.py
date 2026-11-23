# backend/exit_management/utils.py
"""Small helpers: date conversion and JSON-safe output."""
from datetime import date, datetime, timezone
from typing import Optional

from backend.exit_management.serialize import json_safe

_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso_date(value) -> str:
    """Employee_details stores dates as strings like '07/10/2026'.
    Return 'YYYY-MM-DD' (what <input type=date> needs) or '' if unparseable."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def aware(dt: Optional[datetime]) -> Optional[str]:
    """pymongo returns naive UTC datetimes; add the offset so browsers parse them correctly."""
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


ALREADY_SUBMITTED = "You have already submitted your exit form. It cannot be changed."


def public_signature(ref: Optional[dict]) -> Optional[dict]:
    """The signature_file reference as JSON (ObjectId -> str). Never contains file bytes."""
    if not ref:
        return None
    return {"file_id": str(ref.get("gridfs_file_id")), "filename": ref.get("filename"),
            "content_type": ref.get("content_type"), "file_size": ref.get("file_size"),
            "extension": ref.get("extension"), "uploaded_at": aware(ref.get("uploaded_at"))}


def public_form(doc: Optional[dict]) -> Optional[dict]:
    """A stored document as JSON: ObjectId -> str, datetimes -> ISO strings."""
    if not doc:
        return None
    out = {k: v for k, v in doc.items() if k not in ("_id", "created_at", "updated_at", "submitted_at", "signature_file")}
    out["id"] = str(doc["_id"])
    for key in ("created_at", "updated_at", "submitted_at"):
        out[key] = aware(doc.get(key))
    out["signature_file"] = public_signature(doc.get("signature_file"))
    return json_safe(out)                       # nested ObjectIds / datetimes (project_handover, it_clearance, approval) -> strings
