"""
JHS Library chatbot configuration.

This bot is a separate integration ported from the standalone "JHS Library"
audit-observation assistant. It has its own OpenAI key, its own Pinecone
index (dedicated observation embeddings — different dimension/model than the
HR Policy bot's local sentence-transformer), and its own observations
database. Kept isolated from backend/chatbot/config.py on purpose so the two
bots' credentials/indexes never collide.

Chat HISTORY is the one exception — per product requirement, Library chat
history lives in the SAME MongoDB database as the HR Policy bot's history
(ChatbotDB), just a different collection ("Jhs_lib"). See history.py, which
imports the HR bot's chatbot_settings for that connection instead of
duplicating it here.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class LibraryChatbotSettings:
    # ── OpenAI (classification, answers, summaries, drafts, embeddings) ──────
    OPENAI_API_KEY = os.getenv("LIBRARY_OPENAI_API_KEY", "")
    CHAT_MODEL = os.getenv("LIBRARY_CHAT_MODEL", "gpt-4o-mini")
    EMBED_MODEL = os.getenv("LIBRARY_EMBED_MODEL", "text-embedding-3-small")

    # ── Pinecone (semantic search over observations + FAQ cache) ─────────────
    PINECONE_API_KEY = os.getenv("LIBRARY_PINECONE_API_KEY", "")
    PINECONE_INDEX_NAME = os.getenv("LIBRARY_PINECONE_INDEX_NAME", "jhs-chatgpt")
    OBSERVATIONS_NAMESPACE = "consolidated_v1"
    CACHE_NAMESPACE = "faq-cache"
    CACHE_SIMILARITY_THRESHOLD = float(os.getenv("LIBRARY_CACHE_SIMILARITY_THRESHOLD", "0.92"))

    # ── MongoDB (the observation library itself — read-only from this app) ───
    MONGODB_URI = os.getenv("LIBRARY_MONGODB_URI", "")
    MONGO_DB = "JHS_Library"
    MONGO_COLLECTION = "observations"

    # ── Local SQLite FAQ cache (mirrors backend/chatbot/cache.py) ────────────
    CACHE_DB_PATH = os.getenv("LIBRARY_CACHE_DB_PATH", "./backend/library_chatbot/data/cache.db")

    def validate(self):
        missing = [
            name for name, val in (
                ("LIBRARY_OPENAI_API_KEY", self.OPENAI_API_KEY),
                ("LIBRARY_PINECONE_API_KEY", self.PINECONE_API_KEY),
                ("LIBRARY_MONGODB_URI", self.MONGODB_URI),
            ) if not val
        ]
        if missing:
            raise RuntimeError(
                f"Missing required env var(s) for the JHS Library chatbot: {', '.join(missing)}. "
                f"Add them to the project .env file."
            )


library_settings = LibraryChatbotSettings()
