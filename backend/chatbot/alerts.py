"""
Retention-risk keyword detection — scans an employee's own chat message
(never the bot's reply) for language that suggests they may be planning to
leave, and records a match for the admin Dashboard's Alerts tab.

Detection is pure keyword/phrase matching (no LLM call — cheap enough to
run on every message, right alongside history persistence) against a fixed
taxonomy of categories, each with its own severity, plus a set of
"multi-signal" combinations (two related signals in the same message,
which is a stronger indicator than either alone).

Storage: backend/chatbot/router.py's admin_dashboard endpoint reads back
whatever this writes to the `chatbot_alerts` Mongo collection (see
record_if_match, called from each bot's own _persist_turn background task
right after saving normal chat history).
"""
import datetime
import logging
import re
import time

from pymongo import MongoClient

from backend.chatbot.config import chatbot_settings
from backend.database import employee_details_collection

logger = logging.getLogger("chatbot.alerts")

_client = MongoClient(
    chatbot_settings.CHATBOT_MONGO_URI,
    serverSelectionTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
    connectTimeoutMS=chatbot_settings.CHATBOT_MONGO_TIMEOUT_MS,
)
_col = _client[chatbot_settings.CHATBOT_DB_NAME]["chatbot_alerts"]
_col.create_index([("empid", 1), ("created_at", -1)])


# Severity, in escalating order — drives the badge color in the dashboard.
RED = "red"
ORANGE = "orange"
YELLOW = "yellow"
CRITICAL = "critical"  # multi-signal combinations only

