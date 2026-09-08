"""
HR bot — keyword (BM25) side of hybrid retrieval, combined with Pinecone's
semantic search in rag.py via Reciprocal Rank Fusion (RRF).

Why this exists: pure embedding similarity can under-rank a chunk that
contains the EXACT term the question uses ("probation", "notice period",
"encashment") if the chunk's surrounding wording doesn't otherwise read as
semantically close to the question — a free/local embedding model
(sentence-transformers/all-MiniLM-L6-v2) is more prone to this than a large
hosted one. BM25 is a classic exact/near-exact term-frequency ranker with
no such blind spot, so fusing it in recovers matches semantic search alone
would sometimes miss, without giving up semantic search's ability to match
differently-worded-but-related questions.

No new infrastructure: this is a small in-process index over a local JSON
snapshot of the same chunks already upserted to Pinecone (see
ingest_policy.py's _write_corpus_snapshot) — not a new database or service.
The snapshot is the source of truth for BM25 AND for looking up a chunk's
text/section by id (Pinecone's own metadata already has that too, but reading
it from one local structure for both semantic- and BM25-sourced ids is
simpler than a second round-trip to Pinecone for ids Pinecone's own semantic
query didn't happen to return).
"""
import json
import os
import re
import threading
from typing import Dict, List, Tuple

from rank_bm25 import BM25Okapi

CORPUS_PATH = os.path.join(os.path.dirname(__file__), "data", "hr_corpus.json")

_lock = threading.Lock()
_cache = None  # {"ids": [...], "bm25": BM25Okapi, "chunks": {id: {"text","section"}}}


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _load_corpus() -> Dict[str, Dict[str, str]]:
    if not os.path.exists(CORPUS_PATH):
        return {}
    try:
        with open(CORPUS_PATH, encoding="utf-8") as f:
            return json.load(f).get("chunks", {})
    except Exception:
        return {}


def _save_corpus(chunks: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(CORPUS_PATH), exist_ok=True)
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        json.dump({"chunks": chunks}, f, ensure_ascii=False)


def replace_corpus(records: List[Tuple[str, str, str]]) -> None:
    """records: [(id, text, section), ...]. Used by ingest_policy's
    "replace" mode — the local BM25 snapshot mirrors Pinecone's own
    delete-all-then-upsert semantics exactly."""
    chunks = {rec_id: {"text": text, "section": section} for rec_id, text, section in records}
    _save_corpus(chunks)
    invalidate()


def update_corpus(records: List[Tuple[str, str, str]]) -> None:
    """records: [(id, text, section), ...]. Used by ingest_policy's
    "update" mode — merges into whatever's already on disk (purely
    additive, mirroring Pinecone's own additive upsert there)."""
    chunks = _load_corpus()
    for rec_id, text, section in records:
        chunks[rec_id] = {"text": text, "section": section}
    _save_corpus(chunks)
    invalidate()


def invalidate() -> None:
    """Forces the next search to rebuild from disk — call after any
    ingestion so a freshly Updated/Replaced knowledge base is reflected in
    BM25 results immediately, not just in Pinecone."""
    global _cache
    with _lock:
        _cache = None


def _get_cache():
    global _cache
    with _lock:
        if _cache is None:
            chunks = _load_corpus()
            ids = list(chunks.keys())
            tokenized = [_tokenize(chunks[i]["text"]) for i in ids]
            bm25 = BM25Okapi(tokenized) if tokenized else None
            _cache = {"ids": ids, "bm25": bm25, "chunks": chunks}
        return _cache


def bm25_search(query: str, top_k: int) -> List[Tuple[str, float]]:
    """Returns [(chunk_id, bm25_score), ...] ranked highest-first. Empty if
    the corpus snapshot hasn't been built yet (e.g. brand-new index before
    any ingestion) — callers degrade to semantic-only in that case."""
    cache = _get_cache()
    if not cache["bm25"] or not cache["ids"]:
        return []
    scores = cache["bm25"].get_scores(_tokenize(query))
    ranked = sorted(zip(cache["ids"], scores), key=lambda p: p[1], reverse=True)
    return [(i, s) for i, s in ranked[:top_k] if s > 0]  # score 0 = no term overlap at all, not a real match


def lookup(chunk_id: str) -> Dict[str, str]:
    """{"text": ..., "section": ...} for a chunk id, or {} if unknown."""
    return _get_cache()["chunks"].get(chunk_id, {})


def reciprocal_rank_fusion(*ranked_id_lists: List[str], k: int = 60) -> Dict[str, float]:
    """Combines any number of ranked id lists (best first) into one fused
    score per id — standard RRF: score += 1/(k + rank). Chosen over
    normalizing and averaging raw scores because semantic cosine similarity
    and BM25 scores live on completely different, non-comparable scales;
    RRF only cares about RANK POSITION within each list, so no scale
    reconciliation is needed."""
    fused: Dict[str, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, doc_id in enumerate(ranked_ids):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return fused
