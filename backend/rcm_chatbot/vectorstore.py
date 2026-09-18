"""
RCM chatbot's dedicated Pinecone index. One index, one namespace per source
file (e.g. "Consolidated_RCM", "Buyer_Credit_Loan") — mirrors the standalone
Sentinel app's per-file "collection" concept. Every row of every checklist
lives here as a vector; there is no separate Mongo store for the knowledge
base itself (chat history/cache still use Mongo — see history.py/cache.py).
"""
from functools import lru_cache

from pinecone import Pinecone, ServerlessSpec

from backend.rcm_chatbot.config import rcm_settings


@lru_cache(maxsize=1)
def get_pinecone_client() -> Pinecone:
    return Pinecone(api_key=rcm_settings.PINECONE_API_KEY)


def ensure_index_exists():
    pc = get_pinecone_client()
    existing = [idx["name"] for idx in pc.list_indexes()]
    if rcm_settings.PINECONE_INDEX_NAME not in existing:
        pc.create_index(
            name=rcm_settings.PINECONE_INDEX_NAME,
            dimension=rcm_settings.EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=rcm_settings.PINECONE_CLOUD,
                region=rcm_settings.PINECONE_REGION,
            ),
        )


@lru_cache(maxsize=1)
def get_index():
    ensure_index_exists()
    pc = get_pinecone_client()
    return pc.Index(rcm_settings.PINECONE_INDEX_NAME)


def list_namespaces():
    """Every namespace (source file) currently populated in the index."""
    index = get_index()
    stats = index.describe_index_stats()
    namespaces = stats.get("namespaces") or {}
    return list(namespaces.keys())


def namespace_stats():
    """{namespace: vector_count} for every populated namespace."""
    index = get_index()
    stats = index.describe_index_stats()
    namespaces = stats.get("namespaces") or {}
    return {name: info.get("vector_count", 0) for name, info in namespaces.items()}
