# backend/kyc_form/sharepoint.py
"""
Copies every submitted KYC form to the HR Team SharePoint, through Microsoft Graph.

Where it goes (inside the library "Documents" of https://jhsassociatesindia.sharepoint.com/sites/HRTeam):

    KYC DETAILS / <year> / <dd-mm-yyyy> / <Person name (code)> /
        KYC Details - <Person name>.xlsx         every answer, plus the list of documents
        <Question label> - <file name>           every document the person uploaded

<year> and <dd-mm-yyyy> are the day the form was submitted, in India time. A folder that is not there yet is
created (a new year gets a new year folder, a new day a new date folder). Submitting again on the same day
replaces that person's files in the same folder.

TWO PLACES CAN BE USED (either or both):
  1. A folder on the computer the server runs on  ->  KYC_SAVE_DIR  (no Azure permission needed)
     Point it at a folder that OneDrive syncs (for example a folder inside "OneDrive - JHS Associates", or the HR Team
     library synced to the PC). The same structure is written below it, and OneDrive sends it to the cloud by itself.
     KYC_SAVE_DIR is the folder that plays the role of "KYC DETAILS":  <KYC_SAVE_DIR>/<year>/<dd-mm-yyyy>/<person>/
  2. SharePoint through Microsoft Graph  ->  needs the Azure permission below. Switch it off with KYC_SHAREPOINT_UPLOAD=off.

Uses the same Azure app as the e-mails (MS_MAIL_TENANT_ID, MS_MAIL_CLIENT_ID, MS_MAIL_CLIENT_SECRET). The app needs
the Microsoft Graph APPLICATION permission "Sites.ReadWrite.All" (or Sites.Selected with write access to the
HR Team site), with admin consent. Optional settings (the defaults match the HR Team site):
  SHAREPOINT_SITE         default  jhsassociatesindia.sharepoint.com:/sites/HRTeam
  SHAREPOINT_LIBRARY      default  Documents
  SHAREPOINT_KYC_FOLDER   default  KYC DETAILS
"""
import io
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

from backend.buddy_referral import notify

log = logging.getLogger("kyc.sharepoint")

GRAPH = "https://graph.microsoft.com/v1.0"
IST = timedelta(hours=5, minutes=30)
SMALL_UPLOAD = 4 * 1024 * 1024                  # Graph's single-request limit; bigger files use an upload session
_ids: dict = {}                                 # cached site / drive ids


def _cfg() -> dict:
    return {
        "tenant": (os.getenv("MS_MAIL_TENANT_ID") or os.getenv("GRAPH_TENANT_ID", "")).strip(),
        "client_id": (os.getenv("MS_MAIL_CLIENT_ID") or os.getenv("GRAPH_CLIENT_ID", "")).strip(),
        "secret": (os.getenv("MS_MAIL_CLIENT_SECRET") or os.getenv("GRAPH_CLIENT_SECRET", "")).strip(),
        "site": os.getenv("SHAREPOINT_SITE", "").strip() or "jhsassociatesindia.sharepoint.com:/sites/HRTeam",
        "library": os.getenv("SHAREPOINT_LIBRARY", "").strip() or "Documents",
        "root": os.getenv("SHAREPOINT_KYC_FOLDER", "").strip() or "KYC DETAILS",
    }


def graph_configured() -> bool:
    c = _cfg()
    off = os.getenv("KYC_SHAREPOINT_UPLOAD", "").strip().lower() in ("off", "0", "no", "false")
    return bool(c["tenant"] and c["client_id"] and c["secret"]) and not off


def local_dir() -> str:
    return os.getenv("KYC_SAVE_DIR", "").strip().strip('"')


def is_configured() -> bool:
    """True when there is somewhere to save to: the OneDrive folder and / or SharePoint."""
    return bool(local_dir()) or graph_configured()


