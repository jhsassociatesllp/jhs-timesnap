# backend/indexes.py
"""
MongoDB indexes for the project-tracking collections. Idempotent and failure-tolerant: a missing
index only costs speed, so a problem (for example duplicate rows blocking a unique index) is
logged and never stops the app.

  * ensure_all()  - called when the scheduler / metrics CLI starts
  * ensure_once() - called lazily by the first daily-timesheet request in each web process
"""
import logging
import threading

from backend.cycle import digest
from backend.cycle.store import store
from backend.hrms import reco
from backend.metrics import aggregate
from backend.metrics.store import mstore

log = logging.getLogger("indexes")
_lock = threading.Lock()
_done = False


def _specs():
    return [
        (store.entries, [([("employee_id", 1), ("date", 1)], {}), ([("date", 1)], {}),
                         ([("project_code", 1)], {}), ([("employee_id", 1), ("cycle_id", 1)], {}),
                         ([("employee_id", 1), ("task_id", 1)], {}),
                         ([("employee_id", 1), ("legacy_id", 1)], {"sparse": True})]),
        (store.submissions, [([("employee_id", 1), ("date", 1)], {"unique": True}), ([("date", 1)], {})]),
        (store.reviews, [([("kind", 1), ("employee_id", 1), ("cycle_id", 1)], {}),
                         ([("kind", 1), ("task_id", 1)], {}), ([("cycle_id", 1)], {})]),
        (store.uploads, [([("uploaded_at", -1)], {}), ([("sha256", 1)], {})]),
        (store.email_log, [([("created_at", -1)], {})]),
        (mstore.audit, [([("at", -1)], {})]),
    ]


def ensure_all() -> None:
    for coll, indexes in _specs():
        for keys, opts in indexes:
            try:
                coll.create_index(keys, **opts)
            except Exception as exc:                       # e.g. duplicates blocking a unique index
                log.warning("index %s on %s not created: %s", keys, coll.name, str(exc)[:160])
    for fn in (reco.ensure_indexes, digest.ensure_indexes, aggregate.ensure_indexes):
        try:
            fn()
        except Exception as exc:
            log.warning("%s failed: %s", fn.__module__, str(exc)[:160])


def ensure_once() -> None:
    """Create the indexes the first time it is called in this process; never raises."""
    global _done
    if _done:
        return
    with _lock:
        if _done:
            return
        _done = True
        try:
            ensure_all()
        except Exception:
            log.exception("ensure_all failed")
