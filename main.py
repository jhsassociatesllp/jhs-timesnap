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
import secrets
import hashlib
from datetime import datetime, timedelta
import requests




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

INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL")
WHATSAPP_SENDER = os.getenv("WHATSAPP_SENDER")
PRE_INTERVIEW_FORM_URL = os.getenv("PRE_INTERVIEW_FORM_URL")

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
    # department: Optional[str] = None
    weekPeriod: Optional[str] = None
    date: Optional[str] = None
    location: Optional[str] = None
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
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
    projectStartTime: Optional[str] = None
    projectEndTime: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    projectCode: Optional[str] = None
    reportingManagerEntry: Optional[str] = None
    activity: Optional[str] = None
    projectHours: Optional[str] = None
    billable: Optional[str] = None
    remarks: Optional[str] = None
    
# Add this Pydantic model with your other models
class VerifyUserRequest(BaseModel):
    empid: str
    verification_code: str

class ResetPasswordRequest(BaseModel):
    empid: str
    new_password: str


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
    print(employee)
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

# ==========================================
# FORGOT PASSWORD ENDPOINTS
# ==========================================

@app.post("/verify-user")
async def verify_user(request: VerifyUserRequest):
    """
    Verify user by employee ID and verification code (DDYYYYMMMM format)
    DD = Date of birth (2 digits)
    YYYY = Year of birth (4 digits)  
    MMMM = First 4 digits of mobile number
    
    Example: DOB = 01/01/1991, Mobile = 9876543210 → Code = 0119919876
    """
    try:
        empid = request.empid.strip().upper()
        verification_code = request.verification_code.strip()
        
        # Validate verification code length
        if len(verification_code) != 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code must be exactly 10 digits"
            )
        
        # Find employee in database
        employee = employee_details_collection.find_one({"EmpID": empid})
        
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found"
            )
        
        # Extract verification components
        try:
            input_date = verification_code[0:2]      # DD
            input_year = verification_code[2:6]      # YYYY
            input_mobile = verification_code[6:10]   # MMMM (first 4 digits)
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code format"
            )
        
        # Get employee DOB and mobile from database
        # Adjust field names according to your database schema
        emp_dob = employee.get("DOB") or employee.get("Date of Birth") or employee.get("DateOfBirth")
        emp_mobile = employee.get("Mobile") or employee.get("Personal Mobile") or employee.get("MobileNumber")
        
        if not emp_dob or not emp_mobile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee DOB or Mobile number not found in database"
            )
        
        # Parse DOB (handle multiple formats: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD)
        emp_dob_str = str(emp_dob)
        
        # Try different date formats
        actual_date = None
        actual_year = None
        
        for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                parsed_date = datetime.strptime(emp_dob_str, fmt)
                actual_date = parsed_date.strftime("%d")
                actual_year = parsed_date.strftime("%Y")
                break
            except:
                continue
        
        if not actual_date or not actual_year:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to parse employee date of birth"
            )
        
        # Get first 4 digits of mobile number (remove any non-digit characters)
        emp_mobile_str = str(emp_mobile).replace(" ", "").replace("-", "").replace("+", "")
        
        # Handle mobile numbers with country code
        if len(emp_mobile_str) > 10:
            emp_mobile_str = emp_mobile_str[-10:]  # Get last 10 digits
        
        actual_mobile = emp_mobile_str[:4]
        
        # Verify the code
        if input_date != actual_date or input_year != actual_year or input_mobile != actual_mobile:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Verification failed. Invalid verification code."
            )
        
        return {
            "success": True,
            "message": "Verification successful",
            "empid": empid
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in verify_user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error: {str(e)}"
        )


@app.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """
    Reset user password after verification
    """
    try:
        empid = request.empid.strip().upper()
        new_password = request.new_password
        
        # Validate password strength
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters"
            )
        
        if not re.search(r'[A-Z]', new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must contain at least one uppercase letter"
            )
        
        if not re.search(r'[a-z]', new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must contain at least one lowercase letter"
            )
        
        if not re.search(r'\d', new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must contain at least one number"
            )
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must contain at least one special character"
            )
        
        # Check if user exists
        user = users_collection.find_one({"empid": empid})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found. Please register first."
            )
        
        # Hash the new password
        hashed_password = pwd_context.hash(new_password)
        
        # Update password in database
        result = users_collection.update_one(
            {"empid": empid},
            {"$set": {
                "password": hashed_password,
                "password_updated_at": datetime.utcnow()
            }}
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password"
            )
        
        return {
            "success": True,
            "message": "Password reset successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in reset_password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error: {str(e)}"
        )


