# backend/cv_builder/storage.py
"""
GridFS storage for the CV Builder (database CV_Builder, bucket "cv_files").

  photo  the employee's profile photo (JPEG, resized) - one per employee
  cv     the generated profile slide (.pptx) - one per employee, kept for the
         profile version it was built from so repeat downloads / admin
         downloads reuse it instead of rebuilding it

Replacing a file removes the previous one, so each employee has at most one of each.
"""

import base64
import binascii
from io import BytesIO
from typing import Optional, Tuple

import gridfs

from backend.database import cv_db

_fs = gridfs.GridFS(cv_db, collection="cv_files")

MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_MAX_SIDE = 900
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _delete(empid: str, kind: str) -> None:
    for f in _fs.find({"metadata.empid": empid, "metadata.kind": kind}):
        _fs.delete(f._id)


def _find(empid: str, kind: str):
    return _fs.find_one({"metadata.empid": empid, "metadata.kind": kind})


# ── photo ─────────────────────────────────────────────────────────────────────
def normalize_photo(data_url: str) -> bytes:
    """Validate an uploaded image (data: URL) and return it as a resized JPEG. ValueError if unusable."""
    if not data_url.startswith("data:image/") or "," not in data_url:
        raise ValueError("Photo must be an image")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("Photo could not be read")
    if not raw or len(raw) > MAX_PHOTO_BYTES:
        raise ValueError("Photo must be 8 MB or smaller")
    from PIL import Image, ImageOps
    try:
        img = Image.open(BytesIO(raw))
        if img.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("Photo must be a PNG, JPG or WEBP image")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Photo could not be read")
    img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    out = BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def save_photo(empid: str, jpeg: bytes) -> None:
    _delete(empid, "photo")
    _fs.put(jpeg, filename=f"photo_{empid}.jpg", content_type="image/jpeg",
            metadata={"empid": empid, "kind": "photo"})


def get_photo(empid: str) -> Optional[bytes]:
    f = _find(empid, "photo")
    return f.read() if f else None


def delete_photo(empid: str) -> None:
    _delete(empid, "photo")


# ── generated CV ──────────────────────────────────────────────────────────────
def get_cv(empid: str, version: str) -> Optional[bytes]:
    """The stored slide, only if it was built from this profile version."""
    f = _find(empid, "cv")
    if f and (f.metadata or {}).get("version") == version:
        return f.read()
    return None


def save_cv(empid: str, version: str, data: bytes, filename: str) -> None:
    _delete(empid, "cv")
    _fs.put(data, filename=filename, content_type=_PPTX_MIME,
            metadata={"empid": empid, "kind": "cv", "version": version})


def delete_all(empid: str) -> None:
    for f in _fs.find({"metadata.empid": empid}):
        _fs.delete(f._id)