CATEGORIES = [
    {
        "id": "resignation_quitting", "label": "Resignation / Quitting", "severity": RED,
        "keywords": [
            "resignation", "resign", "resigning", "resigned", "quit", "quitting",
            "want to resign", "planning to resign", "thinking of resigning", "decided to resign",
            "want to quit", "planning to quit", "want to leave", "planning to leave",
            "thinking of leaving", "decided to leave", "leaving the company", "leaving the organization",
            "don't want to continue", "don't want to work here anymore",
        ],
    },
    {
        "id": "exit_separation", "label": "Exit / Separation", "severity": ORANGE,
        "keywords": [
            "exit", "exit process", "exit formalities", "separation", "separation process",
            "employee separation", "leaving process", "exit interview", "exit procedure",
            "clearance process", "clearance formalities", "handover process", "handover formalities",
            "resignation process", "resignation submission", "resignation acceptance", "resignation approval",
        ],
    },
    {
        "id": "notice_period", "label": "Notice Period", "severity": ORANGE,
        "keywords": [
            "notice period", "notice period policy", "notice period duration", "notice period rules",
            "notice period requirement", "last working day", "lwd", "notice buyout", "buyout notice",
            "notice waiver", "waive notice period", "waiver of notice", "early release", "early relieving",
            "immediate resignation", "immediate release", "leave during notice period",
            "salary during notice period", "serving notice period", "reduce notice period",
        ],
    },
    {
        "id": "final_settlement", "label": "Final Settlement / Exit Documents", "severity": ORANGE,
        "keywords": [
            "full and final", "f&f", "final settlement", "settlement after resignation",
            "settlement after leaving", "relieving letter", "experience letter", "service certificate",
            "exit documents", "documents after resignation", "documents after leaving",
            "clearance certificate", "final salary", "dues after resignation", "payment after resignation",
            "pf after resignation", "benefits after resignation",
        ],
    },
    {
        "id": "job_search", "label": "Job Search / Job Switch", "severity": RED,
        "keywords": [
            "looking for another job", "looking for a new job", "searching for jobs", "job search",
            "applying for jobs", "looking for opportunities", "new opportunity", "external opportunity",
            "outside opportunity", "job switch", "job switching", "switching jobs", "switch company",
            "switching company", "planning to switch", "career change", "career move", "another company",
            "joining another company", "leaving for another company",
        ],
    },
    {
        "id": "external_offer", "label": "External Job Offer", "severity": RED,
        "keywords": [
            "job offer", "another job offer", "offer from another company", "received an offer",
            "received another offer", "competing offer", "better offer", "better opportunity",
            "higher salary offer", "higher salary elsewhere", "external offer", "outside offer",
            "recruiter contacted me", "recruiter call", "interview at another company",
            "selected by another company", "joining another company",
        ],
    },
    {
        "id": "salary_dissatisfaction", "label": "Salary / Compensation Dissatisfaction", "severity": YELLOW,
        "keywords": [
            "salary is low", "low salary", "underpaid", "salary dissatisfaction", "unhappy with salary",
            "compensation issue", "compensation problem", "salary problem", "salary concern",
            "expecting higher salary", "not happy with compensation", "better salary elsewhere",
            "salary hike", "no salary growth", "insufficient salary",
        ],
    },
    {
        "id": "career_dissatisfaction", "label": "Career / Growth Dissatisfaction", "severity": YELLOW,
        "keywords": [
            "no growth", "no career growth", "lack of growth", "career growth issue", "no promotion",
            "promotion issue", "no opportunity", "lack of opportunity", "career stagnation",
            "no future here", "no future in company", "no development", "limited growth",
            "career concern", "career dissatisfaction",
        ],
    },
    {
        "id": "manager_dissatisfaction", "label": "Manager / Workplace Dissatisfaction", "severity": YELLOW,
        "keywords": [
            "unhappy with manager", "unhappy with management", "bad manager", "toxic manager",
            "manager issue", "manager problem", "unfair treatment", "unfair manager", "workplace issue",
            "work environment issue", "toxic work environment", "poor work environment", "not valued",
            "don't feel valued", "lack of recognition", "no recognition", "frustrated", "demotivated",
            "unhappy at work", "dissatisfied at work",
        ],
    },
    {
        "id": "workload_burnout", "label": "Workload / Burnout Signals", "severity": YELLOW,
        "keywords": [
            "overworked", "workload is too much", "too much workload", "excessive workload",
            "work pressure", "excessive work pressure", "stressed at work", "overwhelmed", "burnout",
            "work-life balance issue", "unable to manage workload", "too much work",
            "unreasonable workload", "long working hours",
        ],
    },
    {
        "id": "direct_exit_questions", "label": "Direct Exit Questions", "severity": RED,
        "keywords": [
            "how do i resign", "how can i resign", "how to resign", "where do i submit resignation",
            "whom should i inform before resigning", "what is the resignation process",
            "what happens if i resign", "what happens after resignation", "what happens after i leave",
            "can i resign immediately", "can i leave immediately", "can i leave without notice",
            "can i leave without serving notice", "can i get early release",
            "can my notice period be waived", "can i join another company during notice period",
        ],
    },
    {
        "id": "retention_risk_questions", "label": "Retention-Risk Questions", "severity": ORANGE,
        "keywords": [
            "should i stay", "is it worth staying", "should i continue here", "should i leave",
            "should i quit", "should i resign", "is there any reason to stay", "what happens if i leave",
            "what are my options if i want to leave", "can i discuss retention", "retention offer",
            "counter offer", "retention bonus", "can company match another offer",
        ],
    },
    {
        # Not a retention signal — a safety one. Kept in the same alerts
        # taxonomy/table (rather than a separate feature) per an explicit
        # request that this surface alongside the retention-risk alerts, so
        # whoever reviews that list sees it too. Always RED regardless of
        # what the category severity scheme would otherwise suggest, given
        # what this is actually about.
        "id": "harassment_posh", "label": "Harassment / Workplace Safety (POSH)", "severity": RED,
        "keywords": [
            "posh complaint", "posh policy", "posh committee", "sexual harassment",
            "harassment complaint", "harassment at work", "workplace harassment",
            "being harassed", "being harassed by", "inappropriate behavior",
            "inappropriate comments", "inappropriate touching", "inappropriate remarks",
            "inappropriate messages", "unwanted advances", "unwanted attention",
            "unwelcome behavior", "hostile work environment", "internal complaints committee",
            "icc complaint", "file a complaint against", "report harassment",
            "feel unsafe at work", "feel unsafe around", "uncomfortable around my manager",
            "uncomfortable around my colleague", "misconduct by", "molestation",
            "verbal abuse at work", "stalking me at work", "gender discrimination",
            "sexual advances", "unwanted physical contact",
        ],
    },
]