# Optional: Add route to serve forgot password page
@app.get("/forgot-password", response_class=FileResponse)
async def forgot_password_page():
    return FileResponse(os.path.join(frontend_path, "forgot_password.html"))




from fastapi import HTTPException, Depends
from typing import List
from bson import ObjectId
from datetime import datetime
import hashlib

def compute_entry_hash(entry: dict) -> str:
    """Avoid duplicates by hashing key fields"""
    key = f"{entry.get('date')}{entry.get('client')}{entry.get('project')}{entry.get('projectCode')}{entry.get('projectHours')}{entry.get('billable')}"
    return hashlib.sha256(key.encode()).hexdigest()

from fastapi import HTTPException, Depends
from datetime import datetime
from bson import ObjectId
from typing import List

@app.post("/save_timesheets")
async def save_timesheets(entries: List[TimesheetEntry], current_user: str = Depends(get_current_user)):
    """
    Save or update employee timesheet data safely.
    Works for both dict payloads and Pydantic TimesheetEntry objects.
    """

    # 1️⃣ Basic validation
    if not entries:
        return {"success": False, "message": "No entries provided"}

    # Convert all entries to dicts (to avoid AttributeError)
    normalized_entries = []
    for e in entries:
        if hasattr(e, "dict"):  # If it's a Pydantic object
            normalized_entries.append(e.dict())
        elif isinstance(e, dict):  # If already a dict
            normalized_entries.append(e)
        else:
            normalized_entries.append(vars(e))

    # 2️⃣ Verify ownership
    for entry in normalized_entries:
        if entry.get("employeeId") != current_user:
            raise HTTPException(status_code=403, detail="Cannot save for another employee")

    emp_id = current_user
    now_iso = datetime.utcnow().isoformat()
    week_data = {}

    # 3️⃣ Group entries by weekPeriod
    for entry in normalized_entries:
        week = entry.get("weekPeriod") or "Uncategorized"
        if week not in week_data:
            week_data[week] = []

        daily_entry = {
            "date": entry.get("date", ""),
            "location": entry.get("location", ""),
            "projectStartTime": entry.get("projectStartTime", ""),
            "projectEndTime": entry.get("projectEndTime", ""),
            "client": entry.get("client", ""),
            "project": entry.get("project", ""),
            "projectCode": entry.get("projectCode", ""),
            "reportingManagerEntry": entry.get("reportingManagerEntry", ""),
            "activity": entry.get("activity", ""),
            "projectHours": entry.get("projectHours", "0"),
            "billable": entry.get("billable", "No"),
            "remarks": entry.get("remarks", ""),
            "id": str(ObjectId()),
            "created_time": now_iso,
            "updated_time": now_iso
        }

        week_data[week].append(daily_entry)

    # 4️⃣ Fetch existing document if present
    existing_doc = timesheets_collection.find_one({"employeeId": emp_id})
    existing_data = existing_doc.get("Data", []) if existing_doc else []

    # 5️⃣ Create hash of existing entries for duplicate prevention
    existing_hashes = set()
    for week_obj in existing_data:
        for week_name, week_entries in week_obj.items():
            for e in week_entries:
                existing_hashes.add(compute_entry_hash(e))

    # 6️⃣ Filter duplicates from incoming entries
    new_week_objects = []
    skipped = 0
    added = 0

    for week_name, new_entries in week_data.items():
        filtered_entries = []
        for e in new_entries:
            h = compute_entry_hash(e)
            if h not in existing_hashes:
                filtered_entries.append(e)
                existing_hashes.add(h)
                added += 1
            else:
                skipped += 1

        if filtered_entries:
            new_week_objects.append({week_name: filtered_entries})

    if not new_week_objects:
        return {"success": True, "message": "No new unique data to save", "added": 0, "skipped": skipped}

    # 7️⃣ Merge with existing data
    if existing_doc and existing_data:
        merged_data = existing_data.copy()
        for new_week in new_week_objects:
            week_name = list(new_week.keys())[0]
            week_found = False
            for existing_week in merged_data:
                if week_name in existing_week:
                    existing_week[week_name].extend(new_week[week_name])
                    week_found = True
                    break
            if not week_found:
                merged_data.append(new_week)
        final_data = merged_data
    else:
        final_data = new_week_objects

    # 8️⃣ Recalculate totals
    total_hours = 0.0
    billable_hours = 0.0
    non_billable_hours = 0.0

    for week_obj in final_data:
        for _, entries_list in week_obj.items():
            for e in entries_list:
                try:
                    hrs = float(e.get("projectHours", 0))
                except:
                    hrs = 0.0
                total_hours += hrs
                if e.get("billable") == "Yes":
                    billable_hours += hrs
                elif e.get("billable") == "No":
                    non_billable_hours += hrs

    # 9️⃣ Prepare final payload safely (no AttributeError)
    first_entry = normalized_entries[0]
    update_payload = {
        "employeeId": emp_id,
        "employeeName": first_entry.get("employeeName", ""),
        "designation": first_entry.get("designation", ""),
        "gender": first_entry.get("gender", ""),
        "partner": first_entry.get("partner", ""),
        "reportingManager": first_entry.get("reportingManager", ""),
        "department": first_entry.get("department", ""),
        "Data": final_data,
        "hits": first_entry.get("hits", ""),
        "misses": first_entry.get("misses", ""),
        "feedback_hr": first_entry.get("feedback_hr", ""),
        "feedback_it": first_entry.get("feedback_it", ""),
        "feedback_crm": first_entry.get("feedback_crm", ""),
        "feedback_others": first_entry.get("feedback_others", ""),
        "updated_time": now_iso,
        "totalHours": round(total_hours, 2),
        "totalBillableHours": round(billable_hours, 2),
        "totalNonBillableHours": round(non_billable_hours, 2)
    }

    # 10️⃣ Insert or update document
    if existing_doc:
        timesheets_collection.update_one(
            {"employeeId": emp_id},
            {"$set": update_payload}
        )
    else:
        update_payload["created_time"] = now_iso
        timesheets_collection.insert_one(update_payload)

    # ✅ 11️⃣ Add employee to Pending collection under their manager
    try:
        emp_doc = employee_details_collection.find_one({"EmpID": emp_id})
        if emp_doc:
            reporting_emp_code = emp_doc.get("ReportingEmpCode", "").strip().upper()
            reporting_emp_name = emp_doc.get("ReportingEmpName", emp_doc.get("ManagerName", "Unknown"))

            if reporting_emp_code:
                # Remove from approved/rejected (safety)
                approved_collection.update_one(
                    {"ReportingEmpCode": reporting_emp_code},
                    {"$pull": {"EmployeesCodes": emp_id}}
                )
                rejected_collection.update_one(
                    {"ReportingEmpCode": reporting_emp_code},
                    {"$pull": {"EmployeesCodes": emp_id}}
                )
                # Add to pending
                add_or_create(pending_collection, reporting_emp_code, reporting_emp_name, emp_id)
                print(f"✅ Added {emp_id} under {reporting_emp_code} in Pending collection.")
            else:
                print(f"⚠️ No ReportingEmpCode found for {emp_id}")
        else:
            print(f"⚠️ Employee record not found for {emp_id}")
    except Exception as e:
        print(f"❌ Error updating Pending collection for {emp_id}: {e}")

    # 12️⃣ Return success response
    return {
        "success": True,
        "message": "Timesheet saved successfully",
        "added": added,
        "skipped": skipped,
        "total_entries": len(existing_hashes)
    }

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
        print(f"Processing Data for employeeId: {employee_id}, Data: {existing_data}")
        
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
        
        print(f"Returning flattened data: {flattened_data}")
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
                                    "client": update_data.client or entry.get("client", ""),
                                    "project": update_data.project or entry.get("project", ""),
                                    "projectCode": update_data.projectCode or entry.get("projectCode", ""),
                                    "reportingManagerEntry": update_data.reportingManagerEntry or entry.get("reportingManagerEntry", ""),
                                    "activity": update_data.activity or entry.get("activity", ""),
                                    "projectHours": update_data.projectHours or entry.get("projectHours", ""),
                                    "billable": update_data.billable or entry.get("billable", ""),
                                    "remarks": update_data.remarks or entry.get("remarks", ""),
                                    "updated_time": now_iso,
                                    "id": entry_id
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
        "client": entry.get("client", ""),
        "project": entry.get("project", ""),
        "projectCode": entry.get("projectCode", ""),
        "reportingManagerEntry": entry.get("reportingManagerEntry", ""),
        "activity": entry.get("activity", ""),
        "projectHours": entry.get("projectHours", ""),
        "billable": entry.get("billable", ""),
        "remarks": entry.get("remarks", "")
    }
    # Sort and JSON dump for consistent hashing
    sorted_fields = json.dumps(key_fields, sort_keys=True)
    return hashlib.sha256(sorted_fields.encode()).hexdigest()


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
                        if new_entries:  
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
        # data = {
        #     "employee_id": doc.get("employeeId"),
        #     "employee_name": doc.get("employeeName"),
        #     "designation": doc.get("designation"),
        #     "gender": doc.get("gender"),
        #     "partner": doc.get("partner"),
        #     "reporting_manager": doc.get("reportingManager")
        # }
        # print(data)
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
            "employee_id": doc.get("employeeId"),
            "employee_name": doc.get("employeeName"),
            "designation": doc.get("designation"),
            "gender": doc.get("gender"),
            "partner": doc.get("partner"),
            "reporting_manager": doc.get("reportingManager"),
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


