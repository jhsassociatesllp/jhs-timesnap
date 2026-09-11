"""Mongo-backed data access: facets, faceted/text search, single-record lookup.

Ported from the standalone JHS Library project — only change is reading the
connection string from library_settings (this app's env convention) instead
of a bare os.getenv() call.
"""
import threading
import time

from pymongo import MongoClient

from backend.library_chatbot.config import library_settings
from backend.library_chatbot.taxonomy import FACET_FIELDS, RISK_SEVERITY_ORDER

_client = MongoClient(library_settings.MONGODB_URI)
collection = _client[library_settings.MONGO_DB][library_settings.MONGO_COLLECTION]

_PROJECTION = {"_id": 0}

_facets_cache = {"data": None, "ts": 0}
_FACETS_TTL_SECONDS = 300
_facets_lock = threading.Lock()


def _sorted_values(field: str, values: list) -> list:
    values = [v for v in values if v]
    if field == "risk":
        values.sort(key=lambda v: RISK_SEVERITY_ORDER.get(v, 99))
    else:
        values.sort(key=str.lower)
    return values


def get_facets(force_refresh: bool = False, filters: dict = None, text_query: str = "") -> dict:
    """Distinct values per filterable field.

    With no active filters/search, returns the cheap in-process-cached
    global list (unchanged fast path — this is what a fresh page load
    hits). Once the caller has any filter or search term active, facet
    values are computed live and CASCADED: each field's own options are
    computed with every OTHER active filter applied (but never itself —
    a facet always shows what else remains possible, not just the one
    value you already picked), so picking a Sector narrows what Risk/
    Process Area/etc. options are even worth showing, standard faceted-
    search behavior. Not cached, since the result depends on the exact
    filter combination; the collection is small enough (~7k rows) for a
    handful of live distinct() calls per request to stay fast."""
    filters = {k: v for k, v in (filters or {}).items() if k in FACET_FIELDS and v}
    if not filters and not (text_query and text_query.strip()):
        now = time.time()
        if not force_refresh and _facets_cache["data"] is not None and now - _facets_cache["ts"] < _FACETS_TTL_SECONDS:
            return _facets_cache["data"]

        with _facets_lock:
            now = time.time()
            if not force_refresh and _facets_cache["data"] is not None and now - _facets_cache["ts"] < _FACETS_TTL_SECONDS:
                return _facets_cache["data"]

            data = {field: _sorted_values(field, collection.distinct(field)) for field in FACET_FIELDS}
            _facets_cache["data"] = data
            _facets_cache["ts"] = now
            return data

    base_filter = {}
    if text_query and text_query.strip():
        base_filter["$text"] = {"$search": text_query.strip()}

    data = {}
    for field in FACET_FIELDS:
        mongo_filter = dict(base_filter)
        for other_field, values in filters.items():
            if other_field != field:
                mongo_filter[other_field] = {"$in": values}
        data[field] = _sorted_values(field, collection.distinct(field, mongo_filter))
    return data


def _risk_sort_key(doc):
    return RISK_SEVERITY_ORDER.get(doc.get("risk", ""), 99)


def query_observations(filters: dict, text_query: str = "", page: int = 1, page_size: int = 20):
    """filters: {field: [values]} for any field in FACET_FIELDS.
    text_query: free text, matched against the Mongo text index when present.
    Returns (rows, total)."""
    mongo_filter = {}
    for field, values in (filters or {}).items():
        if field in FACET_FIELDS and values:
            mongo_filter[field] = {"$in": values}

    sort = None
    if text_query and text_query.strip():
        mongo_filter["$text"] = {"$search": text_query.strip()}
        sort = [("score", {"$meta": "textScore"})]
        projection = dict(_PROJECTION, score={"$meta": "textScore"})
    else:
        projection = _PROJECTION

    total = collection.count_documents(mongo_filter)
    skip = max(page - 1, 0) * page_size

    cursor = collection.find(mongo_filter, projection)
    if sort:
        cursor = cursor.sort(sort)
    rows = list(cursor.skip(skip).limit(page_size))

    if not text_query:
        rows.sort(key=_risk_sort_key)

    for r in rows:
        r.pop("score", None)

    return rows, total


def get_breakdown(field: str, filters: dict = None) -> list:
    """Count of observations grouped by `field`'s distinct values, optionally
    scoped by other active filters (never by `field` itself — grouping by
    the same field you're filtering on would just reproduce the filter).
    Returns [{"value": ..., "count": ...}, ...] — risk-severity ordered for
    field=='risk', highest count first otherwise."""
    mongo_filter = {}
    for f, values in (filters or {}).items():
        if f in FACET_FIELDS and f != field and values:
            mongo_filter[f] = {"$in": values}

    pipeline = [
        {"$match": mongo_filter},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
    ]
    results = collection.aggregate(pipeline)
    rows = [{"value": r["_id"], "count": r["count"]} for r in results if r["_id"]]

    if field == "risk":
        rows.sort(key=lambda r: RISK_SEVERITY_ORDER.get(r["value"], 99))
    else:
        rows.sort(key=lambda r: -r["count"])
    return rows


def get_by_sr_no(sr_no: int):
    return collection.find_one({"sr_no": sr_no}, _PROJECTION)


def get_many_by_sr_no(sr_nos: list):
    docs = list(collection.find({"sr_no": {"$in": sr_nos}}, _PROJECTION))
    by_id = {d["sr_no"]: d for d in docs}
    return [by_id[s] for s in sr_nos if s in by_id]


def get_stats():
    total = collection.count_documents({})
    risk_counts = {}
    for row in collection.aggregate([{"$group": {"_id": "$risk", "count": {"$sum": 1}}}]):
        if row["_id"]:
            risk_counts[row["_id"]] = row["count"]

    def top(field, limit=8):
        pipeline = [
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        return [{"name": r["_id"], "count": r["count"]} for r in collection.aggregate(pipeline) if r["_id"]]

    return {
        "total": total,
        "risk_counts": risk_counts,
        "sectors": top("sector"),
        "audit_types": top("audit_type"),
    }