# Two related signals in the SAME message — a stronger indicator than
# either alone, flagged as CRITICAL. Each side is either a literal phrase
# or ("category", <id>) meaning "any keyword from that category matched".
_LIT = lambda p: ("literal", p)
_CAT = lambda c: ("category", c)
MULTI_SIGNAL_COMBINATIONS = [
    (_CAT("resignation_quitting"), _LIT("notice period")),
    (_CAT("resignation_quitting"), _CAT("final_settlement")),
    (_CAT("resignation_quitting"), _LIT("relieving letter")),
    (_CAT("resignation_quitting"), _LIT("experience letter")),
    (_CAT("resignation_quitting"), _LIT("last working day")),
    (_CAT("resignation_quitting"), _LIT("another company")),
    (_CAT("resignation_quitting"), _LIT("job offer")),
    (_LIT("job offer"), _LIT("notice period")),
    (_LIT("another company"), _LIT("notice period")),
    (_CAT("salary_dissatisfaction"), _CAT("external_offer")),
    (_CAT("manager_dissatisfaction"), _CAT("resignation_quitting")),
    (_LIT("no growth"), _LIT("another job")),
    (_LIT("unhappy"), _LIT("looking for another job")),
    (_LIT("planning to leave"), _LIT("notice period")),
    (_LIT("planning to leave"), _CAT("final_settlement")),
]


def _compile_category_patterns():
    compiled = {}
    for cat in CATEGORIES:
        pattern = r"\b(" + "|".join(re.escape(k) for k in cat["keywords"]) + r")\b"
        compiled[cat["id"]] = re.compile(pattern, re.IGNORECASE)
    return compiled


_CATEGORY_PATTERNS = _compile_category_patterns()
_CATEGORY_BY_ID = {c["id"]: c for c in CATEGORIES}


def _literal_present(text_lower: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text_lower) is not None


def scan_message(text: str) -> dict:
    """Returns {"matches": [{"category_id","label","severity","keyword"}, ...],
    "multi_signal": bool} — matches is [] and multi_signal is False for an
    ordinary message with no retention-risk language at all."""
    if not text or not text.strip():
        return {"matches": [], "multi_signal": False}

    matches = []
    matched_category_ids = set()
    for cat_id, pattern in _CATEGORY_PATTERNS.items():
        m = pattern.search(text)
        if m:
            cat = _CATEGORY_BY_ID[cat_id]
            matches.append({
                "category_id": cat_id,
                "label": cat["label"],
                "severity": cat["severity"],
                "keyword": m.group(1),
            })
            matched_category_ids.add(cat_id)

    text_lower = text.lower()

    def _side_present(side) -> bool:
        kind, value = side
        if kind == "category":
            return value in matched_category_ids
        return _literal_present(text_lower, value)

    multi_signal = any(_side_present(a) and _side_present(b) for a, b in MULTI_SIGNAL_COMBINATIONS)

    return {"matches": matches, "multi_signal": multi_signal}


def _employee_name(empid: str) -> str:
    emp = employee_details_collection.find_one({"EmpID": empid}, {"_id": 0, "Emp Name": 1})
    return (emp or {}).get("Emp Name") or empid


