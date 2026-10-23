# backend/hrms/parser.py
"""
Parse an HRMS attendance export (.xlsx / .csv), one row per employee per day.
Columns are matched by exact header name (case/space-insensitive). Only the columns we
need are read; names, DOJ, department etc. are never stored. See docs/hrms_sample.xlsx.
"""
import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from backend.hrms import rules

REQUIRED = {"employee code": "employee_id", "date": "date", "in time": "in_time",
            "out time": "out_time", "muster": "muster"}
OPTIONAL = {"final status": "final_status"}   # fallback when Muster is blank

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 200_000
MAX_UNCOMPRESSED = 100 * 1024 * 1024      # guards against zip-bomb workbooks
EMP_CODE_RE = re.compile(r"^[A-Z0-9_-]{2,20}$")
MUSTER_RE = re.compile(r"^[A-Z0-9 ./_-]{0,20}$")
ALLOWED_EXT = (".xlsx", ".csv")

_TIME_FORMATS = ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M")
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


class HrmsFileError(Exception):
    """The file as a whole cannot be used (bad type, size, missing columns)."""


@dataclass
class ParseResult:
    rows: List[dict] = field(default_factory=list)
    errors: List[dict] = field(default_factory=list)       # {"row": n, "message": str}
    warnings: List[str] = field(default_factory=list)
    total_rows: int = 0
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    unknown_codes: Dict[str, int] = field(default_factory=dict)
    ignored_blank: int = 0                                  # rows with no status and no punches


def _norm(h: Any) -> str:
    return " ".join(str(h or "").replace("\xa0", " ").split()).lower()


def parse_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:10] if f == "%Y-%m-%d" else s, f).date()
        except ValueError:
            continue
    raise ValueError(f"bad date '{s}'")


def parse_time(v: Any) -> Optional[time]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, datetime):
        return v.time().replace(microsecond=0)
    if isinstance(v, time):
        return v.replace(microsecond=0)
    if isinstance(v, (int, float)) and 0 <= float(v) < 1:       # Excel time fraction
        secs = round(float(v) * 86400)
        return (datetime.min + timedelta(seconds=secs)).time()
    s = str(v).strip().upper().replace("\xa0", " ")
    for f in _TIME_FORMATS:
        try:
            return datetime.strptime(s, f).time()
        except ValueError:
            continue
    raise ValueError(f"bad time '{v}'")


def _read_rows(content: bytes, filename: str) -> List[List[Any]]:
    name = (filename or "").lower()
    if not name.endswith(ALLOWED_EXT):
        raise HrmsFileError("Only .xlsx or .csv files are accepted")
    if len(content) > MAX_BYTES:
        raise HrmsFileError("File is larger than 10 MB")
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        sample = text[:4096]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
    import openpyxl
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
                raise HrmsFileError("The workbook expands to more than 100 MB - refusing to open it")
    except zipfile.BadZipFile:
        raise HrmsFileError("Could not read the Excel file")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise HrmsFileError("Could not read the Excel file")
    rows = []
    try:
        for r in wb.worksheets[0].iter_rows(values_only=True):
            rows.append(list(r))
            if len(rows) > MAX_ROWS + 1:                       # header + MAX_ROWS data rows
                raise HrmsFileError(f"Too many rows (limit {MAX_ROWS})")
    finally:
        wb.close()
    return rows


def parse_hrms(content: bytes, filename: str, status_codes: Optional[Dict[str, str]] = None) -> ParseResult:
    raw = _read_rows(content, filename)
    if not raw:
        raise HrmsFileError("The file is empty")
    # The column titles are normally the first row, but some exports put a title line above them
    # (e.g. "Attendance Type"): use the first of the top rows that holds every required column.
    header_row = 0
    for i, row in enumerate(raw[:10]):
        names = {_norm(h) for h in row}
        if all(k in names for k in REQUIRED):
            header_row = i
            break
    header = [_norm(h) for h in raw[header_row]]
    wanted = {**REQUIRED, **OPTIONAL}
    idx = {wanted[h]: i for i, h in enumerate(header) if h in wanted}
    missing = [h for h, key in REQUIRED.items() if key not in idx]
    if missing:
        raise HrmsFileError("Missing required column(s): " + ", ".join(m.title() for m in missing))
    body = raw[header_row + 1:]
    if len(body) > MAX_ROWS:
        raise HrmsFileError(f"Too many rows (limit {MAX_ROWS})")

    res = ParseResult()
    seen = set()
    dates = []
    for n, r in enumerate(body, start=header_row + 2):        # n = spreadsheet row number
        get = lambda k: (r[idx[k]] if k in idx and idx[k] < len(r) else None)
        if all(c is None or str(c).strip() == "" for c in r):
            continue                                           # blank line
        res.total_rows += 1
        try:
            emp = str(get("employee_id") or "").strip().upper()
            if not emp:
                raise ValueError("missing employee code")
            if not EMP_CODE_RE.match(emp):
                raise ValueError("invalid employee code")
            d = parse_date(get("date"))
            t_in, t_out = parse_time(get("in_time")), parse_time(get("out_time"))
        except ValueError as e:
            res.errors.append({"row": n, "message": str(e)})
            continue
        key = (emp, d)
        if key in seen:
            res.errors.append({"row": n, "message": f"duplicate row for {emp} on {d.isoformat()}"})
            continue
        code = str(get("muster") or get("final_status") or "").strip().upper()
        if not MUSTER_RE.match(code):
            res.errors.append({"row": n, "message": "invalid Muster code"})
            continue
        if not code and t_in is None and t_out is None:
            res.ignored_blank += 1                             # a day with no status and no punches (e.g. before joining)
            continue
        kind = rules.classify(code, status_codes)
        try:
            gross = rules.gross_hours(t_in, t_out)
        except ValueError as e:
            if kind == "working":                              # a bad punch only matters on a day the person was present
                res.errors.append({"row": n, "message": str(e)})
                continue
            gross = None
        seen.add(key)
        if kind == "unknown":
            res.unknown_codes[code or "(blank)"] = res.unknown_codes.get(code or "(blank)", 0) + 1
        net = rules.net_from_gross(gross)
        res.rows.append({
            "employee_id": emp, "date": d.isoformat(),
            "in_time": t_in.strftime("%H:%M") if t_in else None,
            "out_time": t_out.strftime("%H:%M") if t_out else None,
            "gross_hours": gross, "net_hours": net,
            "status_code": code, "kind": kind,
            "leave_flag": kind in rules.OFF_KINDS,
        })
        dates.append(d)
    if dates:
        res.date_from, res.date_to = min(dates).isoformat(), max(dates).isoformat()
    if res.ignored_blank:
        res.warnings.append(f"{res.ignored_blank} row(s) with no status and no punches were ignored")
    for code, count in sorted(res.unknown_codes.items()):
        res.warnings.append(f"Unknown Muster code '{code}' on {count} row(s) - imported but not reconciled")
    return res
