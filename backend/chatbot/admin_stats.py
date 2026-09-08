"""
Cross-bot usage statistics for the chatbot admin Dashboard tab
(static/chatbot/admin.html) — active users and message-activity breakdown
per bot, computed from each bot's own chat-history collection.

All three history collections (backend/chatbot/history.py,
backend/rcm_chatbot/history.py, backend/library_chatbot/history.py) share
the identical document shape — one document per empid, containing nested
sessions of messages — so this is written once here against a raw pymongo
Collection, and the admin router (backend/chatbot/router.py) calls it once
per bot's collection rather than each bot re-implementing the same
aggregation.
"""
import datetime

from pymongo.collection import Collection

from backend.database import employee_details_collection


def _employee_name(empid: str) -> str:
    emp = employee_details_collection.find_one({"EmpID": empid}, {"_id": 0, "Emp Name": 1})
    return (emp or {}).get("Emp Name") or empid


def active_user_count(collection: Collection) -> int:
    """All-time distinct users — one document per empid, so this is just a
    document count."""
    return collection.count_documents({})


def user_activity(collection: Collection, limit: int = 200) -> list:
    """Per-user message counts (today / this week / this month / all-time),
    most active first. `limit` caps how many users are returned — the
    dashboard table doesn't need to render thousands of rows at once."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    today_ts = datetime.datetime.combine(today, datetime.time.min).timestamp()
    week_ts = datetime.datetime.combine(week_start, datetime.time.min).timestamp()
    month_ts = datetime.datetime.combine(month_start, datetime.time.min).timestamp()

    pipeline = [
        {"$unwind": "$sessions"},
        {"$unwind": "$sessions.messages"},
        {
            "$group": {
                "_id": "$empid",
                "all_time": {"$sum": 1},
                "this_month": {"$sum": {"$cond": [{"$gte": ["$sessions.messages.created_at", month_ts]}, 1, 0]}},
                "this_week": {"$sum": {"$cond": [{"$gte": ["$sessions.messages.created_at", week_ts]}, 1, 0]}},
                "today": {"$sum": {"$cond": [{"$gte": ["$sessions.messages.created_at", today_ts]}, 1, 0]}},
                "last_active": {"$max": "$sessions.messages.created_at"},
            }
        },
        {"$sort": {"all_time": -1}},
        {"$limit": limit},
    ]
    rows = list(collection.aggregate(pipeline))
    return [
        {
            "empid": r["_id"],
            "name": _employee_name(r["_id"]),
            "today": r["today"],
            "this_week": r["this_week"],
            "this_month": r["this_month"],
            "all_time": r["all_time"],
            "last_active": r.get("last_active"),
        }
        for r in rows
    ]
