"""
Shared semantic FAQ cache (SQLite + Pinecone).

Many employees ask near-duplicate questions. Instead of hitting the LLM
every time, we embed each incoming question, search the "faq-cache"
Pinecone namespace for a previously-answered question that is semantically
close enough, and reuse that answer if found. Every new Q&A we generate
gets stored back so the bot answers repeat questions instantly.

The vector lives in Pinecone; the actual text lives in a small local
SQLite file (keeps Pinecone metadata small and avoids per-field size limits).

Not scoped by designation: the HR bot no longer personalizes answers to
the asking employee's own designation (every role-differentiated topic
gets the full per-designation breakdown regardless of who's asking — see
rag.py's SYSTEM_PROMPT), so a cached answer is safe to reuse for anyone
asking a semantically-close question.
"""
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

from backend.chatbot.config import chatbot_settings
from backend.chatbot.vectorstore import get_index

_DB_PATH = Path(chatbot_settings.CACHE_DB_PATH)


def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faq_cache (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_hit_at REAL
        )
        """
    )
    return conn


def lookup(query_embedding: list) -> Optional[Tuple[str, str]]:
    """Returns (question, answer) if a close-enough cached match exists,
    else None."""
    index = get_index()
    result = index.query(
        vector=query_embedding,
        top_k=1,
        namespace=chatbot_settings.CACHE_NAMESPACE,
        include_metadata=True,
    )
    matches = result.get("matches") or []
    if not matches:
        return None

    best = matches[0]
    if best["score"] < chatbot_settings.CACHE_SIMILARITY_THRESHOLD:
        return None

    cache_id = best["id"]
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT question, answer FROM faq_cache WHERE id = ?", (cache_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE faq_cache SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
            (time.time(), cache_id),
        )
        conn.commit()
        return row[0], row[1]
    finally:
        conn.close()


def store(question: str, answer: str, embedding: list) -> None:
    """Save a new Q&A pair so future similar questions get answered instantly."""
    cache_id = str(uuid.uuid4())
    index = get_index()
    index.upsert(
        vectors=[{
            "id": cache_id,
            "values": embedding,
            "metadata": {"question": question},
        }],
        namespace=chatbot_settings.CACHE_NAMESPACE,
    )

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO faq_cache (id, question, answer, hit_count, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (cache_id, question, answer, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def stats() -> dict:
    conn = _connect()
    try:
        total, hits = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM faq_cache"
        ).fetchone()
        return {"cached_questions": total, "cache_hits_served": hits}
    finally:
        conn.close()
