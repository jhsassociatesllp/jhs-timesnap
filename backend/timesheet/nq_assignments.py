# backend/timesheet/nq_assignments.py
"""
What an employee may pick on the (existing) timesheet grid, taken from Nexus Quant:
only the clients, projects and activities (NQ tasks) ASSIGNED to them in active projects.

  build_assignment_view(tasks) -> the JSON the grid's client -> project -> code -> activity cascade uses
  activity_errors(entries, assigned_by_id, ...) -> submit-time check that every row names an assigned
                                                   activity (or "Other" with a reason)
Pure functions (no I/O) except load_assigned_tasks().
"""
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from backend.nq import repository as nq_repo
from backend.nq.models import NQTask

LOOKBACK_DAYS = 180          # completed tasks stay selectable for this long after they ended
MIN_REASON_CHARS = 3


def load_assigned_tasks(emp_id: str, today: Optional[date] = None) -> List[NQTask]:
    """Raises NQUnavailable if NQ cannot be reached and nothing is cached."""
    today = today or datetime.now().date()
    return nq_repo.list_tasks_assigned_to((emp_id or "").strip().upper(), today - timedelta(days=LOOKBACK_DAYS))


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def build_assignment_view(tasks: Iterable[NQTask]) -> dict:
    """Group the assigned tasks as clients -> projects -> activities.

    Labels shown to the employee are made UNIQUE (the grid finds a project's code by its label and an
    activity's task by its label): two projects with the same name under one client become
    'Name (CODE)', and two tasks with the same name in one project become 'Name (task uid)'."""
    by_client: Dict[str, Dict[str, dict]] = {}
    for t in tasks:
        client = (t.client_name or "").strip() or "(no client)"
        proj = by_client.setdefault(client, {}).setdefault(t.project_code, {
            "name": (t.project_name or t.project_code).strip(), "code": t.project_code,
            "start": t.project_start, "end": t.project_end, "tasks": []})
        proj["tasks"].append(t)

    clients: List[str] = []
    projects_by_client: Dict[str, List[dict]] = {}
    activities_by_project: Dict[str, List[dict]] = {}
    for client in sorted(by_client, key=str.lower):
        clients.append(client)
        projs = sorted(by_client[client].values(), key=lambda p: (p["name"].lower(), p["code"]))
        name_counts: Dict[str, int] = {}
        for p in projs:
            name_counts[p["name"]] = name_counts.get(p["name"], 0) + 1
        out = []
        for p in projs:
            label = p["name"] if name_counts[p["name"]] == 1 else f"{p['name']} ({p['code']})"
            out.append({"project_name": label, "project_code": p["code"],
                        "execution_start_date": _iso(p["start"]) or "", "execution_end_date": _iso(p["end"]) or ""})
            tasks_sorted = sorted(p["tasks"], key=lambda t: (t.start_date or date.max, t.name.lower(), t.id))
            tn: Dict[str, int] = {}
            for t in tasks_sorted:
                tn[t.name] = tn.get(t.name, 0) + 1
            acts = []
            for t in tasks_sorted:
                suffix = t.task_uid or f"#{t.id}"
                acts.append({
                    "task_id": t.id, "name": t.name, "label": t.name if tn[t.name] == 1 else f"{t.name} ({suffix})",
                    "task_uid": t.task_uid, "parent_task_id": t.parent_task_id,
                    "start_date": _iso(t.start_date), "end_date": _iso(t.end_date),
                    "status": t.status, "is_complete": t.is_complete})
            activities_by_project[p["code"]] = acts
        projects_by_client[client] = out
    return {"clients": clients, "projects_by_client": projects_by_client,
            "activities_by_project": activities_by_project}


def activity_errors(entries: List[dict], assigned_by_id: Dict[int, NQTask], day_off_locations: Iterable[str]) -> List[str]:
    """Row-level problems with the Activity column, in the wording the submit screen shows.
    A working-day row needs EITHER an assigned NQ task (nqTaskId, belonging to the row's project code)
    OR 'Other' (activityOther) with a reason. Client 'Other' rows keep their existing free-text behaviour."""
    off = set(day_off_locations)
    errors: List[str] = []
    for i, e in enumerate(entries, start=1):
        if (e.get("location", "") or "").strip() in off:
            continue
        if (e.get("client", "") or "").strip().upper() == "OTHER":
            continue
        if e.get("activityOther"):
            if len((e.get("activityReason") or "").strip()) < MIN_REASON_CHARS:
                errors.append(f"Row {i}: give a reason for choosing Other as the activity")
            if not (e.get("activity") or "").strip():
                errors.append(f"Row {i}: describe the other activity")
            continue
        try:
            tid = int(e.get("nqTaskId"))
        except (TypeError, ValueError):
            tid = None
        task = assigned_by_id.get(tid) if tid is not None else None
        if task is None:
            errors.append(f"Row {i}: pick one of your assigned activities (or Other with a reason)")
        elif (e.get("projectCode", "") or "").strip().upper() != (task.project_code or "").strip().upper():
            errors.append(f"Row {i}: the activity does not belong to project {e.get('projectCode')}")
    return errors
