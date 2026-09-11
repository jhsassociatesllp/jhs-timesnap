"""
One Pinecone index, two namespaces:
  - "hr-policy" : chunks of the HR policy document (knowledge base)
  - "faq-cache" : embeddings of past questions, used as a semantic cache

Splitting by namespace keeps them logically separate while sharing a single
free-tier-friendly serverless index.
"""
from functools import lru_cache

from pinecone import Pinecone, ServerlessSpec

from backend.chatbot.config import chatbot_settings


@lru_cache(maxsize=1)
def get_pinecone_client() -> Pinecone:
    return Pinecone(api_key=chatbot_settings.PINECONE_API_KEY)


def ensure_index_exists():
    pc = get_pinecone_client()
    existing = [idx["name"] for idx in pc.list_indexes()]
    if chatbot_settings.PINECONE_INDEX_NAME not in existing:
        pc.create_index(
            name=chatbot_settings.PINECONE_INDEX_NAME,
            dimension=chatbot_settings.EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=chatbot_settings.PINECONE_CLOUD,
                region=chatbot_settings.PINECONE_REGION,
            ),
        )


@lru_cache(maxsize=1)
def get_index():
    ensure_index_exists()
    pc = get_pinecone_client()
    return pc.Index(chatbot_settings.PINECONE_INDEX_NAME)
