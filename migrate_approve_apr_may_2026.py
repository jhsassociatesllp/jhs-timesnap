"""
One-time migration: Approve all submitted timesheets for the April 2026 – May 2026 cycle.

What this script does:
  - For each employee who submitted a timesheet for the April-May 2026 cycle,
    sets approval_status = "approved" in Timesheet_data with their actual TL's
    details (code + name) fetched from Employee_details.ReportingEmpCode.

What this script does NOT touch:
  - Pending / Approved / Rejected collections (unchanged).
  - Any other payroll cycle.

Run from the project root:
    python migrate_approve_apr_may_2026.py

Safe to re-run: already-approved records are skipped.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_URI:
    raise SystemExit("ERROR: MONGO_CONNECTION_STRING not set in .env")

client = MongoClient(MONGO_URI)
db = client["Timesheets"]

timesheets_col     = db["Timesheet_data"]
payroll_cycles_col = db["payroll_cycles"]
emp_details_col    = db["Employee_details"]   # has ReportingEmpCode per employee

NOW_ISO = datetime.now(timezone.utc).isoformat()

# Match any cycle label containing all these keywords (case-insensitive)
TARGET_KEYWORDS = ["april", "may", "2026"]


# ── helpers ───────────────────────────────────────────────────────────────────

def find_target_cycle():
    for c in payroll_cycles_col.find({}):
        label = (c.get("cycle_label") or "").lower()
        if all(kw in label for kw in TARGET_KEYWORDS):
            return c
    return None


def get_tl_details(emp_code: str):
    """
    Look up the employee in Employee_details by EmpID to get their TL.
    Each Employee_details doc has:
      - ReportingEmpCode  → TL's employee code
      - ReportingEmpName  → TL's name (already stored on the employee's own record)
    """
    emp_doc = emp_details_col.find_one({"EmpID": emp_code})
    if not emp_doc:
        return None, None

    tl_code = (emp_doc.get("ReportingEmpCode") or "").strip()
    tl_name = (emp_doc.get("ReportingEmpName") or "").strip()

    if not tl_code:
        return None, None

    return tl_code, tl_name or tl_code


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  April–May 2026 Approval Migration (Timesheet_data only)")
    print("=" * 62)

    # 1. Find the cycle
    cycle = find_target_cycle()
    if not cycle:
        print("\nERROR: No cycle matched keywords:", TARGET_KEYWORDS)
        print("Available cycles:")
        for c in payroll_cycles_col.find({}, {"cycle_label": 1}):
            print(f"  - {c.get('cycle_label')}  (id: {c['_id']})")
        return

    cycle_id    = str(cycle["_id"])
    cycle_label = cycle.get("cycle_label", "")
    print(f"\nTarget cycle : {cycle_label}")
    print(f"Cycle ID     : {cycle_id}\n")

    # 2. Find employees with a submitted payroll for this cycle
    docs = list(timesheets_col.find(
        {"payrolls": {"$elemMatch": {"cycle_id": cycle_id, "submitted": True}}},
        {"employeeId": 1, "payrolls": 1}
    ))

    if not docs:
        print("No submitted timesheets found for this cycle. Nothing to do.")
        return

    print(f"Found {len(docs)} employee(s) with submitted timesheets.\n")
    print(f"{'EmpCode':<12} {'TL Code':<12} {'TL Name':<30} {'Result'}")
    print("-" * 72)

    skipped = 0
    approved = 0
    no_tl    = 0

    for doc in docs:
        emp_code = doc.get("employeeId", "")

        # Skip if already approved
        for p in doc.get("payrolls", []):
            if p.get("cycle_id") == cycle_id and p.get("approval_status") == "approved":
                print(f"{emp_code:<12} {'—':<12} {'—':<30} SKIP (already approved)")
                skipped += 1
                break
        else:
            # Get this employee's TL from Employee_details
            tl_code, tl_name = get_tl_details(emp_code)

            if not tl_code:
                print(f"{emp_code:<12} {'NOT FOUND':<12} {'—':<30} WARN (no TL in Employee_details)")
                no_tl += 1
                # Still approve, just with unknown TL
                tl_code = "UNKNOWN"
                tl_name = "Unknown TL"

            # Update Timesheet_data only
            timesheets_col.update_one(
                {"employeeId": emp_code},
                {"$set": {
                    "payrolls.$[elem].approval_status":  "approved",
                    "payrolls.$[elem].approved_by":       tl_code,
                    "payrolls.$[elem].approved_by_name":  tl_name,
                    "payrolls.$[elem].approved_at":       NOW_ISO,
                    "payrolls.$[elem].status_updated_at": NOW_ISO,
                }},
                array_filters=[{"elem.cycle_id": cycle_id, "elem.submitted": True}],
            )

            print(f"{emp_code:<12} {tl_code:<12} {tl_name:<30} OK")
            approved += 1

    print("-" * 72)
    print(f"\nDone.")
    print(f"  Approved : {approved}")
    print(f"  Skipped  : {skipped}  (already approved)")
    print(f"  No TL    : {no_tl}   (approved with 'Unknown TL')")
    print()
    print("Pending / Approved / Rejected collections were NOT modified.")
    print("=" * 62)


if __name__ == "__main__":
    main()
