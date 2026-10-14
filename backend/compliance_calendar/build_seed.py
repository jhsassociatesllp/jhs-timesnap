# backend/compliance_calendar/build_seed.py
"""
Loads the Excel-sourced compliance due dates into MongoDB (database Compliance_Table,
collection compliance_calendar_items, source="excel"). Run whenever the Excel files change:

    python -m backend.compliance_calendar.build_seed [input_dir]           # import
    python -m backend.compliance_calendar.build_seed [input_dir] --dry-run  # parse only

Re-running replaces only the source="excel" rows; dates added by admins in the Control
Panel (source="manual") are never touched.

Sources:
  * compliance-26-27.xlsx  - one sheet, real dates (Sep-Dec 2026).
  * Compliance_Calendar_2027*.xlsx - one sheet per month, due dates as text
    ("7th Jan"); the year comes from the sheet name.

Rows with no usable calendar date (blank / "-" / free text) are skipped and
reported. "22nd / 24th Jan" yields one row per date. "Within 7 working days ..." rows are placed on the 7th working
day (Mon-Fri, holidays not considered) of the sheet's month.
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import openpyxl

DEFAULT_INPUT = r"F:\osama\JHS Projects\compliance calender\input"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_WORDS = r"(january|february|march|april|may|june|july|august|september|october|november|december)"


def group_key(law: str, text: str) -> str:
    """Identifies 'the same compliance' across months (month/year words removed)."""
    t = re.sub(r"\([^)]*\)", " ", text.lower())
    t = re.sub(_MONTH_WORDS, " ", t)
    t = re.sub(r"\b(19|20)\d\d(-\d\d)?\b", " ", t)
    t = re.sub(r"\b(quarter|ended|during|for|the|of|month|year|financial)\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return f"{law.strip().upper()}|{t}"


def nth_working_day(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def main(input_dir: str, dry_run: bool = False):
    items, skipped = [], []

    def add(law, comp, d, src):
        law, comp = clean(law), clean(comp)
        if not law or law == "-" or not comp or comp == "-":
            skipped.append((src, law, comp, d, "missing law/compliance"))
            return
        items.append({"law": law, "compliance": comp, "date": d.isoformat(),
                      "group": group_key(law, comp)})

    f26 = os.path.join(input_dir, "compliance-26-27.xlsx")
    for r in list(openpyxl.load_workbook(f26, data_only=True).active.iter_rows(values_only=True))[1:]:
        law, comp, due = r[:3]
        if isinstance(due, datetime):
            add(law, comp, due.date(), "26-27")
        else:
            skipped.append(("26-27", clean(law), clean(comp), due, "no calendar date"))

    f27 = glob.glob(os.path.join(input_dir, "Copy of Compliance_Calendar_2027*.xlsx"))[0]
    for ws in openpyxl.load_workbook(f27, data_only=True):
        m = re.fullmatch(r"([A-Za-z]{3}) (\d{4})", ws.title)
        if not m:
            continue
        mon, year = MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))
        for r in list(ws.iter_rows(values_only=True))[1:]:
            law, comp, due = r[:3]
            due = clean(due)
            dm = re.match(r"^((?:\d{1,2}(?:st|nd|rd|th)\s*/?\s*)+)([A-Za-z]{3})", due)
            if dm:   # "7th Jan" or "22nd / 24th Jan" (one row per date)
                for day in re.findall(r"\d{1,2}", dm.group(1)):
                    add(law, comp, date(year, MONTHS.index(dm.group(2).lower()) + 1, int(day)), ws.title)
            elif due.lower().startswith("within 7 working days"):
                add(law, comp, nth_working_day(year, mon, 7), ws.title)
            elif law or comp:
                skipped.append((ws.title, clean(law), comp, due, "no calendar date"))

    seen, out = set(), []
    for it in sorted(items, key=lambda x: (x["date"], x["law"], x["compliance"])):
        k = (it["law"].upper(), it["compliance"].lower(), it["date"])
        if k not in seen:
            seen.add(k)
            out.append(it)
    if dry_run:
        print(f"{len(out)} items parsed ({len(items) - len(out)} duplicates dropped); nothing written")
    else:
        from backend.database import compliance_db
        coll = compliance_db["compliance_calendar_items"]
        coll.delete_many({"source": "excel"})
        if out:
            coll.insert_many([dict(it, source="excel") for it in out])
        print(f"{len(out)} items stored in Compliance_Table.compliance_calendar_items ({len(items) - len(out)} duplicates dropped)")
    for s in skipped:
        print("SKIPPED:", s)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else DEFAULT_INPUT, "--dry-run" in sys.argv)
