"""
FULL TIMESHEET MIGRATION + CLEANUP SCRIPT
=========================================

WHAT THIS SCRIPT DOES
---------------------

1. Migrates OLD format:
   {
      Data: [...]
   }

TO NEW format:
   {
      payrolls: [...]
   }

2. Removes OLD fields completely:
   - Data
   - totalHours
   - feedback_hr
   - etc.

3. Recalculates totals safely

4. Handles:
   - yyyy-mm-dd
   - 4/1/26
   - Excel serial dates
   - mixed date formats

5. Creates backup before migration

6. Safe to rerun

IMPORTANT
---------
AFTER migration:
ONLY payrolls should exist.

No old Data field should remain.

"""

import os
import sys
import copy
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv
from dateutil import parser

load_dotenv()

# =========================================================
# CONFIG
# =========================================================

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")

if not MONGO_CONNECTION_STRING:
    print("❌ MONGO_CONNECTION_STRING missing in .env")
    sys.exit(1)

DATABASE_NAME = "Timesheets"

COLLECTION_NAME = "Timesheet_data"
BACKUP_COLLECTION = "Timesheet_data_backup"
PAYROLL_CYCLE_COLLECTION = "payroll_cycles"

MIGRATION_CYCLE_LABEL = "April 2026 - May 2026"

MIGRATION_CYCLE_ID = "6a0d4b111d7617b444140524"

# =========================================================
# CONNECT
# =========================================================

client = MongoClient(MONGO_CONNECTION_STRING)

db = client[DATABASE_NAME]

timesheets_col = db[COLLECTION_NAME]
backup_col = db[BACKUP_COLLECTION]
cycles_col = db[PAYROLL_CYCLE_COLLECTION]

# =========================================================
# DATE PARSER
# =========================================================

def parse_date(value):

    try:

        # Excel serial date
        if isinstance(value, (int, float)):
            return datetime(1899, 12, 30) + timedelta(days=value)

        return parser.parse(str(value))

    except Exception as e:

        print(f"⚠️ Invalid Date: {value} | {e}")

        return None


# =========================================================
# TOTAL CALCULATOR
# =========================================================

def calculate_totals(weeks):

    total = 0.0
    billable = 0.0
    non_billable = 0.0

    for week in weeks:

        entries = week.get("entries", [])

        for entry in entries:

            try:
                hrs = float(entry.get("projectHours", 0))

            except:
                hrs = 0.0

            total += hrs

            if str(entry.get("billable", "")).strip().lower() == "yes":
                billable += hrs
            else:
                non_billable += hrs

    return (
        round(total, 2),
        round(billable, 2),
        round(non_billable, 2)
    )


# =========================================================
# GET PAYROLL CYCLE
# =========================================================

def get_cycle():

    try:

        cycle = cycles_col.find_one({
            "_id": ObjectId(MIGRATION_CYCLE_ID)
        })

        if cycle:

            print(
                f"✅ Using Cycle: "
                f"{cycle.get('cycle_label')} "
                f"({MIGRATION_CYCLE_ID})"
            )

            return str(cycle["_id"]), cycle["cycle_label"]

    except:
        pass

    cycle = cycles_col.find_one({
        "cycle_label": {
            "$regex": f"^{MIGRATION_CYCLE_LABEL}$",
            "$options": "i"
        }
    })

    if cycle:

        return str(cycle["_id"]), cycle["cycle_label"]

    print("❌ Payroll cycle not found.")
    sys.exit(1)


# =========================================================
# MIGRATE DOCUMENT
# =========================================================

