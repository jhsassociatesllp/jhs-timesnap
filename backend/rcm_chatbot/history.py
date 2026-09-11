"""
Per-user RCM chat history, stored in MongoDB — same per-empid-document/
nested-sessions model as backend/chatbot/history.py, pointed at its own
collection (rcm_chat_history) in the same chatbot Mongo database.
"""
import time
from typing import Dict, List

from pymongo import MongoClient

from backend.rcm_chatbot.config import rcm_settings

_client = MongoClient(
    rcm_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=rcm_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=rcm_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_db = _client[rcm_settings.CHATBOT_DB_NAME]
_col = _db[rcm_settings.HISTORY_COLLECTION_NAME]

_col.create_index("empid", unique=True)


def _make_title(first_message: str) -> str:
    text = " ".join(first_message.split())
    return text[:48] + ("…" if len(text) > 48 else "")


def ensure_session(empid: str, session_id: str, first_message: str) -> None:
    now = time.time()

    touched = _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {"$set": {"sessions.$.updated_at": now}},
    )
    if touched.matched_count:
        return

    _col.update_one(
        {"empid": empid},
        {"$setOnInsert": {"empid": empid, "sessions": []}},
        upsert=True,
    )
    _col.update_one(
        {"empid": empid, "sessions.session_id": {"$ne": session_id}},
        {
            "$push": {
                "sessions": {
                    "session_id": session_id,
                    "title": _make_title(first_message),
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                }
            }
        },
    )


def append_turn(empid: str, session_id: str, user_content: str, assistant_content: str) -> None:
    now = time.time()
    _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {
            "$push": {
                "sessions.$.messages": {
                    "$each": [
                        {"role": "user", "content": user_content, "created_at": now},
                        {"role": "assistant", "content": assistant_content, "created_at": now},
                    ]
                }
            },
            "$set": {"sessions.$.updated_at": now},
        },
    )


def save_turn(empid: str, session_id: str, user_content: str, assistant_content: str) -> None:
    ensure_session(empid, session_id, first_message=user_content)
    append_turn(empid, session_id, user_content, assistant_content)


def get_messages(empid: str, session_id: str) -> List[Dict]:
    doc = _col.find_one(
        {"empid": empid, "sessions.session_id": session_id},
        {"sessions.$": 1},
    )
    if not doc or not doc.get("sessions"):
        return []
    session = doc["sessions"][0]
    return [
        {
            "role": m["role"],
            "content": m["content"],
            "created_at": m.get("created_at"),
        }
        for m in session.get("messages", [])
    ]


def get_recent_messages(empid: str, session_id: str, max_turns: int) -> List[Dict[str, str]]:
    messages = get_messages(empid, session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages[-max_turns * 2:]]


def list_sessions(empid: str) -> List[Dict]:
    doc = _col.find_one({"empid": empid}, {"sessions": 1})
    if not doc:
        return []
    sessions = doc.get("sessions", [])
    sessions_sorted = sorted(sessions, key=lambda s: s.get("updated_at", 0), reverse=True)
    return [
        {
            "id": s["session_id"],
            "title": s["title"],
            "updated_at": s["updated_at"],
        }
        for s in sessions_sorted
    ]


def delete_session(empid: str, session_id: str) -> None:
    _col.update_one(
        {"empid": empid},
        {"$pull": {"sessions": {"session_id": session_id}}},
    )
