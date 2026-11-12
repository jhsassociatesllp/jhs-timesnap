# backend/resume_ranker/duplicates.py
"""
Duplicate-candidate detection (the same person applying twice).

Two signals, run after each resume is parsed:
  high      same email, or same phone number (last 10 digits)
  possible  same normalised name AND at least one employer in common
The earliest upload in a group is kept as the canonical record; the rest point
at it through `duplicate_of`. Nothing is deleted — HR can still open, compare
and score the duplicate — but ranked lists hide duplicates by default.
"""
from __future__ import annotations

import re

from backend.resume_ranker.db import resumes

_PARSED = {"status": "parsed"}


def name_key(name: str | None) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _companies(doc: dict) -> set[str]:
    return {re.sub(r"[^a-z0-9]", "", (e.get("company") or "").lower())
            for e in (doc.get("parsed") or {}).get("experience", []) if e.get("company")} - {""}


def find_matches(doc: dict) -> list[tuple[dict, str, str]]:
    """Other parsed resumes that look like the same person: [(doc, confidence, reason)]."""
    others: dict = {}
    out = []

    def add(match, confidence, reason):
        if match["_id"] not in others and match["_id"] != doc["_id"]:
            others[match["_id"]] = True
            out.append((match, confidence, reason))

    if doc.get("email"):
        for m in resumes.find({**_PARSED, "email": doc["email"]}):
            add(m, "high", "same email address")
    if doc.get("phone_key"):
        for m in resumes.find({**_PARSED, "phone_key": doc["phone_key"]}):
            add(m, "high", "same phone number")
    nk = name_key(doc.get("name"))
    if len(nk) >= 5:
        mine = _companies(doc)
        for m in resumes.find({**_PARSED, "name_key": nk}):
            shared = mine & _companies(m)
            if shared:
                add(m, "possible", "same name and a common employer")
    return out


def apply_duplicate_flags(doc: dict) -> None:
    """Recompute duplicate links for the group this resume belongs to."""
    matches = find_matches(doc)
    if not matches:
        return
    members = {doc["_id"]: doc}
    reasons = {}
    for m, confidence, reason in matches:
        members[m["_id"]] = m
        reasons[m["_id"]] = (confidence, reason)
    # pull in canonical records the matches already point at
    for m in list(members.values()):
        root_id = m.get("duplicate_of")
        if root_id and _oid(root_id) not in members:
            root = resumes.find_one({"_id": _oid(root_id)})
            if root:
                members[root["_id"]] = root

    def order(d):
        return (d.get("uploaded_at"), str(d["_id"]))

    canonical = min(members.values(), key=order)
    resumes.update_one({"_id": canonical["_id"]},
                       {"$unset": {"duplicate_of": "", "duplicate_reason": "", "duplicate_confidence": ""}})
    for mid, member in members.items():
        if mid == canonical["_id"]:
            continue
        confidence, reason = reasons.get(mid) or reasons.get(doc["_id"]) or next(iter(reasons.values()))
        if mid == doc["_id"]:
            confidence, reason = _best_reason(reasons)
        resumes.update_one({"_id": mid}, {"$set": {
            "duplicate_of": str(canonical["_id"]), "duplicate_reason": reason,
            "duplicate_confidence": confidence}})


def _best_reason(reasons: dict) -> tuple[str, str]:
    for confidence, reason in reasons.values():
        if confidence == "high":
            return confidence, reason
    return next(iter(reasons.values()))


def _oid(value):
    from bson import ObjectId
    return value if isinstance(value, ObjectId) else ObjectId(str(value))
