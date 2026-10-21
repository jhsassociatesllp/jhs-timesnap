# backend/cycle/locks.py
"""Cycle-level lock: once a manager approves an employee's cycle, NOTHING in it can change -
not even adding an entry on a day that was left empty. A cycle the manager SENT BACK (or an admin
reopened) is editable again, even after its deadline, until it is approved."""
from typing import Optional

from backend.cycle.store import store


def cycle_review(employee_id: str, cycle_id: str) -> Optional[dict]:
    return store.reviews.find_one({"kind": "approval", "employee_id": employee_id.strip().upper(),
                                   "cycle_id": cycle_id})


def cycle_locked(employee_id: str, cycle_id: str) -> bool:
    return store.reviews.find_one({"kind": "approval", "employee_id": employee_id.strip().upper(),
                                   "cycle_id": cycle_id, "status": "approved"}, {"_id": 1}) is not None


def cycle_reopened(employee_id: str, cycle_id: str) -> bool:
    """True while a send-back (or an admin's unlock) keeps the cycle open past its deadline."""
    return store.reviews.find_one({"kind": "approval", "employee_id": employee_id.strip().upper(),
                                   "cycle_id": cycle_id, "status": {"$in": ["sent_back", "reopened"]}},
                                  {"_id": 1}) is not None