def record_if_match(empid: str, bot: str, session_id: str, message: str) -> None:
    """Scans `message` (the EMPLOYEE's own text, never the bot's reply) and
    inserts an alert document if anything matched. Never raises — called
    from a background task right after normal chat-history persistence, so
    a scanning hiccup must never affect the actual chat reply."""
    try:
        result = scan_message(message)
        if not result["matches"]:
            return
        _col.insert_one({
            "empid": empid,
            "name": _employee_name(empid),
            "bot": bot,
            "session_id": session_id,
            "message": message,
            "matches": result["matches"],
            "multi_signal": result["multi_signal"],
            "created_at": time.time(),
        })
    except Exception:
        logger.exception("Retention-risk scan failed for empid=%s bot=%s", empid, bot)


def list_alerts(limit: int = 500) -> list:
    """Most recent alerts first. Nothing here is ever overwritten — every
    match gets its own document (see record_if_match), so this is the full
    history, not just each user's latest state."""
    docs = list(_col.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    return docs


def list_alerts_in_range(start_ts: float = None, end_ts: float = None, limit: int = 5000) -> list:
    """Same as list_alerts, but scoped to a [start_ts, end_ts] unix-timestamp
    window (either end optional) — backs the Excel export's week/month/
    custom date filter."""
    query = {}
    ts_filter = {}
    if start_ts is not None:
        ts_filter["$gte"] = start_ts
    if end_ts is not None:
        ts_filter["$lte"] = end_ts
    if ts_filter:
        query["created_at"] = ts_filter
    return list(_col.find(query, {"_id": 0}).sort("created_at", -1).limit(limit))


def generate_excel(rows: list) -> bytes:
    """One row per (alert, matched category) — a single alert with 2
    matched categories becomes 2 spreadsheet rows sharing everything else,
    so a category/severity filter in Excel itself (AutoFilter) works
    cleanly instead of needing to parse a combined cell."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Retention-risk alerts"

    headers = ["Date", "Time", "Employee", "Emp ID", "Bot", "Category", "Severity", "Matched keyword", "Multi-signal", "Message"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for a in rows:
        dt = datetime.datetime.fromtimestamp(a.get("created_at", 0)) if a.get("created_at") else None
        date_str = dt.strftime("%Y-%m-%d") if dt else ""
        time_str = dt.strftime("%H:%M") if dt else ""
        matches = a.get("matches") or [{"label": "", "severity": "", "keyword": ""}]
        for m in matches:
            ws.append([
                date_str, time_str, a.get("name", ""), a.get("empid", ""),
                a.get("bot", ""), m.get("label", ""), m.get("severity", ""),
                m.get("keyword", ""), "Yes" if a.get("multi_signal") else "No",
                a.get("message", ""),
            ])

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col_idx in range(1, len(headers) + 1):
        col_letter = get_column_letter(col_idx)
        width = max((len(str(c.value)) for c in ws[col_letter] if c.value is not None), default=10)
        ws.column_dimensions[col_letter].width = min(max(width + 2, 10), 60)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def high_alert_users(session_threshold: int = 5) -> list:
    """Employees with a RED-severity match in MORE than `session_threshold`
    distinct chat sessions — repeated red flags across separate
    conversations, not just several red words in one sitting, which is a
    meaningfully stronger signal than a single flagged chat. Returns
    [{"empid", "name", "red_session_count"}, ...], worst first."""
    pipeline = [
        {"$match": {"matches.severity": RED}},
        {"$group": {"_id": {"empid": "$empid", "session_id": "$session_id"}}},
        {"$group": {"_id": "$_id.empid", "red_session_count": {"$sum": 1}}},
        {"$match": {"red_session_count": {"$gt": session_threshold}}},
        {"$sort": {"red_session_count": -1}},
    ]
    results = list(_col.aggregate(pipeline))
    return [
        {"empid": r["_id"], "name": _employee_name(r["_id"]), "red_session_count": r["red_session_count"]}
        for r in results
    ]
