# backend/exit_management/signature.py
"""Signature file handling for the Exit Form: upload, view/download, remove, and the pre-submit check.

The signature is a PDF / JPG / JPEG / PNG file of at most 5 MB, stored in the GridFS bucket
`signature_files` (same shared database as `exist_form`). The form document keeps only a reference:

    signature_file: {gridfs_file_id, filename, content_type, file_size, extension, uploaded_at}

GridFS file metadata: employee_id, form_id (the exist_form _id), original_filename, content_type,
extension, uploaded_at.  A file is only ever read/changed through the signed-in employee's OWN form
document, and its metadata.employee_id is re-checked on every read.

`store_upload` / `stream_response` / `delete_file` are shared with the Reporting Manager's handover form
(manager.py), which stores one such file per row with extra metadata (kind, row_key, uploaded_by).
"""
import logging
import os
import re
from urllib.parse import quote

from bson import ObjectId
from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from gridfs.errors import NoFile
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.exit_management import repository as repo
from backend.exit_management.utils import ALREADY_SUBMITTED, public_signature, utcnow

log = logging.getLogger("exit_management")

MAX_BYTES = 5 * 1024 * 1024          # 5 MB
CHUNK = 256 * 1024                   # files are streamed in 256 KB pieces, never read whole into memory

# kind -> (stored content type, allowed file extensions)
TYPES = {
    "pdf":  ("application/pdf", {".pdf"}),
    "jpeg": ("image/jpeg", {".jpg", ".jpeg"}),
    "png":  ("image/png", {".png"}),
}
# What a browser may legitimately declare as Content-Type (None = no information, rely on the file content).
DECLARED = {"application/pdf": "pdf", "image/jpeg": "jpeg", "image/pjpeg": "jpeg", "image/png": "png",
            "image/x-png": "png", "application/octet-stream": None, "": None}


def _sniff(head: bytes):
    """Identify the file from its first bytes (an allow-list: anything else is rejected)."""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def _clean_filename(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:200] or "signature"


