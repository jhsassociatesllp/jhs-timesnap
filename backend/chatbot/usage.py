"""
Per-bot LLM call-usage tracking — backs the chatbot admin Dashboard's
"API usage per bot" numbers.

Tracks CALL COUNTS, not tokens: a token/usage field isn't reliably
available across every call path (a streamed response in particular
doesn't return a usage block by default), while a call count is simple,
always available, and — now that each bot has its own dedicated OpenAI
API key (HR_OPENAI_API_KEY / RCM_OPENAI_API_KEY / LIBRARY_OPENAI_API_KEY)
— maps directly onto that key's own actual usage, since it's the only
caller spending it.

Day-bucketed so the dashboard can show today/this-week/this-month/
all-time without re-scanning everything on every request.
"""
import datetime
import logging

from pymongo import MongoClient

from backend.chatbot.config import chatbot_settings

logger = logging.getLogger("chatbot.usage")

_client = MongoClient(
    chatbot_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_col = _client[chatbot_settings.CHATBOT_DB_NAME]["chatbot_usage"]
_col.create_index([("bot", 1), ("date", 1)], unique=True)


def record_call(bot: str) -> None:
    """Increments today's LLM call count for `bot` ('hr'|'rcm'|'library').
    Never raises — a usage-tracking hiccup must never break an actual
    chat reply, so this is called right after a real LLM call already
    succeeded and is best-effort from there."""
    if not bot:
        return
    try:
        today = datetime.date.today().isoformat()
        _col.update_one({"bot": bot, "date": today}, {"$inc": {"calls": 1}}, upsert=True)
    except Exception:
        logger.exception("Failed to record LLM call usage for bot=%s", bot)


def _sum_since(bot: str, since_date: str) -> int:
    pipeline = [
        {"$match": {"bot": bot, "date": {"$gte": since_date}}},
        {"$group": {"_id": None, "total": {"$sum": "$calls"}}},
    ]
    result = list(_col.aggregate(pipeline))
    return result[0]["total"] if result else 0


def get_usage(bot: str) -> dict:
    """Returns {"today", "this_week", "this_month", "all_time"} LLM call
    counts for `bot`. Week starts Monday; month is calendar-month-to-date."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "today": _sum_since(bot, today.isoformat()),
        "this_week": _sum_since(bot, week_start.isoformat()),
        "this_month": _sum_since(bot, month_start.isoformat()),
        "all_time": _sum_since(bot, "0001-01-01"),
    }
