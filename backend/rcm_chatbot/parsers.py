"""
File parsers, ported from the standalone Sentinel RCM app. Every parser
returns a list of "sheets":
    [{"name": str, "header": [str, ...], "rows": [[str, ...], ...]}, ...]
This uniform shape is what gets flattened into rows for embedding/upsert
into Pinecone (see ingest.py) — same shape the standalone app flattened into
MongoDB documents.
"""
import csv
import io
import json
import zipfile
from typing import List, Dict, Any, Optional, Tuple

import openpyxl
from docx import Document as DocxDocument
import pdfplumber
import olefile


def _clean(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def parse_xlsx(file_bytes: bytes) -> List[Dict[str, Any]]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    sheets = []
    for sn in wb.sheetnames:
        ws = wb[sn]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [_clean(c) for c in rows[0]]
        data_rows = []
        for r in rows[1:]:
            vals = [_clean(c) for c in r]
            if any(vals):
                data_rows.append(vals)
        sheets.append({"name": sn, "header": header, "rows": data_rows})
    sheets.extend(_extract_embedded_attachments(file_bytes, "xl/embeddings/"))
    return sheets


def parse_csv(file_bytes: bytes) -> List[Dict[str, Any]]:
    text = file_bytes.decode("utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader]
    if not rows:
        return []
    header = [_clean(c) for c in rows[0]]
    data_rows = [[_clean(c) for c in r] for r in rows[1:] if any(str(c).strip() for c in r)]
    return [{"name": "Sheet1", "header": header, "rows": data_rows}]


def parse_docx(file_bytes: bytes) -> List[Dict[str, Any]]:
    doc = DocxDocument(io.BytesIO(file_bytes))
    sheets = []
    if doc.tables:
        for ti, table in enumerate(doc.tables):
            header, data_rows = [], []
            for ri, row in enumerate(table.rows):
                vals = [c.text.strip() for c in row.cells]
                if ri == 0:
                    header = vals
                elif any(vals):
                    data_rows.append(vals)
            sheets.append({"name": f"Table{ti + 1}", "header": header, "rows": data_rows})
    else:
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        sheets.append({"name": "Content", "header": ["Text"], "rows": [[p] for p in paras]})
    sheets.extend(_extract_embedded_attachments(file_bytes, "word/embeddings/"))
    return sheets


def parse_pdf(file_bytes: bytes) -> List[Dict[str, Any]]:
    sheets = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for pi, page in enumerate(pdf.pages):
            # find_tables() (not extract_tables()) so each table's bbox is
            # available below, for excluding it from the plain-text pass.
            found_tables = page.find_tables()
            for ti, t in enumerate(found_tables):
                table = t.extract()
                if not table:
                    continue
                header = [_clean(c) for c in table[0]]
                data_rows = [[_clean(c) for c in r] for r in table[1:] if any(_clean(c) for c in r)]
                if data_rows:
                    sheets.append({"name": f"Page{pi + 1}_Table{ti + 1}", "header": header, "rows": data_rows})

            # ALWAYS also extract the page's plain text — even when it has
            # tables — a real page routinely mixes a table with surrounding
            # paragraphs/bullets (e.g. a disciplinary-band matrix immediately
            # followed by separate policy bullet points on the very same
            # page); skipping plain text whenever a table was found once
            # silently dropped every non-table line on such a page, which is
            # exactly how a real policy fact went missing without any error.
            #
            # But the plain text is taken with every detected table's own
            # region EXCLUDED, not the raw whole-page text — extract_text()
            # reading a wide multi-column table (e.g. one designation-rate
            # column per row) produces the wrapped header/cell text in
            # left-to-right, top-to-bottom READING order, which does not
            # preserve which cell belongs to which column. That garbled
            # reading is actively misleading (worse than not having it) once
            # it sits in the knowledge base next to the correctly
            # column-mapped table extraction above — it's exactly how a
            # different designation's Fuel allowance once got misread as the
            # asked-about designation's Conveyance figure. The properly
            # extracted table sheets above already cover that same content
            # correctly, so the excluded region loses nothing.
            text_page = page
            for t in found_tables:
                try:
                    text_page = text_page.outside_bbox(t.bbox)
                except Exception:
                    pass  # a degenerate/zero-area bbox — leave text_page as-is
            text = text_page.extract_text() or ""
            paras = [p.strip() for p in text.split("\n") if p.strip()]
            if paras:
                sheets.append({"name": f"Page{pi + 1}", "header": ["Text"], "rows": [[p] for p in paras]})
    if not sheets:
        raise ValueError("No extractable text or tables found in this PDF (it may be a scanned image).")
    return sheets


# "Insert > Object > Create from File" in Excel/Word wraps whatever file was
# embedded (PDF, .docx, .xlsx, ...) in an OLE compound-file container, stored
# in the workbook/document's own zip under xl/embeddings/ or word/embeddings/
# as e.g. "oleObject1.bin" - regardless of the embedded file's real type. The
# actual bytes are recovered by unwrapping that container (see
# _unwrap_ole_embedding) and are then run back through the normal parser for
# whatever type they turn out to be, so their content becomes searchable rows
# too instead of being silently dropped.
_ATTACHMENT_PARSERS = {
    "pdf": lambda b: parse_pdf(b),
    "docx": lambda b: parse_docx(b),
    "xlsx": lambda b: parse_xlsx(b),
}


def _unwrap_ole_embedding(raw: bytes) -> Optional[Tuple[bytes, str]]:
    """Pull the real embedded file's bytes out of an OLE compound-file (.bin)
    container. Office puts the embedded file verbatim in a "Package" stream
    for file-based embeds (used for PDFs and other zip/OOXML formats) or a
    "CONTENTS" stream for legacy binary formats - try both, then sniff the
    actual file type from its own magic bytes, since the OLE wrapper itself
    doesn't reliably say what's inside. Returns None if the container isn't
    a real OLE file, has neither stream, or wraps a type we don't parse
    (e.g. a legacy pre-2007 .doc/.xls, or a non-file OLE object)."""
    try:
        ole = olefile.OleFileIO(io.BytesIO(raw))
    except Exception:
        return None
    try:
        for stream in (["Package"], ["CONTENTS"], ["Contents"]):
            if not ole.exists("/".join(stream)):
                continue
            data = ole.openstream(stream).read()
            if data[:4] == b"%PDF":
                return data, "pdf"
            if data[:4] == b"PK\x03\x04":
                try:
                    inner_names = zipfile.ZipFile(io.BytesIO(data)).namelist()
                except zipfile.BadZipFile:
                    return None
                if any(n.startswith("word/") for n in inner_names):
                    return data, "docx"
                if any(n.startswith("xl/") for n in inner_names):
                    return data, "xlsx"
            return None
    finally:
        ole.close()
    return None


def _extract_embedded_attachments(file_bytes: bytes, embeddings_prefix: str) -> List[Dict[str, Any]]:
    """Scan an .xlsx/.docx's own zip for embedded PDF/Word/Excel attachments
    under `embeddings_prefix` and parse each one through its normal parser,
    returning extra "sheets" (same shape every parser returns) so the
    attachment's content is inserted as additional searchable rows alongside
    the workbook/document's own data. Never raises: a corrupt or unsupported
    embedded object is skipped rather than failing the whole upload."""
    sheets: List[Dict[str, Any]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return sheets
    for name in zf.namelist():
        if not name.startswith(embeddings_prefix):
            continue
        label = name.rsplit("/", 1)[-1]
        try:
            raw = zf.read(name)
        except Exception:
            continue
        ext = label.rsplit(".", 1)[-1].lower() if "." in label else ""
        payload, payload_ext = raw, ext
        if ext == "bin":
            unwrapped = _unwrap_ole_embedding(raw)
            if unwrapped is None:
                continue
            payload, payload_ext = unwrapped
        parser = _ATTACHMENT_PARSERS.get(payload_ext)
        if not parser:
            continue
        try:
            attachment_sheets = parser(payload)
        except Exception:
            continue
        for s in attachment_sheets:
            sheets.append({
                "name": f"Attachment - {label} - {s['name']}",
                "header": s["header"],
                "rows": s["rows"],
            })
    return sheets


def parse_txt(file_bytes: bytes) -> List[Dict[str, Any]]:
    text = file_bytes.decode("utf-8", errors="ignore")
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return [{"name": "Content", "header": ["Text"], "rows": [[p] for p in paras]}]


def parse_json_file(file_bytes: bytes) -> List[Dict[str, Any]]:
    data = json.loads(file_bytes.decode("utf-8", errors="ignore"))
    if isinstance(data, list) and data and isinstance(data[0], dict):
        header = list(data[0].keys())
        rows = [[_clean(obj.get(h, "")) for h in header] for obj in data]
        return [{"name": "Records", "header": header, "rows": rows}]
    return [{"name": "Content", "header": ["Value"], "rows": [[json.dumps(data)]]}]


def parse_file(filename: str, file_bytes: bytes) -> List[Dict[str, Any]]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls"):
        return parse_xlsx(file_bytes)
    if ext == "csv":
        return parse_csv(file_bytes)
    if ext == "docx":
        return parse_docx(file_bytes)
    if ext == "pdf":
        return parse_pdf(file_bytes)
    if ext == "txt":
        return parse_txt(file_bytes)
    if ext == "json":
        return parse_json_file(file_bytes)
    raise ValueError(f"Unsupported file type: .{ext}")
