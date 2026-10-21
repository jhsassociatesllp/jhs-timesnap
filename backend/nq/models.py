# backend/nq/models.py
"""
Clean models for NQ data, plus the ONE place that knows NQ's real column names
(see docs/nq_schema.sql). Everything outside backend/nq/ uses these names.
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel

# tbl_project_task_status ids
TASK_STATUS_NAMES = {1: "To Do", 2: "In Process", 3: "Hold", 4: "Complete"}
TASK_STATUS_COMPLETE = 4

# tbl_projects.project_status enum
PROJECT_STATUS_NAMES = {"0": "inactive", "1": "active", "2": "hold", "3": "closed"}


class NQUnavailable(Exception):
    """NQ could not be reached (connect/query failure or timeout)."""


class NQProject(BaseModel):
    id: int                      # tbl_projects.id (what tasks reference)
    project_code: str            # tbl_projects.project_id, e.g. "PL-T001"
    project_name: str = ""
    client_name: str = ""
    manager_ids: List[int] = []  # tbl_projects.project_manager (may be a comma list)
    partner_id: Optional[int] = None
    status: str = "active"
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class NQTask(BaseModel):
    id: int
    task_uid: str = ""
    parent_task_id: Optional[int] = None
    project_id: int              # tbl_projects.id
    project_code: str = ""
    project_name: str = ""
    client_name: str = ""
    name: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    assignee_ids: List[int] = []     # NQ tbl_user ids (assigned_to may be a comma list)
    status_id: int = 1
    status: str = "To Do"
    is_complete: bool = False
    is_overdue: bool = False         # set by the repository relative to the query date
    project_start: Optional[date] = None
    project_end: Optional[date] = None


class NQUser(BaseModel):
    id: int
    emp_id: str
    name: str = ""
    reporting_to: Optional[int] = None


class NQAssignment(BaseModel):
    """One assignee of one task."""
    task_id: int
    task_name: str = ""
    nq_user_id: int
    emp_id: str = ""
    employee_name: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # NQ has no allocation % column: treated as 100% until it does.
    allocation_pct: float = 100.0


def parse_id_list(value) -> List[int]:
    """'3', '3,4', '4, 5', None -> list of ints (junk tokens ignored)."""
    out = []
    for tok in str(value or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return out


def task_from_row(row: dict, on_date: Optional[date] = None) -> NQTask:
    status_id = int(row.get("task_status") or 1)
    complete = status_id == TASK_STATUS_COMPLETE or str(row.get("is_complete")) == "1"
    end = row.get("end_date")
    return NQTask(
        id=row["id"],
        task_uid=row.get("task_uid") or "",
        parent_task_id=row.get("parent_task_id"),
        project_id=row["project_id"],
        project_code=row.get("project_code") or "",
        project_name=row.get("project_name") or "",
        client_name=row.get("client_name") or "",
        name=row.get("task_name") or "",
        start_date=row.get("start_date"),
        end_date=end,
        assignee_ids=parse_id_list(row.get("assigned_to")),
        status_id=status_id,
        status=TASK_STATUS_NAMES.get(status_id, str(status_id)),
        is_complete=complete,
        is_overdue=bool(on_date and end and end < on_date and not complete),
        project_start=row.get("project_start"),
        project_end=row.get("project_end"),
    )


def project_from_row(row: dict) -> NQProject:
    return NQProject(
        id=row["id"],
        project_code=row.get("project_id") or "",
        project_name=row.get("project_name") or "",
        client_name=row.get("client_name") or "",
        manager_ids=parse_id_list(row.get("project_manager")),
        partner_id=row.get("project_partner"),
        status=PROJECT_STATUS_NAMES.get(str(row.get("project_status")), "active"),
        start_date=row.get("start_date"),
        end_date=row.get("end_date"),
    )
