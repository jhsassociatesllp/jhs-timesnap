"""Pinecone semantic search + fuzzy matching of free text against live facet
vocabulary. Ported from the standalone JHS Library project — reads
credentials from library_settings instead of bare os.getenv() calls."""
import difflib

from openai import OpenAI
from pinecone import Pinecone

from backend.library_chatbot.config import library_settings

_pc = Pinecone(api_key=library_settings.PINECONE_API_KEY)
_index = _pc.Index(library_settings.PINECONE_INDEX_NAME)
_openai = OpenAI(api_key=library_settings.OPENAI_API_KEY)


def embed(text: str) -> list:
    resp = _openai.embeddings.create(model=library_settings.EMBED_MODEL, input=text)
    return resp.data[0].embedding


def similar_by_sr_no(sr_no: int, top_k: int = 6) -> list:
    """Returns [(sr_no, score), ...] of the nearest neighbors to an
    existing observation, excluding itself."""
    fetched = _index.fetch(ids=[str(sr_no)], namespace=library_settings.OBSERVATIONS_NAMESPACE)
    vec = fetched.vectors.get(str(sr_no))
    if vec is None:
        return []
    result = _index.query(
        vector=vec.values, top_k=top_k + 1, namespace=library_settings.OBSERVATIONS_NAMESPACE, include_metadata=False
    )
    out = []
    for match in result["matches"]:
        if match["id"] == str(sr_no):
            continue
        out.append((int(match["id"]), match["score"]))
    return out[:top_k]


def similar_by_text(text: str, filters: dict = None, top_k: int = 15) -> list:
    """Returns [(sr_no, score), ...] for an arbitrary query string, optionally
    scoped to Pinecone metadata filters (sector/audit_type/risk/...)."""
    vector = embed(text)
    query_kwargs = {
        "vector": vector, "top_k": top_k,
        "namespace": library_settings.OBSERVATIONS_NAMESPACE, "include_metadata": False,
    }
    if filters:
        query_kwargs["filter"] = {k: {"$eq": v} for k, v in filters.items() if v}
    result = _index.query(**query_kwargs)
    return [(int(m["id"]), m["score"]) for m in result["matches"]]


def fuzzy_match_facet(value: str, canonical_values: list, cutoff: float = 0.6):
    """Best-effort match of free text (e.g. a word the LLM classifier pulled
    out of a question) against the live, normalized facet vocabulary.
    Case-insensitive, tolerant of typos/partial phrasing. Returns the
    canonical value or None."""
    if not value or not canonical_values:
        return None
    value_l = value.strip().lower()
    lower_map = {v.lower(): v for v in canonical_values}

    if value_l in lower_map:
        return lower_map[value_l]

    # substring containment either direction (e.g. "bank" -> "Banking")
    for lower, canon in lower_map.items():
        if value_l in lower or lower in value_l:
            return canon

    close = difflib.get_close_matches(value_l, list(lower_map.keys()), n=1, cutoff=cutoff)
    return lower_map[close[0]] if close else None
