"""
One-off: copy legacy nested timesheets (Timesheet_data) into timesheet_entries.

SAFETY: run against a COPY of the database first. The script is a dry run unless
--apply is given, only ever writes the new `timesheet_entries` collection, never
changes or deletes Timesheet_data, and refuses to touch the URI in the
MONGO_CONNECTION_STRING environment variable (assumed production) unless
--allow-production is passed.

  python migrate_timesheet_entries.py --uri mongodb://localhost:27018/ --db Timesheets_copy
  python migrate_timesheet_entries.py --uri mongodb://localhost:27018/ --db Timesheets_copy --apply
"""
import argparse
import os
import sys

from pymongo import ASCENDING, MongoClient

from backend.timesheet.legacy_migration import migrate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", required=True, help="MongoDB URI of the COPY")
    ap.add_argument("--db", required=True, help="database name holding Timesheet_data")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--allow-production", action="store_true")
    args = ap.parse_args()

    prod = os.getenv("MONGO_CONNECTION_STRING", "")
    if prod and args.uri.strip() == prod.strip() and not args.allow_production:
        print("Refusing: --uri equals MONGO_CONNECTION_STRING (production). Use a copy, "
              "or pass --allow-production if you really mean it.", file=sys.stderr)
        return 2

    db = MongoClient(args.uri)[args.db]
    source, dest = db["Timesheet_data"], db["timesheet_entries"]
    stats = migrate(source, dest, apply=args.apply)
    if args.apply:
        dest.create_index([("employee_id", ASCENDING), ("date", ASCENDING)])
        dest.create_index([("employee_id", ASCENDING), ("legacy_id", ASCENDING)], sparse=True)
        dest.create_index([("task_id", ASCENDING)])
        dest.create_index([("cycle_id", ASCENDING)])
    print(("APPLIED" if args.apply else "DRY RUN"), stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
