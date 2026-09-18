# backend/hr_policy_quiz/db.py
"""
Separate DB connection for the HR Policy Quiz module (its own logical
database on the same MongoDB host as the rest of the platform, so its
collections never collide with Timesheet/KRA/Quality Audit data).
"""
from pymongo import MongoClient

from backend.hr_policy_quiz.config import settings

_client = MongoClient(settings.MONGO_URI)
db = _client[settings.DB_NAME]

# Explicitly create the database + collections on startup so they show up
# in Compass immediately, instead of waiting for the first insert.
COLLECTION_NAMES = ["hr_quiz_candidates", "hr_quiz_documents", "hr_quiz_questions", "hr_quiz_attempts", "hr_quiz_deleted_candidates", "hr_quiz_admins", "hr_quiz_sets"]
existing_collections = db.list_collection_names()
for name in COLLECTION_NAMES:
    if name not in existing_collections:
        db.create_collection(name)

candidates = db["hr_quiz_candidates"]
documents = db["hr_quiz_documents"]
questions = db["hr_quiz_questions"]
attempts = db["hr_quiz_attempts"]
deleted_candidates = db["hr_quiz_deleted_candidates"]

# Reusable named quiz compositions: { name, documents: [{document_id,
# document_title, count}], total_questions, created_by, created_at,
# updated_at }. A candidate is assigned a quiz_set_id (not a raw
# document_id) - see router.py's start_quiz for how the weighted mix of
# questions is assembled at quiz time.
quiz_sets = db["hr_quiz_sets"]

# JHS employee codes allowed to open the HR dashboard directly with their
# normal Timesnap login (no separate hr-login screen). One document per
# code: { "empid": "JHS01" }. Add more any time - straight from Compass
# works too, the access check reads this collection live on every request.
hr_quiz_admins = db["hr_quiz_admins"]

DEFAULT_ADMIN_EMPIDS = ["JHS01", "JHS1494", "JHS1191"]
for _empid in DEFAULT_ADMIN_EMPIDS:
    hr_quiz_admins.update_one({"empid": _empid}, {"$setOnInsert": {"empid": _empid}}, upsert=True)

# Helpful indexes. Safe to call every startup - MongoDB ignores duplicates.
candidates.create_index("email", unique=True)
attempts.create_index([("candidate_email", 1), ("started_at", -1)])
deleted_candidates.create_index([("email", 1), ("deleted_at", -1)])
hr_quiz_admins.create_index("empid", unique=True)
quiz_sets.create_index("created_at")
