"""
migrate_timesheet_data.py
=========================
Migrates Timesheet_data documents from the OLD flat structure to the NEW
payroll-based structure.

OLD structure (Timesheet_data):
{
  "employeeId": "JHS001",
  "employeeName": "...",
  "designation": "...",
  "gender": "...",
  "partner": "...",
  "reportingManager": "...",
  "Data": [
    { "Week1 Label": [ { entry... }, ... ] },
    { "Week2 Label": [ { entry... }, ... ] }
  ],
  "hits": "...", "misses": "...",
  "feedback_hr": "...", "feedback_it": "...",
  "feedback_crm": "...", "feedback_others": "...",
  "totalHours": 40.0,
  "totalBillableHours": 32.0,
  "totalNonBillableHours": 8.0,
  "updated_time": "...",
  "created_time": "..."
}

NEW structure (Timesheet_data):
{
  "employeeId": "JHS001",
  "employeeName": "...",
  "designation": "...",
  "gender": "...",
  "partner": "...",
  "reportingManager": "...",
  "payrolls": [
    {
      "cycle_id": "<ObjectId of Apr-May cycle>",
      "cycle_label": "April - May 2026",
      "submitted": true,
      "submitted_at": "<original updated_time>",
      "totalHours": 40.0,
      "totalBillableHours": 32.0,
      "totalNonBillableHours": 8.0,
      "metadata": {
        "employeeName": "...",
        "designation": "...",
        "gender": "...",
        "partner": "...",
        "reportingManager": "...",
        "hits": "...", "misses": "...",
        "feedback_hr": "...", "feedback_it": "...",
        "feedback_crm": "...", "feedback_others": "..."
      },
      "weeks": [
        {
          "week_period": "Week1 Label",
          "entries": [ { entry... }, ... ]
        }
      ]
    }
  ],
  "updated_time": "...",
  "created_time": "..."
}

HOW TO RUN:
  1. Make sure your .env file has MONGO_CONNECTION_STRING set.
  2. Run: python migrate_timesheet_data.py
  3. The script will:
     a. Show a preview of what will be migrated (dry run first)
     b. Ask for confirmation before writing
     c. Back up old documents to Timesheet_data_backup collection
     d. Migrate all documents to the new structure

NOTES:
  - Documents already in the new structure (have "payrolls" field) are SKIPPED.
  - The script assigns all old data to the "April - May 2026" payroll cycle.
    If you have a different cycle in your payroll_cycles collection, update
    MIGRATION_CYCLE_LABEL below.
  - You can run this multiple times safely — already-migrated docs are skipped.
"""

import os
import sys
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

# Label to assign to all migrated old data.
# This should match the cycle_label of your existing "April - May 2026" cycle
# in the payroll_cycles collection.
MIGRATION_CYCLE_LABEL = "April 2026 - May 2026"

# If you want to use a specific cycle_id from payroll_cycles, set it here.
# Leave as None to auto-detect from payroll_cycles collection by label.
MIGRATION_CYCLE_ID = "6a0d4b111d7617b444140524"  # e.g. "6a0d4b111d7617b444140524"

# ── Connect ───────────────────────────────────────────────────────────────────

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    print("❌ MONGO_CONNECTION_STRING not set in .env")
    sys.exit(1)

client = MongoClient(MONGO_CONNECTION_STRING)
db = client["Timesheets"]