# --- admin set payroll endpoint ---
from fastapi import Body
from calendar import monthrange

@app.post("/admin/set-payroll")
async def admin_set_payroll(month: int = Body(...), year: int = Body(...), par_status: str = Body("enable"), current_user: str = Depends(get_current_user)):
    """
    Admin saves payroll month/year.
    month: 1..12, year: full year
    Saves payroll_start and payroll_end as ISO strings.
    """
    try:
        # compute start (21st of given month) and end (20th of next month)
        start = datetime(year, month, 21)
        next_month = month + 1
        next_year = year
        if next_month == 13:
            next_month = 1
            next_year = year + 1
        end = datetime(next_year, next_month, 20)

        payload = {
            "par_status": par_status,
            "payroll_start": start.isoformat(),
            "payroll_end": end.isoformat(),
            "updated_by": current_user,
            "updated_time": datetime.utcnow().isoformat()
        }

        admin_details_collection.update_one({}, {"$set": payload}, upsert=True)

        return {"success": True, "message": "Payroll window updated", "start": payload["payroll_start"], "end": payload["payroll_end"]}
    except Exception as e:
        print("admin_set_payroll error:", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- replace your existing get-par-current-status body with this ---
@app.get("/get-par-current-status")
async def get_par_current_status(current_user: str = Depends(get_current_user)):
    """
    Returns par_status and payroll window start/end (ISO strings).
    """
    try:
        admin = admin_details_collection.find_one({}, {"par_status": 1, "payroll_start": 1, "payroll_end": 1})
        if not admin:
            return {"par_status": "disable"}
        return {
            "par_status": admin.get("par_status", "disable"),
            "start": admin.get("payroll_start"),
            "end": admin.get("payroll_end")
        }
    except Exception as e:
        print("Error fetching PAR status:", e)
        return {"par_status": "disable"}

# --------------------------------------------------------------
# APPROVE ALL (Pending → Approved  OR  Rejected → Approved)
# --------------------------------------------------------------
@app.post("/approve_all_timesheets")
async def approve_all_timesheets(
    reporting_emp_code: str = Body(...),           # manager code
    source: str = Body(...),                       # "Pending" or "Rejected"
    current_user: str = Depends(get_current_user)
):
    manager_code = reporting_emp_code.strip().upper()
    source = source.strip().title()                # make sure it is "Pending" or "Rejected"

    if source not in ["Pending", "Rejected"]:
        raise HTTPException(status_code=400, detail="source must be Pending or Rejected")

    # Choose the source collection
    source_coll = pending_collection if source == "Pending" else rejected_collection

    # 1. Get the manager document (contains the EmployeesCodes array)
    manager_doc = source_coll.find_one({"ReportingEmpCode": manager_code})

    if not manager_doc or not manager_doc.get("EmployeesCodes"):
        return {"success": True, "approved": 0, "message": "No employees to approve"}

    employees_to_approve = manager_doc["EmployeesCodes"]

    # 2. Remove them from BOTH pending AND rejected (just in case)
    pending_collection.update_one(
        {"ReportingEmpCode": manager_code},
        {"$pull": {"EmployeesCodes": {"$in": employees_to_approve}}}
    )
    rejected_collection.update_one(
        {"ReportingEmpCode": manager_code},
        {"$pull": {"EmployeesCodes": {"$in": employees_to_approve}}}
    )

    # 3. Add them to Approved collection
    manager_detail = employee_details_collection.find_one(
        {"ReportingEmpCode": manager_code}
    )
    manager_name = manager_detail.get("ReportingEmpName") if manager_detail else "Unknown"

    # Use the same helper you already have for single approve
    for emp_code in employees_to_approve:
        add_or_create(approved_collection, manager_code, manager_name, emp_code)

    return {
        "success": True,
        "approved": len(employees_to_approve),
        "message": f"{len(employees_to_approve)} employee(s) approved successfully."
    }

def generate_otp():
    return str(secrets.randbelow(900000) + 100000)  # 6 digit OTP

def hash_otp(otp: str):
    return hashlib.sha256(otp.encode()).hexdigest()

def send_otp_email(to_email, otp):
    url = "https://api.brevo.com/v3/smtp/email"

    payload = {
        "sender": {"name": "JHSTimesnap", "email": "vasugadde0203@gmail.com"},
        "to": [{"email": to_email}],
        "subject": "Your Password Reset OTP",
        "htmlContent": f"""
            <h2>Timesnap Password Reset</h2>
            <p>Your OTP for resetting your password is:</p>
            <h1 style="font-size: 32px; letter-spacing: 4px;">{otp}</h1>
            <p>This OTP is valid for 5 minutes.</p>
        """
    }

    headers = {
        "accept": "application/json",
        "api-key": os.getenv("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    return response

@app.post("/forgot-password")
async def forgot_password(empid: str = Body(...)):
    empid = empid.strip().upper()

    # get employee email
    emp = employee_details_collection.find_one({"EmpID": empid})
    if not emp:
        raise HTTPException(status_code=400, detail="Employee not found")

    email = emp.get("Email") or emp.get("Personal Email")
    print(f"Email from databae: {email}")
    if not email:
        raise HTTPException(status_code=400, detail="No email associated with this employee")

    # generate OTP
    otp = generate_otp()
    hashed = hash_otp(otp)
    expires = datetime.utcnow() + timedelta(minutes=5)

    # save OTP in DB
    forgot_password_otps_collection.update_one(
        {"empid": empid},
        {
            "$set": {
                "empid": empid,
                "otp_hash": hashed,
                "expires_at": expires,
                "created_at": datetime.utcnow()
            }
        },
        upsert=True
    )

    # send email
    response = send_otp_email(email, otp)
    if response.status_code != 201:
        raise HTTPException(status_code=500, detail="Failed to send OTP email")

    return {"success": True, "message": "OTP sent to registered email"}

@app.post("/verify-otp")
async def verify_otp(empid: str = Body(...), otp: str = Body(...)):
    empid = empid.strip().upper()
    record = forgot_password_otps_collection.find_one({"empid": empid})

    if not record:
        raise HTTPException(status_code=400, detail="OTP not requested")

    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="OTP expired")

    if hash_otp(otp) != record["otp_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    return {"success": True, "message": "OTP verified"}

@app.post("/reset-password")
async def reset_password(empid: str = Body(...), password: str = Body(...)):
    empid = empid.strip().upper()

    # validate password strength
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    hashed_password = pwd_context.hash(password)

    result = users_collection.update_one(
        {"empid": empid},
        {"$set": {"password": hashed_password}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Employee not registered")

    # delete OTP after use
    forgot_password_otps_collection.delete_one({"empid": empid})

    return {"success": True, "message": "Password updated successfully"}

# ----------------------------- Helper -----------------------------
def send_to_infobip(endpoint, payload):
    url = f"{INFOBIP_BASE_URL}{endpoint}"
    headers = {
        "Authorization": INFOBIP_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    res = requests.post(url, data=json.dumps(payload), headers=headers)
    print(f"\n=== Request to {endpoint} ===")
    print(json.dumps(payload, indent=2))
    print("Response:", res.status_code, res.text)
    return res

def send_slot_selection_list(to_number, name, selected_date, selected_shift, slots):
    to_number = "91" + to_number
    rows = [
        {
            "id": f"slot_{slot}_{selected_date}",
            "title": slot[:24],  # Direct from DB, max 24 chars
            "description": f"{selected_shift.title()} slot"
        }
        for slot in slots
    ]
    payload = {
        "from": WHATSAPP_SENDER,
        "to": to_number,
        "messageId": f"slot-{os.urandom(4).hex()}",
        "content": {
            "body": {"text": f"Hi {name} 👋\nSelect your preferred *{selected_shift}* slot for *{selected_date}*:"},
            "action": {"title": "Select Slot", "sections": [{"title": f"{selected_shift.title()} Slots", "rows": rows}]},
            "footer": {"text": "JHS Connect Bot"}
        }
    }
    send_to_infobip("/whatsapp/1/message/interactive/list", payload)

def send_date_selection_list(to_number, name, company, available_dates):
    to_number = "91" + to_number
    rows = [
        {"id": f"date_{date}", "title": date, "description": f"Interview available on {date}"}
        for date in available_dates[:5]
    ]
    payload = {
        "from": WHATSAPP_SENDER,
        "to": to_number,
        "messageId": f"date-{os.urandom(4).hex()}",
        "content": {
            "body": {"text": f"Hi {name} 👋\nPlease select your preferred *interview date* with {company}."},
            "action": {"title": "Select Date", "sections": [{"title": "Available Dates", "rows": rows}]},
            "footer": {"text": "JHS Connect Bot"}
        }
    }
    send_to_infobip("/whatsapp/1/message/interactive/list", payload)

def send_shift_selection_template(to_number, name, selected_date):
    to_number = "91" + to_number
    payload = {
        "messages": [{
            "from": WHATSAPP_SENDER,
            "to": to_number,
            "content": {
                "templateName": "interview_shift_selection",
                "language": "en_US",
                "templateData": {
                    "body": {"placeholders": [name, selected_date]},
                    "buttons": [
                        {"type": "QUICK_REPLY", "parameter": "Morning"},
                        {"type": "QUICK_REPLY", "parameter": "Afternoon"}
                    ]
                }
            }
        }]
    }
    send_to_infobip("/whatsapp/1/message/template", payload)

def remove_slot_from_global(slots_collection, hr_email, date, slot):
    doc = slots_collection.find_one({"hr_email": hr_email})
    if not doc:
        return False
    removed = False
    for d in doc["available_dates"]:
        if d["date"] == date:
            for sh, sl in d["shifts"].items():
                if slot in sl:
                    sl.remove(slot)
                    removed = True
                    break
            if removed:
                break
    if removed:
        slots_collection.update_one({"hr_email": hr_email}, {"$set": {"available_dates": doc["available_dates"]}})
    return removed

def send_confirmation(to_number, name, role, selected_date, slot):
    to_number = "91" + to_number
    start_time = slot.split(' - ')[0]
    end_time = slot.split(' - ')[1]
    payload = {
        "messages": [{
            "from": WHATSAPP_SENDER,
            "to": to_number,
            "content": {
                "templateName": "interview_scheduled_message",
                "language": "en_US",
                "templateData": {
                    "body": {"placeholders": [name, role, selected_date, start_time, end_time]}
                }
            }
        }]
    }
    send_to_infobip("/whatsapp/1/message/template", payload)
    send_pre_interview_form(to_number)
    
def send_pre_interview_form(to_number):
    to_number = "91" + to_number
    payload = {
        "from": WHATSAPP_SENDER,
        "to": to_number,
        "messageId": f"form-{os.urandom(4).hex()}",
        "content": {
            "body": {"text": "📋 Before attending your interview, please fill out this *Pre-Interview Form* 👇"},
            "action": {"displayText": "Open Form", "url": PRE_INTERVIEW_FORM_URL}
        }
    }
    send_to_infobip("/whatsapp/1/message/interactive/url-button", payload)

def get_current_slots(slots_collection, hr_email, date, shift):
    doc = slots_collection.find_one({"hr_email": hr_email})
    if not doc:
        return []
    for d in doc["available_dates"]:
        if d["date"] == date:
            return d["shifts"].get(shift, [])
    return []

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("\n=== Incoming Webhook ===")
    print(json.dumps(data, indent=2))
    
    client = MongoClient(os.getenv("MONGO_CONNECTION_STRING"))  # Local MongoDB for development
    db = client["production_TCD"]
    resumes_collection = db["resumes"]
    matched_resumes_collection = db["matched_resumes"]
    interviews_collection = db["interviews"]
    messaged_collection = db["Messaged"]
    scheduled_collection = db["Scheduled"]
    users_collection = db["users"]
    availability_collection = db["availability"]
    conversations_collection = db["Conversations"]
    slots_collection = db['Slots']
    selected_collection = db['Selected']
    rejected_collection = db['Rejected'] 
        
    # Helpers for global slots
    def get_current_available_dates(hr_email):
        doc = slots_collection.find_one({"hr_email": hr_email})
        if not doc:
            return []
        return [d["date"] for d in doc["available_dates"] if any(len(s) > 0 for s in d["shifts"].values())]


    try:
        result = data["results"][0]
        from_number = result.get("from", "")
        from_number = from_number[2:]  # Remove '91'
        message = result.get("message", {})
        msg_type = message.get("type", "").upper()

        # Save candidate message
        conv = conversations_collection.find_one({"candidate_number": from_number})
        if conv:
            conversations_collection.update_one(
                {"candidate_number": from_number},
                {"$push": {
                    "messages": {
                        "sender": "candidate",
                        "content": str(message),
                        "timestamp": datetime.utcnow()
                    }
                }}
            )

        # --- 1. TEXT: Yes / No ---
        if "text" in message:
            txt = message["text"].strip().lower()
            record = messaged_collection.find_one({"candidate_number": from_number})
            if not record:
                return {"status": "no record"}

            if txt == "yes":
                dates = get_current_available_dates(record["hr_email"])
                if not dates:
                    send_to_infobip("/whatsapp/1/message/text", {
                        "from": WHATSAPP_SENDER,
                        "to": '91' + from_number,
                        "content": {"text": "Sorry, no interview dates available at the moment."}
                    })
                    return {"status": "no dates"}

                send_date_selection_list(from_number, record["candidate_name"], record["company"], dates)
                messaged_collection.update_one({"candidate_number": from_number}, {"$set": {"status": "Replied"}})
                return {"status": "date list sent"}

            elif txt == "no":
                send_to_infobip("/whatsapp/1/message/text", {
                    "from": WHATSAPP_SENDER,
                    "to": '91' + from_number,
                    "content": {"text": "Thank you. Better luck next time!"}
                })
                messaged_collection.update_one({"candidate_number": from_number}, {"$set": {"status": "Replied"}})
                return {"status": "rejected"}

        # --- 2. LIST REPLY: Date Selection ---
        if msg_type == "INTERACTIVE_LIST_REPLY":
            reply_id = message.get("id", "")
            record = messaged_collection.find_one({"candidate_number": from_number})
            if not record:
                return {"status": "no record"}

            if reply_id.startswith("date_"):
                selected_date = reply_id.split("_", 1)[1]
                # STORE SELECTED DATE
                messaged_collection.update_one(
                    {"candidate_number": from_number},
                    {"$set": {"selected_date": selected_date}}
                )
                send_shift_selection_template(from_number, record["candidate_name"], selected_date)
                return {"status": "shift selection sent"}

            # SLOT SELECTION
            elif reply_id.startswith("slot_"):
                parts = reply_id.split("_", 2)
                if len(parts) != 3:
                    return {"status": "invalid slot id"}
                _, slot, selected_date = parts

                if remove_slot_from_global(slots_collection, record["hr_email"], selected_date, slot):
                    send_confirmation(
                        from_number,
                        record["candidate_name"],
                        record["role"],
                        selected_date,
                        slot
                    )

                    scheduled_collection.insert_one({
                        "hr_email": record["hr_email"],
                        "candidate_number": from_number,
                        "candidate_name": record["candidate_name"],
                        "candidate_id": record.get("candidate_id"), 
                        "role": record["role"],
                        "date": selected_date,
                        "slot": slot,
                        "status": "Scheduled",
                        "scheduled_at": datetime.utcnow()
                    })

                    # Delete from messaged
                    messaged_collection.delete_one({"candidate_number": from_number})

                    return {"status": "interview scheduled"}
                else:
                    send_to_infobip("/whatsapp/1/message/text", {
                        "from": WHATSAPP_SENDER,
                        "to": '91' + from_number,
                        "content": {"text": "Sorry, the selected slot is no longer available. Please choose another."}
                    })
                    # Resend shift selection
                    send_shift_selection_template(from_number, record["candidate_name"], selected_date)
                    return {"status": "slot taken"}

        # --- 3. BUTTON REPLY: Morning / Afternoon ---
        if msg_type == "BUTTON":
            payload_text = message.get("payload", "").strip()
            print("Payload:", payload_text)

            if payload_text in ["Morning", "Afternoon"]:
                record = messaged_collection.find_one({"candidate_number": from_number})
                if not record:
                    return {"status": "no record"}

                selected_date = record.get("selected_date")
                if not selected_date:
                    send_to_infobip("/whatsapp/1/message/text", {
                        "from": WHATSAPP_SENDER,
                        "to": '91' + from_number,
                        "content": {"text": "Please select a date first."}
                    })
                    return {"status": "no date selected"}

                selected_shift = payload_text.lower()
                slots = get_current_slots(slots_collection, record["hr_email"], selected_date, selected_shift)

                if not slots:
                    send_to_infobip("/whatsapp/1/message/text", {
                        "from": WHATSAPP_SENDER,
                        "to": '91' + from_number,
                        "content": {"text": f"No {selected_shift} slots available for {selected_date}."}
                    })
                    return {"status": "no slots"}

                send_slot_selection_list(
                    from_number,
                    record["candidate_name"],
                    selected_date,
                    selected_shift,
                    slots
                )
                return {"status": "slot list sent"}

    except Exception as e:
        print("Webhook Error:", e)
        return {"error": str(e)}

    return {"status": "ignored"}

@app.post("/")
async def root_fallback(request: Request):
    print("\n=== Incoming POST on root ===")
    return await webhook(request)

# @app.get("/get_employee_projects/{employee_id}")
# async def get_employee_projects(employee_id: str, current_user: str = Depends(get_current_user)):
#     """
#     Fetch projects filtered by employee's partner code.
#     Returns unique clients, projects, and project codes.
#     """
#     if employee_id != current_user:
#         raise HTTPException(status_code=403, detail="Unauthorized access")
    
#     try:
#         # Get employee details
#         employee = employee_details_collection.find_one({"EmpID": employee_id})
#         if not employee:
#             return {"clients": [], "projects": [], "project_codes": []}
        
#         partner_emp_code = employee.get("PartnerEmpCode", "").strip().upper()
#         if not partner_emp_code:
#             return {"clients": [], "projects": [], "project_codes": []}
        
#         # Fetch all projects for this partner
#         projects = list(db["Projects"].find({"partner_emp_code": partner_emp_code}))
        
#         # Extract unique values
#         clients = list(set([p.get("client_name", "") for p in projects if p.get("client_name")]))
#         project_names = list(set([p.get("project_name", "") for p in projects if p.get("project_name")]))
#         project_codes = list(set([p.get("project_code", "") for p in projects if p.get("project_code")]))
        
#         # Sort alphabetically
#         clients.sort()
#         project_names.sort()
#         project_codes.sort()
        
#         return {
#             "clients": clients,
#             "projects": project_names,
#             "project_codes": project_codes
#         }
    
#     except Exception as e:
#         print(f"Error fetching employee projects: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_employee_projects/{employee_id}")
async def get_employee_projects(employee_id: str, current_user: str = Depends(get_current_user)):
    """
    Fetch projects filtered by employee's partner code.
    Returns clients with their associated projects and project codes.
    """
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized access")
    
    try:
        # Get employee details
        employee = employee_details_collection.find_one({"EmpID": employee_id})
        if not employee:
            return {"clients": [], "projects_by_client": {}}
        
        partner_emp_code = employee.get("PartnerEmpCode", "").strip().upper()
        if not partner_emp_code:
            return {"clients": [], "projects_by_client": {}}
        
        # Fetch all projects for this partner
        projects = list(db["Projects"].find({"partner_emp_code": partner_emp_code}))
        
        # Build nested structure: client -> projects with codes
        projects_by_client = {}
        
        for p in projects:
            client = p.get("client_name", "").strip()
            proj_name = p.get("project_name", "").strip()
            proj_code = p.get("project_code", "").strip()
            
            if not client or not proj_name or not proj_code:
                continue
            
            if client not in projects_by_client:
                projects_by_client[client] = []
            
            # Avoid duplicates
            if not any(item["project_name"] == proj_name for item in projects_by_client[client]):
                projects_by_client[client].append({
                    "project_name": proj_name,
                    "project_code": proj_code
                })
        
        # Sort clients alphabetically
        clients = sorted(projects_by_client.keys())
        
        # Sort projects within each client
        for client in projects_by_client:
            projects_by_client[client].sort(key=lambda x: x["project_name"])
        
        return {
            "clients": clients,
            "projects_by_client": projects_by_client
        }
    
    except Exception as e:
        print(f"Error fetching employee projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    