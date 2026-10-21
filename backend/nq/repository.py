# backend/nq/repository.py
"""
The ONLY place with Nexus Quant SQL. Rules:
  * parameterised queries only (%s) -- user input never reaches the SQL text;
  * explicit column lists, never SELECT * (tbl_user holds credential columns);
  * reads use the read-only user; write-back uses the write-back user and
    touches tbl_project_tasks.end_date only;
  * NQ down -> NQUnavailable, or the last cached value (see cache.py).
Column names come from docs/nq_schema.sql; mapping to clean models is in models.py.
"""
import logging
import threading
from datetime import date
from typing import Callable, List, Optional

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

from backend.nq import cache
from backend.nq.models import (
    NQAssignment,
    NQProject,
    NQTask,
    NQUnavailable,
    NQUser,
    parse_id_list,
    project_from_row,
    task_from_row,
)
from backend.nq.settings import NQSettings

log = logging.getLogger("nq")

_settings: Optional[NQSettings] = None
_pools: dict = {}
_pool_lock = threading.Lock()
_health = {"last_success": None}


def configure(settings: NQSettings) -> None:
    """Set the settings (tests) and drop existing pools and cache."""
    global _settings
    with _pool_lock:
        _settings = settings
        for p in _pools.values():
            try:
                p.close()
            except Exception:
                pass
        _pools.clear()
    cache.clear()


def _get_settings() -> NQSettings:
    global _settings
    if _settings is None:
        _settings = NQSettings.from_env()
    return _settings


def _pool(write: bool) -> PooledDB:
    s = _get_settings()
    key = "wb" if write else "ro"
    with _pool_lock:
        if key not in _pools:
            user, pw = (s.wb_user, s.wb_password) if write else (s.user, s.password)
            if not user:
                raise NQUnavailable("NQ write-back user is not configured" if write
                                    else "NQ read-only user is not configured")
            _pools[key] = PooledDB(
                creator=pymysql, maxconnections=s.pool_size, blocking=True,
                ping=1,  # check the connection is alive when it is taken from the pool
                host=s.host, port=s.port, user=user, password=pw, database=s.database,
                connect_timeout=s.connect_timeout, read_timeout=s.query_timeout,
                write_timeout=s.query_timeout, charset="utf8mb4",
                cursorclass=DictCursor, autocommit=False,
            )
        return _pools[key]


def _run(sql: str, params: tuple = (), write: bool = False):
    """Execute one parameterised statement. Returns rows (read) or rowcount (write)."""
    try:
        conn = _pool(write).connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result = cur.rowcount if write else cur.fetchall()
            conn.commit()
        finally:
            conn.close()
    except NQUnavailable:
        raise
    except (pymysql.err.OperationalError, pymysql.err.InterfaceError, OSError) as e:
        log.error("NQ unavailable: %s", e)
        raise NQUnavailable(str(e)) from e
    if not write:
        import time
        _health["last_success"] = time.time()
    return result


def ping() -> float:
    """Round-trip a trivial query; returns seconds. Raises NQUnavailable."""
    import time
    t0 = time.perf_counter()
    _run("SELECT 1 AS ok")
    return time.perf_counter() - t0


def last_success() -> Optional[float]:
    return _health["last_success"]


def _cached(key: tuple, loader: Callable):
    return cache.cached(key, _get_settings().cache_ttl, loader)


def _in_clause(n: int) -> str:
    return ",".join(["%s"] * n)  # only placeholders are generated, never values


# Tasks joined to their (non-deleted) project. assigned_to may be a comma list
# ('3', '3,4', '4, 5'), so assignee matching uses FIND_IN_SET on the id list.
_TASK_COLS = """
    t.id, t.task_uid, t.parent_task_id, t.project_id, t.task_name,
    t.start_date, t.end_date, t.assigned_to, t.task_status, t.is_complete,
    p.project_id AS project_code, p.project_name, p.client_name
"""
_TASK_FROM = """
    FROM tbl_project_tasks t
    JOIN tbl_projects p ON p.id = t.project_id AND p.is_deleted = '0'
"""
_ASSIGNED_TO_USER = "FIND_IN_SET(u.id, REPLACE(t.assigned_to, ' ', '')) > 0"


