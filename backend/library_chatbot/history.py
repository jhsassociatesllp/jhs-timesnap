"""
Per-user chat history for the JHS Library "Ask" bot — stored in the SAME
MongoDB database as the HR Policy bot's history (Chat_bot, via the HR bot's
own chatbot_settings/connection), just a different collection
("observation_bot" — fixed name, not meant to change). That's a deliberate
product requirement, not an accident — see backend/chatbot/history.py for
the canonical version of this pattern, which this mirrors document-for-document.

Document shape:
{
  "empid": "JHS001",
  "sessions": [
    {
      "session_id": "uuid",
      "title": "First 48 chars of first message…",
      "created_at": 1234567890.0,
      "updated_at": 1234567890.0,
      "messages": [
        {"role": "user",      "content": "...", "created_at": 1234567890.0},
        {"role": "assistant", "content": "...", "created_at": 1234567890.0, "sr_nos": [1, 4, 5]}
      ]
    }
  ]
}
"""
import time
from typing import Dict, List

from pymongo import MongoClient

from backend.chatbot.config import chatbot_settings
from backend.library_chatbot import data_access

# Reuses the HR Policy bot's Mongo connection/database on purpose — Library
# chat history lives alongside HR/RCM history in Chat_bot, just its own
# collection.
_client = MongoClient(
    chatbot_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_db = _client[chatbot_settings.CHATBOT_DB_NAME]
_col = _db["observation_bot"]

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


def append_turn(empid: str, session_id: str, user_content: str, assistant_content: str, sr_nos: List[int] = None) -> None:
    now = time.time()
    assistant_msg = {"role": "assistant", "content": assistant_content, "created_at": now}
    if sr_nos:
        # The Sr. Nos of whichever observations the answer was actually
        # grounded in — stored so reopening this chat later can still show
        # its "View N observations" panel (see get_messages below).
        # Storing just the ids (not the full row text) so history stays
        # small and always reflects the observation's CURRENT text if it's
        # ever corrected, rather than a frozen copy from when this was asked.
        assistant_msg["sr_nos"] = sr_nos
    _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {
            "$push": {
                "sessions.$.messages": {
                    "$each": [
                        {"role": "user", "content": user_content, "created_at": now},
                        assistant_msg,
                    ]
                }
            },
            "$set": {"sessions.$.updated_at": now},
        },
    )


def save_turn(empid: str, session_id: str, user_content: str, assistant_content: str, sr_nos: List[int] = None) -> None:
    """Persist one full chat turn. `assistant_content` should be the plain
    HTML answer string (same as what the frontend renders). `sr_nos`: the
    Sr. Nos of the observations the answer drew on, if any (see
    append_turn) — omitted/empty for answers that didn't match any rows."""
    ensure_session(empid, session_id, first_message=user_content)
    append_turn(empid, session_id, user_content, assistant_content, sr_nos)


def get_messages(empid: str, session_id: str) -> List[Dict]:
    """Each assistant message that had matching observations includes
    `rows` — the full current row data for its stored sr_nos (re-fetched
    live from data_access, not a stored snapshot), in the same shape the
    live /ask response uses, so the frontend can render its "View N
    observations" panel identically whether the message just arrived or
    came from history."""
    doc = _col.find_one(
        {"empid": empid, "sessions.session_id": session_id},
        {"sessions.$": 1},
    )
    if not doc or not doc.get("sessions"):
        return []
    session = doc["sessions"][0]
    messages = session.get("messages", [])

    all_sr_nos = sorted({sr for m in messages for sr in (m.get("sr_nos") or [])})
    rows_by_sr_no = {}
    if all_sr_nos:
        rows_by_sr_no = {r["sr_no"]: r for r in data_access.get_many_by_sr_no(all_sr_nos)}

    result = []
    for m in messages:
        entry = {
            "role": m["role"],
            "content": m["content"],
            "created_at": m.get("created_at"),
        }
        sr_nos = m.get("sr_nos") or []
        if sr_nos:
            entry["rows"] = [rows_by_sr_no[sr] for sr in sr_nos if sr in rows_by_sr_no]
        result.append(entry)
    return result


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
