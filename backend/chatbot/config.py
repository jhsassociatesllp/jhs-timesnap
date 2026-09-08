"""
Chatbot configuration — all values read from the project's shared .env.
Add the chatbot-specific variables to .env (see comments below).

LLM Provider switch:
  Keep BOTH HF_API_KEY and LLM_API_KEY in .env at the same time — nothing
  needs to be deleted or commented out. Flip the active provider with one
  line:

    LLM_PROVIDER=huggingface   -> uses HF_API_KEY / HF_MODEL / HF_BASE_URL
    LLM_PROVIDER=openai        -> uses LLM_API_KEY / LLM_MODEL / LLM_BASE_URL

  If LLM_PROVIDER is left unset, the old auto-detect behaviour applies
  (whichever key is present; HuggingFace wins if both are present).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val or val.startswith("your-"):
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Add it to the project .env file."
        )
    return val


class ChatbotSettings:
    # ── Pinecone ──────────────────────────────────────────────────────────────
    PINECONE_API_KEY    = os.getenv("PINECONE_API_KEY", "")
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "hr-policy-bot")
    PINECONE_CLOUD      = os.getenv("PINECONE_CLOUD", "aws")
    PINECONE_REGION     = os.getenv("PINECONE_REGION", "us-east-1")

    # ── LLM Provider (explicit switch, with auto-detect fallback) ─────────────
    #
    #   Set LLM_PROVIDER=huggingface or LLM_PROVIDER=openai in .env to choose
    #   which credentials/model/base-url block is active. Both key sets can
    #   stay in .env at once — flipping providers is a one-line change.
    #
    #   If LLM_PROVIDER isn't set at all, falls back to the old behaviour:
    #   whichever key is present wins (HF first).
    #
    _HF_KEY  = os.getenv("HF_API_KEY",  "")   # HuggingFace token
    _LLM_KEY = os.getenv("LLM_API_KEY", "")   # Any OpenAI-compatible key
    _PROVIDER_OVERRIDE = os.getenv("LLM_PROVIDER", "").strip().lower()

    if _PROVIDER_OVERRIDE in ("huggingface", "hf"):
        LLM_PROVIDER = "huggingface"
    elif _PROVIDER_OVERRIDE in ("openai", "api", "llm"):
        LLM_PROVIDER = "openai"
    else:
        # No explicit choice made — auto-detect from whichever key exists.
        LLM_PROVIDER = "huggingface" if _HF_KEY else "openai"

    # The single key the LLM module will use (resolved automatically)
    ACTIVE_API_KEY = _HF_KEY if LLM_PROVIDER == "huggingface" else _LLM_KEY

    # Base URL: HF router vs. OpenAI (or any custom endpoint)
    ACTIVE_BASE_URL = (
        os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")
        if LLM_PROVIDER == "huggingface"
        else os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    )

    # Model name: HF model vs. OpenAI model
    ACTIVE_MODEL = (
        os.getenv("HF_MODEL",  "deepseek-ai/DeepSeek-V4-Flash")
        if LLM_PROVIDER == "huggingface"
        else os.getenv("LLM_MODEL", "gpt-4o-mini")
    )

    # ── Local embedding model (no cost, no API key) ───────────────────────────
    EMBEDDING_MODEL_NAME = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

    # ── HR bot's own LLM provider (product decision: HR only) ────────────────
    #   Independent of LLM_PROVIDER above — RCM and the general assistant
    #   reply still use the shared HuggingFace/OpenAI switch above unchanged.
    #   HR answers specifically go through OpenAI, using the SAME key as the
    #   JHS Library bot (falls back to LIBRARY_OPENAI_API_KEY when
    #   HR_OPENAI_API_KEY isn't set, same "reuse another bot's already-set
    #   env var by name" pattern as CHATBOT_MONGO_URI below) — see rag.py's
    #   HR_PROVIDER, passed explicitly into every call_llm/stream_llm call
    #   the HR bot makes.
    HR_OPENAI_API_KEY  = os.getenv("HR_OPENAI_API_KEY") or os.getenv("LIBRARY_OPENAI_API_KEY", "")
    HR_OPENAI_MODEL    = os.getenv("HR_OPENAI_MODEL", "gpt-4o-mini")
    HR_OPENAI_BASE_URL = os.getenv("HR_OPENAI_BASE_URL", "https://api.openai.com/v1")

    # ── RAG behaviour ─────────────────────────────────────────────────────────
    # 8, not 4: a low top_k dropped relevant policy chunks on multi-part
    # questions, which under-informed the model's answer even when the sibling-
    # fetch in rag.py pulled the rest of a matched section back in.
    TOP_K                      = int(os.getenv("TOP_K", "8"))
    CACHE_SIMILARITY_THRESHOLD = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.90"))
    SESSION_HISTORY_TURNS      = int(os.getenv("SESSION_HISTORY_TURNS", "6"))
    # Floor on raw cosine similarity for a semantically-matched chunk to be
    # kept — a pure safety net against filling top_k with near-noise, not an
    # aggressive filter. Deliberately low: this free/local embedding model's
    # absolute scores run modest even for genuinely relevant matches (real
    # observed range for on-topic HR policy chunks is roughly 0.25-0.45), so
    # a stricter floor risks dropping true matches, which is worse than
    # letting a weak one through. A chunk that only matched via BM25
    # keyword search (no semantic score at all) is never floor-filtered —
    # exact term matches are the whole reason hybrid retrieval exists.
    MIN_SEMANTIC_SIMILARITY   = float(os.getenv("HR_MIN_SEMANTIC_SIMILARITY", "0.15"))

    # ── Pinecone namespaces ───────────────────────────────────────────────────
    POLICY_NAMESPACE = "hr-policy"
    CACHE_NAMESPACE  = "faq-cache"

    # ── Local SQLite FAQ cache (shared across users) ──────────────────────────
    CACHE_DB_PATH = os.getenv("CACHE_DB_PATH", "./backend/chatbot/data/cache.db")

    # ── MongoDB Chat History (SEPARATE database from the main app) ────────────
    #
    #   CHATBOT_MONGO_URI points at a different DATABASE than the main app,
    #   but should normally be the SAME reachable Mongo host/cluster as
    #   MONGO_CONNECTION_STRING — pointing it at "localhost" only works if a
    #   local mongod is actually running on the server, and if it isn't, every
    #   chat message stalls for ~20-30s waiting on a Mongo connection that
    #   will never succeed before it times out. If CHATBOT_MONGO_URI isn't
    #   set at all, we fall back to the main app's connection string so the
    #   bot never silently points at an unreachable localhost.
    #
    CHATBOT_MONGO_URI = os.getenv("CHATBOT_MONGO_URI") or os.getenv(
        "MONGO_CONNECTION_STRING", "mongodb://localhost:27017/"
    )
    CHATBOT_DB_NAME         = os.getenv("CHATBOT_DB_NAME", "ChatbotDB")
    CHATBOT_COLLECTION_NAME = os.getenv("CHATBOT_COLLECTION_NAME", "chat_history")

    # Fail fast instead of hanging: if Mongo is unreachable, give up after
    # this many milliseconds rather than blocking the request for ~30s.
    CHATBOT_MONGO_TIMEOUT_MS = int(os.getenv("CHATBOT_MONGO_TIMEOUT_MS", "5000"))

    def validate(self):
        _require("PINECONE_API_KEY")
        if not self.ACTIVE_API_KEY:
            needed = "HF_API_KEY" if self.LLM_PROVIDER == "huggingface" else "LLM_API_KEY"
            raise RuntimeError(
                f"LLM_PROVIDER is set to '{self.LLM_PROVIDER}' but {needed} is empty "
                f"in .env. Either fill in {needed}, or change LLM_PROVIDER."
            )
        if not self.HR_OPENAI_API_KEY:
            raise RuntimeError(
                "HR bot has no OpenAI key: set HR_OPENAI_API_KEY (or LIBRARY_OPENAI_API_KEY, "
                "which it falls back to) in .env."
            )


chatbot_settings = ChatbotSettings()
