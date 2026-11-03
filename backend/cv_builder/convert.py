# backend/cv_builder/convert.py
"""
Profile slide (.pptx) -> PDF, used for the in-browser "View" of a CV.

  * Linux / Docker: LibreOffice in headless mode (installed in the Dockerfile).
  * Windows (local development): Microsoft PowerPoint, driven through PowerShell COM.
"""

import os
import shutil
import subprocess
import tempfile
import threading

_ppt_lock = threading.Lock()           # PowerPoint handles one conversion at a time


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def _ppt_available() -> bool:
    if os.name != "nt" or not shutil.which("powershell"):
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application"))
        return True
    except OSError:
        return False


_PPT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$p = New-Object -ComObject PowerPoint.Application
try {
  $d = $p.Presentations.Open($args[0], $true, $false, $false)
  $d.SaveAs($args[1], 32)
  $d.Close()
} finally { if ($p.Presentations.Count -eq 0) { $p.Quit() } }
"""


def pptx_to_pdf(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="cvppt_") as tmp:
        src, out = os.path.join(tmp, "profile.pptx"), os.path.join(tmp, "profile.pdf")
        with open(src, "wb") as f:
            f.write(data)
        if _soffice():
            r = subprocess.run([_soffice(), "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                               capture_output=True, timeout=90,
                               env={**os.environ, "HOME": os.environ.get("HOME", tmp)})
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("PDF conversion failed")
        elif _ppt_available():
            script = os.path.join(tmp, "convert.ps1")
            with open(script, "w", encoding="utf-8") as f:
                f.write(_PPT_SCRIPT)
            with _ppt_lock:
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, src, out],
                                   capture_output=True, timeout=120)
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("PDF conversion failed")
        else:
            raise RuntimeError("PDF conversion is not available on this server")
        with open(out, "rb") as f:
            return f.read()
