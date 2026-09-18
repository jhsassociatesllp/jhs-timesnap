"""
RCM chatbot configuration.

This bot is ported from the standalone "Sentinel" RCM/checklist assistant.
It gets its own dedicated Pinecone index (RCM_PINECONE_API_KEY/INDEX_NAME) —
isolated from the HR and Library bots' indexes, same pattern as
backend/library_chatbot/config.py. Everything else it needs (the local
embedding model, the LLM provider, and the Mongo connection used for chat
history/cache) is reused from backend/chatbot/config.py's chatbot_settings
rather than duplicated.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from backend.chatbot.config import chatbot_settings


class RcmChatbotSettings:
    # ── Pinecone (dedicated index — the RCM knowledge base itself lives here) ─
    PINECONE_API_KEY = os.getenv("RCM_PINECONE_API_KEY", "")
    # Pinecone index names must be lowercase letters/digits/hyphens only —
    # normalize defensively so a differently-cased value in .env still works.
    PINECONE_INDEX_NAME = os.getenv("RCM_PINECONE_INDEX_NAME", "rcm-checklist-bot").lower()
    PINECONE_CLOUD = os.getenv("RCM_PINECONE_CLOUD", chatbot_settings.PINECONE_CLOUD)
    PINECONE_REGION = os.getenv("RCM_PINECONE_REGION", chatbot_settings.PINECONE_REGION)

    # ── Embeddings (shared, free, local — same model as the HR bot) ──────────
    EMBEDDING_MODEL_NAME = chatbot_settings.EMBEDDING_MODEL_NAME
    EMBEDDING_DIM = chatbot_settings.EMBEDDING_DIM

    # ── LLM ────────────────────────────────────────────────────────────────────
    # Falls back to the shared platform provider (chatbot_settings.LLM_PROVIDER)
    # when RCM_OPENAI_API_KEY isn't set, so nothing breaks before it's added —
    # same "own dedicated key, falls back to shared" pattern as the HR bot's
    # HR_OPENAI_API_KEY (backend/chatbot/config.py) and the Library bot's
    # LIBRARY_OPENAI_API_KEY. Once set, RCM's own key is used for every RCM
    # LLM call (answer.py's RCM_PROVIDER), so usage tracking (backend/chatbot
    # /usage.py) lines up with what that key's own OpenAI dashboard shows.
    LLM_PROVIDER = chatbot_settings.LLM_PROVIDER
    ACTIVE_MODEL = chatbot_settings.ACTIVE_MODEL
    OPENAI_API_KEY = os.getenv("RCM_OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("RCM_OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL = os.getenv("RCM_OPENAI_BASE_URL", "https://api.openai.com/v1")

    # ── Retrieval behaviour ────────────────────────────────────────────────────
    TOP_K = int(os.getenv("RCM_TOP_K", "50"))
    PRODUCT_LOCK_TOP_K = int(os.getenv("RCM_PRODUCT_LOCK_TOP_K", "150"))
    SESSION_HISTORY_TURNS = chatbot_settings.SESSION_HISTORY_TURNS

    # ── MongoDB (same DB as the HR bot's chat history — separate collections) ──
    CHATBOT_MONGO_URI = chatbot_settings.CHATBOT_MONGO_URI
    CHATBOT_DB_NAME = chatbot_settings.CHATBOT_DB_NAME
    CHATBOT_MONGO_TIMEOUT_MS = chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS
    # "RCM" — fixed name, not meant to change: matches the pre-existing
    # collection in the shared Chat_bot database (see backend/chatbot/
    # config.py's CHATBOT_DB_NAME/CHATBOT_COLLECTION_NAME comment).
    HISTORY_COLLECTION_NAME = os.getenv("RCM_HISTORY_COLLECTION_NAME", "RCM")
    QA_CACHE_COLLECTION_NAME = os.getenv("RCM_QA_CACHE_COLLECTION_NAME", "rcm_qa_cache")

    def validate(self):
        if not self.PINECONE_API_KEY:
            raise RuntimeError(
                "Missing required environment variable: RCM_PINECONE_API_KEY. "
                "Add it to the project .env file."
            )
        if not self.OPENAI_API_KEY and not chatbot_settings.ACTIVE_API_KEY:
            needed = "HF_API_KEY" if self.LLM_PROVIDER == "huggingface" else "LLM_API_KEY"
            raise RuntimeError(
                f"RCM chatbot has no LLM key: set RCM_OPENAI_API_KEY, or the shared "
                f"{needed} (LLM_PROVIDER='{self.LLM_PROVIDER}') in .env."
            )


rcm_settings = RcmChatbotSettings()
