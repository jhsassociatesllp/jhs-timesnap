# backend/timesheet/me.py
"""
"Who am I" for the shared menu of the new timesheet screens: which links to show. The menu only hides links;
every endpoint behind them checks the role again on its own.
"""
from fastapi import APIRouter, Depends

from backend.auth import get_current_user
from backend.cycle.store import config_doc, store
from backend.metrics import access
from backend.timesheet import scope

router = APIRouter(prefix="/timesheet/v2", tags=["Timesheet"])


@router.get("/me")
def whoami(current_user: str = Depends(get_current_user)):
    emp = access.me(current_user)
    doc = store.employees.find_one({"EmpID": emp}, {"Emp Name": 1}) or {}
    has_reportees = store.employees.find_one({"ReportingEmpCode": emp}, {"_id": 1}) is not None
    admin = access.is_admin(emp)
    return {
        "employee_id": emp, "name": doc.get("Emp Name") or "",
        "new_timesheet": scope.is_enabled(emp, config_doc(), store.employees),
        "is_admin": admin, "is_partner": access.is_partner(emp),
        "has_reportees": has_reportees, "is_manager": has_reportees or access.is_manager(emp),
    }