def safe_name(text: str, limit: int = 100) -> str:
    """A name SharePoint accepts as a file / folder name."""
    t = re.sub(r'[\x00-\x1f"*:<>?/\\|#%~&{}]+', " ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip(" .")
    return (t[:limit].strip(" .") or "Unknown")


def folder_segments(name: str, empid: str, submitted_at) -> list:
    """[ 'KYC DETAILS', '2026', '14-10-2026', 'Name (JHS1191)' ] — the day is the IST day of the submission."""
    when = submitted_at if isinstance(submitted_at, datetime) else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    day = (when.astimezone(timezone.utc) + IST)
    return [_cfg()["root"], str(day.year), day.strftime("%d-%m-%Y"), f"{safe_name(name, 80)} ({safe_name(empid, 20)})"]


def _error(resp) -> str:
    try:
        e = resp.json().get("error") or {}
        return f"{resp.status_code} {e.get('code', '')}: {str(e.get('message', ''))[:160]}".strip()
    except Exception:
        return f"{resp.status_code} {resp.text[:120]}"


def _call(method: str, url: str, token: str, tries: int = 3, **kw):
    """One Graph call; waits and retries on throttling (429) and server hiccups (5xx)."""
    headers = {"Authorization": f"Bearer {token}", **kw.pop("headers", {})}
    for attempt in range(tries):
        resp = getattr(requests, method)(url, headers=headers, timeout=120, **kw)
        if resp.status_code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
            return resp
        try:
            wait = min(int(resp.headers.get("Retry-After", 2 * (attempt + 1))), 30)
        except Exception:
            wait = 2 * (attempt + 1)
        time.sleep(wait)
    return resp


def _drive_id(token: str) -> str:
    c = _cfg()
    key = (c["site"], c["library"])
    if key in _ids:
        return _ids[key]
    r = _call("get", f"{GRAPH}/sites/{c['site']}", token)
    if r.status_code in (400, 401, 403):
        # Graph answers 400 / 403 here when the Azure app has no SharePoint permission at all
        raise RuntimeError("the Azure app has no SharePoint permission yet: add the Microsoft Graph APPLICATION permission "
                           f"Sites.ReadWrite.All (with admin consent) to the app, then save again ({_error(r)})")
    if r.status_code != 200:
        raise RuntimeError(f"cannot open the SharePoint site ({_error(r)})")
    site_id = r.json()["id"]
    r = _call("get", f"{GRAPH}/sites/{site_id}/drives?$select=id,name", token)
    if r.status_code != 200:
        raise RuntimeError(f"cannot list the document libraries ({_error(r)})")
    want = c["library"].lower()
    names = {d["name"].lower(): d["id"] for d in r.json().get("value", [])}
    if want in names:
        drive = names[want]
    elif want in ("documents", "shared documents") and ({"documents", "shared documents"} & set(names)):
        drive = names.get("documents") or names["shared documents"]
    else:
        raise RuntimeError(f"document library '{c['library']}' not found on the SharePoint site")
    _ids[key] = drive
    return drive


def _upload(token: str, drive: str, segments: list, filename: str, data: bytes) -> None:
    """Put one file at <segments>/<filename>; missing folders are created, an existing file is replaced."""
    path = "/".join(urllib.parse.quote(s, safe="") for s in segments + [safe_name(filename, 150)])
    base = f"{GRAPH}/drives/{drive}/root:/{path}:"
    if len(data) <= SMALL_UPLOAD:
        r = _call("put", f"{base}/content?@microsoft.graph.conflictBehavior=replace", token, data=data,
                  headers={"Content-Type": "application/octet-stream"})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"upload of '{filename}' failed ({_error(r)})")
        return
    r = _call("post", f"{base}/createUploadSession", token, json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload of '{filename}' failed ({_error(r)})")
    url = r.json()["uploadUrl"]
    r = requests.put(url, data=data, timeout=300,
                     headers={"Content-Length": str(len(data)), "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"})
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"upload of '{filename}' failed ({_error(r)})")


