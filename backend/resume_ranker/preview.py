# backend/resume_ranker/preview.py
"""
Browser-viewable PDF previews of uploaded CVs.

Browsers only render PDFs, so Word / PowerPoint / RTF / HTML CVs are converted
with LibreOffice (headless) on first view and cached next to the original
(stored in the database next to the CV), so every uploaded CV can be opened in the viewer.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading

from backend.resume_ranker.extract import sniff_kind

_lock = threading.Lock()          # one soffice at a time; conversions are rare and short
_EXT = {"docx": "docx", "doc": "doc", "pptx": "pptx", "ppt": "ppt", "rtf": "rtf", "html": "html"}


class PreviewError(Exception):
    """The CV could not be turned into a viewable PDF."""


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert(data: bytes, kind: str, target: str) -> bytes:
    """Convert document bytes of `kind` to `target` ("pdf" / "pptx") with LibreOffice."""
    exe = _soffice()
    if not exe:
        raise PreviewError("Document conversion is not available on this server")
    with _lock, tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, f"cv.{_EXT.get(kind, kind)}")
        with open(src, "wb") as fh:
            fh.write(data)
        profile = os.path.join(tmp, "lo_profile")   # own profile: no clashes, works with a read-only HOME
        try:
            subprocess.run([exe, f"-env:UserInstallation=file:///{profile.replace(os.sep, '/')}",
                            "--headless", "--convert-to", target, "--outdir", tmp, src],
                           check=True, timeout=120, capture_output=True)
        except subprocess.TimeoutExpired:
            raise PreviewError("Conversion timed out")
        except (subprocess.CalledProcessError, OSError) as exc:
            raise PreviewError(f"Conversion failed: {exc}")
        out = os.path.join(tmp, f"cv.{target}")
        if not os.path.exists(out):
            raise PreviewError("Conversion produced no output — the file may be corrupt")
        with open(out, "rb") as fh:
            return fh.read()


def to_pdf_bytes(data: bytes) -> bytes:
    """PDF bytes the browser can display for a stored CV (the CV itself if it is already a PDF)."""
    kind = sniff_kind(data)
    if kind == "pdf":
        return data
    if kind not in _EXT:
        raise PreviewError("This file type cannot be previewed")
    return convert(data, kind, "pdf")
