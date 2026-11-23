# backend/exit_management/serialize.py
"""JSON-safe conversion of MongoDB documents, used only inside Employee Exit Management."""
from datetime import date, datetime, timezone

from bson import ObjectId


def json_safe(value):
    """Return `value` with every ObjectId turned into a string and every datetime/date into an ISO string,
    recursively through dicts, lists and tuples. Other values are returned unchanged (GridFS file bytes are never in these documents)."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:                                  # pymongo returns naive UTC datetimes
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