def build_excel(name: str, empid: str, data: dict, files: dict, answers: list, uploads: list) -> bytes:
    """The person's KYC answers (sheet 1) and the list of their documents (sheet 2)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "KYC Details"
    ws.append(["Emp Code", empid])
    ws.append(["Name", name])
    ws.append([])
    ws.append(["Question", "Answer"])
    head = ws.max_row
    for i, (key, label, _t, _x) in enumerate(answers, start=1):
        ws.append([f"{i}. {label}", data.get(key, "")])
    for c in ws[head]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2C3E50")
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 60
    for row in ws.iter_rows(min_row=head + 1):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws2 = wb.create_sheet("Documents")
    ws2.append(["Document", "File name", "Size (KB)", "Uploaded on (UTC)"])
    for c in ws2[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2C3E50")
    for key, label in uploads:
        f = files.get(key)
        up = f.get("uploaded_at") if f else None
        ws2.append([label, f["name"] if f else "Not uploaded", round(f["size"] / 1024) if f else "",
                    up.strftime("%d/%m/%Y %H:%M") if isinstance(up, datetime) else ""])
    for col, w in (("A", 60), ("B", 40), ("C", 12), ("D", 22)):
        ws2.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _save_local(base: str, segments: list, excel_name: str, excel: bytes, files: dict, label: dict, read_file) -> str:
    """Write the Excel and the documents under <base>/<year>/<date>/<person>/. Returns that folder."""
    root = os.path.abspath(base)
    target = os.path.abspath(os.path.join(root, *segments[1:]))            # segments[0] is "KYC DETAILS": the base folder IS that
    if os.path.commonpath([root, target]) != root:                           # names are already sanitised; belt and braces
        raise RuntimeError("refusing to write outside the save folder")
    os.makedirs(target, exist_ok=True)

    def put(filename: str, data: bytes) -> None:
        with open(os.path.join(target, safe_name(filename, 150)), "wb") as fh:
            fh.write(data)
    put(excel_name, excel)
    for key, meta in files.items():
        put(f"{label.get(key, key)} - {meta['name']}", read_file(meta["file_id"]))
    return target


def save_submission(doc: dict, name: str, answers: list, uploads: list, read_file) -> dict:
    """Save the Excel and every uploaded document of one submitted KYC form: to the OneDrive folder (KYC_SAVE_DIR)
    and / or SharePoint. read_file(file_id) -> bytes.
    Returns {"status": "saved" | "partial", "where": [...], "path", "local_path", "files", "at", "error"};
    raises RuntimeError only when it could not be saved anywhere."""
    c = _cfg()
    local, graph = local_dir(), graph_configured()
    if not (local or graph):
        raise RuntimeError("Nothing is set up to save to: set KYC_SAVE_DIR (a synced OneDrive folder) and / or the Microsoft Graph settings.")
    empid = doc["empid"]
    segs = folder_segments(name, empid, doc.get("submitted_at"))
    files = doc.get("files") or {}
    label = dict(uploads)
    excel_name = f"KYC Details - {safe_name(name, 60)}.xlsx"
    excel = build_excel(name, empid, doc.get("data") or {}, files, answers, uploads)
    out: dict = {"status": "saved", "files": len(files), "where": [], "at": datetime.now(timezone.utc)}
    errors = []
    if local:
        try:
            out["local_path"] = _save_local(local, segs, excel_name, excel, files, label, read_file)
            out["where"].append("OneDrive folder")
        except Exception as exc:
            errors.append(f"OneDrive folder: {str(exc)[:200]}")
    if graph:
        try:
            token = notify._graph_access_token(c["tenant"], c["client_id"], c["secret"])
            drive = _drive_id(token)
            _upload(token, drive, segs, excel_name, excel)
            for key, meta in files.items():
                _upload(token, drive, segs, f"{label.get(key, key)} - {meta['name']}", read_file(meta["file_id"]))
            out["path"] = "/".join(segs)
            out["where"].append("SharePoint")
        except Exception as exc:
            errors.append(f"SharePoint: {str(exc)[:240]}")
    if not out["where"]:
        raise RuntimeError("; ".join(errors))
    if errors:
        out["status"], out["error"] = "partial", "; ".join(errors)
    return out


# ── Reading back from SharePoint (for admin detail view after MongoDB wipe) ──

def _folder_drive_item_id(token: str, drive: str, segments: list):
    """Return the Graph item-id for the person's folder, or None if not found."""
    path = "/".join(__import__("urllib.parse", fromlist=["quote"]).parse.quote(s, safe="") for s in segments)
    url = f"{GRAPH}/drives/{drive}/root:/{path}"
    r = _call("get", url, token)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"cannot open SharePoint folder ({_error(r)})")
    return r.json()["id"]


