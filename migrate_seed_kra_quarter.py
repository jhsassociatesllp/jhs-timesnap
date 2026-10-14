"""
One-time migration: seed a KRA quarter document for the pre-existing,
hardcoded "2025-26" appraisal period so historical Appraisal_data records
keep resolving correctly once the KRA module switches from a hardcoded
`period` constant to the dynamic Appraisal_cycles collection.

What this script does:
  - Creates one Appraisal_cycles document: quarter_id="KRA_2025_26",
    quarter_label="2025-26". Its status is "live" if the legacy
    Admin.cycleOpen flag is currently True, else "closed".
  - Backfills quarter_id="KRA_2025_26" onto every Appraisal_data document
    where period == "2025-26" and quarter_id is missing.
  - Backfills Appraisal_eligibility for KRA_2025_26 from the distinct
    employeeIds already present in those records, so the Admin Dashboard's
    historical "Eligible Employees" count is accurate. This has no effect
    on live gating once a new quarter is activated.

What this script does NOT touch:
  - Any other collection (Timesheet_data, payroll_cycles, etc.).
  - Appraisal_data documents for any other period value.

Run from the project root:
    python migrate_seed_kra_quarter.py

Safe to re-run: every step checks existing state before writing.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_URI:
    raise SystemExit("ERROR: MONGO_CONNECTION_STRING not set in .env")

client = MongoClient(MONGO_URI)
timesheets_db = client["Timesheets"]
appraisal_db  = client["Appraisal"]

appraisal_collection          = appraisal_db["Appraisal_data"]
appraisal_admin_collection    = appraisal_db["Admin"]
appraisal_cycles_collection   = appraisal_db["Appraisal_cycles"]
appraisal_eligibility_collection = appraisal_db["Appraisal_eligibility"]

QUARTER_ID    = "KRA_2025_26"
QUARTER_LABEL = "2025-26"


def main():
    print("=" * 62)
    print("  KRA Quarter Seed Migration (2025-26)")
    print("=" * 62)

    # 1. Create/confirm the cycle document
    existing_cycle = appraisal_cycles_collection.find_one({"quarter_id": QUARTER_ID})
    if existing_cycle:
        print(f"\nCycle '{QUARTER_ID}' already exists (status: {existing_cycle.get('status')}). Skipping creation.")
    else:
        admin_doc  = appraisal_admin_collection.find_one({})
        was_open   = bool(admin_doc.get("cycleOpen", False)) if admin_doc else False
        status     = "live" if was_open else "closed"
        now        = datetime.utcnow()
        appraisal_cycles_collection.insert_one({
            "quarter_id":    QUARTER_ID,
            "quarter_label": QUARTER_LABEL,
            "status":        status,
            "created_at":    now,
            "created_by":    "MIGRATION",
            "updated_at":    now,
            "updated_by":    "MIGRATION",
        })
        print(f"\nCreated cycle '{QUARTER_ID}' with status '{status}' (legacy cycleOpen was {was_open}).")

    # 2. Backfill quarter_id onto existing Appraisal_data records
    result = appraisal_collection.update_many(
        {"period": QUARTER_LABEL, "quarter_id": {"$exists": False}},
        {"$set": {"quarter_id": QUARTER_ID}},
    )
    print(f"Backfilled quarter_id on {result.modified_count} Appraisal_data record(s).")

    # 3. Backfill eligibility list from distinct employees who already have records
    already_seeded = appraisal_eligibility_collection.count_documents({"quarter_id": QUARTER_ID})
    if already_seeded:
        print(f"Eligibility list for '{QUARTER_ID}' already has {already_seeded} row(s). Skipping backfill.")
    else:
        emp_ids = appraisal_collection.distinct("employeeId", {"period": QUARTER_LABEL})
        if emp_ids:
            now = datetime.utcnow()
            emp_lookup = {
                e["EmpID"].upper(): e
                for e in timesheets_db["Employee_details"].find(
                    {"EmpID": {"$in": [eid.upper() for eid in emp_ids]}},
                    {"EmpID": 1, "Emp Name": 1, "Name": 1}
                )
            }
            rows = []
            for eid in emp_ids:
                code = eid.upper()
                emp  = emp_lookup.get(code, {})
                rows.append({
                    "quarter_id":    QUARTER_ID,
                    "employee_code": code,
                    "employee_name": emp.get("Emp Name") or emp.get("Name") or "",
                    "uploaded_at":   now,
                    "uploaded_by":   "MIGRATION",
                })
            appraisal_eligibility_collection.insert_many(rows)
            print(f"Backfilled {len(rows)} eligibility row(s) for '{QUARTER_ID}' from existing submissions.")
        else:
            print(f"No existing Appraisal_data records found for period '{QUARTER_LABEL}' — nothing to backfill.")

    print("\nDone.")
    print("=" * 62)


if __name__ == "__main__":
    main()
