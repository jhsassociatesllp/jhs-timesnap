# backend/timesheet/nested_view.py
"""
A READ-ONLY MongoDB view, `employee_timesheets`, that shows the new timesheet the way people think about it:

  one document per employee
    payrolls[]   (21st to 20th; payroll_id is the month it ends in, '2026-10' = 21 Sep - 20 Oct 2026)
      cycles[]   (three 10-day cycles: 21-end of the previous month, 1-10, 11-20)
        status / approved_by / note   (from cycle_reviews)
        entries[]  (date, client, project, task, hours, status, remarks, location ...)

Nothing is copied: the view is a saved aggregation over `timesheet_entries`, computed only when someone opens it
(Compass, an export). The application itself never reads it, so it adds no load to saving or loading a timesheet.
You cannot edit documents in a view - corrections are made on `timesheet_entries` (one row per entry).

Setup (once per database; changes the database, so it asks for --yes and prints which server it will use):
  python -m backend.timesheet.nested_view status
  python -m backend.timesheet.nested_view create --yes
  python -m backend.timesheet.nested_view drop --yes
"""
import sys
from typing import List

VIEW_NAME = "employee_timesheets"

_ENTRY_FIELDS = ["date", "location", "client", "project", "project_code", "task_id", "task_name", "hours",
                 "task_status", "remarks", "extra_remarks", "is_unplanned", "reporting_manager_name", "approved", "locked", "legacy"]


def pipeline(reviews: str = "cycle_reviews", employees: str = "Employee_details") -> List[dict]:
    pm = {"$cond": [{"$eq": ["$_c", "3"]}, {"$cond": [{"$eq": ["$_m", 12]}, 1, {"$add": ["$_m", 1]}]}, "$_m"]}
    py = {"$cond": [{"$and": [{"$eq": ["$_c", "3"]}, {"$eq": ["$_m", 12]}]}, {"$add": ["$_y", 1]}, "$_y"]}
    pad = {"$cond": [{"$lt": ["$_pm", 10]}, {"$concat": ["0", {"$toString": "$_pm"}]}, {"$toString": "$_pm"}]}
    return [
        {"$match": {"cycle_id": {"$type": "string"}, "employee_id": {"$type": "string"}}},
        {"$addFields": {"_y": {"$toInt": {"$substrBytes": ["$cycle_id", 0, 4]}},
                        "_m": {"$toInt": {"$substrBytes": ["$cycle_id", 5, 2]}},
                        "_c": {"$substrBytes": ["$cycle_id", 9, 1]}}},
        {"$addFields": {"_pm": pm, "_py": py}},
        {"$addFields": {"payroll_id": {"$concat": [{"$toString": "$_py"}, "-", pad]}}},
        {"$sort": {"date": 1, "created_at": 1}},
        {"$group": {"_id": {"e": "$employee_id", "p": "$payroll_id", "c": "$cycle_id"},
                    "hours": {"$sum": {"$ifNull": ["$hours", 0]}},
                    "entries": {"$push": {f: f"${f}" for f in _ENTRY_FIELDS}}}},
        {"$sort": {"_id.e": 1, "_id.p": 1, "_id.c": 1}},
        {"$lookup": {"from": reviews, "let": {"e": "$_id.e", "c": "$_id.c"},
                     "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$kind", "approval"], },
                                                               {"$eq": ["$employee_id", "$$e"]},
                                                               {"$eq": ["$cycle_id", "$$c"]}]}}},
                                  {"$project": {"_id": 0, "status": 1, "approved_by": 1, "approved_at": 1, "note": 1}}],
                     "as": "_review"}},
        {"$group": {"_id": {"e": "$_id.e", "p": "$_id.p"}, "hours": {"$sum": "$hours"},
                    "cycles": {"$push": {
                        "cycle_id": "$_id.c",
                        "status": {"$ifNull": [{"$arrayElemAt": ["$_review.status", 0]}, "pending"]},
                        "approved_by": {"$arrayElemAt": ["$_review.approved_by", 0]},
                        "approved_at": {"$arrayElemAt": ["$_review.approved_at", 0]},
                        "note": {"$arrayElemAt": ["$_review.note", 0]},
                        "total_hours": {"$round": ["$hours", 2]},
                        "entries": "$entries"}}}},
        {"$sort": {"_id.e": 1, "_id.p": 1}},
        {"$group": {"_id": "$_id.e",
                    "payrolls": {"$push": {"payroll_id": "$_id.p", "total_hours": {"$round": ["$hours", 2]}, "cycles": "$cycles"}}}},
        {"$lookup": {"from": employees, "localField": "_id", "foreignField": "EmpID", "as": "_emp"}},
        {"$project": {"_id": 1, "employee_id": "$_id",
                      "employee_name": {"$arrayElemAt": ["$_emp.Emp Name", 0]},
                      "reporting_manager": {"$arrayElemAt": ["$_emp.ReportingEmpName", 0]},
                      "payrolls": 1}},
    ]


def ensure_view(db, name: str = VIEW_NAME, source: str = "timesheet_entries",
                reviews: str = "cycle_reviews", employees: str = "Employee_details") -> str:
    """Create the view, or update its definition if it exists. Refuses to touch a real collection."""
    found = list(db.list_collections(filter={"name": name}))
    if found and found[0].get("type") != "view":
        raise RuntimeError(f"'{name}' exists and is a normal collection - not touching it")
    pipe = pipeline(reviews, employees)
    if found:
        db.command("collMod", name, viewOn=source, pipeline=pipe)
        return "updated"
    db.command("create", name, viewOn=source, pipeline=pipe)
    return "created"


def drop_view(db, name: str = VIEW_NAME) -> str:
    found = list(db.list_collections(filter={"name": name}))
    if not found:
        return "absent"
    if found[0].get("type") != "view":
        raise RuntimeError(f"'{name}' is a normal collection - not dropping it")
    db.drop_collection(name)
    return "dropped"


def main(argv: List[str]) -> int:
    from backend.database import MONGO_CONNECTION_STRING, db
    host = MONGO_CONNECTION_STRING.split("@")[-1].split("/")[0]
    cmd = argv[0] if argv else ""
    if cmd not in ("status", "create", "drop"):
        print(__doc__)
        return 2
    print(f"database: {db.name} on {host}")
    found = list(db.list_collections(filter={"name": VIEW_NAME}))
    print(f"{VIEW_NAME}:", ("view" if found and found[0].get("type") == "view" else "NORMAL COLLECTION") if found else "does not exist")
    if cmd == "status":
        return 0
    if "--yes" not in argv:
        print("This changes the database above. Run again with --yes to continue.")
        return 2
    print(ensure_view(db) if cmd == "create" else drop_view(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
