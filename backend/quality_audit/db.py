# backend/quality_audit/db.py
"""
Separate DB connection for Quality_Audit database.
Add this import to backend/database.py or use independently.
"""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_CONNECTION_STRING", "mongodb://localhost:27017")

_qa_client = MongoClient(MONGO_URI)
qa_db = _qa_client["Quality_Audit"]

# Collections
qa_users_collection      = qa_db["users"]          # { user: [...emails], admin: [...emails] }
qa_audit_collection      = qa_db["Audit_Data"]      # submitted audits
qa_temp_collection       = qa_db["Temp_Audit"]      # saved (draft) audits
