# main.py
"""
Entry point — mounts static files and includes all module routers.
Shared routes (login, register, session, admin) live here.
Module-specific routes live in their own router files.
"""
import os
import re
import json
import secrets
from datetime import datetime, timedelta
import jwt
import requests
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, status, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional

load_dotenv()

# ── internal imports ──────────────────────────────────────────────────────────
from backend.database import (
    sessions_collection,
    employee_details_collection,
    users_collection,
    admin_details_collection,
    forgot_password_otps_collection,
)
from backend.auth import (
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    oauth2_scheme,
)
from backend.timesheet.router import router as timesheet_router
from backend.appraisal.router  import router as appraisal_router

# ── admin router (keep existing admin.py) ────────────────────────────────────
from backend.timesheet.timesheet_admin import admin_router   # your existing admin.py

# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="JHS Platform API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── include routers ───────────────────────────────────────────────────────────
app.include_router(timesheet_router)   # prefix: /timesheet
app.include_router(appraisal_router)   # prefix: /appraisal
app.include_router(admin_router)       # prefix: /admin  (from existing admin.py)

# ── static files ──────────────────────────────────────────────────────────────
# Root static folder (login, register, modules, shared assets)
static_root = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_root), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto",
                           bcrypt__ident="2b", bcrypt__rounds=12)


# ─────────────────────────────────────────────────────────────────────────────
# Shared Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    empid: str
    password: str

class VerifyUserRequest(BaseModel):
    empid: str
    verification_code: str

class ResetPasswordRequest(BaseModel):
    empid: str
    new_password: str


# ─────────────────────────────────────────────────────────────────────────────
# Page routes  (serve HTML files)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def root():
    return FileResponse(os.path.join(static_root, "login.html"))

@app.get("/login", response_class=FileResponse)
async def login_page():
    return FileResponse(os.path.join(static_root, "login.html"))

@app.get("/modules", response_class=FileResponse)
async def modules_page():
    """Module selector — shown right after login."""
    return FileResponse(os.path.join(static_root, "modules.html"))

@app.get("/timesheet", response_class=FileResponse)
async def timesheet_page():
    """Serve the timesheet SPA."""
    return FileResponse(os.path.join(static_root, "timesheet", "index.html"))

@app.get("/appraisal", response_class=FileResponse)
async def appraisal_page():
    """Serve the appraisal SPA."""
    return FileResponse(os.path.join(static_root, "appraisal", "index.html"))

# Keep /dashboard pointing to timesheet for backward compatibility
@app.get("/dashboard", response_class=FileResponse)
async def dashboard_page():
    return FileResponse(os.path.join(static_root, "timesheet", "index.html"))

@app.get("/forgot-password", response_class=FileResponse)
async def forgot_password_page():
    return FileResponse(os.path.join(static_root, "forgot_password.html"))


# ─────────────────────────────────────────────────────────────────────────────
# Auth API routes  (shared by all modules)
# ─────────────────────────────────────────────────────────────────────────────