def list_folder_files(token: str, drive: str, folder_item_id: str) -> list:
    """Return [{name, size, webUrl, downloadUrl}] for every file in the folder."""
    url = f"{GRAPH}/drives/{drive}/items/{folder_item_id}/children?$select=name,size,file,@microsoft.graph.downloadUrl,webUrl"
    r = _call("get", url, token)
    if r.status_code != 200:
        raise RuntimeError(f"cannot list SharePoint folder ({_error(r)})")
    return [
        {"name": item["name"], "size": item.get("size", 0),
         "webUrl": item.get("webUrl", ""),
         "downloadUrl": item.get("@microsoft.graph.downloadUrl", "")}
        for item in r.json().get("value", [])
        if "file" in item
    ]


def read_from_sharepoint(sp_meta: dict, answers: list, uploads: list) -> dict:
    """Read KYC answers and file list back from SharePoint.

    sp_meta is the 'sharepoint' sub-document stored in MongoDB
    (must have status='saved' and path set).

    Returns {"data": {...}, "files": {...}} in the same shape as the MongoDB document,
    with an extra "sp_web_url" on each file entry pointing to SharePoint.
    Raises RuntimeError if the folder / Excel cannot be reached.
    """
    if not graph_configured():
        raise RuntimeError("SharePoint (Microsoft Graph) is not configured")
    path_str = (sp_meta or {}).get("path", "")
    if not path_str:
        raise RuntimeError("SharePoint path not recorded — cannot read back")

    c = _cfg()
    token = __import__("backend.buddy_referral.notify", fromlist=["_graph_access_token"])._graph_access_token(
        c["tenant"], c["client_id"], c["secret"]
    )
    drive = _drive_id(token)

    # sp_meta["path"] = "KYC DETAILS/2026/02-11-2026/ORINA (NJ-DE1743)"
    segments = path_str.split("/")
    folder_id = _folder_drive_item_id(token, drive, segments)
    if not folder_id:
        raise RuntimeError(f"SharePoint folder not found: {path_str}")

    sp_files = list_folder_files(token, drive, folder_id)
    name_map = {f["name"]: f for f in sp_files}

    # ── Parse the Excel for answers ──────────────────────────────────────────
    excel_file = next((f for f in sp_files if f["name"].endswith(".xlsx")), None)
    data = {}
    if excel_file and excel_file.get("downloadUrl"):
        import requests as _req
        resp = _req.get(excel_file["downloadUrl"], timeout=60)
        if resp.status_code == 200:
            import io
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
            ws = wb.active
            answer_keys = [a[0] for a in answers]
            # Rows 5+ are answers (row 1=EmpCode, 2=Name, 3=blank, 4=header)
            row_idx = 0
            for row in ws.iter_rows(min_row=5, values_only=True):
                if row_idx >= len(answer_keys):
                    break
                data[answer_keys[row_idx]] = str(row[1] or "") if row[1] is not None else ""
                row_idx += 1
            wb.close()

    # ── Map uploaded files back by label prefix ───────────────────────────────
    label_map = dict(uploads)          # key -> label string
    files = {}
    for key, label in uploads:
        # File was uploaded as "<label> - <original_filename>"
        prefix = safe_name(label, 80) + " - "
        matched = next((f for f in sp_files if f["name"].startswith(prefix)), None)
        if matched:
            files[key] = {
                "name": matched["name"][len(prefix):],   # original filename
                "size": matched.get("size", 0),
                "sp_web_url": matched.get("webUrl", ""),
                "sp_download_url": matched.get("downloadUrl", ""),
                "uploaded_at": None,
            }

    return {"data": data, "files": files}