def get_tasks_for_employee(employee_id: str, on_date: date) -> List[NQTask]:
    """Open work for an employee (Timesnap EmpID == tbl_user.emp_id) on a date:
    tasks whose start..end window contains on_date, plus overdue tasks not done.
    Tasks without dates are not listed. Sub-tasks are included."""
    def load():
        rows = _run(
            f"SELECT {_TASK_COLS} {_TASK_FROM} "
            "JOIN tbl_user u ON u.emp_id = %s AND u.is_deleted = '0' "
            f"WHERE t.is_deleted = '0' AND {_ASSIGNED_TO_USER} "
            "AND t.end_date IS NOT NULL AND t.start_date IS NOT NULL AND ("
            "  (t.start_date <= %s AND t.end_date >= %s) "
            "  OR (t.end_date < %s AND t.task_status <> 4 AND t.is_complete = '0')) "
            "ORDER BY t.end_date, t.id",
            (employee_id, on_date, on_date, on_date),
        )
        return [task_from_row(r, on_date) for r in rows]
    return _cached(("tasks_for_employee", employee_id, on_date), load)


def list_tasks_assigned_to(employee_id: str, since: date) -> List[NQTask]:
    """Every live task assigned to an employee (Timesnap EmpID == tbl_user.emp_id) in an ACTIVE project
    (project_status = '1'): all open tasks, plus completed ones that ended on/after `since` (so a task
    finished last week can still be picked for last week's timesheet rows). Sub-tasks included.
    Carries the project's own start/end dates."""
    def load():
        rows = _run(
            f"SELECT {_TASK_COLS}, p.start_date AS project_start, p.end_date AS project_end {_TASK_FROM} "
            "JOIN tbl_user u ON u.emp_id = %s AND u.is_deleted = '0' "
            f"WHERE p.project_status = '1' AND t.is_deleted = '0' AND {_ASSIGNED_TO_USER} "
            "AND ((t.is_complete = '0' AND t.task_status <> 4) OR t.end_date >= %s) "
            "ORDER BY p.client_name, p.project_name, t.start_date, t.id",
            (employee_id, since),
        )
        return [task_from_row(r, date.today()) for r in rows]
    return _cached(("assigned_tasks", employee_id, since), load)


def get_tasks_for_project(project_code: str) -> List[NQTask]:
    """All live tasks of a project (any dates, any assignee), for progress / RAG figures."""
    def load():
        rows = _run(
            f"SELECT {_TASK_COLS} {_TASK_FROM} "
            "WHERE p.project_id = %s AND t.is_deleted = '0' ORDER BY t.id",
            (project_code,),
        )
        return [task_from_row(r, date.today()) for r in rows]
    return _cached(("tasks_for_project", project_code), load)


def get_task(task_id: int) -> Optional[NQTask]:
    def load():
        rows = _run(
            f"SELECT {_TASK_COLS} {_TASK_FROM} WHERE t.id = %s AND t.is_deleted = '0'",
            (task_id,),
        )
        return task_from_row(rows[0], date.today()) if rows else None
    return _cached(("task", task_id), load)


def get_project(project_code: str) -> Optional[NQProject]:
    def load():
        rows = _run(
            "SELECT id, project_id, project_name, client_name, project_manager, "
            "project_partner, project_status, start_date, end_date "
            "FROM tbl_projects WHERE project_id = %s AND is_deleted = '0'",
            (project_code,),
        )
        return project_from_row(rows[0]) if rows else None
    return _cached(("project", project_code), load)


