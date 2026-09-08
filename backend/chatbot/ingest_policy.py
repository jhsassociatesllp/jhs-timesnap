"""
HR Policy knowledge-base ingestion — the CLI script for the bundled policy
doc (`python -m backend.chatbot.ingest_policy`), AND the shared functions
the admin hub's Update/Replace endpoints call for an ad-hoc uploaded .docx
(see backend/chatbot/router.py's /admin/knowledge/* routes).

Why chunk by SECTION, not fixed windows:
  The previous retrieval behaviour picked whichever single chunk embedded
  closest to the question and handed the model just that. When a policy
  section states different rules per role (Manager / Trainee / Article /
  Executive, etc.), plain top-k similarity chunking has no notion of
  "these rules belong together" — it was pure luck which role's rule
  actually reached the model, so "what is the work from home policy?"
  answered for whichever role happened to embed closest, not all of them.

  This keeps each policy SECTION whole (heading + full body, including any
  tables in it) as one chunk wherever it reasonably fits, instead of
  splitting on a fixed character window irrespective of meaning — so a
  section covering three roles stays together and the model can see all
  three in one retrieval. Sections that are still too long to embed well
  are split, but every sub-chunk keeps the same `section` metadata, so
  rag.py's sibling-fetch (see retrieve_context) can pull the rest of that
  section back in even if the top match was only one piece of it.

Two ingestion modes (see ingest_records):
  REPLACE — clears the "hr-policy" namespace first, deterministic slug IDs.
            Used by the CLI script and the admin hub's "Replace" button.
  UPDATE  — does NOT clear anything, random (uuid) IDs so new chunks can
            never collide with (and silently overwrite) existing ones —
            purely additive, old content stays exactly as it was. Used by
            the admin hub's "Update" button.
"""
import os
import re
import uuid
from typing import List, Tuple

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from backend.chatbot.config import chatbot_settings
from backend.chatbot.embeddings import embed_batch
from backend.chatbot import hybrid_search
from backend.chatbot.vectorstore import get_index

DOCX_PATH = os.path.join(os.path.dirname(__file__), "data", "JHS_HR_Policy_2026.docx")

# A section bigger than this gets sub-split (still tagged with the same
# `section` name) — most individual policy sections are well under this.
MAX_CHUNK_CHARS = 2200
SUB_CHUNK_OVERLAP = 300


def _heading_level(paragraph) -> int:
    """Returns 1/2 for a Word 'Heading 1'/'Heading 2' style paragraph, else 0."""
    style_name = (paragraph.style.name or "") if paragraph.style else ""
    m = re.match(r"Heading (\d)", style_name)
    return int(m.group(1)) if m and int(m.group(1)) <= 2 else 0


def _iter_block_items(doc: DocxDocument):
    """Yields each top-level paragraph AND table in the document, in the
    order they actually appear. doc.paragraphs / doc.tables each only
    return one type, flattened and in isolation — that silently dropped
    every table from ingestion entirely (e.g. a per-designation
    conveyance/allowance rate grid sitting right after its section's intro
    bullets). Standard python-docx recipe for in-order body iteration."""
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


def _table_to_text(table: DocxTable) -> str:
    """Flattens a table into plain lines the embedding model can actually
    use: one line per data row, formatted "<row label> — <col header>:
    <value>; <col header>: <value>; ..." so a per-designation rate grid
    reads as an explicit, quotable mapping rather than a bag of numbers
    with no column context."""
    rows = table.rows
    if not rows:
        return ""
    header_cells = [" ".join(c.text.split()) for c in rows[0].cells]
    lines = []
    for row in rows[1:]:
        cells = [" ".join(c.text.split()) for c in row.cells]
        if not any(cells):
            continue
        row_label = cells[0]
        pairs = [
            f"{h}: {v}"
            for h, v in zip(header_cells[1:], cells[1:])
            if v
        ]
        lines.append(f"{row_label} — {'; '.join(pairs)}" if row_label and pairs else "; ".join(pairs) or row_label)
    return "\n".join(lines)


def _extract_sections(doc: DocxDocument) -> List[Tuple[str, str]]:
    """Groups paragraphs (and any tables between them) into (title, body)
    sections split on Heading 1/2 boundaries. If the document has no such
    headings at all (style names not applied), falls back to fixed-size
    paragraph-boundary chunking so ingestion still works rather than
    producing one giant section."""
    sections: List[Tuple[str, str]] = []
    current_title = "General"
    current_lines: List[str] = []
    any_heading_found = False

    for block in _iter_block_items(doc):
        if isinstance(block, DocxTable):
            table_text = _table_to_text(block)
            if table_text:
                current_lines.append(table_text)
            continue

        text = block.text.strip()
        if not text:
            continue
        level = _heading_level(block)
        if level:
            any_heading_found = True
            if current_lines:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = text
            current_lines = []
        else:
            current_lines.append(text)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines)))

    if any_heading_found:
        return [(t, b) for t, b in sections if b.strip()]

    # No heading styles in this document — fall back to fixed-size chunks
    # over the whole flattened text, one "section" per chunk.
    full_text = "\n".join(l for _, b in sections for l in b.split("\n"))
    return _fallback_chunks(full_text)