timesheets_col = db["Timesheet_data2"]
backup_col     = db["Timesheet_data_backup"]
cycles_col     = db["payroll_cycles"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def recalc_payroll_totals(weeks: list) -> tuple:
    total = billable = non_billable = 0.0
    for w in weeks:
        for e in w.get("entries", []):
            try:
                hrs = float(e.get("projectHours", 0))
            except (ValueError, TypeError):
                hrs = 0.0
            total += hrs
            if e.get("billable") == "Yes":
                billable += hrs
            elif e.get("billable") == "No":
                non_billable += hrs
    return round(total, 2), round(billable, 2), round(non_billable, 2)


def get_or_find_cycle_id() -> str:
    """Find the cycle_id for the migration cycle label."""
    global MIGRATION_CYCLE_ID

    if MIGRATION_CYCLE_ID:
        # Validate it exists
        try:
            doc = cycles_col.find_one({"_id": ObjectId(MIGRATION_CYCLE_ID)})
            if doc:
                print(f"✅ Using specified cycle: {doc.get('cycle_label')} ({MIGRATION_CYCLE_ID})")
                return MIGRATION_CYCLE_ID
        except Exception:
            pass
        print(f"⚠️  Specified MIGRATION_CYCLE_ID '{MIGRATION_CYCLE_ID}' not found. Searching by label...")

    # Search by label (case-insensitive)
    doc = cycles_col.find_one({
        "cycle_label": {"$regex": f"^{MIGRATION_CYCLE_LABEL}$", "$options": "i"}
    })
    if doc:
        cid = str(doc["_id"])
        print(f"✅ Found cycle by label: '{doc['cycle_label']}' → {cid}")
        return cid

    # Not found — create a placeholder cycle
    print(f"⚠️  No cycle found with label '{MIGRATION_CYCLE_LABEL}'.")
    print(f"   Creating a placeholder cycle in payroll_cycles...")
    result = cycles_col.insert_one({
        "cycle_label": MIGRATION_CYCLE_LABEL,
        "start_date": "2026-04-21",
        "end_date": "2026-05-20",
        "deadline_date": "2026-05-24",
        "deadline_time": "18:30",
        "status": "closed",
        "show_lunch_travel": False,
        "created_at": datetime.utcnow(),
        "created_by": "migration_script",
        "note": "Auto-created by migrate_timesheet_data.py"
    })
    cid = str(result.inserted_id)
    print(f"   Created placeholder cycle with id: {cid}")
    return cid


def migrate_document(doc: dict, cycle_id: str, cycle_label: str) -> dict:
    """Convert one old-format document to the new payroll-based structure."""

    emp_id = doc.get("employeeId", "")

    # Build weeks list from old Data array
    weeks = []
    old_data = doc.get("Data", [])
    for week_obj in old_data:
        for week_period, entries in week_obj.items():
            # Ensure each entry has an id
            clean_entries = []
            for e in entries:
                entry = dict(e)
                if not entry.get("id"):
                    entry["id"] = str(ObjectId())
                # Add lunchTime/travelTime if missing
                entry.setdefault("lunchTime", "")
                entry.setdefault("travelTime", "")
                clean_entries.append(entry)
            weeks.append({
                "week_period": week_period,
                "entries": clean_entries,
            })

    # Recalculate totals
    total, billable, non_billable = recalc_payroll_totals(weeks)

    # Build metadata from old doc fields
    metadata = {
        "employeeName":   doc.get("employeeName", ""),
        "designation":    doc.get("designation", ""),
        "gender":         doc.get("gender", ""),
        "partner":        doc.get("partner", "") or doc.get("Partner", ""),
        "reportingManager": doc.get("reportingManager", ""),
        "hits":           doc.get("hits", ""),
        "misses":         doc.get("misses", ""),
        "feedback_hr":    doc.get("feedback_hr", ""),
        "feedback_it":    doc.get("feedback_it", ""),
        "feedback_crm":   doc.get("feedback_crm", ""),
        "feedback_others": doc.get("feedback_others", ""),
    }

    payroll = {
        "cycle_id":              cycle_id,
        "cycle_label":           cycle_label,
        "submitted":             True,   # old data = already submitted
        "submitted_at":          doc.get("updated_time") or doc.get("created_time"),
        "totalHours":            total,
        "totalBillableHours":    billable,
        "totalNonBillableHours": non_billable,
        "metadata":              metadata,
        "weeks":                 weeks,
    }

    new_doc = {
        "employeeId":      emp_id,
        "employeeName":    doc.get("employeeName", ""),
        "designation":     doc.get("designation", ""),
        "gender":          doc.get("gender", ""),
        "partner":         doc.get("partner", "") or doc.get("Partner", ""),
        "reportingManager": doc.get("reportingManager", ""),
        "payrolls":        [payroll],
        "updated_time":    doc.get("updated_time") or datetime.utcnow().isoformat(),
        "created_time":    doc.get("created_time") or datetime.utcnow().isoformat(),
    }

    return new_doc


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  JHS Timesheet Data Migration Script")
    print("=" * 60)
    print()

    # Count documents
    total_docs   = timesheets_col.count_documents({})
    already_new  = timesheets_col.count_documents({"payrolls": {"$exists": True}})
    needs_migrate = timesheets_col.count_documents({"Data": {"$exists": True}, "payrolls": {"$exists": False}})

    print(f"📊 Total documents in Timesheet_data: {total_docs}")
    print(f"✅ Already in new format (payrolls):  {already_new}")
    print(f"🔄 Need migration (old Data format):  {needs_migrate}")
    print()

    if needs_migrate == 0:
        print("✅ Nothing to migrate. All documents are already in the new format.")
        return

    # Get/create cycle
    cycle_id    = get_or_find_cycle_id()
    cycle_label = MIGRATION_CYCLE_LABEL

    # Verify cycle label from DB
    try:
        cycle_doc = cycles_col.find_one({"_id": ObjectId(cycle_id)})
        if cycle_doc:
            cycle_label = cycle_doc.get("cycle_label", MIGRATION_CYCLE_LABEL)
    except Exception:
        pass

    print()
    print(f"📦 Migration target cycle: '{cycle_label}' (id: {cycle_id})")
    print()

    # Preview first 3 docs
    print("🔍 Preview (first 3 documents to migrate):")
    preview_docs = list(timesheets_col.find(
        {"Data": {"$exists": True}, "payrolls": {"$exists": False}},
        limit=3
    ))
    for doc in preview_docs:
        week_count  = len(doc.get("Data", []))
        entry_count = sum(len(list(wk.values())[0]) for wk in doc.get("Data", []) if wk)
        print(f"   • {doc.get('employeeId','?')} — {doc.get('employeeName','?')} "
              f"| {week_count} weeks | {entry_count} entries")
    print()

    # Confirm
    confirm = input(f"⚠️  Proceed with migrating {needs_migrate} document(s)? [yes/no]: ").strip().lower()
    if confirm not in ("yes", "y"):
        print("❌ Migration cancelled.")
        return

    print()
    print("💾 Backing up old documents to Timesheet_data_backup...")

    migrated = 0
    errors   = 0

    old_docs = list(timesheets_col.find(
        {"Data": {"$exists": True}, "payrolls": {"$exists": False}}
    ))

    for doc in old_docs:
        emp_id = doc.get("employeeId", str(doc["_id"]))
        try:
            # 1. Back up original
            backup_doc = dict(doc)
            backup_doc["_migrated_at"] = datetime.utcnow().isoformat()
            backup_doc["_original_id"] = str(doc["_id"])
            backup_doc.pop("_id", None)
            backup_col.update_one(
                {"_original_id": str(doc["_id"])},
                {"$set": backup_doc},
                upsert=True
            )

            # 2. Build new document
            new_doc = migrate_document(doc, cycle_id, cycle_label)

            # 3. Replace in place (keep same _id)
            timesheets_col.replace_one({"_id": doc["_id"]}, new_doc)

            migrated += 1
            print(f"   ✅ {emp_id} — {doc.get('employeeName','?')}")

        except Exception as e:
            errors += 1
            print(f"   ❌ {emp_id} — ERROR: {e}")

    print()
    print("=" * 60)
    print(f"✅ Migration complete!")
    print(f"   Migrated:  {migrated}")
    print(f"   Errors:    {errors}")
    print(f"   Backup:    Timesheet_data_backup collection ({migrated} docs)")
    print()
    print("📌 Next steps:")
    print("   1. Restart your FastAPI server")
    print("   2. Open the timesheet app — History should now show all old data")
    print("   3. Users can fill new payroll cycles (May-June, etc.) going forward")
    print("=" * 60)


if __name__ == "__main__":
    main()
