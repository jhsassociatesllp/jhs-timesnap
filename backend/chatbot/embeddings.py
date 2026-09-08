"""
Embeddings run locally via sentence-transformers — completely free, no API key needed.
Model is loaded once (singleton) for speed across requests.
"""
from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

from backend.chatbot.config import chatbot_settings


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    # Once the model has been downloaded once, it never needs to hit the
    # network again — but by default sentence-transformers still makes a
    # HEAD request to huggingface.co on every load just to check for updates.
    # On a slow/restricted connection that check alone can stall startup (and
    # the first chat reply, if warm-up didn't finish) for a minute or more
    # while it retries. Try the local cache first; only reach out to the
    # network if the model genuinely isn't cached yet (e.g. first-ever run).
    try:
        return SentenceTransformer(chatbot_settings.EMBEDDING_MODEL_NAME, local_files_only=True)
    except Exception:
        return SentenceTransformer(chatbot_settings.EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> List[float]:
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]
