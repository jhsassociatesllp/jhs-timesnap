# backend/cycle/locks.py
"""Cycle-level lock: once a manager approves an employee's cycle, NOTHING in it can change -
not even adding an entry on a day that was left empty."""
from backend.cycle.store import store


def cycle_locked(employee_id: str, cycle_id: str) -> bool:
    return store.reviews.find_one({"kind": "approval", "employee_id": employee_id.strip().upper(),
                                   "cycle_id": cycle_id, "status": "approved"}, {"_id": 1}) is not None
