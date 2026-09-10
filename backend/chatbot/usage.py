"""
Per-bot LLM call-usage tracking — backs the chatbot admin Dashboard's
"API usage per bot" and "$ spent per bot" KPIs.

Tracks call counts always (reliable across every call path, including a
streamed response that returns no token-usage block), and additionally
token counts + an estimated USD cost whenever the caller has them —
non-streaming call_llm() and the JHS Library bot's own OpenAI SDK calls
both get a `usage` block back from the API and pass it through; a
streamed reply just records the call with no tokens, so it still counts
toward "calls" but contributes $0 toward "$ spent" (JHS Library and HR/RCM
answer generation are all non-streaming under the hood — see rag.py's own
note on why — so this covers the overwhelming majority of real spend).

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

# USD per token, from OpenAI's published pricing — an ESTIMATE, not a bill:
# it doesn't account for cached-input discounts, promotional credits, or a
# price change since this was written. Cross-check against the OpenAI
# dashboard's own usage page for anything that actually needs to be exact.
# A model not listed here (e.g. the shared HuggingFace-routed model used
# when a bot has no dedicated OpenAI key) contributes $0 — HuggingFace's
# Inference Providers billing isn't a simple flat per-token USD rate the
# same way, so it's deliberately left untracked rather than guessed at.
MODEL_PRICING_PER_TOKEN = {
    "gpt-4o-mini": {"input": 0.150 / 1_000_000, "output": 0.600 / 1_000_000},
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = MODEL_PRICING_PER_TOKEN.get(model or "")
    if not rates:
        return 0.0
    return prompt_tokens * rates["input"] + completion_tokens * rates["output"]


def record_call(bot: str, model: str = None, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Increments today's LLM call count (and, when token counts are
    available, token totals + estimated USD cost) for `bot`
    ('hr'|'rcm'|'library'). Never raises — a usage-tracking hiccup must
    never break an actual chat reply, so this is called right after a real
    LLM call already succeeded and is best-effort from there."""
    if not bot:
        return
    try:
        today = datetime.date.today().isoformat()
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)
        _col.update_one(
            {"bot": bot, "date": today},
            {"$inc": {
                "calls": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }},
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to record LLM call usage for bot=%s", bot)


def _sum_since(bot: str, since_date: str) -> dict:
    pipeline = [
        {"$match": {"bot": bot, "date": {"$gte": since_date}}},
        {"$group": {
            "_id": None,
            "calls": {"$sum": "$calls"},
            "cost_usd": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
        }},
    ]
    result = list(_col.aggregate(pipeline))
    return result[0] if result else {"calls": 0, "cost_usd": 0.0}


def get_usage(bot: str) -> dict:
    """Returns {"today", "this_week", "this_month", "all_time"} LLM call
    counts for `bot`, plus a "cost_usd" dict with the same four windows
    (estimated — see MODEL_PRICING_PER_TOKEN's own caveat above). Week
    starts Monday; month is calendar-month-to-date."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    windows = {
        "today": _sum_since(bot, today.isoformat()),
        "this_week": _sum_since(bot, week_start.isoformat()),
        "this_month": _sum_since(bot, month_start.isoformat()),
        "all_time": _sum_since(bot, "0001-01-01"),
    }
    return {
        **{k: v["calls"] for k, v in windows.items()},
        "cost_usd": {k: round(v["cost_usd"], 4) for k, v in windows.items()},
    }
