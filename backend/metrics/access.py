# backend/metrics/access.py
"""Who may see which dashboard. Roles are re-derived from the data on every request:
  admin    = has_admin_module(user, "timesheet")
  partner  = Employee_details."Grade Name" == "PND"  (the same rule the appraisal module uses)
  manager  = has reportees (Employee_details.ReportingEmpCode == user) or manages projects in project_metrics
Admins and partners see firm-wide data; managers only their own projects and reportees."""
from backend.access_manager.router import has_admin_module
from backend.cycle.store import store
from backend.metrics.store import mstore


def me(user: str) -> str:
    return (user or "").strip().upper()


def is_admin(user: str) -> bool:
    return has_admin_module(me(user), "timesheet")


def is_partner(user: str) -> bool:
    doc = store.employees.find_one({"EmpID": me(user)}, {"Grade Name": 1}) or {}
    return (doc.get("Grade Name") or "").strip().upper() == "PND"


def is_manager(user: str) -> bool:
    u = me(user)
    return (store.employees.find_one({"ReportingEmpCode": u}, {"_id": 1}) is not None
            or mstore.projects.find_one({"manager_emp_ids": u}, {"_id": 1}) is not None)


def can_see_firm(user: str) -> bool:
    return is_admin(user) or is_partner(user)
