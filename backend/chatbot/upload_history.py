"""
Document upload history — backs the "document history" list shown under
each bot's knowledge-base card in the admin panel (HR Policy, Observation
Library), matching what RCM's admin tab already shows via its per-file
Pinecone namespaces (backend/rcm_chatbot/router.py's list_collections).

HR and Library don't have RCM's one-namespace-per-file structure (they
each keep a single knowledge base that Update/Replace act on), so there's
no live per-file listing to read back — this module instead logs each
upload EVENT (who, when, which mode, how much was added) so the admin
panel can show a chronological record even though the underlying store
doesn't remember file boundaries.
"""
import logging
import time

from pymongo import MongoClient

from backend.chatbot.config import chatbot_settings
from backend.database import employee_details_collection

logger = logging.getLogger("chatbot.upload_history")

_client = MongoClient(
    chatbot_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_col = _client[chatbot_settings.CHATBOT_DB_NAME]["chatbot_upload_history"]
_col.create_index([("bot", 1), ("created_at", -1)])


def _employee_name(empid: str) -> str:
    emp = employee_details_collection.find_one({"EmpID": empid}, {"_id": 0, "Emp Name": 1})
    return (emp or {}).get("Emp Name") or empid


def record_upload(bot: str, empid: str, mode: str, filename: str, count: int) -> None:
    """Logs one upload event. Never raises — a logging hiccup must never
    break the actual upload it's describing, so this is best-effort and
    called right after the real ingest already succeeded."""
    try:
        _col.insert_one({
            "bot": bot,
            "empid": empid,
            "name": _employee_name(empid),
            "mode": mode,
            "filename": filename,
            "count": count,
            "created_at": time.time(),
        })
    except Exception:
        logger.exception("Failed to record upload history for bot=%s file=%s", bot, filename)


def list_uploads(bot: str, limit: int = 50) -> list:
    rows = list(
        _col.find({"bot": bot}, {"_id": 0}).sort("created_at", -1).limit(limit)
    )
    return rows
