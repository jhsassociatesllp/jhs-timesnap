"""
Generic "any supported file type -> [(chunk_text, section_title), ...]"
bridge, shared by the HR Policy and JHS Library admin uploads so an admin
isn't limited to one specific file format per bot.

.docx gets the specialized, heading/table-aware extraction already in
ingest_policy.py (keeps a real Word doc's structure — the best case, and
what the bundled HR policy doc actually is). Every other supported type
(pdf, xlsx, xls, csv, txt, json) goes through backend/rcm_chatbot/parsers.py's
existing multi-format parsers (already battle-tested for the RCM bot) and
gets flattened into the same (chunk_text, section_title) shape generically:
one section per "sheet" (a PDF page, a spreadsheet sheet, a table found in
a docx/xlsx, ...), header/rows flattened into readable lines, split further
if a section runs long (reuses ingest_policy's own MAX_CHUNK_CHARS logic).
"""
import io
import re
from typing import List, Tuple

from backend.chatbot import ingest_policy
from backend.rcm_chatbot import parsers as rcm_parsers

SUPPORTED_EXTS = ("docx", "pdf", "xlsx", "xls", "csv", "txt", "json")

# A PDF page's own "sheet" name (from rcm_parsers.parse_pdf) is a bare
# "PageN" / "PageN_TableM" implementation detail — meaningful for internal
# chunk grouping, but not something a user asking a policy question should
# see quoted back as a "source" (a real sheet name like an actual Excel tab
# is still worth keeping, so this is deliberately narrow, not "hide every
# sheet name").
_PAGE_REF_RE = re.compile(r"^Page\d+(?:_Table\d+)?$", re.IGNORECASE)


def _clean_cell(v) -> str:
    # Collapses embedded newlines/runs of whitespace to single spaces — a
    # PDF table cell whose text wraps onto multiple visual lines (e.g. a
    # header like "Notice Period (After\nProbation)") otherwise leaves a
    # literal newline INSIDE one cell's value; since _sheet_to_text below
    # joins every flattened row with "\n" too, an unnormalized cell like
    # that corrupts the shape of the whole flattened table — a wrapped
    # header cell reads as an extra, bogus row instead of one column
    # heading, misleading both retrieval and the model reading it. Same
    # normalization ingest_policy.py's own docx table handler already
    # applies for exactly this reason.
    return " ".join(str(v).split())


def _sheet_to_text(sheet: dict) -> str:
    """Flattens one RCM-parser "sheet" ({"name", "header", "rows"}) into
    readable lines — the same "<row label> — <col>: <val>; ..." shape
    ingest_policy._table_to_text uses for a docx table, just built off
    plain lists instead of python-docx objects, so it works for any
    parser's output uniformly."""
    header = [_clean_cell(h) for h in (sheet.get("header") or [])]
    rows = sheet.get("rows") or []
    lines = []
    for raw_row in rows:
        if not any(str(v).strip() for v in raw_row):
            continue
        row = [_clean_cell(v) for v in raw_row]
        row_label = row[0] if row else ""
        pairs = [f"{h}: {v}" for h, v in zip(header[1:], row[1:]) if v]
        if row_label and pairs:
            lines.append(f"{row_label} — {'; '.join(pairs)}")
        elif pairs:
            lines.append("; ".join(pairs))
        elif row_label:
            lines.append(row_label)
    return "\n".join(lines)


def build_chunks_any_format(
    filename: str, content: bytes, collapse_page_refs: bool = True
) -> List[Tuple[str, str]]:
    """Returns [(chunk_text, section_title), ...] — same shape
    ingest_policy.build_chunks() returns — regardless of the uploaded
    file's actual type. Raises ValueError for an unsupported extension.

    collapse_page_refs: when True (default — JHS Library's behavior,
    unchanged), a PDF page's bare "PageN"/"PageN_TableM" sheet name
    collapses into just the filename, since Library only uses this as a
    short observation headline. Pass False (the HR bot's admin uploads do)
    to keep the granular per-page section title instead — the HR bot's
    retrieval groups related chunks BY this value (see rag.py's sibling-
    fetch), so collapsing it there would make every chunk from a multi-page
    PDF share one section and defeat that grouping. HR still shows a clean,
    page-free citation to the employee — rag.py strips the page suffix at
    DISPLAY time instead, from this same granular value."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported file type: .{ext}. Supported: {', '.join('.' + e for e in SUPPORTED_EXTS)}"
        )

    if ext == "docx":
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(content))
        return ingest_policy.build_chunks(doc)

    sheets = rcm_parsers.parse_file(filename, content)
    chunks: List[Tuple[str, str]] = []
    for sheet in sheets:
        text = _sheet_to_text(sheet)
        if not text:
            continue
        sheet_name = sheet.get("name", "Sheet1")
        if collapse_page_refs and _PAGE_REF_RE.match(sheet_name):
            section_title = filename
        else:
            section_title = f"{filename} — {sheet_name}"
        for piece in ingest_policy._sub_split(text):
            chunks.append((f"{section_title}\n\n{piece}", section_title))
    return chunks
