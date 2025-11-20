from fastapi import FastAPI, HTTPException, Depends, status, Request, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
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
import json
import pandas as pd
from io import BytesIO
import asyncio

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b", bcrypt__rounds=12)

load_dotenv()

app = FastAPI(title="Professional Time Sheet API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING environment variable is required")

print("MongoDB Connection String:", MONGO_CONNECTION_STRING)
client = MongoClient(MONGO_CONNECTION_STRING)
db = client["Timesheets"]
timesheets_collection = db["Timesheet_data"]
sessions_collection = db["sessions"]
employee_details_collection = db["Employee_details"]
client_details_collection = db["Client_details"]
users_collection = db["users"]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

# ------------------- MODELS -------------------
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
    punchIn: Optional[str] = None          # Added
    punchOut: Optional[str] = None         # Added
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
    workingHours: Optional[str] = None     # Added
    projectHours: Optional[str] = None
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
    punchIn: Optional[str] = None
    punchOut: Optional[str] = None
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
    workingHours: Optional[str] = None
    projectHours: Optional[str] = None
    billable: Optional[str] = None
    remarks: Optional[str] = None

# ------------------- AUTH -------------------
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=1440))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        if not employee_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        session = sessions_collection.find_one({
            "token": token,
            "employeeId": employee_id,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        return employee_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

# ------------------- STATIC FILES -------------------
frontend_path = os.path.join(os.path.dirname(__file__), "static")
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

# ------------------- AUTH ENDPOINTS -------------------
@app.post("/register")
async def register(request: RegisterRequest):
    empid = request.empid.strip().upper()
    password = request.password

    if len(password) < 8 or not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password) or not re.search(r'\d', password) or not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise HTTPException(status_code=400, detail="Password must meet complexity requirements")

    employee = employee_details_collection.find_one({"EmpID": empid})
    if not employee:
        raise HTTPException(status_code=400, detail="Employee does not exist")

    if users_collection.find_one({"empid": empid}):
        raise HTTPException(status_code=400, detail="User already registered")

    users_collection.insert_one({"empid": empid, "password": pwd_context.hash(password)})
    return {"success": True, "detail": "Registration successful. Please login."}

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    empid = form_data.username.strip().upper()
    user = users_collection.find_one({"empid": empid})
    if not user or not pwd_context.verify(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid Employee Code or Password")

    access_token = create_access_token(data={"sub": empid})
    session_data = {
        "employeeId": empid,
        "token": access_token,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    sessions_collection.insert_one(session_data)

    return {"success": True, "access_token": access_token, "token_type": "bearer", "employeeId": empid}

@app.post("/verify_session")
async def verify_session(token: str = Depends(oauth2_scheme)):
    await get_current_user(token)
    return {"message": "Session valid"}

@app.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    sessions_collection.delete_one({"token": token})
    return {"message": "Logged out successfully"}

# ------------------- DATA ENDPOINTS -------------------
@app.get("/employees")
async def get_employees(current_user: str = Depends(get_current_user)):
    return list(employee_details_collection.find({}, {"_id": 0}))

@app.get("/clients")
async def get_clients(current_user: str = Depends(get_current_user)):
    return list(client_details_collection.find({}, {"_id": 0}))

# ------------------- HASH & VALIDATION -------------------
def compute_entry_hash(entry: dict) -> str:
    key_fields = {
        "date": entry.get("date", ""),
        "location": entry.get("location", ""),
        "punchIn": entry.get("punchIn", ""),
        "punchOut": entry.get("punchOut", ""),
        "projectStartTime": entry.get("projectStartTime", ""),
        "projectEndTime": entry.get("projectEndTime", ""),
        "client": entry.get("client", ""),
        "project": entry.get("project", ""),
        "projectCode": entry.get("projectCode", ""),
        "reportingManagerEntry": entry.get("reportingManagerEntry", ""),
        "activity": entry.get("activity", ""),
        "workingHours": entry.get("workingHours", ""),
        "projectHours": entry.get("projectHours", ""),
        "billable": entry.get("billable", ""),
        "remarks": entry.get("remarks", "")
    }
    return hashlib.sha256(json.dumps(key_fields, sort_keys=True).encode()).hexdigest()

def is_valid_entry(entry) -> bool:
    meaningful = [entry.date, entry.projectStartTime, entry.projectEndTime, entry.client, entry.project, entry.projectCode, entry.activity]
    return any(str(f).strip() and str(f).strip().upper() != 'NA' for f in meaningful)

# ------------------- SAVE TIMESHEETS -------------------
@app.post("/save_timesheets")
async def save_timesheets(entries: List[TimesheetEntry], current_user: str = Depends(get_current_user)):
    print(f"Received {len(entries)} entries")
    if not entries:
        return {"message": "No data to save", "success": False}

    # Validate user
    for e in entries:
        if e.employeeId != current_user:
            raise HTTPException(status_code=403, detail="Unauthorized employee ID")

    # Filter valid entries
    valid_entries = [e for e in entries if is_valid_entry(e)]
    skipped_blank = len(entries) - len(valid_entries)

    if not valid_entries:
        return {"message": "All entries were blank", "skipped_blank": skipped_blank, "success": False}

    # Group by employee & week
    employee_data = {}
    now_iso = datetime.utcnow().isoformat()

    for e in valid_entries:
        emp_id = e.employeeId
        week = e.weekPeriod or "No Week"

        if emp_id not in employee_data:
            employee_data[emp_id] = {
                "employeeId": e.employeeId,
                "employeeName": e.employeeName or "",
                "designation": e.designation or "",
                "gender": e.gender or "",
                "partner": e.partner or "",
                "reportingManager": e.reportingManager or "",
                "department": e.department or "",
                "Data": [],
                "hits": e.hits or "",
                "misses": e.misses or "",
                "feedback_hr": e.feedback_hr or "",
                "feedback_it": e.feedback_it or "",
                "feedback_crm": e.feedback_crm or "",
                "feedback_others": e.feedback_others or "",
                "created_time": now_iso,
                "updated_time": now_iso
            }

        daily_entry = {
            "date": e.date or "",
            "location": e.location or "",
            "punchIn": e.punchIn or "",           # Added
            "punchOut": e.punchOut or "",         # Added
            "projectStartTime": e.projectStartTime or "",
            "projectEndTime": e.projectEndTime or "",
            "client": e.client or "",
            "project": e.project or "",
            "projectCode": e.projectCode or "",
            "reportingManagerEntry": e.reportingManagerEntry or "",
            "activity": e.activity or "",
            "workingHours": e.workingHours or "", # Added
            "projectHours": e.projectHours or "",
            "billable": e.billable or "",
            "remarks": e.remarks or "",
            "id": str(ObjectId()),
            "created_time": now_iso,
            "updated_time": now_iso
        }

        # Add to week
        week_found = False
        for week_obj in employee_data[emp_id]["Data"]:
            if week in week_obj:
                week_obj[week].append(daily_entry)
                week_found = True
                break
        if not week_found:
            employee_data[emp_id]["Data"].append({week: [daily_entry]})

    # Save with duplicate protection
    saved_count = skipped_duplicate = 0
    for emp_id, data in employee_data.items():
        doc = timesheets_collection.find_one({"employeeId": emp_id})
        existing_hashes = set()

        if doc:
            existing_data = doc.get("Data", [])
            for week_obj in existing_data:
                for entries in week_obj.values():
                    for e in entries:
                        existing_hashes.add(compute_entry_hash(e))

            new_data_to_add = []
            for week_obj in data["Data"]:
                week = list(week_obj.keys())[0]
                new_entries = week_obj[week]
                filtered = []
                for e in new_entries:
                    h = compute_entry_hash(e)
                    if h in existing_hashes:
                        skipped_duplicate += 1
                        continue
                    filtered.append(e)
                    existing_hashes.add(h)
                if filtered:
                    week_found = any(week in w for w in existing_data)
                    if week_found:
                        for w in existing_data:
                            if week in w:
                                w[week].extend(filtered)
                                break
                    else:
                        existing_data.append({week: filtered})

            # Recalculate totals
            total_h = total_b = total_nb = 0.0
            for week_obj in existing_data:
                for entries in week_obj.values():
                    for e in entries:
                        hrs = float(e.get("projectHours") or 0)
                        total_h += hrs
                        if e.get("billable") == "Yes": total_b += hrs
                        elif e.get("billable") == "No": total_nb += hrs

            timesheets_collection.update_one(
                {"employeeId": emp_id},
                {"$set": {
                    "Data": existing_data,
                    "employeeName": data["employeeName"],
                    "designation": data["designation"],
                    "gender": data["gender"],
                    "partner": data["partner"],
                    "reportingManager": data["reportingManager"],
                    "department": data["department"],
                    "hits": data["hits"],
                    "misses": data["misses"],
                    "feedback_hr": data["feedback_hr"],
                    "feedback_it": data["feedback_it"],
                    "feedback_crm": data["feedback_crm"],
                    "feedback_others": data["feedback_others"],
                    "totalHours": round(total_h, 2),
                    "totalBillableHours": round(total_b, 2),
                    "totalNonBillableHours": round(total_nb, 2),
                    "updated_time": now_iso
                }}
            )
            saved_count += 1
        else:
            # New doc
            total_h = total_b = total_nb = 0.0
            for week_obj in data["Data"]:
                for entries in week_obj.values():
                    for e in entries:
                        hrs = float(e.get("projectHours") or 0)
                        total_h += hrs
                        if e.get("billable") == "Yes": total_b += hrs
                        elif e.get("billable") == "No": total_nb += hrs
            data.update({
                "totalHours": round(total_h, 2),
                "totalBillableHours": round(total_b, 2),
                "totalNonBillableHours": round(total_nb, 2),
                "created_time": now_iso
            })
            timesheets_collection.insert_one(data)
            saved_count += 1

    return {
        "message": "Timesheets saved",
        "saved_documents": saved_count,
        "valid_entries": len(valid_entries),
        "skipped_blank": skipped_blank,
        "skipped_duplicate": skipped_duplicate,
        "success": True
    }

# ------------------- GET TIMESHEETS -------------------
@app.get("/timesheets/{employee_id}")
async def get_timesheets(employee_id: str, current_user: str = Depends(get_current_user)):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        return {"success": True, "Data": [], "totalHours": 0, "totalBillableHours": 0, "totalNonBillableHours": 0}

    flattened = []
    info = {k: doc.get(k, "") for k in ["employeeId", "employeeName", "designation", "gender", "partner", "reportingManager", "department", "hits", "misses", "feedback_hr", "feedback_it", "feedback_crm", "feedback_others"]}
    info.update({"totalHours": doc.get("totalHours", 0), "totalBillableHours": doc.get("totalBillableHours", 0), "totalNonBillableHours": doc.get("totalNonBillableHours", 0)})

    for week_obj in doc.get("Data", []):
        for week, entries in week_obj.items():
            for e in entries:
                entry = {**info, **e, "weekPeriod": week}
                flattened.append(entry)

    return {"success": True, "Data": flattened, **info}

# ------------------- UPDATE & DELETE -------------------
@app.put("/update_timesheet/{employee_id}/{entry_id}")
async def update_timesheet(employee_id: str, entry_id: str, update_data: UpdateTimesheetRequest, current_user: str = Depends(get_current_user)):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")

    now_iso = datetime.utcnow().isoformat()
    updated = False

    for week_obj in doc.get("Data", []):
        for week, entries in week_obj.items():
            for i, e in enumerate(entries):
                if e.get("id") == entry_id:
                    entries[i].update({
                        "date": update_data.date or e.get("date", ""),
                        "location": update_data.location or e.get("location", ""),
                        "punchIn": update_data.punchIn or e.get("punchIn", ""),
                        "punchOut": update_data.punchOut or e.get("punchOut", ""),
                        "projectStartTime": update_data.projectStartTime or e.get("projectStartTime", ""),
                        "projectEndTime": update_data.projectEndTime or e.get("projectEndTime", ""),
                        "client": update_data.client or e.get("client", ""),
                        "project": update_data.project or e.get("project", ""),
                        "projectCode": update_data.projectCode or e.get("projectCode", ""),
                        "reportingManagerEntry": update_data.reportingManagerEntry or e.get("reportingManagerEntry", ""),
                        "activity": update_data.activity or e.get("activity", ""),
                        "workingHours": update_data.workingHours or e.get("workingHours", ""),
                        "projectHours": update_data.projectHours or e.get("projectHours", ""),
                        "billable": update_data.billable or e.get("billable", ""),
                        "remarks": update_data.remarks or e.get("remarks", ""),
                        "updated_time": now_iso
                    })
                    updated = True
                    break
            if updated: break
        if updated: break

    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Recalculate totals
    total_h = total_b = total_nb = 0.0
    for week_obj in doc["Data"]:
        for entries in week_obj.values():
            for e in entries:
                hrs = float(e.get("projectHours") or 0)
                total_h += hrs
                if e.get("billable") == "Yes": total_b += hrs
                elif e.get("billable") == "No": total_nb += hrs

    timesheets_collection.update_one(
        {"employeeId": employee_id},
        {"$set": {
            "Data": doc["Data"],
            "totalHours": round(total_h, 2),
            "totalBillableHours": round(total_b, 2),
            "totalNonBillableHours": round(total_nb, 2),
            "updated_time": now_iso
        }}
    )
    return {"success": True, "message": "Updated"}



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

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/upload_timesheet")
async def upload_timesheet(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Invalid file format")

    content = await file.read()
    df = pd.read_excel(BytesIO(content))

    # Clean column names
    df.columns = [str(c).strip() for c in df.columns]

    required = [
        "Employee ID", "Date", "Location of Work", "Punch In", "Punch Out",
        "Project Start Time", "Project End Time", "Client",
        "Project", "Project Code", "Reporting Manager Entry",
        "Activity", "Project Hours", "Working Hours",
        "Billable", "Remarks", "Week Period"
    ]

    for r in required:
        if r not in df.columns:
            raise HTTPException(status_code=400, detail=f"Missing column: {r}")

    entries = []

    for _, row in df.iterrows():
        entry = {
            "employeeId": str(row["Employee ID"]),
            "employeeName": row.get("Employee Name", ""),
            "designation": row.get("Designation", ""),
            "gender": row.get("Gender", ""),
            "partner": row.get("Partner", ""),
            "reportingManager": row.get("Reporting Manager", ""),
            "weekPeriod": row.get("Week Period", ""),
            "date": str(row["Date"]),
            "location": row.get("Location of Work", ""),
            "punchIn": row.get("Punch In", ""),
            "punchOut": row.get("Punch Out", ""),
            "projectStartTime": row.get("Project Start Time", ""),
            "projectEndTime": row.get("Project End Time", ""),
            "client": row.get("Client", ""),
            "project": row.get("Project", ""),
            "projectCode": row.get("Project Code", ""),
            "reportingManagerEntry": row.get("Reporting Manager Entry", ""),
            "activity": row.get("Activity", ""),
            "projectHours": str(row.get("Project Hours", "")),
            "workingHours": str(row.get("Working Hours", "")),
            "billable": row.get("Billable", ""),
            "remarks": row.get("Remarks", ""),
            "hits": row.get("3 HITS", ""),
            "misses": row.get("3 MISSES", ""),
            "feedback_hr": row.get("FEEDBACK FOR HR", ""),
            "feedback_it": row.get("FEEDBACK FOR IT", ""),
            "feedback_crm": row.get("FEEDBACK FOR CRM", ""),
            "feedback_others": row.get("FEEDBACK FOR OTHERS", "")
        }
        entries.append(entry)

    # Insert using your existing logic
    await save_timesheets(entries, current_user)

    return {"success": True, "message": "Uploaded and saved to database"}
