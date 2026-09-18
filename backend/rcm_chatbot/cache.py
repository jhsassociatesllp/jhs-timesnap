"""
RCM Q&A cache — ported from the standalone Sentinel app's exact-match,
content-hash cache (its search.py: _qa_cache_key/call_openai_cached), just
relocated from a dedicated Mongo db into a collection (rcm_qa_cache) in the
shared chatbot Mongo database.

Unlike the HR bot's semantic (embedding-similarity) FAQ cache, this is an
exact cache: the key is a hash of (prompt version, normalized question,
collection scope, retrieved context) — so it only ever serves a cached
answer for the literal same question against the literal same retrieved
rows, never a "close enough" different question. This matches the original
bot's behaviour exactly.
"""
import datetime
import hashlib

from pymongo import MongoClient

from backend.rcm_chatbot.config import rcm_settings

_client = MongoClient(
    rcm_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=rcm_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=rcm_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_db = _client[rcm_settings.CHATBOT_DB_NAME]
_col = _db[rcm_settings.QA_CACHE_COLLECTION_NAME]

_col.create_index("cache_key", unique=True)
# Auto-expire cached answers after 30 days, same as the standalone app.
_col.create_index("created_at", expireAfterSeconds=30 * 24 * 60 * 60)


def make_key(prompt_version: str, query: str, context_hash: str) -> str:
    import re
    normalized_query = re.sub(r"\s+", " ", query.strip().lower())
    raw = f"{prompt_version}|{normalized_query}|{context_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(cache_key: str):
    doc = _col.find_one({"cache_key": cache_key})
    return doc["reply"] if doc else None


def set(cache_key: str, query: str, reply: str) -> None:
    _col.update_one(
        {"cache_key": cache_key},
        {"$set": {
            "cache_key": cache_key,
            "reply": reply,
            "query": query,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }},
        upsert=True,
    )