def _validate(upload: UploadFile):
    """Check name, size and real content BEFORE anything is written. Returns (kind, filename, extension)."""
    name = _clean_filename(upload.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in {e for _, exts in TYPES.values() for e in exts}:
        raise HTTPException(415, "Unsupported file type. Please upload a PDF, JPG, JPEG or PNG file.")
    f = upload.file
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size == 0:
        raise HTTPException(400, "The selected file is empty.")
    if size > MAX_BYTES:
        raise HTTPException(413, "File is too large. Maximum size is 5 MB.")
    kind = _sniff(f.read(16))
    f.seek(0)
    if kind is None:
        raise HTTPException(415, "Unsupported or unsafe file. Only real PDF, JPG, JPEG and PNG files are accepted.")
    if ext not in TYPES[kind][1]:
        raise HTTPException(415, "The file extension does not match the file content.")
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared not in DECLARED:
        raise HTTPException(415, "Unsupported file type. Please upload a PDF, JPG, JPEG or PNG file.")
    if DECLARED[declared] not in (None, kind):
        raise HTTPException(415, "The file type does not match the file content.")
    if kind in ("jpeg", "png"):                   # images must also decode as real images
        from PIL import Image
        try:
            with Image.open(f) as im:
                im.verify()
                fmt = im.format
        except Exception:
            raise HTTPException(415, "The image file is damaged or not a valid image.")
        finally:
            f.seek(0)
        if fmt != kind.upper():
            raise HTTPException(415, "The image content does not match its file type.")
    return kind, name, ext


def delete_file(file_id) -> None:
    """Remove a GridFS file; a missing file is fine, other failures are logged (never raised)."""
    try:
        repo.signature_bucket.delete(file_id)
    except NoFile:
        pass
    except PyMongoError:
        log.exception("could not delete GridFS file %s", file_id)


def store_upload(upload: UploadFile, extra_metadata: dict):
    """Validate the uploaded file and stream it into GridFS (nothing is left behind on failure).
    Returns (gridfs_file_id, reference dict). The caller attaches the reference to a document and,
    if that fails, must delete_file() the new file."""
    kind, name, ext = _validate(upload)
    ctype = TYPES[kind][0]
    now = utcnow()
    f = upload.file
    f.seek(0)
    grid_in = repo.signature_bucket.open_upload_stream(name, metadata={
        **extra_metadata, "original_filename": name, "content_type": ctype, "extension": ext, "uploaded_at": now})
    new_id, total = grid_in._id, 0
    try:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:                  # safety net (size was already checked)
                raise HTTPException(413, "File is too large. Maximum size is 5 MB.")
            grid_in.write(chunk)
        if total == 0:
            raise HTTPException(400, "The selected file is empty.")
        grid_in.close()
    except HTTPException:
        grid_in.abort()                            # removes any chunks already written: no orphans
        raise
    except Exception:
        log.exception("file upload to GridFS failed")
        try:
            grid_in.abort()
        except Exception:
            pass
        raise HTTPException(503, "Could not save the file. Please try again.")
    return new_id, {"gridfs_file_id": new_id, "filename": name, "content_type": ctype,
                    "file_size": total, "extension": ext, "uploaded_at": now}


def stream_response(ref: dict, meta_ok, download: bool = False) -> StreamingResponse:
    """Stream a stored file with its real content type. `meta_ok(metadata) -> bool` decides whether the
    GridFS file really belongs where the caller found the reference (otherwise: 404)."""
    try:
        grid_out = repo.signature_bucket.open_download_stream(ref["gridfs_file_id"])
    except NoFile:
        raise HTTPException(404, "Signature file not found.")
    meta = grid_out.metadata or {}
    if not meta_ok(meta):                          # never serve a file that is not where it claims to be
        grid_out.close()
        raise HTTPException(404, "Signature file not found.")

    def stream():
        try:
            while True:
                chunk = grid_out.read(CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            grid_out.close()

    name = ref.get("filename") or "signature"
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
    disposition = f'{"attachment" if download else "inline"}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'
    return StreamingResponse(stream(), media_type=meta.get("content_type") or ref.get("content_type"),
                             headers={"Content-Disposition": disposition, "Content-Length": str(grid_out.length),
                                      "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


def own_file(file_id, meta_ok):
    """The GridFS file `file_id`, only if it exists AND `meta_ok(metadata)`; else None."""
    try:
        found = list(repo.signature_bucket.find({"_id": file_id}).limit(1))
    except PyMongoError:
        log.exception("GridFS lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if not found or not meta_ok(found[0].metadata or {}):
        return None
    return found[0]


# ── the employee's own signature on the Exit Form ─────────────────────────────
def upload_signature(empid: str, upload: UploadFile) -> dict:
    """Validate, stream the file into GridFS, then point the employee's DRAFT form at it.
    The previous file is deleted only after the new one is saved and referenced."""
    repo.ensure_indexes()
    existing = repo.find_form(empid)
    if existing and existing.get("status") == "submitted":
        raise HTTPException(409, ALREADY_SUBMITTED)
    form_id = existing["_id"] if existing else ObjectId()
    now = utcnow()
    new_id, ref = store_upload(upload, {"employee_id": empid, "form_id": form_id})
    try:
        before = repo.collection.find_one_and_update(
            {"employee_id": empid, "status": "draft"},
            {"$set": {"signature_file": ref, "updated_at": now},
             "$setOnInsert": {"_id": form_id, "employee_id": empid, "status": "draft", "created_at": now}},
            upsert=True, return_document=ReturnDocument.BEFORE)
    except DuplicateKeyError:                      # the form was submitted meanwhile
        delete_file(new_id)
        raise HTTPException(409, ALREADY_SUBMITTED)
    except PyMongoError:
        log.exception("could not attach signature for %s", empid)
        delete_file(new_id)
        raise HTTPException(503, "Could not reach the database. Please try again.")

    old = ((before or {}).get("signature_file") or {}).get("gridfs_file_id")
    if old and old != new_id:
        delete_file(old)                           # only now that the new file is safely referenced
    log.info("signature uploaded for %s (%s, %d bytes)", empid, ref["content_type"], ref["file_size"])
    return public_signature(ref)


def _own_signature_ref(empid: str):
    doc = repo.find_form(empid)
    ref = (doc or {}).get("signature_file")
    if not doc or not ref:
        raise HTTPException(404, "No signature file uploaded.")
    return doc, ref


def get_signature(empid: str, download: bool = False) -> StreamingResponse:
    """Stream the employee's own signature file with its real content type."""
    _, ref = _own_signature_ref(empid)
    return stream_response(ref, lambda meta: meta.get("employee_id") == empid, download)


def delete_signature(empid: str) -> dict:
    """Remove the signature from the employee's DRAFT. A submitted form's signature is never deleted."""
    doc, ref = _own_signature_ref(empid)
    if doc.get("status") == "submitted":
        raise HTTPException(409, ALREADY_SUBMITTED)
    file_id = ref["gridfs_file_id"]
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "employee_id": empid, "status": "draft", "signature_file.gridfs_file_id": file_id},
            {"$unset": {"signature_file": ""}, "$set": {"updated_at": utcnow()}})
    except PyMongoError:
        log.exception("could not remove signature reference for %s", empid)
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if res.modified_count == 0:
        raise HTTPException(409, "The signature changed or the form was submitted. Please reload the page.")
    delete_file(file_id)
    return {"deleted": True}


def check_for_submit(empid: str):
    """Pre-submit checks. Returns (error list, form document). Raises 409 if already submitted."""
    doc = repo.find_form(empid)
    if doc and doc.get("status") == "submitted":
        raise HTTPException(409, ALREADY_SUBMITTED)
    ref = (doc or {}).get("signature_file")
    if not ref:
        return ["Please upload your signature document"], doc
    gf = own_file(ref.get("gridfs_file_id"), lambda m: m.get("employee_id") == empid)
    if gf is None:
        return ["Your uploaded signature file could not be found - please upload it again"], doc
    if str((gf.metadata or {}).get("form_id")) != str(doc["_id"]):
        return ["Your uploaded signature does not belong to this form - please upload it again"], doc
    if gf.length <= 0 or gf.length > MAX_BYTES:
        return ["Your uploaded signature file has an invalid size - please upload it again"], doc
    return [], doc
