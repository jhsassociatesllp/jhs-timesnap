from fastapi import FastAPI, HTTPException, Depends, status, Request, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pymongo import MongoClient
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import jwt
import secrets
from bson import ObjectId
from bson.errors import InvalidId
import hashlib
from dotenv import load_dotenv
import os
import re
from passlib.context import CryptContext
import hashlib
import json
from admin import *



pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b", bcrypt__rounds=12)

# Load environment variables
load_dotenv()

app = FastAPI(title="Professional Time Sheet API", version="1.0.0")


# CORS middleware - Update allow_origins for production security
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)

# Generate a secure JWT secret key (use environment variable in production)
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

# MongoDB connection
MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING environment variable is required")

print(MONGO_CONNECTION_STRING)
client = MongoClient(MONGO_CONNECTION_STRING)
db = client["Timesheets"]
timesheets_collection = db["Timesheet_data"]
sessions_collection = db["sessions"]
employee_details_collection = db["Employee_details"]
client_details_collection = db["Client_details"]
users_collection = db["users"]
reporting_managers_collection = db["Reporting_managers"]
pending_collection = db["Pending"]
approved_collection = db["Approved"]
rejected_collection = db["Rejected"]

# OAuth2 scheme for token-based authentication
oauth2_scheme = HTTPBearer()

class RegisterRequest(BaseModel):
    empid: str
    password: str

class TimesheetEntry(BaseModel):
    employeeId: str
    employeeName: Optional[str] = None
    designation: Optional[str] = None
    gender: Optional[str] = None
    partner: Optional[str] = None
    reportingManager: Optional[str] = None
    department: Optional[str] = None
    weekPeriod: Optional[str] = None
    date: Optional[str] = None
    location: Optional[str] = None
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    punchIn: Optional[str] = None
    punchOut: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
    projectHours: Optional[str] = None
    workingHours: Optional[str] = None
    billable: Optional[str] = None
    remarks: Optional[str] = None
    hits: Optional[str] = None
    misses: Optional[str] = None
    feedback_hr: Optional[str] = None
    feedback_it: Optional[str] = None
    feedback_crm: Optional[str] = None
    feedback_others: Optional[str] = None

class LoginRequest(BaseModel):
    empid: str
    password: str

class UpdateTimesheetRequest(BaseModel):
    date: str
    location: Optional[str] = None
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    punchIn: Optional[str] = None
    punchOut: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
    projectHours: Optional[str] = None
    workingHours: Optional[str] = None
    billable: Optional[str] = None
    remarks: Optional[str] = None

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    print(f"Expires delta: {expires_delta}")
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=1440)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# async def get_current_user(token: str = Depends(oauth2_scheme)):
#     if not token:
#         print("No token")
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         employee_id: str = payload.get("sub")
#         print(f"Decoded payload: {payload}")
#         if employee_id is None:
#             print("No employee_id")
#             raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
#         print(f"Token: {token}, Employee_id: {employee_id}")
        
#         session = sessions_collection.find_one({
#             "token": token, 
#             "employeeId": employee_id,
#             "expires_at": {"$gt": datetime.utcnow()}
#         })
        
#         if not session:
#             print("No session")
#             raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
            
