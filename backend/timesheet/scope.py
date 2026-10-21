# backend/timesheet/scope.py
"""
Who uses the new day-by-day timesheet ("My day").

  config.timesheet_scope = "all"   (default)  every employee, except the free-text employees below
  config.timesheet_scope = "pilot"            only the codes in config.pilot_employees (a staged roll-out)

Free-text employees (partner JHS01 and a few named codes) have no fixed client/project list in Nexus Quant,
so they keep the classic timesheet in both modes - unless listed in config.new_timesheet_include, which lets
named employees onto the new timesheet anyway (they then see the tasks NQ has assigned to them).
"""
from typing import Set

# Partner whose employees have no fixed client/project list; their fields are free-typed in the classic app.
FREE_TEXT_PARTNER_CODE = "JHS01"
# Individual employees exempted the same way regardless of their partner.
FREE_TEXT_EMPLOYEE_CODES = {"JHS1562"}

CONFIG_ID = "timesheet"


def is_free_text(emp_code: str, partner_code: str) -> bool:
    return ((partner_code or "").strip().upper() == FREE_TEXT_PARTNER_CODE
            or (emp_code or "").strip().upper() in FREE_TEXT_EMPLOYEE_CODES)


def pilot_codes(config_doc: dict) -> Set[str]:
    return {str(e).strip().upper() for e in (config_doc or {}).get("pilot_employees", []) or []}


def include_codes(config_doc: dict) -> Set[str]:
    return {str(e).strip().upper() for e in (config_doc or {}).get("new_timesheet_include", []) or []}


def pilot_only(config_doc: dict) -> bool:
    return str((config_doc or {}).get("timesheet_scope", "all")).strip().lower() == "pilot"


def is_enabled(emp: str, config_doc: dict, employees) -> bool:
    emp = (emp or "").strip().upper()
    if not emp:
        return False
    if pilot_only(config_doc) and emp not in pilot_codes(config_doc):
        return False
    if emp in include_codes(config_doc):
        return True
    doc = employees.find_one({"EmpID": emp}, {"PartnerEmpCode": 1}) or {}
    return not is_free_text(emp, doc.get("PartnerEmpCode") or "")


def enabled_set(config_coll, employees) -> Set[str]:
    """Every employee code on the new timesheet (used by reconciliation, dashboards, the digest, cycle review)."""
    cfg = config_coll.find_one({"_id": CONFIG_ID}) or {}
    if pilot_only(cfg):
        return {c for c in pilot_codes(cfg) if is_enabled(c, cfg, employees)}
    out = set(include_codes(cfg))
    for d in employees.find({}, {"EmpID": 1, "PartnerEmpCode": 1}):
        code = str(d.get("EmpID") or "").strip().upper()
        if code and not is_free_text(code, d.get("PartnerEmpCode") or ""):
            out.add(code)
    return out
