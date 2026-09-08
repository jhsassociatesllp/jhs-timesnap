"""
Shared ingestion logic — turns parsed sheets (parsers.py's uniform
[{name, header, rows}] shape) into vectors in the RCM Pinecone index.
Used by both the one-off seed script (seed.py) and the admin upload
endpoints (router.py). A bulk "import folder" upload routinely mixes file
types (xlsx checklists next to PDF write-ups next to plain .txt notes), and
parsers.py's own output already tells us which shape each sheet actually
is — see _is_prose_sheet below for how that's used to embed each shape
appropriately instead of one-size-fits-all.

Namespace = one source file (e.g. "Consolidated_RCM"), matching the
standalone Sentinel app's own bulk-upload auto-naming (_slugify(filename)).
Each namespace holds exactly the rows of whichever file was most recently
ingested into it — ingesting always fully replaces the namespace's content
(delete-all, then upsert), which keeps deletes/replacements simple and
correct without relying on Pinecone metadata-filtered deletes.
"""
import re
import uuid
from typing import Any, Dict, List

from backend.chatbot.embeddings import embed_batch
from backend.chatbot.ingest_policy import _sub_split as _split_prose
from backend.rcm_chatbot.vectorstore import get_index

# Pinecone caps total metadata per vector at 40KB. Real checklist cells are
# almost always well under this, but a handful of rows (see search.py's own
# comments on this data) can hold a whole procedure write-up in one cell —
# cap generously so those still fit comfortably, with room to spare.
MAX_CELL_CHARS = 1500
MAX_TEXT_CHARS = 8000


def slugify(text: str) -> str:
    """Turn a filename into a safe Pinecone namespace — same convention the
    standalone app used for its auto-named MongoDB collections."""
    text = re.sub(r"\.[^.]+$", "", text)  # strip file extension
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "collection"


def _row_to_text(file: str, sheet: str, header: List[str], row: List[str]) -> str:
    parts = [" ".join(str(x) for x in header), " ".join(str(x) for x in row), file, sheet]
    return " ".join(parts).lower()


def _cap(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit] + " …[truncated]"


# parsers.py's uniform sheet shape means both a genuinely tabular sheet
# (an xlsx sheet, a docx/pdf table — real columns, one self-contained fact
# per row) and pure prose (a PDF page's plain text, a .txt file, a JSON
# fallback dump — one PARAGRAPH per row, header=["Text"]) come out looking
# structurally the same: {header, rows}. They are NOT the same kind of
# content, though, and embedding them the same way (one vector per row)
# is wrong for prose: a multi-step procedure or multi-part discussion
# spread across several paragraphs needs those paragraphs to reach the
# model TOGETHER, not as disconnected single-paragraph fragments that lose
# each other's context — exactly the problem the HR bot's section-based
# chunking (backend/chatbot/ingest_policy.py) already solved once. This is
# the one reliable signal parsers.py gives us for "this sheet is prose, not
# a table" — every prose-producing parser branch uses this exact header.
_PROSE_HEADER = ["Text"]


def _prose_records(sheet: Dict[str, Any], filename: str) -> List[Dict[str, Any]]:
    """Joins a prose sheet's paragraphs back into one block and re-splits
    it into appropriately-sized, slightly-overlapping chunks (reusing the
    HR bot's own chunking, rather than re-inventing it) — one record per
    chunk, instead of one record per isolated paragraph."""
    paras = [str(row[0]).strip() for row in sheet.get("rows", []) if row and str(row[0]).strip()]
    full_text = "\n".join(paras)
    if not full_text:
        return []
    sheet_name = sheet.get("name", "Sheet1")
    return [
        {
            "file": filename,
            "sheet": sheet_name,
            "header": _PROSE_HEADER,
            "row": [_cap(piece, MAX_CELL_CHARS)],
            "text": _cap(f"{filename} {sheet_name} {piece}".lower(), MAX_TEXT_CHARS),
        }
        for piece in _split_prose(full_text)
    ]


def ingest_sheets(namespace: str, filename: str, sheets: List[Dict[str, Any]]) -> int:
    """Replace `namespace`'s content with the rows from `sheets` (all under
    `filename`). Returns the number of records inserted (rows for a tabular
    sheet, chunks for a prose one — see _prose_records)."""
    records = []
    for sheet in sheets:
        if sheet.get("header") == _PROSE_HEADER:
            records.extend(_prose_records(sheet, filename))
            continue
        header = [_cap(str(h), MAX_CELL_CHARS) for h in sheet.get("header", [])]
        for row in sheet.get("rows", []):
            row = [_cap(str(v), MAX_CELL_CHARS) for v in row]
            text = _cap(_row_to_text(filename, sheet.get("name", "Sheet1"), header, row), MAX_TEXT_CHARS)
            records.append({
                "file": filename,
                "sheet": sheet.get("name", "Sheet1"),
                "header": header,
                "row": row,
                "text": text,
            })

    index = get_index()

    try:
        index.delete(delete_all=True, namespace=namespace)
    except Exception:
        # Namespace doesn't exist yet on a brand-new index — nothing to clear.
        pass

    if not records:
        return 0

    texts = [r["text"] for r in records]
    embeddings = embed_batch(texts)

    vectors = [
        {
            "id": str(uuid.uuid4()),
            "values": vec,
            "metadata": {
                "file": rec["file"],
                "sheet": rec["sheet"],
                "header": rec["header"],
                "row": rec["row"],
                "text": rec["text"],
            },
        }
        for rec, vec in zip(records, embeddings)
    ]

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        index.upsert(vectors=vectors[i:i + batch_size], namespace=namespace)

    return len(records)


def delete_namespace(namespace: str) -> None:
    index = get_index()
    try:
        index.delete(delete_all=True, namespace=namespace)
    except Exception:
        pass