#         return employee_id
#     except jwt.PyJWTError:
#         print(f"Error decoding token: {token}")
#         print("Invalid token")
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials  # Extract Bearer token
    if not token:
        print("No token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        print(f"Decoded payload: {payload}")
        if employee_id is None:
            print("No employee_id")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
        print(f"Token: {token}, Employee_id: {employee_id}")
        
        session = sessions_collection.find_one({
            "token": token, 
            "employeeId": employee_id,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        if not session:
            print("No session")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
            
        return employee_id
    except jwt.PyJWTError:
        print(f"Error decoding token: {token}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# Define frontend path
frontend_path = os.path.join(os.path.dirname(__file__), "static")
print("Frontend path:", frontend_path)
if os.path.exists(frontend_path):
    print("Files in frontend:", os.listdir(frontend_path))
else:
    print(f"Frontend directory not found at: {frontend_path}")

# Mount static files for assets
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/", response_class=FileResponse)
async def read_root():
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/login", response_class=FileResponse)
async def login_page():
    return FileResponse(os.path.join(frontend_path, "login.html"))

@app.get("/dashboard", response_class=FileResponse)
async def dashboard_page():
    return FileResponse(os.path.join(frontend_path, "index.html"))


@app.post("/register")
async def register(request: RegisterRequest):
    empid = request.empid.strip().upper()
    password = request.password

    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one lowercase letter")
    if not re.search(r'\d', password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one special character")

    employee = employee_details_collection.find_one({"EmpID": empid})
    if not employee:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee does not exist")

    existing_user = users_collection.find_one({"empid": empid})
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already registered")

    hashed_password = pwd_context.hash(password)
    user_data = {
        "empid": empid,
        "password": hashed_password
    }
    users_collection.insert_one(user_data)

    return {"success": True, "detail": "Registration successful. Please login."}

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    empid = form_data.username.strip().upper()
    password = form_data.password

    if not empid or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee Code and Password are required")

    user = users_collection.find_one({"empid": empid})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Employee Code or Password")

    if not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Employee Code or Password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": empid}, expires_delta=access_token_expires
    )

    session_data = {
        "employeeId": empid,
        "token": access_token,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + access_token_expires
    }
    sessions_collection.insert_one(session_data)

    return {"success": True, "access_token": access_token, "token_type": "bearer", "employeeId": empid, "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}

# @app.post("/verify_session")
# async def verify_session(token: str = Depends(oauth2_scheme)):
#     employee_id = await get_current_user(token)
#     session = sessions_collection.find_one({"token": token, "employeeId": employee_id})
#     if not session or session["expires_at"] < datetime.utcnow():
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
#     return {"message": "Session valid"}

@app.post("/verify_session")
async def verify_session(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials  # ✅ Extract the Bearer token string
    employee_id = await get_current_user(credentials)  # ✅ Pass credentials to your function
    session = sessions_collection.find_one({"token": token, "employeeId": employee_id})
    
    if not session or session["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
    
    return {"message": "Session valid"}


# @app.post("/logout")
# async def logout(token: str = Depends(oauth2_scheme)):
#     sessions_collection.delete_one({"token": token})
#     return {"message": "Logged out successfully"}

@app.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials  # ✅ Extract string
    sessions_collection.delete_one({"token": token})
    return {"message": "Logged out successfully"}


@app.get("/employees")
async def get_employees(current_user: str = Depends(get_current_user)):
    employees = list(employee_details_collection.find({}, {"_id": 0}))
    return employees

@app.get("/clients")
async def get_clients(current_user: str = Depends(get_current_user)):
    clients = list(client_details_collection.find({}, {"_id": 0}))
    return clients

def compute_entry_hash(entry: dict) -> str:
    """Compute a unique hash for an entry based on key fields (exclude id, timestamps)."""
    key_fields = {
        "date": entry.get("date", ""),
        "location": entry.get("location", ""),
        "projectStartTime": entry.get("projectStartTime", ""),
        "projectEndTime": entry.get("projectEndTime", ""),
        "punchIn": entry.get("punchIn", ""),
        "punchOut": entry.get("punchOut", ""),
        "client": entry.get("client", ""),
        "project": entry.get("project", ""),
        "projectCode": entry.get("projectCode", ""),
        "reportingManagerEntry": entry.get("reportingManagerEntry", ""),
        "activity": entry.get("activity", ""),
        "projectHours": entry.get("projectHours", ""),
        "workingHours": entry.get("workingHours", ""),
        "billable": entry.get("billable", ""),
        "remarks": entry.get("remarks", "")
    }
    # Sort and JSON dump for consistent hashing
    sorted_fields = json.dumps(key_fields, sort_keys=True)
    return hashlib.sha256(sorted_fields.encode()).hexdigest()

@app.post("/save_timesheets")
async def save_timesheets(entries: List[TimesheetEntry], current_user: str = Depends(get_current_user)):
    print("Received timesheets:", entries)
    collection = timesheets_collection

    if not entries:
        print("No timesheets to save.")
        return {"message": "No data to save", "success": False}

    # Validate that employeeId matches the authenticated user
    for entry in entries:
        if entry.employeeId != current_user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized employee ID")

    employee_data = {}
    now_iso = datetime.utcnow().isoformat()
    
    for timesheet in entries:
        employee_id = timesheet.employeeId
        week_period = timesheet.weekPeriod or "No Week"

        if employee_id not in employee_data:
            employee_data[employee_id] = {
                "employeeId": timesheet.employeeId,
                "employeeName": timesheet.employeeName or "",
                "designation": timesheet.designation or "",
                "gender": timesheet.gender or "",
                "partner": timesheet.partner or "",
                "reportingManager": timesheet.reportingManager or "",
                "department": timesheet.department or "",
                "Data": [],
                "hits": timesheet.hits or "",
                "misses": timesheet.misses or "",
                "feedback_hr": timesheet.feedback_hr or "",
                "feedback_it": timesheet.feedback_it or "",
                "feedback_crm": timesheet.feedback_crm or "",
                "feedback_others": timesheet.feedback_others or "",
                "created_time": now_iso,
                "updated_time": now_iso
            }

        daily_entry = {
            "date": timesheet.date or "",
            "location": timesheet.location or "",
            "projectStartTime": timesheet.projectStartTime or "",
            "projectEndTime": timesheet.projectEndTime or "",
            "punchIn": timesheet.punchIn or "",
            "punchOut": timesheet.punchOut or "",
            "client": timesheet.client or "",
            "project": timesheet.project or "",
            "projectCode": timesheet.projectCode or "",
            "reportingManagerEntry": timesheet.reportingManagerEntry or "",
            "activity": timesheet.activity or "",
            "projectHours": timesheet.projectHours or "",
            "workingHours": timesheet.workingHours or "",
            "billable": timesheet.billable or "",
            "remarks": timesheet.remarks or "",
            "id": str(ObjectId()),
            "created_time": now_iso,
            "updated_time": now_iso
        }

        # Find or create the week entry in employee_data
        week_found = False
        for week_obj in employee_data[employee_id]["Data"]:
            if week_period in week_obj:
                week_obj[week_period].append(daily_entry)
                week_found = True
                break
        if not week_found:
            employee_data[employee_id]["Data"].append({week_period: [daily_entry]})

    print("Processing and saving data to DB...")
    for employee_id, data in employee_data.items():
        existing_doc = collection.find_one({"employeeId": employee_id})
        if existing_doc:
            print(f"Updating existing document for employeeId: {employee_id}")
            existing_data = existing_doc.get("Data", [])
            
            # Pre-compute hashes for all existing entries (for duplicate check)
            existing_hashes = set()
            for week_obj in existing_data:
                for week, entries in week_obj.items():
                    for entry in entries:
                        existing_hashes.add(compute_entry_hash(entry))
            
            # Merge new data with existing data, skipping duplicates
            new_data = data["Data"]
            skipped_count = 0
            for new_week_obj in new_data:
                week = list(new_week_obj.keys())[0]
                new_week_entries = new_week_obj[week]
                
                # Filter out duplicates from new entries
                filtered_entries = []
                for new_entry in new_week_entries:
                    new_hash = compute_entry_hash(new_entry)
                    if new_hash in existing_hashes:
                        print(f"Skipping duplicate entry for date {new_entry['date']} (hash: {new_hash})")
                        skipped_count += 1
                        continue
                    filtered_entries.append(new_entry)
                    # Add to existing hashes to prevent intra-batch duplicates
                    existing_hashes.add(new_hash)
                
                if not filtered_entries:
                    continue  # Skip empty week
                
                # Find if the week exists in existing_data
                week_found = False
                for existing_week_obj in existing_data:
                    if week in existing_week_obj:
                        existing_week_obj[week].extend(filtered_entries)
                        week_found = True
                        break
                if not week_found:
                    existing_data.append({week: filtered_entries})
            
            # Recalculate totals from all entries
            total_hours = 0
            total_billable_hours = 0
            total_non_billable_hours = 0
            for week_obj in existing_data:
                for week, entries in week_obj.items():
                    for entry in entries:
                        try:
                            hours = float(entry['projectHours'] or 0)
                        except ValueError:
                            hours = 0
                        total_hours += hours
                        if entry.get('billable') == "Yes":
                            total_billable_hours += hours
                        elif entry.get('billable') == "No":
                            total_non_billable_hours += hours

            # Update the document
            result = collection.update_one(
                {"employeeId": employee_id},
                {"$set": {
                    "Data": existing_data,
                    "employeeName": data["employeeName"],
                    "designation": data["designation"],
                    "gender": data["gender"],
                    "partner": data["partner"],
                    "reportingManager": data["reportingManager"],
                    "department": data["department"],
                    "updated_time": now_iso,
                    "hits": data["hits"] or "",
                    "misses": data["misses"] or "",
                    "feedback_hr": data["feedback_hr"] or "",
                    "feedback_it": data["feedback_it"] or "",
                    "feedback_crm": data["feedback_crm"] or "",
                    "feedback_others": data["feedback_others"] or "",
                    "totalHours": total_hours,
                    "totalBillableHours": total_billable_hours,
                    "totalNonBillableHours": total_non_billable_hours
                }}
            )
            print(f"Updated {result.modified_count} document(s). Skipped {skipped_count} duplicates.")
        else:
            print(f"Inserting new document for employeeId: {employee_id}")
            # For new docs, no duplicate check needed (nothing existing)
            # Calculate totals for new document
            total_hours = 0
            total_billable_hours = 0
            total_non_billable_hours = 0
            for week_obj in data["Data"]:
                for week, entries in week_obj.items():
                    for entry in entries:
                        try:
                            hours = float(entry['projectHours'] or 0)
                        except ValueError:
                            hours = 0
                        total_hours += hours
                        if entry.get('billable') == "Yes":
                            total_billable_hours += hours
                        elif entry.get('billable') == "No":
                            total_non_billable_hours += hours

            data["totalHours"] = total_hours
            data["totalBillableHours"] = total_billable_hours
            data["totalNonBillableHours"] = total_non_billable_hours
            data["created_time"] = now_iso
            result = collection.insert_one(data)
            print(f"Inserted document with ID: {result.inserted_id}")

    print("adding employee codein pending if notexists")
    for emp_id in employee_data.keys():
        # Step 1: Fetch employee details
        employee_doc = employee_details_collection.find_one({"EmpID": emp_id})
        if not employee_doc:
            print(f"Employee {emp_id} not found in employee_details.")
            continue

        print(employee_doc)
        reporting_emp_code = employee_doc.get("ReportingEmpCode")
        reporting_emp_name = employee_doc.get("ReportingEmpName")

        # Step 2: Check if Reporting Manager info exists
        if reporting_emp_code and reporting_emp_name:
            existing_pending = pending_collection.find_one({"ReportingEmpCode": reporting_emp_code})

            if existing_pending:
                # Step 3: Prevent duplicate entries in EmployeesCodes array
                employee_codes = existing_pending.get("EmployeesCodes", [])

                if emp_id not in employee_codes:
                    pending_collection.update_one(
                        {"ReportingEmpCode": reporting_emp_code},
                        {"$addToSet": {"EmployeesCodes": emp_id}}  # $addToSet ensures no duplicates
                    )
                    print(f"Added employee {emp_id} under existing ReportingEmpCode {reporting_emp_code}.")
                else:
                    print(f"Employee {emp_id} already exists under ReportingEmpCode {reporting_emp_code}. Skipping.")
            else:
                # Step 4: Create a new document if manager not found in pending
                new_pending_doc = {
                    "ReportingEmpCode": reporting_emp_code,
                    "ReportingEmpName": reporting_emp_name,
                    "EmployeesCodes": [emp_id],
                    "created_time": datetime.utcnow().isoformat()
                }
                pending_collection.insert_one(new_pending_doc)
                print(f"Created new pending doc for ReportingEmpCode {reporting_emp_code} with employee {emp_id}.")
        else:
            print(f"No ReportingEmpCode found for employee {emp_id}.")

    return {"message": "Timesheets saved successfully", "employee_ids": list(employee_data.keys()), "success": True}

#     print("✅ Adding employee under Reporting Manager’s pending list...")

# for emp_id in employee_data.keys():
#     employee_doc = employee_details_collection.find_one({"EmpID": emp_id})
#     if not employee_doc:
#         print(f"❌ Employee {emp_id} not found in employee_details.")
#         continue

#     reporting_emp_code = employee_doc.get("ReportingEmpCode")
#     reporting_emp_name = employee_doc.get("ReportingEmpName")

#     if reporting_emp_code and reporting_emp_name:
#         existing_pending = pending_collection.find_one({"ReportingEmpCode": reporting_emp_code})

#         if existing_pending:
#             if emp_id not in existing_pending.get("EmployeesCodes", []):
#                 pending_collection.update_one(
#                     {"ReportingEmpCode": reporting_emp_code},
#                     {"$addToSet": {"EmployeesCodes": emp_id}}
#                 )
#                 print(f"✅ Added employee {emp_id} under manager {reporting_emp_code} in Pending.")
#         else:
#             new_doc = {
#                 "ReportingEmpCode": reporting_emp_code,
#                 "ReportingEmpName": reporting_emp_name,
#                 "EmployeesCodes": [emp_id],
#                 "created_time": datetime.utcnow().isoformat()
#             }
#             pending_collection.insert_one(new_doc)
#             print(f"✅ Created Pending doc for manager {reporting_emp_code} with employee {emp_id}.")
#     else:
#         print(f"⚠️ No Reporting Manager found for employee {emp_id}. Skipping.")

@app.get("/timesheets/{employee_id}")
async def get_timesheets(employee_id: str, current_user: str = Depends(get_current_user)):
    if employee_id != current_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access")
    
    try:
        doc = timesheets_collection.find_one({"employeeId": employee_id})
        if not doc:
            print(f"No document found for employeeId: {employee_id}")
            return {"success": True, "Data": [], "totalHours": 0, "totalBillableHours": 0, "totalNonBillableHours": 0}
        
        # Flatten the nested structure for frontend
        flattened_data = []
        
        # Get top-level employee info
        employee_info = {
            "employeeId": doc.get("employeeId", ""),
            "employeeName": doc.get("employeeName", ""),
            "designation": doc.get("designation", ""),
            "gender": doc.get("gender", ""),
            "partner": doc.get("partner", ""),
            "reportingManager": doc.get("reportingManager", ""),
            "department": doc.get("department", ""),
            "hits": doc.get("hits", ""),
            "misses": doc.get("misses", ""),
            "feedback_hr": doc.get("feedback_hr", ""),
            "feedback_it": doc.get("feedback_it", ""),
            "feedback_crm": doc.get("feedback_crm", ""),
            "feedback_others": doc.get("feedback_others", ""),
            "totalHours": doc.get("totalHours", 0),
            "totalBillableHours": doc.get("totalBillableHours", 0),
            "totalNonBillableHours": doc.get("totalNonBillableHours", 0)
        }
        
        # Handle Data field as a list of {week: [entries]}
        existing_data = doc.get("Data", [])
        print(f"Processing Data for employeeId: {employee_id}")
        
        for week_item in existing_data:
            if isinstance(week_item, dict):
                week_period = next(iter(week_item), None)
                if week_period:
                    week_entries = week_item.get(week_period, [])
                    for entry in week_entries:
                        if isinstance(entry, dict):
                            flattened_entry = {**employee_info, **entry}
                            flattened_entry["weekPeriod"] = week_period
                            flattened_data.append(flattened_entry)
        
        print(f"Returning flattened data")
        return {
            "success": True,
            "Data": flattened_data,
            "totalHours": employee_info["totalHours"],
            "totalBillableHours": employee_info["totalBillableHours"],
            "totalNonBillableHours": employee_info["totalNonBillableHours"]
        }
    except Exception as e:
        print(f"Error fetching timesheets for employeeId: {employee_id}, Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch timesheets: {str(e)}")

@app.put("/update_timesheet/{employee_id}/{entry_id}")
async def update_timesheet(employee_id: str, entry_id: str, update_data: UpdateTimesheetRequest, current_user: str = Depends(get_current_user)):
    print(f"Updating timesheet entry {entry_id} for employee {employee_id} with data: {update_data}")
    if employee_id != current_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access")
    
    try:
        now_iso = datetime.utcnow().isoformat()
        collection = timesheets_collection
        
        # Find the document
        doc = collection.find_one({"employeeId": employee_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Employee document not found")
        
        entry_found = False
        week_found = None
        updated = False
        
        # Search through all weeks and entries - Data is a list of {week: [entries]}
        if "Data" in doc and isinstance(doc["Data"], list):
            for week_obj in doc["Data"]:
                for week_period, week_entries in week_obj.items():
                    if isinstance(week_entries, list):
                        for i, entry in enumerate(week_entries):
                            if entry.get("id") == entry_id:
                                # Update this specific entry
                                updated_entry = {
                                    "date": update_data.date or entry.get("date", ""),
                                    "location": update_data.location or entry.get("location", ""),
                                    "projectStartTime": update_data.projectStartTime or entry.get("projectStartTime", ""),
                                    "projectEndTime": update_data.projectEndTime or entry.get("projectEndTime", ""),
                                    "punchIn": update_data.punchIn or entry.get("punchIn", ""),
                                    "punchOut": update_data.punchOut or entry.get("punchOut", ""),
                                    "client": update_data.client or entry.get("client", ""),
                                    "project": update_data.project or entry.get("project", ""),
                                    "projectCode": update_data.projectCode or entry.get("projectCode", ""),
                                    "reportingManagerEntry": update_data.reportingManagerEntry or entry.get("reportingManagerEntry", ""),
                                    "activity": update_data.activity or entry.get("activity", ""),
                                    "projectHours": update_data.projectHours or entry.get("projectHours", ""),
                                    "workingHours": update_data.workingHours or entry.get("workingHours", ""),
                                    "billable": update_data.billable or entry.get("billable", ""),
                                    "remarks": update_data.remarks or entry.get("remarks", ""),
                                    "updated_time": now_iso,
                                    "id": entry_id  # Keep the same ID
                                }
                                
                                # Replace the entry in the array
                                week_obj[week_period][i] = updated_entry
                                updated = True
                                entry_found = True
                                week_found = week_period
                                break
                    if updated:
                        break
        
        if not entry_found:
            raise HTTPException(status_code=404, detail="Timesheet entry not found")

        # Recalculate totals
        total_hours = 0
        total_billable_hours = 0
        total_non_billable_hours = 0
        for week_obj in doc["Data"]:
            for week, entries in week_obj.items():
                for entry in entries:
                    try:
                        hours = float(entry['projectHours'] or 0)
                    except ValueError:
                        hours = 0
                    total_hours += hours
                    if entry.get('billable') == "Yes":
                        total_billable_hours += hours
                    elif entry.get('billable') == "No":
                        total_non_billable_hours += hours
        
        # Update the document in database
        collection.update_one(
            {"employeeId": employee_id},
            {"$set": {
                "Data": doc["Data"],
                "updated_time": now_iso,
                "totalHours": total_hours,
                "totalBillableHours": total_billable_hours,
                "totalNonBillableHours": total_non_billable_hours
            }}
        )
        
        return {"success": True, "message": "Timesheet entry updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update timesheet: {str(e)}")

@app.delete("/delete_timesheet/{employee_id}/{entry_id}")
async def delete_timesheet(employee_id: str, entry_id: str, current_user: str = Depends(get_current_user)):
    print(f"Deleting timesheet entry {entry_id} for employee {employee_id}")
    if employee_id != current_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access")
    
    try:
        now_iso = datetime.utcnow().isoformat()
        collection = timesheets_collection
        
        # Find the document
        doc = collection.find_one({"employeeId": employee_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Employee document not found")
        
        entry_found = False
        
        # Search through all weeks and entries
        if "Data" in doc and isinstance(doc["Data"], list):
            new_data = []
            for week_obj in doc["Data"]:
                new_week_obj = {}
                for week_period, week_entries in week_obj.items():
                    if isinstance(week_entries, list):
                        new_entries = [entry for entry in week_entries if entry.get("id") != entry_id]
                        if len(new_entries) != len(week_entries):
                            entry_found = True
                        if new_entries:  # Only add if not empty
                            new_week_obj[week_period] = new_entries
                if new_week_obj:
                    new_data.append(new_week_obj)
            doc["Data"] = new_data
        
        if not entry_found:
            raise HTTPException(status_code=404, detail="Timesheet entry not found")
        
        # Recalculate totals
        total_hours = 0
        total_billable_hours = 0
        total_non_billable_hours = 0
        for week_obj in doc["Data"]:
            for week, entries in week_obj.items():
                for entry in entries:
                    try:
                        hours = float(entry['projectHours'] or 0)
                    except ValueError:
                        hours = 0
                    total_hours += hours
                    if entry.get('billable') == "Yes":
                        total_billable_hours += hours
                    elif entry.get('billable') == "No":
                        total_non_billable_hours += hours
        
        # Update the document
        collection.update_one(
            {"employeeId": employee_id},
            {"$set": {
                "Data": doc["Data"],
                "updated_time": now_iso,
                "totalHours": total_hours,
                "totalBillableHours": total_billable_hours,
                "totalNonBillableHours": total_non_billable_hours
            }}
        )
        
        return {"success": True, "message": "Timesheet entry deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete timesheet: {str(e)}")

@app.get("/check_reporting_manager/{emp_code}")
async def check_reporting_manager(emp_code: str, current_user: str = Depends(get_current_user)):
    emp_code = emp_code.strip().upper()
    reporting_manager = reporting_managers_collection.find_one({"ReportingEmpCode": emp_code})
    return {"isManager": bool(reporting_manager)}

def get_employees_by_status(reporting_emp_code: str, collection_name: str):
    status_collection = db[collection_name]
    timesheet_collection = db["Timesheet_data"]
    print("Reporting emp code ", reporting_emp_code)
    pending_doc = status_collection.find_one({"ReportingEmpCode": reporting_emp_code})
    print(pending_doc)
    if not pending_doc:
        return {"message": f"No data found for ReportingEmpCode: {reporting_emp_code}", "employees": []}

    employee_codes = pending_doc.get("EmployeesCodes", [])
    employees_data = []

    print(employee_codes)
    for emp_code in employee_codes:
        
        emp_timesheet = timesheet_collection.find_one({"employeeId": emp_code}, {"_id": 0})
        print(emp_timesheet)
        if emp_timesheet:
            employees_data.append({
                "employeeId": emp_code,
                "timesheetData": emp_timesheet
            })
        else:
            employees_data.append({
                "employeeId": emp_code,
                "timesheetData": None
            })

    return {
        "reporting_manager": reporting_emp_code,
        "employees": employees_data
    }

# @app.get("/get_pending_employees/{reporting_emp_code}")
# async def get_pending_employees(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
#     """
#     Returns employees and their timesheet data under a Reporting Manager from 'pending' collection.
#     """
#     print("Current user: ", current_user)
#     reporting_emp_code = current_user
#     return get_employees_by_status(reporting_emp_code.strip(), "Pending")

@app.get("/get_pending_employees/{reporting_emp_code}")
async def get_pending_employees(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    """
    Returns employees and their timesheet data under a Reporting Manager from 'Pending' collection.
    """
    print(f"🔹 Pending employees requested for manager: {reporting_emp_code}")
    print(f"🔹 Authenticated user: {current_user}")

    # 🧠 Use the URL param if given, otherwise fallback to logged-in user
    manager_code = (reporting_emp_code or current_user).strip().upper()

    # 🟢 Fetch data for that reporting manager
    return get_employees_by_status(manager_code, "Pending")


@app.get("/get_approved_employees/{reporting_emp_code}")
async def get_approved_employees(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    """
    Returns employees and their timesheet data under a Reporting Manager from 'approved' collection.
    """
    return get_employees_by_status(reporting_emp_code.strip(), "Approved")


@app.get("/get_approved_employees/{reporting_emp_code}")
async def get_approved_employees(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    """
    Returns employees and their timesheet data under a Reporting Manager from 'Approved' collection.
    """
    manager_code = (reporting_emp_code or current_user).strip().upper()
    return get_employees_by_status(manager_code, "Approved")

@app.get("/get_rejected_employees/{reporting_emp_code}")
async def get_rejected_employees(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    """
    Returns employees and their timesheet data under a Reporting Manager from 'rejected' collection.
    """
    return get_employees_by_status(reporting_emp_code.strip(), "Rejected")


# ✅ Manager ke liye employee ka timesheet dekhne ka route
@app.get("/get_timesheet/{employee_id}")
async def get_employee_timesheet(employee_id: str):
    """
    Manager ke view ke liye: Employee ka pura timesheet + feedback deta hai.
    """
    try:
        # MongoDB me data dhundho
        doc = timesheets_collection.find_one({"employeeId": employee_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail=f"No timesheet found for employee {employee_id}")

        # Nested data flatten karo
        flattened_entries = []
        for week_item in doc.get("Data", []):
            if isinstance(week_item, dict):
                for week_period, entries in week_item.items():
                    for entry in entries:
                        flattened_entries.append({
                            "weekPeriod": week_period,
                            "date": entry.get("date", ""),
                            "client": entry.get("client", ""),
                            "project": entry.get("project", ""),
                            "activity": entry.get("activity", ""),
                            "location": entry.get("location", ""),
                            "start_time": entry.get("projectStartTime", ""),
                            "end_time": entry.get("projectEndTime", ""),
                            "hours": entry.get("projectHours", ""),
                            "billable": entry.get("billable", ""),
                            "remarks": entry.get("remarks", "")
                        })

        # Ye response frontend ko milega
        return {
            "entries": flattened_entries,
            "hits": doc.get("hits", ""),
            "misses": doc.get("misses", ""),
            "feedback_hr": doc.get("feedback_hr", ""),
            "feedback_it": doc.get("feedback_it", ""),
            "feedback_crm": doc.get("feedback_crm", ""),
            "feedback_others": doc.get("feedback_others", "")
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_employee_timesheet for {employee_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# ============================
# 🔐 FORGOT PASSWORD FLOW
# ============================
from email.mime.text import MIMEText
import smtplib
import random

# Temporary OTP store (Mongo collection)
otp_collection = db["otp_storage"]

# Gmail credentials (use app password)
EMAIL_USER = "yourcompanyemail@gmail.com"
EMAIL_PASS = "your_app_password"

def send_email(to_email, subject, body):
    """Send email via Gmail SMTP"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, to_email, msg.as_string())
    except Exception as e:
        print("❌ Email sending failed:", e)
        raise HTTPException(status_code=500, detail="Failed to send OTP email")


# ✅ 1️⃣ Send OTP
@app.post("/send-otp")
async def send_otp(data: dict):
    empid = data.get("empid", "").strip().upper()
    if not empid:
        raise HTTPException(status_code=400, detail="Employee ID is required")

    emp = employee_details_collection.find_one({"EmpID": empid})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    email = emp.get("Email") or emp.get("email") or emp.get("MailID") or emp.get("OfficialEmail")
    if not email:
        raise HTTPException(status_code=400, detail="No email found for this employee")

    otp = str(random.randint(100000, 999999))
    expiry_time = datetime.utcnow() + timedelta(minutes=1)

    otp_collection.update_one(
        {"empid": empid},
        {"$set": {"otp": otp, "expires_at": expiry_time}},
        upsert=True
    )

    body = f"Your OTP for password reset is {otp}. It is valid for 1 minute."
    send_email(email, "Password Reset OTP - Professional Timesheet", body)

    return {"success": True, "message": "OTP sent successfully to your registered email."}


# ✅ 2️⃣ Verify OTP
@app.post("/verify-otp")
async def verify_otp(data: dict):
    empid = data.get("empid", "").strip().upper()
    otp = data.get("otp", "").strip()

    if not empid or not otp:
        raise HTTPException(status_code=400, detail="Employee ID and OTP are required")

    record = otp_collection.find_one({"empid": empid})
    if not record:
        raise HTTPException(status_code=400, detail="OTP not found")

    if record["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="OTP expired")

    return {"success": True, "message": "OTP verified successfully"}


# ✅ 3️⃣ Reset Password
@app.post("/reset-password")
async def reset_password(data: dict):
    empid = data.get("empid", "").strip().upper()
    new_password = data.get("new_password", "")

    if not empid or not new_password:
        raise HTTPException(status_code=400, detail="Employee ID and new password are required")

    user = users_collection.find_one({"empid": empid})
    if not user:
        raise HTTPException(status_code=404, detail="User not registered")

    # Password validation
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not re.search(r'[A-Z]', new_password):
        raise HTTPException(status_code=400, detail="Must contain uppercase letter")
    if not re.search(r'[a-z]', new_password):
        raise HTTPException(status_code=400, detail="Must contain lowercase letter")
    if not re.search(r'\d', new_password):
        raise HTTPException(status_code=400, detail="Must contain number")
    if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', new_password):
        raise HTTPException(status_code=400, detail="Must contain special character")

    hashed_password = pwd_context.hash(new_password)
    users_collection.update_one({"empid": empid}, {"$set": {"password": hashed_password}})

    otp_collection.delete_one({"empid": empid})  # cleanup OTP

    return {"success": True, "message": "Password reset successful"}




# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

def add_or_create(collection, reporting_emp_code, reporting_emp_name, employee_code):
    existing_doc = collection.find_one({"ReportingEmpCode": reporting_emp_code})
    if existing_doc:
        # Add only if not already present
        if employee_code not in existing_doc.get("EmployeesCodes", []):
            collection.update_one(
                {"ReportingEmpCode": reporting_emp_code},
                {"$addToSet": {"EmployeesCodes": employee_code}}
            )
            print(f"Added {employee_code} to {collection.name} for manager {reporting_emp_code}.")
    else:
        new_doc = {
            "ReportingEmpCode": reporting_emp_code,
            "ReportingEmpName": reporting_emp_name,
            "EmployeesCodes": [employee_code],
            "created_time": datetime.utcnow().isoformat()
        }
        collection.insert_one(new_doc)
        print(f"Created new {collection.name} document for {reporting_emp_code} with employee {employee_code}.")

from threading import Thread
import time

def cleanup_expired_otps():
    """Deletes expired OTPs every 60 seconds."""
    while True:
        now = datetime.utcnow()
        result = otp_collection.delete_many({"expires_at": {"$lt": now}})
        if result.deleted_count > 0:
            print(f"🧹 Cleaned up {result.deleted_count} expired OTP(s) at {now.isoformat()}")
        time.sleep(60)  # check every 1 minute

# Start cleanup thread in background
Thread(target=cleanup_expired_otps, daemon=True).start()


@app.post("/approve_timesheet")
async def approve_timesheet(
    reporting_emp_code: str = Body(...),
    employee_code: str = Body(...),
    current_user: str = Depends(get_current_user)
):
    reporting_emp_code = reporting_emp_code.strip().upper()
    employee_code = employee_code.strip().upper()


    # ✅ Remove from pending
    pending_collection.update_one(
        {"ReportingEmpCode": reporting_emp_code},
        {"$pull": {"EmployeesCodes": employee_code}}
    )

    # ✅ Remove from rejected
    rejected_collection.update_one(
        {"ReportingEmpCode": reporting_emp_code},
        {"$pull": {"EmployeesCodes": employee_code}}
    )

    # ✅ Fetch manager name (if available)
    manager_doc = employee_details_collection.find_one({"ReportingEmpCode": reporting_emp_code})
    reporting_emp_name = manager_doc.get("ReportingEmpName") if manager_doc else "Unknown"

    # ✅ Add or create in approved
    add_or_create(approved_collection, reporting_emp_code, reporting_emp_name, employee_code)

    return {"success": True, "message": f"Employee {employee_code} approved successfully."}

# @app.post("/approve_timesheet")
# async def approve_timesheet(
#     reporting_emp_code: str = Body(...),
#     employee_code: str = Body(...),
#     current_user: str = Depends(get_current_user)
# ):
#     reporting_emp_code = reporting_emp_code.strip().upper()
#     employee_code = employee_code.strip().upper()

#     print(f"✅ Approving employee {employee_code} by manager {reporting_emp_code}")

#     # ✅ Remove from Pending and Rejected
#     pending_collection.update_one({"ReportingEmpCode": reporting_emp_code}, {"$pull": {"EmployeesCodes": employee_code}})
#     rejected_collection.update_one({"ReportingEmpCode": reporting_emp_code}, {"$pull": {"EmployeesCodes": employee_code}})

#     # ✅ Fetch manager name
#     manager_doc = employee_details_collection.find_one({"ReportingEmpCode": reporting_emp_code})
#     reporting_emp_name = manager_doc.get("ReportingEmpName") if manager_doc else "Unknown"

#     # ✅ Add to Approved collection
#     add_or_create(approved_collection, reporting_emp_code, reporting_emp_name, employee_code)

#     print(f"✅ Employee {employee_code} moved to Approved for manager {reporting_emp_code}")
#     return {"success": True, "message": f"Employee {employee_code} approved successfully."}

@app.post("/reject_timesheet")
async def reject_timesheet(
    reporting_emp_code: str = Body(...),
    employee_code: str = Body(...),
    current_user: str = Depends(get_current_user)
):
    reporting_emp_code = reporting_emp_code.strip().upper()
    employee_code = employee_code.strip().upper()

    # ✅ Remove from pending and approved
    pending_collection.update_one(
        {"ReportingEmpCode": reporting_emp_code},
        {"$pull": {"EmployeesCodes": employee_code}}
    )
    approved_collection.update_one(
        {"ReportingEmpCode": reporting_emp_code},
        {"$pull": {"EmployeesCodes": employee_code}}
    )

    # ✅ Fetch manager name
    manager_doc = employee_details_collection.find_one({"ReportingEmpCode": reporting_emp_code})
    reporting_emp_name = manager_doc.get("ReportingEmpName") if manager_doc else "Unknown"

    # ✅ Add to rejected
    add_or_create(rejected_collection, reporting_emp_code, reporting_emp_name, employee_code)

    return {"success": True, "message": f"Employee {employee_code} rejected successfully."}

# @app.post("/reject_timesheet")
# async def reject_timesheet(
#     reporting_emp_code: str = Body(...),
#     employee_code: str = Body(...),
#     current_user: str = Depends(get_current_user)
# ):
#     reporting_emp_code = reporting_emp_code.strip().upper()
#     employee_code = employee_code.strip().upper()

#     print(f"❌ Rejecting employee {employee_code} by manager {reporting_emp_code}")

#     # ✅ Remove from Pending and Approved
#     pending_collection.update_one({"ReportingEmpCode": reporting_emp_code}, {"$pull": {"EmployeesCodes": employee_code}})
#     approved_collection.update_one({"ReportingEmpCode": reporting_emp_code}, {"$pull": {"EmployeesCodes": employee_code}})

#     # ✅ Fetch manager name
#     manager_doc = employee_details_collection.find_one({"ReportingEmpCode": reporting_emp_code})
#     reporting_emp_name = manager_doc.get("ReportingEmpName") if manager_doc else "Unknown"

#     # ✅ Add to Rejected collection
#     add_or_create(rejected_collection, reporting_emp_code, reporting_emp_name, employee_code)

#     print(f"❌ Employee {employee_code} moved to Rejected for manager {reporting_emp_code}")
#     return {"success": True, "message": f"Employee {employee_code} rejected successfully."}

# =====================================
# 🔘 GET CURRENT PAR STATUS (Global)
# =====================================
@app.get("/get-par-current-status")
async def get_par_current_status(current_user: str = Depends(get_current_user)):
    """
    Returns the current global PAR status.
    """
    try:        
        admin = admin_details_collection.find_one({}, {"par_status": 1})
        print(f"Admin document: {admin}")
        if not admin:
            return {"par_status": "disable"}
        return {"par_status": admin.get("par_status", "disable")}
    except Exception as e:
        print("Error fetching PAR status:", e)
        return {"par_status": "disable"}
