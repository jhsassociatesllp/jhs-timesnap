from bson import ObjectId
from pymongo import MongoClient
import secrets
import os
from dotenv import load_dotenv

load_dotenv()

# Generate a secure JWT secret key (use environment variable in production)
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

# MongoDB connection
MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING environment variable is required")

print("MongoDB Connection String:", MONGO_CONNECTION_STRING)
client = MongoClient(MONGO_CONNECTION_STRING)
# client = MongoClient("mongodb://mongodb:'Jh$20212'@jhstimesnap_mongo:27017/?authSource=admin")
db = client["Timesheets"]
timesheets_collection = db["Timesheet_data"]
sessions_collection = db["sessions"]
employee_details_collection = db["Employee_details"]
client_details_collection = db["Client_details"]
users_collection = db["users"]
admin_details_collection = db["Admin_details"]

