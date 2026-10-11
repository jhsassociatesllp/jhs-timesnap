# backend/cv_builder/convert.py
"""
Word -> PDF conversion for the CV Builder.

  * Linux / Docker: LibreOffice in headless mode (installed in the Dockerfile).
  * Windows (local development): Microsoft Word, driven through PowerShell COM.
    If Word is already open it is reused and left open; we only close our own
    document.
"""

import os
import shutil
import subprocess
import tempfile
import threading

_word_lock = threading.Lock()          # Word handles one conversion at a time


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def _word_available() -> bool:
    if os.name != "nt" or not shutil.which("powershell"):
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application"))
        return True
    except OSError:
        return False


def pdf_engine():
    if _soffice():
        return "libreoffice"
    if _word_available():
        return "word"
    return None


def pdf_available() -> bool:
    return pdf_engine() is not None


_WORD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$running = [bool](Get-Process WINWORD -ErrorAction SilentlyContinue)
$w = New-Object -ComObject Word.Application
if (-not $running) { $w.Visible = $false; $w.DisplayAlerts = 0 }
$d = $null
try {
  $d = $w.Documents.Open($env:CV_IN, $false, $true, $false)
  $d.ExportAsFixedFormat($env:CV_OUT, 17)
} finally {
  if ($d) { $d.Close(0) }
  if (-not $running) { $w.Quit() }
}
"""


def docx_to_pdf(data: bytes, name: str = "cv") -> bytes:
    """Convert .docx bytes to PDF bytes. Raises RuntimeError if impossible."""
    engine = pdf_engine()
    if engine is None:
        raise RuntimeError("PDF export is not available on this server")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, name + ".docx")
        out = os.path.join(tmp, name + ".pdf")
        with open(src, "wb") as f:
            f.write(data)
        try:
            if engine == "libreoffice":
                # own profile dir: parallel conversions / a read-only HOME don't clash
                profile = os.path.join(tmp, "lo_profile")
                subprocess.run(
                    [_soffice(), f"-env:UserInstallation=file:///{profile.replace(os.sep, '/')}",
                     "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                    check=True, timeout=120, capture_output=True)
            else:
                env = dict(os.environ, CV_IN=src, CV_OUT=out)
                with _word_lock:
                    subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WORD_SCRIPT],
                        check=True, timeout=120, capture_output=True, env=env)
            with open(out, "rb") as f:
                return f.read()
        except subprocess.TimeoutExpired:
            raise RuntimeError("PDF conversion timed out")
        except subprocess.CalledProcessError as e:
            raise RuntimeError("PDF conversion failed: " + (e.stderr or b"").decode("utf-8", "ignore")[:200])
        except FileNotFoundError:
            raise RuntimeError("PDF conversion failed")
