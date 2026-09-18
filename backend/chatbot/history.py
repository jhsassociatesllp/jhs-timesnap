"""
Per-user chat history stored in MongoDB.

Each employee has ONE document in the collection, identified by their empid.
Sessions (conversation threads) are nested inside that document.

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
        {"role": "assistant", "content": "...", "created_at": 1234567890.0}
      ]
    }
  ]
}
"""
import time
import uuid
from typing import Dict, List, Optional

from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

from backend.chatbot.config import chatbot_settings

# Uses CHATBOT_MONGO_URI -- a separate DATABASE from the main app's
# MONGO_CONNECTION_STRING, but normally the same reachable host/cluster.
# Short timeouts here mean a Mongo hiccup fails in seconds instead of
# hanging the request for pymongo's ~30s default server-selection timeout.
_client = MongoClient(
    chatbot_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_db = _client[chatbot_settings.CHATBOT_DB_NAME]
_col = _db[chatbot_settings.CHATBOT_COLLECTION_NAME]

# Ensure index for fast lookups by empid
_col.create_index("empid", unique=True)


def _make_title(first_message: str) -> str:
    text = " ".join(first_message.split())
    return text[:48] + ("…" if len(text) > 48 else "")


# ─────────────────────────────────────────────────────────────────────────────
# Session management
# ─────────────────────────────────────────────────────────────────────────────

def ensure_session(empid: str, session_id: str, first_message: str) -> None:
    """Create the session entry under this employee's document if it doesn't exist.

    Fast path (the common case — an existing session getting another message):
    a single indexed update_one that matches and returns immediately.
    Slow path (brand-new session) only runs the extra upsert/push once.
    """
    now = time.time()

    # Fast path: session already exists — one round trip, no-op write.
    touched = _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {"$set": {"sessions.$.updated_at": now}},
    )
    if touched.matched_count:
        return

    # Slow path: first message of a brand-new session for this employee.
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
    """Append both sides of one turn and bump updated_at in a single round trip."""
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
    """Persist one full chat turn (creating the session on first use). Meant to be
    called AFTER the reply has already been sent to the user — see the /chat
    endpoint, which schedules this as a background task so DB latency never
    delays the answer the employee is waiting on."""
    ensure_session(empid, session_id, first_message=user_content)
    append_turn(empid, session_id, user_content, assistant_content)


# Kept for backward compatibility with any other caller of the old, more
# granular API (the /chat endpoint itself now uses save_turn() above).
def append_message(empid: str, session_id: str, role: str, content: str) -> None:
    """Append a single message to a session's messages array."""
    _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {
            "$push": {
                "sessions.$.messages": {
                    "role": role,
                    "content": content,
                    "created_at": time.time(),
                }
            }
        },
    )


def touch_session(empid: str, session_id: str) -> None:
    """Update the session's updated_at timestamp."""
    _col.update_one(
        {"empid": empid, "sessions.session_id": session_id},
        {"$set": {"sessions.$.updated_at": time.time()}},
    )


def get_messages(empid: str, session_id: str) -> List[Dict]:
    """Full transcript for a session, oldest first — used to repopulate the UI.
    Includes created_at so the widget can show a timestamp under each bubble."""
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
    """Last N turns (user/assistant pairs) for LLM context — role/content only."""
    messages = get_messages(empid, session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages[-max_turns * 2:]]


def list_sessions(empid: str) -> List[Dict]:
    """All sessions for this employee, most recently active first."""
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
    """Remove a session and all its messages from the employee's document."""
    _col.update_one(
        {"empid": empid},
        {"$pull": {"sessions": {"session_id": session_id}}},
    )