def list_projects_for_manager(manager_emp_id: str) -> List[NQProject]:
    """Active (not deleted, not closed) projects where the manager (tbl_user.emp_id)
    is listed in project_manager. NOTE: project_manager is assumed to hold tbl_user.id
    value(s); verify against live data before relying on it."""
    def load():
        rows = _run(
            "SELECT p.id, p.project_id, p.project_name, p.client_name, p.project_manager, "
            "p.project_partner, p.project_status, p.start_date, p.end_date "
            "FROM tbl_projects p "
            "JOIN tbl_user u ON u.emp_id = %s AND u.is_deleted = '0' "
            "WHERE p.is_deleted = '0' AND p.project_status <> '3' "
            "AND FIND_IN_SET(u.id, REPLACE(p.project_manager, ' ', '')) > 0 "
            "ORDER BY p.project_id",
            (manager_emp_id,),
        )
        return [project_from_row(r) for r in rows]
    return _cached(("projects_for_manager", manager_emp_id), load)


# ── bulk reads for the nightly metrics job (no cache: the job wants current data) ──────────

def list_active_projects() -> List[NQProject]:
    """Every live project whose status is 'active' (project_status = '1')."""
    rows = _run(
        "SELECT id, project_id, project_name, client_name, project_manager, project_partner, "
        "project_status, start_date, end_date FROM tbl_projects "
        "WHERE is_deleted = '0' AND project_status = '1' ORDER BY project_id")
    return [project_from_row(r) for r in rows]


def list_tasks_of_active_projects() -> List[NQTask]:
    """All live tasks of all active projects in ONE query (instead of one query per project)."""
    rows = _run(
        f"SELECT {_TASK_COLS} {_TASK_FROM} "
        "WHERE t.is_deleted = '0' AND p.project_status = '1' ORDER BY p.project_id, t.id")
    return [task_from_row(r) for r in rows]


def list_users() -> List[NQUser]:
    """Live NQ users (id, emp_id, name, reporting_to only - never credential columns)."""
    rows = _run("SELECT id, emp_id, name, reporting_to FROM tbl_user "
                "WHERE is_deleted = '0' AND emp_id IS NOT NULL AND emp_id <> ''")
    return [NQUser(**r) for r in rows]


def get_assignments_for_project(project_code: str) -> List[NQAssignment]:
    """One row per (task, assignee) for a project's live tasks."""
    def load():
        tasks = _run(
            "SELECT t.id, t.task_name, t.start_date, t.end_date, t.assigned_to "
            "FROM tbl_project_tasks t "
            "JOIN tbl_projects p ON p.id = t.project_id AND p.is_deleted = '0' "
            "WHERE p.project_id = %s AND t.is_deleted = '0' "
            "AND t.assigned_to IS NOT NULL AND t.assigned_to <> '' ORDER BY t.id",
            (project_code,),
        )
        ids = sorted({uid for t in tasks for uid in parse_id_list(t["assigned_to"])})
        users = {}
        if ids:
            for u in _run(
                "SELECT id, emp_id, name FROM tbl_user "
                f"WHERE is_deleted = '0' AND id IN ({_in_clause(len(ids))})",
                tuple(ids),
            ):
                users[u["id"]] = u
        out = []
        for t in tasks:
            for uid in parse_id_list(t["assigned_to"]):
                u = users.get(uid)
                if not u:
                    continue  # deleted or unknown user
                out.append(NQAssignment(
                    task_id=t["id"], task_name=t["task_name"] or "",
                    nq_user_id=uid, emp_id=u["emp_id"] or "", employee_name=u["name"] or "",
                    start_date=t["start_date"], end_date=t["end_date"],
                ))
        return out
    return _cached(("assignments", project_code), load)


def get_user_by_emp_id(emp_id: str) -> Optional[NQUser]:
    def load():
        rows = _run(
            "SELECT id, emp_id, name, reporting_to FROM tbl_user "
            "WHERE emp_id = %s AND is_deleted = '0'", (emp_id,),
        )
        return NQUser(**rows[0]) if rows else None
    return _cached(("user", emp_id), load)


def update_task_end_date(task_id: int, new_end_date: date) -> int:
    """Write-back (Phase 4): set end_date for one task. Uses the write-back user,
    which is only granted UPDATE on that column. Returns rows changed (0 or 1)."""
    changed = _run(
        "UPDATE tbl_project_tasks SET end_date = %s WHERE id = %s",
        (new_end_date, task_id), write=True,
    )
    cache.clear()  # reads must see the new date
    return changed