def migrate_document(doc, cycle_id, cycle_label):

    weeks = []

    old_data = doc.get("Data", [])

    # =====================================================
    # LOOP ALL WEEKS
    # =====================================================

    for week_obj in old_data:

        for week_period, entries in week_obj.items():

            clean_entries = []

            for entry in entries:

                e = copy.deepcopy(entry)

                # Ensure valid ID
                if not e.get("id"):
                    e["id"] = str(ObjectId())

                # Add missing fields
                e.setdefault("lunchTime", "")
                e.setdefault("travelTime", "")

                # Validate date
                parsed_date = parse_date(e.get("date"))

                if not parsed_date:
                    print(
                        f"⚠️ Skipping Invalid Entry Date "
                        f"{e.get('date')}"
                    )
                    continue

                # Normalize date format
                e["date"] = parsed_date.strftime("%Y-%m-%d")

                clean_entries.append(e)

            # ADD COMPLETE WEEK
            weeks.append({
                "week_period": week_period,
                "entries": clean_entries
            })

    # =====================================================
    # RECALCULATE TOTALS
    # =====================================================

    total, billable, non_billable = calculate_totals(weeks)

    # =====================================================
    # METADATA
    # =====================================================

    metadata = {

        "employeeName":
            doc.get("employeeName", ""),

        "designation":
            doc.get("designation", ""),

        "gender":
            doc.get("gender", ""),

        "partner":
            doc.get("partner", "") or doc.get("Partner", ""),

        "reportingManager":
            doc.get("reportingManager", ""),

        "hits":
            doc.get("hits", ""),

        "misses":
            doc.get("misses", ""),

        "feedback_hr":
            doc.get("feedback_hr", ""),

        "feedback_it":
            doc.get("feedback_it", ""),

        "feedback_crm":
            doc.get("feedback_crm", ""),

        "feedback_others":
            doc.get("feedback_others", ""),
    }

    # =====================================================
    # PAYROLL OBJECT
    # =====================================================

    payroll = {

        "cycle_id":
            cycle_id,

        "cycle_label":
            cycle_label,

        "submitted":
            True,

        "submitted_at":
            doc.get("updated_time")
            or doc.get("created_time"),

        "totalHours":
            total,

        "totalBillableHours":
            billable,

        "totalNonBillableHours":
            non_billable,

        "metadata":
            metadata,

        "weeks":
            weeks
    }

    # =====================================================
    # FINAL CLEAN DOCUMENT
    # =====================================================

    new_doc = {

        "_id":
            doc["_id"],

        "employeeId":
            doc.get("employeeId", ""),

        "employeeName":
            doc.get("employeeName", ""),

        "designation":
            doc.get("designation", ""),

        "gender":
            doc.get("gender", ""),

        "partner":
            doc.get("partner", "") or doc.get("Partner", ""),

        "reportingManager":
            doc.get("reportingManager", ""),

        "payrolls":
            [payroll],

        "updated_time":
            doc.get("updated_time")
            or datetime.utcnow().isoformat(),

        "created_time":
            doc.get("created_time")
            or datetime.utcnow().isoformat()
    }

    return new_doc


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("JHS TIMESHEET FULL MIGRATION")
    print("=" * 60)
    print()

    cycle_id, cycle_label = get_cycle()

    docs = list(timesheets_col.find({
        "Data": {"$exists": True}
    }))

    print(f"📊 Documents Found: {len(docs)}")
    print()

    if not docs:
        print("✅ Nothing to migrate.")
        return

    confirm = input(
        "⚠️ Proceed with FULL migration? [yes/no]: "
    ).strip().lower()

    if confirm not in ["yes", "y"]:
        print("❌ Cancelled")
        return

    print()

    migrated = 0
    errors = 0

    for doc in docs:

        emp_id = doc.get("employeeId", "UNKNOWN")

        try:

            # =================================================
            # BACKUP
            # =================================================

            backup_doc = copy.deepcopy(doc)

            backup_doc["_backup_time"] = (
                datetime.utcnow().isoformat()
            )

            backup_doc["_original_id"] = str(doc["_id"])

            backup_doc.pop("_id", None)

            backup_col.update_one(
                {
                    "_original_id": str(doc["_id"])
                },
                {
                    "$set": backup_doc
                },
                upsert=True
            )

            # =================================================
            # MIGRATE
            # =================================================

            new_doc = migrate_document(
                doc,
                cycle_id,
                cycle_label
            )

            # =================================================
            # REPLACE ENTIRE DOCUMENT
            # =================================================

            timesheets_col.replace_one(
                {"_id": doc["_id"]},
                new_doc
            )

            migrated += 1

            payroll_count = len(
                new_doc["payrolls"][0]["weeks"]
            )

            entry_count = sum(
                len(w["entries"])
                for w in new_doc["payrolls"][0]["weeks"]
            )

            print(
                f"✅ {emp_id} | "
                f"Weeks: {payroll_count} | "
                f"Entries: {entry_count}"
            )

        except Exception as e:

            errors += 1

            print(f"❌ {emp_id} | ERROR: {e}")

    print()
    print("=" * 60)
    print("MIGRATION COMPLETED")
    print("=" * 60)

    print(f"✅ Migrated: {migrated}")
    print(f"❌ Errors: {errors}")

    print()
    print("IMPORTANT:")
    print("1. Restart FastAPI server")
    print("2. Clear frontend cache")
    print("3. Verify payrolls[0].weeks")
    print("4. Data field should NOT exist anymore")
    print()


if __name__ == "__main__":
    main()