# backend/employee_declaration/html_render.py
"""
Converts the fixed Employee Declaration Word document to HTML once, at
import time, and caches it - the document doesn't change per-request so
there's no reason to re-run mammoth on every page load.
"""
import os

import mammoth

_DOCX_PATH = os.path.join(os.path.dirname(__file__), "document.docx")

with open(_DOCX_PATH, "rb") as _f:
    _result = mammoth.convert_to_html(_f)

DECLARATION_HTML = _result.value
