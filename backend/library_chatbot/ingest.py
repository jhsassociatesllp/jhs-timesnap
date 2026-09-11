"""
JHS Library knowledge-base ingestion — backs the admin hub's Update/Replace
endpoints for observations (backend/library_chatbot/router.py's
/admin/knowledge/* routes). Adapted from the standalone JHS Library
project's backend/ingest.py (there, a manual CLI script run by hand) into
reusable functions callable from an HTTP upload — reuses this app's
already-ported taxonomy.py (COLUMN_MAP / normalize_row / embedding_text)
and the existing Mongo/Pinecone/OpenAI clients from data_access.py /
search.py instead of opening new ones.

Two upload shapes:
  Tabular (.xlsx/.xls/.csv) — a header row matching taxonomy.COLUMN_MAP's
    source columns (Sr. No., Headline, Observation, Risk, Root Cause,
    Recommendation, Management Action Plan, Sector, Audit Type, ...), same
    shape as the standalone project's "JHS Library Data Consolidated.xlsx".
    Keeps the file's own Sr. No. values on Replace.
  Anything else (.pdf, .docx, .txt, .json) — no fixed observation schema
    exists in a freeform document, so each extracted chunk (see
    backend/chatbot/multi_format.py — the same generic chunker HR Policy
    uses) becomes its own "unclassified" observation: headline/observation
    populated, every facet field (sector/audit_type/risk/...) left blank.
    This makes the content genuinely searchable (SUMMARY's semantic search,
    and SHOW_ALL's Mongo free-text search both work off headline/observation
    regardless of facets) — it just can't be filtered by sector/risk/etc.
    since a freeform document never actually states those. Always
    auto-numbered (a PDF has no "Sr. No." column to preserve).

Two ingestion modes:
  REPLACE — deletes every existing observation (Mongo + the whole Pinecone
            namespace), then inserts only the uploaded file's rows.
  UPDATE  — appends the uploaded file's rows starting after the current
            highest sr_no (so they can never collide with an existing row
            via the unique index) — every existing row is left untouched.

Chat history is never touched by either mode — only the observations
collection and the "consolidated_v1" Pinecone namespace.
"""
import io
from typing import List, Tuple

import pandas as pd

from backend.library_chatbot import data_access
from backend.library_chatbot.config import library_settings
from backend.library_chatbot.search import _index, _openai
from backend.library_chatbot.taxonomy import COLUMN_MAP, normalize_row, embedding_text

EMBED_BATCH = 50
_METADATA_FACETS = ("sector", "audit_type", "risk", "process_area", "risk_theme", "coso_component", "fs_assertion")

# Every field a normal (tabular) observation row has — an "unclassified"
# row from a freeform upload still gets all of these (blank where a
# freeform document simply can't tell us a value), so it's shaped
# identically to a normal row everywhere downstream (data_access, ai.py,
# embedding_text) rather than needing special-casing.
_ALL_FIELDS = list(COLUMN_MAP.values())

TABULAR_EXTS = ("xlsx", "xls", "csv")


def _unclassified_rows_from_any_format(filename: str, content: bytes) -> List[dict]:
    from backend.chatbot.multi_format import build_chunks_any_format
    chunks = build_chunks_any_format(filename, content)
    rows = []
    for text, section_title in chunks:
        row = {f: "" for f in _ALL_FIELDS}
        row["headline"] = section_title[:200]
        row["observation"] = text
        rows.append(row)
    return rows


def parse_uploaded_rows(filename: str, content: bytes) -> Tuple[List[dict], bool]:
    """Returns (rows, file_provides_sr_no). file_provides_sr_no is True only
    for the tabular path (the file has its own "Sr. No." column) — freeform
    uploads are always auto-numbered by the caller."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in TABULAR_EXTS:
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
        missing = [c for c in COLUMN_MAP if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected column(s): {', '.join(missing)}")
        return [normalize_row(r) for r in df.to_dict(orient="records")], True

    return _unclassified_rows_from_any_format(filename, content), False


def _ensure_indexes() -> None:
    data_access.collection.create_index("sr_no", unique=True)
    data_access.collection.create_index(
        [(f, "text") for f in ("headline", "observation", "root_cause", "recommendation", "management_action")],
        name="observations_text_index",
    )


def _embed_and_upsert(rows: List[dict], clear_namespace_first: bool) -> None:
    if clear_namespace_first:
        try:
            _index.delete(namespace=library_settings.OBSERVATIONS_NAMESPACE, delete_all=True)
        except Exception:
            pass  # namespace doesn't exist yet on a brand-new index — nothing to clear

    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i:i + EMBED_BATCH]
        texts = [embedding_text(r) for r in batch]
        resp = _openai.embeddings.create(model=library_settings.EMBED_MODEL, input=texts)
        vectors = []
        for row, emb in zip(batch, resp.data):
            metadata = {k: row.get(k, "") for k in _METADATA_FACETS}
            metadata["headline"] = row.get("headline", "")
            vectors.append({"id": str(row["sr_no"]), "values": emb.embedding, "metadata": metadata})
        for j in range(0, len(vectors), 20):
            _index.upsert(vectors=vectors[j:j + 20], namespace=library_settings.OBSERVATIONS_NAMESPACE, timeout=120)


def _clear_faq_cache() -> None:
    # The FAQ cache (cache.py) is a pure semantic (question-similarity)
    # cache with no content-hash invalidation — it has no way to know the
    # observation data underneath it just changed, so a previously-cached
    # answer would otherwise keep being served verbatim forever, even after
    # it's now stale/wrong. ANY knowledge mutation (update or replace) can
    # invalidate an existing cached answer, so both modes clear it.
    try:
        _index.delete(delete_all=True, namespace=library_settings.CACHE_NAMESPACE)
    except Exception:
        pass  # cache namespace empty/doesn't exist yet — nothing to clear


def replace(filename: str, content: bytes) -> dict:
    rows, file_numbered = parse_uploaded_rows(filename, content)
    if not file_numbered:
        for i, row in enumerate(rows, 1):
            row["sr_no"] = i
    data_access.collection.delete_many({})
    if rows:
        data_access.collection.insert_many(rows)
    _ensure_indexes()
    _embed_and_upsert(rows, clear_namespace_first=True)
    data_access.get_facets(force_refresh=True)
    _clear_faq_cache()
    return {"mode": "replace", "rows_inserted": len(rows)}


def update(filename: str, content: bytes) -> dict:
    rows, _file_numbered = parse_uploaded_rows(filename, content)
    last = data_access.collection.find_one(sort=[("sr_no", -1)])
    next_sr_no = (last["sr_no"] + 1) if last else 1
    for row in rows:
        row["sr_no"] = next_sr_no
        next_sr_no += 1
    if rows:
        data_access.collection.insert_many(rows)
    _ensure_indexes()
    _embed_and_upsert(rows, clear_namespace_first=False)
    data_access.get_facets(force_refresh=True)
    _clear_faq_cache()
    return {"mode": "update", "rows_inserted": len(rows)}


def stats() -> dict:
    total = data_access.collection.count_documents({})
    return {"observations": total}
