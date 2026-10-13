# backend/resume_ranker/db.py
"""
Own logical database on the shared MongoDB host so nothing collides with
Timesheet / KRA / HR Quiz data.

  jobs      one doc per job opening (criteria + weights)
  resumes   one doc per uploaded file: extracted text, parsed fields, tags, notes
  scores    one doc per (resume, job): total, sub-scores, flags, HR stage
  batches   one doc per bulk upload (progress tracking)
  tasks     the background work queue (parse / score), claimed atomically
  Holders   who is allowed into the module (all HR, partners, JHS1191)
"""
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

load_dotenv()

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING env var is required")

_client = MongoClient(MONGO_CONNECTION_STRING)
db = _client["Resume_Ranker"]

jobs = db["Jobs"]
resumes = db["Resumes"]
scores = db["Scores"]
adhoc_scores = db["AdhocScores"]
batches = db["Batches"]
tasks = db["Tasks"]
holders = db["Holders"]   # who may open the Resume Ranker: HR, partners and the owner

OWNER_EMPID = "JHS1191"   # always a holder; re-added on every startup


# People who get access on a fresh database. Edit the Holders collection afterwards
# (add {"empid": "JHSxxxx"} or {"empids": [...]}); this list is never re-applied once it has data.
DEFAULT_HOLDERS = {
    "JHS1191": ("Vasu Ramesh Gadde", "owner"),
    "JHS911": ("Pavitra Shravan Sharma", "hr"),
    "JHS1575": ("Juee Sunil Pawar", "hr"),
    "JHS1423": ("Roussel Anthony Swaries", "holder"),
}


def seed_holders() -> None:
    """Make sure the owner is a holder, and on first run (empty collection) add DEFAULT_HOLDERS.
    After that the collection is edited by hand and is never re-seeded, so removals stick."""
    now = datetime.utcnow()
    if holders.count_documents({}) == 0:
        for empid, (name, role) in DEFAULT_HOLDERS.items():
            holders.update_one({"empid": empid}, {"$setOnInsert": {
                "empid": empid, "name": name, "role": role, "added_by": "seed", "added_at": now}}, upsert=True)
    holders.update_one({"empid": OWNER_EMPID}, {"$setOnInsert": {
        "empid": OWNER_EMPID, "role": "owner", "added_by": "seed", "added_at": now}}, upsert=True)


def ensure_indexes() -> None:
    """Called from the app startup hook (not at import) so a slow/unreachable
    MongoDB can't stall importing the module."""
    try:
        resumes.create_index([("uploaded_at", DESCENDING)])
        resumes.create_index("batch_id")
        resumes.create_index("sha256")
        resumes.create_index("status")
        resumes.create_index("email")
        resumes.create_index("phone_key")
        resumes.create_index("skills_key")
        scores.create_index([("job_id", ASCENDING), ("resume_id", ASCENDING)], unique=True)
        scores.create_index([("job_id", ASCENDING), ("total", DESCENDING)])
        adhoc_scores.create_index([("sig", ASCENDING), ("resume_id", ASCENDING)], unique=True)
        tasks.create_index([("status", ASCENDING), ("run_after", ASCENDING), ("created_at", ASCENDING)])
        tasks.create_index("batch_id")
        # partial, so array-style docs ({"empids": [...]}) with no "empid" don't collide
        try:
            holders.create_index("empid", unique=True, partialFilterExpression={"empid": {"$type": "string"}})
        except Exception:
            holders.drop_index("empid_1")
            holders.create_index("empid", unique=True, partialFilterExpression={"empid": {"$type": "string"}})
        seed_holders()
    except Exception as exc:  # pragma: no cover - startup best effort
        logging.warning("[ResumeRanker] index creation skipped: %s", exc)