def _validate_password(password: str):
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(400, "Password must contain an uppercase letter")
    if not re.search(r'[a-z]', password):
        raise HTTPException(400, "Password must contain a lowercase letter")
    if not re.search(r'\d', password):
        raise HTTPException(400, "Password must contain a number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise HTTPException(400, "Password must contain a special character")


@app.post("/register")
async def register(request: RegisterRequest):
    empid = request.empid.strip().upper()
    _validate_password(request.password)
    print(employee_details_collection)
    if not employee_details_collection.find_one({"EmpID": empid}):
        raise HTTPException(400, "Employee does not exist")
    if users_collection.find_one({"empid": empid}):
        raise HTTPException(400, "User already registered")

    users_collection.insert_one({"empid": empid, "password": pwd_context.hash(request.password)})
    return {"success": True, "detail": "Registration successful. Please login."}


@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    empid    = form_data.username.strip().upper()
    password = form_data.password

    user = users_collection.find_one({"empid": empid})
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Employee Code or Password")

    expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token   = create_access_token({"sub": empid}, expires)

    sessions_collection.insert_one({
        "employeeId": empid,
        "token": token,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + expires,
    })
    return {"success": True, "access_token": token, "token_type": "bearer",
            "employeeId": empid, "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@app.post("/verify_session")
async def verify_session(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token       = credentials.credentials
    employee_id = await get_current_user(credentials)
    session     = sessions_collection.find_one({"token": token, "employeeId": employee_id})
    if not session or session["expires_at"] < datetime.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return {"message": "Session valid"}


@app.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    sessions_collection.delete_one({"token": credentials.credentials})
    return {"message": "Logged out"}


# ─────────────────────────────────────────────────────────────────────────────
# Forgot-password flow  (shared)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_otp() -> str:
    return str(secrets.randbelow(900000) + 100000)

def _hash_otp(otp: str) -> str:
    import hashlib
    return hashlib.sha256(otp.encode()).hexdigest()

def _send_otp_email(to_email: str, otp: str):
    BREVO_API_KEY = os.getenv("BREVO_API_KEY")
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "JHSTimesnap", "email": "vasugadde0203@gmail.com"},
        "to": [{"email": to_email}],
        "subject": "Your Password Reset OTP",
        "htmlContent": f"<h2>Timesnap Password Reset</h2><p>Your OTP:</p><h1>{otp}</h1><p>Valid for 5 minutes.</p>",
    }
    headers = {"accept": "application/json", "api-key": BREVO_API_KEY, "content-type": "application/json"}
    return requests.post(url, json=payload, headers=headers)

@app.post("/forgot-password")
async def forgot_password(empid: str = Body(...)):
    empid = empid.strip().upper()
    emp   = employee_details_collection.find_one({"EmpID": empid})
    if not emp:
        raise HTTPException(400, "Employee not found")

    email = emp.get("Email") or emp.get("Personal Email")
    if not email:
        raise HTTPException(400, "No email on record for this employee")

    otp     = _generate_otp()
    expires = datetime.utcnow() + timedelta(minutes=5)
    forgot_password_otps_collection.update_one(
        {"empid": empid},
        {"$set": {"empid": empid, "otp_hash": _hash_otp(otp), "expires_at": expires, "created_at": datetime.utcnow()}},
        upsert=True,
    )
    res = _send_otp_email(email, otp)
    if res.status_code != 201:
        raise HTTPException(500, "Failed to send OTP email")
    return {"success": True, "message": "OTP sent to registered email"}


@app.post("/verify-otp")
async def verify_otp(empid: str = Body(...), otp: str = Body(...)):
    empid  = empid.strip().upper()
    record = forgot_password_otps_collection.find_one({"empid": empid})
    if not record:
        raise HTTPException(400, "OTP not requested")
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(400, "OTP expired")
    if _hash_otp(otp) != record["otp_hash"]:
        raise HTTPException(400, "Invalid OTP")
    return {"success": True, "message": "OTP verified"}

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


# ─────────────────────────────────────────────────────────────────────────────
# PAR / Payroll status  (shared — used by timesheet frontend)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/get-par-current-status")
async def get_par_current_status(current_user: str = Depends(get_current_user)):
    admin = admin_details_collection.find_one({}, {"par_status": 1, "payroll_start": 1, "payroll_end": 1})
    if not admin:
        return {"par_status": "disable"}
    return {
        "par_status": admin.get("par_status", "disable"),
        "start": admin.get("payroll_start"),
        "end":   admin.get("payroll_end"),
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# Legacy URL aliases  (so old bookmarks / existing JS still works)
# Map old flat routes → new prefixed routes via simple re-export
# ─────────────────────────────────────────────────────────────────────────────

from backend.timesheet.router import (
    save_timesheets,
    get_timesheets,
    update_timesheet,
    delete_timesheet,
    get_employees,
    get_clients,
    get_employee_projects,
    check_reporting_manager,
    get_employee_timesheet_for_manager,
    get_pending,
    get_approved,
    get_rejected,
    approve_timesheet,
    reject_timesheet,
    approve_all,
)

# Re-register old URLs so existing script.js calls still work
app.add_api_route("/save_timesheets",                          save_timesheets,                    methods=["POST"])
app.add_api_route("/timesheets/{employee_id}",                  get_timesheets,                     methods=["GET"])
app.add_api_route("/update_timesheet/{employee_id}/{entry_id}", update_timesheet,                   methods=["PUT"])
app.add_api_route("/delete_timesheet/{employee_id}/{entry_id}", delete_timesheet,                   methods=["DELETE"])
app.add_api_route("/employees",                                 get_employees,                      methods=["GET"])
app.add_api_route("/clients",                                   get_clients,                        methods=["GET"])
app.add_api_route("/get_employee_projects/{employee_id}",       get_employee_projects,              methods=["GET"])
app.add_api_route("/check_reporting_manager/{emp_code}",        check_reporting_manager,            methods=["GET"])
app.add_api_route("/get_timesheet/{employee_id}",               get_employee_timesheet_for_manager, methods=["GET"])
app.add_api_route("/get_pending_employees/{reporting_emp_code}", get_pending,                       methods=["GET"])
app.add_api_route("/get_approved_employees/{reporting_emp_code}", get_approved,                     methods=["GET"])
app.add_api_route("/get_rejected_employees/{reporting_emp_code}", get_rejected,                     methods=["GET"])
app.add_api_route("/approve_timesheet",                         approve_timesheet,                  methods=["POST"])
app.add_api_route("/reject_timesheet",                          reject_timesheet,                   methods=["POST"])
app.add_api_route("/approve_all_timesheets",                    approve_all,                        methods=["POST"])