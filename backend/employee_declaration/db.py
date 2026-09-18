# backend/employee_declaration/db.py
"""
Separate DB connection for the Employee Declaration module (its own logical
database on the same MongoDB host as the rest of the platform, so its
collections never collide with Timesheet/KRA/HR Quiz data).
"""
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING env var is required")

_client = MongoClient(MONGO_CONNECTION_STRING)
db = _client["Employee_Declaration"]

# One document per employee who has submitted:
# { empid, employee_name, signature (base64 PNG data URL), submitted_at }
submissions = db["Employee_Filled_Data"]

# Employee codes allowed to open the Employee Declaration Admin dashboard.
# One document per code: { "empid": "JHS1283" }. Add more any time - straight
# from Compass works too, the access check reads this collection live.
admins = db["Admin"]

DEFAULT_ADMIN_EMPIDS = ["JHS1283", "JHS1191"]
for _empid in DEFAULT_ADMIN_EMPIDS:
    admins.update_one({"empid": _empid}, {"$setOnInsert": {"empid": _empid}}, upsert=True)

# Helpful indexes. Safe to call every startup - MongoDB ignores duplicates.
submissions.create_index("empid", unique=True)
admins.create_index("empid", unique=True)
