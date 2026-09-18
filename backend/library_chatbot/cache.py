"""
Shared semantic FAQ cache for the JHS Library "Ask" bot — mirrors
backend/chatbot/cache.py's design (SQLite for the text, Pinecone for the
similarity search) but points at the Library's own Pinecone index, since its
OpenAI embeddings are a different model/dimension than the HR bot's local
sentence-transformer and the two can't share a namespace.

Many employees ask near-duplicate audit questions ("high risk items in
banking", "banking high-risk observations", ...). Instead of re-running the
classify+answer OpenAI calls every time, we embed the incoming question,
search the "faq-cache" namespace for a previously-answered question that's
semantically close enough, and reuse that whole response if found.
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from pinecone import Pinecone

from backend.library_chatbot.config import library_settings

_DB_PATH = Path(library_settings.CACHE_DB_PATH)
_pc = Pinecone(api_key=library_settings.PINECONE_API_KEY)
_index = _pc.Index(library_settings.PINECONE_INDEX_NAME)


def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faq_cache (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            response_json TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_hit_at REAL
        )
        """
    )
    return conn


def lookup(query_embedding: list) -> Optional[dict]:
    """Returns the cached response dict (same shape ask_bot() returns) if a
    close-enough cached match exists, else None."""
    result = _index.query(
        vector=query_embedding,
        top_k=1,
        namespace=library_settings.CACHE_NAMESPACE,
        include_metadata=True,
    )
    matches = result.get("matches") or []
    if not matches:
        return None

    best = matches[0]
    if best["score"] < library_settings.CACHE_SIMILARITY_THRESHOLD:
        return None

    cache_id = best["id"]
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT response_json FROM faq_cache WHERE id = ?", (cache_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE faq_cache SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
            (time.time(), cache_id),
        )
        conn.commit()
        return json.loads(row[0])
    finally:
        conn.close()


def store(question: str, response: dict, embedding: list) -> None:
    """Save a new question/response pair so future similar questions get
    answered instantly. `response` must be JSON-serializable (ask_bot()'s
    return dict is)."""
    cache_id = str(uuid.uuid4())
    _index.upsert(
        vectors=[{"id": cache_id, "values": embedding, "metadata": {"question": question}}],
        namespace=library_settings.CACHE_NAMESPACE,
    )

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO faq_cache (id, question, response_json, hit_count, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (cache_id, question, json.dumps(response), time.time()),
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