def _fallback_chunks(text: str) -> List[Tuple[str, str]]:
    words = text.split()
    chunks = []
    chunk_size_words = 350
    for i in range(0, len(words), chunk_size_words):
        body = " ".join(words[i : i + chunk_size_words])
        if body.strip():
            chunks.append((f"Section {len(chunks) + 1}", body))
    return chunks


def _sub_split(body: str) -> List[str]:
    """Splits an overlong section body into overlapping pieces, keeping the
    same section title on every piece so retrieval can recombine them."""
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    pieces = []
    start = 0
    while start < len(body):
        end = start + MAX_CHUNK_CHARS
        pieces.append(body[start:end])
        start = end - SUB_CHUNK_OVERLAP
    return pieces


def _slugify(title: str, idx: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "section"
    return f"{slug}-{idx}"


def build_chunks(doc: DocxDocument) -> List[Tuple[str, str]]:
    """Returns [(chunk_text, section_title), ...] — the doc broken into
    section-scoped chunks, ready to embed. Pure/no side effects, so both
    the CLI script and the admin upload endpoints can call it the same way
    regardless of where the document came from."""
    sections = _extract_sections(doc)
    chunks = []
    for title, body in sections:
        for piece in _sub_split(body):
            chunks.append((f"{title}\n\n{piece}", title))
    return chunks


def ingest_records(chunks: List[Tuple[str, str]], mode: str) -> int:
    """Embeds and upserts `chunks` ([(text, section_title), ...]) into the
    "hr-policy" namespace.

    mode="replace": clears the namespace first, deterministic slug IDs
      (matches the old always-replace behavior — re-running against the
      same document produces the same IDs, so it cleanly overwrites itself
      rather than accumulating duplicates on repeated runs).
    mode="update": does NOT clear anything; random (uuid) IDs so this can
      never collide with (and silently overwrite) any existing chunk —
      purely additive, exactly what an admin's "Update" upload should do.

    Returns the number of chunks upserted.
    """
    if mode not in ("replace", "update"):
        raise ValueError(f"mode must be 'replace' or 'update', got {mode!r}")

    if mode == "replace":
        section_counts = {}
        records = []
        for text, section in chunks:
            i = section_counts.get(section, 0)
            section_counts[section] = i + 1
            records.append((_slugify(section, i), text, section))
    else:
        records = [(str(uuid.uuid4()), text, section) for text, section in chunks]

    if not records:
        return 0

    embeddings = embed_batch([r[1] for r in records])
    index = get_index()

    if mode == "replace":
        try:
            index.delete(delete_all=True, namespace=chatbot_settings.POLICY_NAMESPACE)
        except Exception:
            pass  # namespace doesn't exist yet on a brand-new index — nothing to clear

    vectors = [
        {"id": rec_id, "values": vec, "metadata": {"text": text, "section": section}}
        for (rec_id, text, section), vec in zip(records, embeddings)
    ]
    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        index.upsert(vectors=vectors[i : i + batch_size], namespace=chatbot_settings.POLICY_NAMESPACE)

    # Mirror the same records into the local BM25 snapshot (hybrid_search.py)
    # that rag.py's keyword-search side reads — same replace-vs-update
    # semantics as the Pinecone upsert above, just kept as a separate local
    # index since Pinecone itself has no BM25/keyword scoring.
    if mode == "replace":
        hybrid_search.replace_corpus(records)
    else:
        hybrid_search.update_corpus(records)

    # The FAQ cache (cache.py) is a pure semantic (question-similarity)
    # cache with no content-hash invalidation — it has no way to know the
    # knowledge base underneath it just changed, so a previously-cached
    # answer would otherwise keep being served verbatim forever, even after
    # it's now wrong (this is exactly how a stale, factually incorrect
    # cached answer survived a full Replace once already). ANY knowledge
    # mutation — update or replace — can make an existing cached answer
    # stale, so both modes clear it, not just replace.
    try:
        index.delete(delete_all=True, namespace=chatbot_settings.CACHE_NAMESPACE)
    except Exception:
        pass  # cache namespace empty/doesn't exist yet — nothing to clear

    return len(vectors)


def ingest() -> None:
    print(f"Reading {DOCX_PATH} ...")
    doc = DocxDocument(DOCX_PATH)
    chunks = build_chunks(doc)
    print(f"Built {len(chunks)} chunk(s). Replacing '{chatbot_settings.POLICY_NAMESPACE}' namespace ...")
    count = ingest_records(chunks, mode="replace")
    print(f"Upserted {count} vector(s) into namespace '{chatbot_settings.POLICY_NAMESPACE}'. Done.")


if __name__ == "__main__":
    ingest()
