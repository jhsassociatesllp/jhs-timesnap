# main.py  —  JHS Platform API  v3.0
"""
Entry point — mounts static files and includes all module routers.
Auth update: login accepts Employee Code OR JHS Email (either match = success).
Session stores both empid & email.
"""
import os, re, json, secrets
from datetime import datetime, timedelta
import jwt, requests
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
    module_admin_collection,
    payroll_cycles_collection,
    timesheet_temp_collection,
)

from backend.auth import (
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    oauth2_scheme,
)
from backend.timesheet.router          import router as timesheet_router
from backend.appraisal.router          import router as appraisal_router
from backend.quality_audit.router      import router as quality_audit_router   # ← NEW
from backend.timesheet.timesheet_admin import admin_router
from backend.hr_policy_quiz.router     import router as hr_quiz_router         # ← NEW
from backend.employee_declaration.router import router as employee_declaration_router  # ← NEW

# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="JHS Platform API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── Cache-Control middleware ──────────────────────────────────────────────────
# Forces the browser to NEVER store any app file in cache.
# Every JS, CSS, HTML request always fetches the latest from the server.
_NO_STORE_EXTENSIONS = (".js", ".css", ".html")
_NO_STORE_PATHS      = {"/", "/login", "/modules", "/timesheet", "/appraisal",
                         "/quality-audit", "/dashboard", "/forgot-password",
                         "/control-panel", "/admin-dashboard",
                         "/hr-quiz", "/hr-quiz/", "/hr-quiz/candidate-login",
                         "/hr-quiz/hr-dashboard", "/hr-quiz/quiz",
                         "/employee-declaration", "/employee-declaration/admin"}

@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path

    if (any(path.endswith(ext) for ext in _NO_STORE_EXTENSIONS)
            or path in _NO_STORE_PATHS):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]        = "no-cache"
        response.headers["Expires"]       = "0"

    return response

app.include_router(timesheet_router)
app.include_router(appraisal_router)
app.include_router(quality_audit_router)   # prefix: /quality-audit
app.include_router(admin_router)
app.include_router(hr_quiz_router)         # prefix: /hr-quiz
app.include_router(employee_declaration_router)  # prefix: /employee-declaration

static_root = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_root), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto",
                           bcrypt__ident="2b", bcrypt__rounds=12)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
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
# Page routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def root():
    return FileResponse(os.path.join(static_root, "login.html"))

@app.get("/login", response_class=FileResponse)
async def login_page():
    return FileResponse(os.path.join(static_root, "login.html"))

@app.get("/modules", response_class=FileResponse)
async def modules_page():
    return FileResponse(os.path.join(static_root, "modules.html"))

@app.get("/timesheet", response_class=FileResponse)
async def timesheet_page():
    return FileResponse(os.path.join(static_root, "timesheet", "index.html"))

@app.get("/appraisal", response_class=FileResponse)
async def appraisal_page():
    return FileResponse(os.path.join(static_root, "appraisal", "index.html"))

@app.get("/quality-audit", response_class=FileResponse)         # ← NEW
async def quality_audit_page():
    return FileResponse(os.path.join(static_root, "quality_audit", "index.html"))

@app.get("/hr-quiz", response_class=FileResponse)                # ← NEW
async def hr_quiz_landing():
    return FileResponse(os.path.join(static_root, "hr_policy_quiz", "index.html"))

@app.get("/hr-quiz/", response_class=FileResponse)                # ← NEW
async def hr_quiz_landing_slash():
    return FileResponse(os.path.join(static_root, "hr_policy_quiz", "index.html"))

@app.get("/hr-quiz/candidate-login", response_class=FileResponse)  # ← NEW
async def hr_quiz_candidate_login():
    return FileResponse(os.path.join(static_root, "hr_policy_quiz", "candidate-login.html"))

@app.get("/hr-quiz/hr-dashboard", response_class=FileResponse)    # ← NEW
async def hr_quiz_hr_dashboard():
    return FileResponse(os.path.join(static_root, "hr_policy_quiz", "hr-dashboard.html"))

@app.get("/hr-quiz/quiz", response_class=FileResponse)            # ← NEW
async def hr_quiz_quiz_page():
    return FileResponse(os.path.join(static_root, "hr_policy_quiz", "quiz.html"))

@app.get("/employee-declaration", response_class=FileResponse)   # ← NEW
async def employee_declaration_page():
    return FileResponse(os.path.join(static_root, "employee_declaration", "index.html"))

@app.get("/employee-declaration/admin", response_class=FileResponse)   # ← NEW
async def employee_declaration_admin_page():
    return FileResponse(os.path.join(static_root, "employee_declaration", "admin.html"))

@app.get("/dashboard", response_class=FileResponse)
async def dashboard_page():
    return FileResponse(os.path.join(static_root, "timesheet", "index.html"))

@app.get("/forgot-password", response_class=FileResponse)
async def forgot_password_page():
    return FileResponse(os.path.join(static_root, "forgot_password.html"))

@app.get("/control-panel", response_class=FileResponse)
async def control_panel_page():
    return FileResponse(os.path.join(static_root, "control_panel.html"))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
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


def _resolve_login_input(raw_input: str):
    """
    Given whatever the user typed (emp code OR email), return (empid, email, user_doc).
    Raises HTTPException if not found.
    """
    raw = raw_input.strip()

    # Case 1 — looks like an email
    if "@" in raw:
        email_lower = raw.lower()
        # Find employee by JHS email field
        emp = employee_details_collection.find_one({
            "$or": [
                {"EMail":     {"$regex": f"^{re.escape(email_lower)}$", "$options": "i"}},
                {"JHS Email": {"$regex": f"^{re.escape(email_lower)}$", "$options": "i"}},
            ]
        })
        if not emp:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No account found for this email")
        empid = emp.get("EmpID", "").strip().upper()
        email = email_lower
        user_doc = users_collection.find_one({"empid": empid})
        return empid, email, user_doc

    # Case 2 — emp code
    empid = raw.upper()
    emp = employee_details_collection.find_one({"EmpID": empid})
    email = ""
    if emp:
        email = (emp.get("Email") or emp.get("JHS Email") or "").lower().strip()
    user_doc = users_collection.find_one({"empid": empid})
    return empid, email, user_doc


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/register")
async def register(request: RegisterRequest):
    empid = request.empid.strip().upper()
    _validate_password(request.password)
    if not employee_details_collection.find_one({"EmpID": empid}):
        raise HTTPException(400, "Employee does not exist")
    if users_collection.find_one({"empid": empid}):
        raise HTTPException(400, "User already registered")
    users_collection.insert_one({"empid": empid, "password": pwd_context.hash(request.password)})
    return {"success": True, "detail": "Registration successful. Please login."}


@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Accepts Employee Code OR JHS Email in the username field.
    Either match triggers auth. Session stores both empid & email.
    """
    raw_input = form_data.username
    password  = form_data.password

    try:
        empid, email, user_doc = _resolve_login_input(raw_input)
    except HTTPException:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Employee Code / Email or Password")

    if not user_doc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not registered. Please register first.")

    if not pwd_context.verify(password, user_doc["password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Employee Code / Email or Password")

    expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token   = create_access_token({"sub": empid}, expires)

    sessions_collection.insert_one({
        "employeeId": empid,
        "email":      email,
        "token":      token,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + expires,
    })

    return {
        "success":       True,
        "access_token":  token,
        "token_type":    "bearer",
        "employeeId":    empid,
        "email":         email,
        "expires_in":    ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }

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
# Forgot-password flow
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
        "sender":      {"name": "JHSTimesnap", "email": "vasugadde0203@gmail.com"},
        "to":          [{"email": to_email}],
        "subject":     "Your Password Reset OTP",
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
    try:
        empid = request.empid.strip().upper()
        verification_code = request.verification_code.strip()
        if len(verification_code) != 10:
            raise HTTPException(400, "Verification code must be exactly 10 digits")
        employee = employee_details_collection.find_one({"EmpID": empid})
        if not employee:
            raise HTTPException(404, "Employee not found")
        input_date   = verification_code[0:2]
        input_year   = verification_code[2:6]
        input_mobile = verification_code[6:10]
        emp_dob    = employee.get("DOB") or employee.get("Date of Birth") or employee.get("DateOfBirth")
        emp_mobile = employee.get("Mobile") or employee.get("Personal Mobile") or employee.get("MobileNumber")
        if not emp_dob or not emp_mobile:
            raise HTTPException(400, "Employee DOB or Mobile number not found in database")
        actual_date = actual_year = None
        for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                parsed = datetime.strptime(str(emp_dob), fmt)
                actual_date = parsed.strftime("%d")
                actual_year = parsed.strftime("%Y")
                break
            except:
                continue
        if not actual_date:
            raise HTTPException(500, "Unable to parse employee date of birth")
        mob_str = str(emp_mobile).replace(" ","").replace("-","").replace("+","")
        if len(mob_str) > 10:
            mob_str = mob_str[-10:]
        actual_mobile = mob_str[:4]
        if input_date != actual_date or input_year != actual_year or input_mobile != actual_mobile:
            raise HTTPException(401, "Verification failed. Invalid verification code.")
        return {"success": True, "message": "Verification successful", "empid": empid}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Server error: {str(e)}")


@app.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    try:
        empid = request.empid.strip().upper()
        _validate_password(request.new_password)
        user = users_collection.find_one({"empid": empid})
        if not user:
            raise HTTPException(404, "User not found. Please register first.")
        result = users_collection.update_one(
            {"empid": empid},
            {"$set": {"password": pwd_context.hash(request.new_password), "password_updated_at": datetime.utcnow()}}
        )
        if result.modified_count == 0:
            raise HTTPException(500, "Failed to update password")
        return {"success": True, "message": "Password reset successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Server error: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Shared endpoints
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

@app.get("/get-module-access")
async def get_module_access(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    print(f"[ModuleAccess] Looking up empid: '{empid}' (len={len(empid)})")
    doc = module_admin_collection.find_one({"empid": empid})
    print(f"[ModuleAccess] Found doc: {doc}")
    if not doc:
        # Also try case-insensitive search to help debug
        doc_ci = module_admin_collection.find_one({"empid": {"$regex": f"^{empid}$", "$options": "i"}})
        print(f"[ModuleAccess] Case-insensitive fallback: {doc_ci}")
        if doc_ci:
            modules = doc_ci.get("modules", [])
            print(f"[ModuleAccess] Using case-insensitive match, modules: {modules}")
            return {"modules": modules, "is_admin": len(modules) > 0}
        return {"modules": [], "is_admin": False}
    modules = doc.get("modules", [])
    print(f"[ModuleAccess] Returning modules: {modules}")
    return {"modules": modules, "is_admin": len(modules) > 0}


class ModuleAccessRequest(BaseModel):
    empid: str
    modules: list


@app.post("/set-module-access")
async def set_module_access(
    request: ModuleAccessRequest,
    current_user: str = Depends(get_current_user),
):
    """
    Set module admin access for a user.
    Only callable by users who themselves have all-module access (super admin).
    modules: list of strings from ["timesheet", "quality_audit", "kra"]
    """
    # Check caller is a super admin (has all 3 modules)
    caller_doc = module_admin_collection.find_one({"empid": current_user.strip().upper()})
    caller_modules = caller_doc.get("modules", []) if caller_doc else []
    if set(["timesheet", "quality_audit", "kra"]) != set(caller_modules):
        raise HTTPException(403, "Only super admins can assign module access")

    valid = {"timesheet", "quality_audit", "kra"}
    modules = [m for m in request.modules if m in valid]
    empid = request.empid.strip().upper()

    module_admin_collection.update_one(
        {"empid": empid},
        {"$set": {"empid": empid, "modules": modules}},
        upsert=True,
    )
    return {"success": True, "empid": empid, "modules": modules}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# Payroll Cycle Management
# ─────────────────────────────────────────────────────────────────────────────

class PayrollCycleRequest(BaseModel):
    cycle_label: str          # e.g. "Apr-May 2025"
    start_date: str           # "2025-04-21"
    end_date: str             # "2025-05-20"
    deadline_date: str        # "2025-05-23"
    deadline_time: str        # "18:30"  (24h IST)
    status: str               # "live" | "upcoming" | "closed"
    show_lunch_travel: bool = True  # False = hide Lunch Time & Travel Time fields


def _cycle_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    # Ensure show_lunch_travel has a default
    doc.setdefault("show_lunch_travel", True)
    return doc


def _is_timesheet_admin(empid: str) -> bool:
    doc = module_admin_collection.find_one({"empid": empid.strip().upper()})
    if not doc:
        doc = module_admin_collection.find_one(
            {"empid": {"$regex": f"^{empid.strip().upper()}$", "$options": "i"}}
        )
    if doc and "timesheet" in doc.get("modules", []):
        return True
    # Also allow legacy admin_details users
    return bool(admin_details_collection.find_one({"userid": empid.strip().upper()}))


@app.get("/payroll-cycles")
async def list_payroll_cycles(current_user: str = Depends(get_current_user)):
    """Admin: list all payroll cycles."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    cycles = list(payroll_cycles_collection.find({}).sort("start_date", -1))
    return {"cycles": [_cycle_to_dict(c) for c in cycles]}


@app.post("/payroll-cycles")
async def create_payroll_cycle(
    req: PayrollCycleRequest,
    current_user: str = Depends(get_current_user),
):
    """Admin: create a new payroll cycle. Multiple cycles can be live simultaneously."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    if req.status not in ("live", "upcoming", "closed"):
        raise HTTPException(400, "status must be live, upcoming, or closed")
    doc = {
        "cycle_label": req.cycle_label,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "deadline_date": req.deadline_date,
        "deadline_time": req.deadline_time,
        "status": req.status,
        "show_lunch_travel": req.show_lunch_travel,
        "created_at": datetime.utcnow(),
        "created_by": current_user,
    }
    result = payroll_cycles_collection.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return {"success": True, "cycle": doc}


@app.put("/payroll-cycles/{cycle_id}")
async def update_payroll_cycle(
    cycle_id: str,
    req: PayrollCycleRequest,
    current_user: str = Depends(get_current_user),
):
    """Admin: update a payroll cycle. Multiple cycles can be live simultaneously."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    if req.status not in ("live", "upcoming", "closed"):
        raise HTTPException(400, "status must be live, upcoming, or closed")
    try:
        from bson import ObjectId
        oid = ObjectId(cycle_id)
    except Exception:
        raise HTTPException(400, "Invalid cycle ID")
    payroll_cycles_collection.update_one(
        {"_id": oid},
        {"$set": {
            "cycle_label": req.cycle_label,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "deadline_date": req.deadline_date,
            "deadline_time": req.deadline_time,
            "status": req.status,
            "show_lunch_travel": req.show_lunch_travel,
            "updated_at": datetime.utcnow(),
            "updated_by": current_user,
        }}
    )
    return {"success": True}

class ActiveApprovalPayrollRequest(BaseModel):
    cycle_id: str  # pass empty string "" to clear (show all live cycles)


@app.post("/admin/set-active-approval-payroll")
async def set_active_approval_payroll(
    req: ActiveApprovalPayrollRequest,
    current_user: str = Depends(get_current_user),
):
    """Admin: set which payroll cycle TLs/Managers see in approval screens."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")

    if req.cycle_id:
        try:
            from bson import ObjectId
            oid = ObjectId(req.cycle_id)
        except Exception:
            raise HTTPException(400, "Invalid cycle ID")
        cycle = payroll_cycles_collection.find_one({"_id": oid})
        if not cycle:
            raise HTTPException(404, "Cycle not found")
        admin_details_collection.update_one(
            {},
            {"$set": {"active_approval_cycle_id": req.cycle_id, "active_approval_cycle_label": cycle.get("cycle_label", "")}},
            upsert=True,
        )
        return {"success": True, "active_approval_cycle_id": req.cycle_id, "cycle_label": cycle.get("cycle_label", "")}
    else:
        # Clear → fall back to all live cycles
        admin_details_collection.update_one(
            {},
            {"$unset": {"active_approval_cycle_id": "", "active_approval_cycle_label": ""}},
        )
        return {"success": True, "active_approval_cycle_id": None, "cycle_label": "All Live Cycles"}


@app.get("/admin/active-approval-payroll")
async def get_active_approval_payroll(current_user: str = Depends(get_current_user)):
    """Admin: get currently selected active approval cycle."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    admin = admin_details_collection.find_one({}, {"active_approval_cycle_id": 1, "active_approval_cycle_label": 1})
    if admin and admin.get("active_approval_cycle_id"):
        return {
            "active_approval_cycle_id": admin["active_approval_cycle_id"],
            "cycle_label": admin.get("active_approval_cycle_label", ""),
        }
    return {"active_approval_cycle_id": None, "cycle_label": "All Live Cycles"}


@app.post("/admin/bulk-set-cycle-status")
async def bulk_set_cycle_status(
    cycle_id: str = Body(...),
    status: str = Body(...),
    current_user: str = Depends(get_current_user),
):
    """Admin: bulk-set approval_status for ALL submitted payrolls in a cycle.
    Also moves employees to the Approved/Rejected collection accordingly.
    """
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    if status not in ("approved", "rejected", "pending"):
        raise HTTPException(400, "status must be approved, rejected, or pending")

    from backend.database import timesheets_collection

    now_iso = __import__("datetime").datetime.utcnow().isoformat()

    # 1. Update approval_status in Timesheet_data for all employees with this cycle
    result = timesheets_collection.update_many(
        {"payrolls": {"$elemMatch": {"cycle_id": cycle_id, "submitted": True}}},
        {"$set": {
            "payrolls.$[elem].approval_status": status,
            "payrolls.$[elem].status_updated_at": now_iso,
            "payrolls.$[elem].status_updated_by": current_user,
        }},
        array_filters=[{"elem.cycle_id": cycle_id, "elem.submitted": True}],
    )

    # 2. Move employees from Pending/Rejected → Approved in the approval collections
    if status == "approved":
        affected_employees = list(timesheets_collection.find(
            {"payrolls": {"$elemMatch": {"cycle_id": cycle_id, "submitted": True}}},
            {"employeeId": 1, "_id": 0}
        ))
        from backend.database import (
            pending_collection, approved_collection, rejected_collection,
            reporting_managers_collection as rm_coll, employee_details_collection,
        )
        from backend.timesheet.router import add_or_create
        for emp_doc in affected_employees:
            emp_code = emp_doc.get("employeeId", "")
            if not emp_code:
                continue
            # Find reporting manager
            rm = rm_coll.find_one({"EmployeeCode": emp_code})
            mgr_code = rm.get("ReportingEmpCode", "") if rm else ""
            if not mgr_code:
                continue
            mgr_doc = employee_details_collection.find_one({"ReportingEmpCode": mgr_code})
            mgr_name = mgr_doc.get("ReportingEmpName", "") if mgr_doc else ""
            pending_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_code}})
            rejected_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_code}})
            add_or_create(approved_collection, mgr_code, mgr_name, emp_code)

    return {
        "success": True,
        "updated": result.modified_count,
        "status": status,
        "cycle_id": cycle_id,
        "message": f"{result.modified_count} payroll(s) set to '{status}'",
    }


@app.delete("/payroll-cycles/{cycle_id}")
async def delete_payroll_cycle(
    cycle_id: str,
    current_user: str = Depends(get_current_user),
):
    """Admin: delete a payroll cycle."""
    if not _is_timesheet_admin(current_user):
        raise HTTPException(403, "Admin access required")
    try:
        from bson import ObjectId
        oid = ObjectId(cycle_id)
    except Exception:
        raise HTTPException(400, "Invalid cycle ID")
    payroll_cycles_collection.delete_one({"_id": oid})
    return {"success": True}


@app.get("/active-payroll-cycle")
async def get_active_payroll_cycle(current_user: str = Depends(get_current_user)):
    """
    Returns the currently live payroll cycle for users.
    Also checks if the deadline has passed — if so, returns locked=True.
    Falls back to the old payroll_status logic if no cycles exist.
    """
    from pytz import timezone as tz
    import pytz

    cycle = payroll_cycles_collection.find_one({"status": "live"})

    if not cycle:
        # Fallback: use old admin_details payroll_status
        admin = admin_details_collection.find_one({}, {"payroll_status": 1, "par_status": 1})
        if admin and admin.get("payroll_status"):
            p = admin["payroll_status"]
            return {
                "found": True,
                "cycle_label": "Current Payroll",
                "start_date": p.get("start_date"),
                "end_date": p.get("end_date"),
                "deadline_date": None,
                "deadline_time": None,
                "locked": False,
                "par_status": admin.get("par_status", "disable"),
            }
        return {"found": False, "locked": True, "par_status": "disable"}

    # Check deadline
    locked = False
    try:
        ist = pytz.timezone("Asia/Kolkata")
        deadline_str = f"{cycle['deadline_date']} {cycle['deadline_time']}"
        deadline_naive = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        deadline_ist = ist.localize(deadline_naive)
        now_ist = datetime.now(ist)
        locked = now_ist > deadline_ist
    except Exception:
        locked = False

    # Also check PAR status
    admin = admin_details_collection.find_one({}, {"par_status": 1})
    par_status = admin.get("par_status", "disable") if admin else "disable"

    return {
        "found": True,
        "id": str(cycle["_id"]),
        "cycle_label": cycle.get("cycle_label", ""),
        "start_date": cycle.get("start_date"),
        "end_date": cycle.get("end_date"),
        "deadline_date": cycle.get("deadline_date"),
        "deadline_time": cycle.get("deadline_time"),
        "locked": locked,
        "par_status": par_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Active Payroll Cycles for users (live + upcoming that have started)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/available-payroll-cycles")
async def get_available_payroll_cycles(current_user: str = Depends(get_current_user)):
    """
    Returns all cycles a user can currently fill:
    - 'live' cycles always shown
    - 'upcoming' cycles shown only if today >= their start_date
    Each cycle includes locked status based on deadline.
    """
    import pytz
    from datetime import date as date_type

    today_str = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)

    cycles = list(payroll_cycles_collection.find(
        {"status": {"$in": ["live", "upcoming"]}},
        sort=[("start_date", 1)]
    ))

    result = []
    for c in cycles:
        # Upcoming: only show if start_date <= today
        if c["status"] == "upcoming" and c.get("start_date", "9999") > today_str:
            continue

        locked = False
        try:
            deadline_str = f"{c['deadline_date']} {c['deadline_time']}"
            deadline_naive = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
            deadline_ist = ist.localize(deadline_naive)
            locked = now_ist > deadline_ist
        except Exception:
            locked = False

        result.append({
            "id": str(c["_id"]),
            "cycle_label": c.get("cycle_label", ""),
            "start_date": c.get("start_date"),
            "end_date": c.get("end_date"),
            "deadline_date": c.get("deadline_date"),
            "deadline_time": c.get("deadline_time"),
            "status": c.get("status"),
            "locked": locked,
            "show_lunch_travel": c.get("show_lunch_travel", True),
        })

    return {"cycles": result}


# ─────────────────────────────────────────────────────────────────────────────
# Timesheet Draft (Temp) & Submit
# ─────────────────────────────────────────────────────────────────────────────

class DraftSaveRequest(BaseModel):
    cycle_id: str
    cycle_label: str
    week_period: str
    entries: list
    metadata: Optional[dict] = None   # empName, designation, etc.


class TimesheetSubmitRequest(BaseModel):
    cycle_id: str
    cycle_label: str
    metadata: Optional[dict] = None


@app.post("/timesheet/save-draft")
async def save_timesheet_draft(
    req: DraftSaveRequest,
    current_user: str = Depends(get_current_user),
):
    """Save one week period's entries to the temp collection (draft)."""
    from bson import ObjectId as ObjId
    now_iso = datetime.utcnow().isoformat()

    # Validate cycle exists and is not locked
    try:
        cycle_doc = payroll_cycles_collection.find_one({"_id": ObjId(req.cycle_id)})
    except Exception:
        raise HTTPException(400, "Invalid cycle ID")
    if not cycle_doc:
        raise HTTPException(404, "Cycle not found")

    # Check deadline
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    try:
        dl = datetime.strptime(f"{cycle_doc['deadline_date']} {cycle_doc['deadline_time']}", "%Y-%m-%d %H:%M")
        if datetime.now(ist) > ist.localize(dl):
            raise HTTPException(403, "Submission deadline has passed for this cycle")
    except HTTPException:
        raise
    except Exception:
        pass

    # Find or create temp doc for this employee+cycle
    temp_doc = timesheet_temp_collection.find_one({
        "employeeId": current_user,
        "cycle_id": req.cycle_id,
    })

    if temp_doc and temp_doc.get("submitted"):
        raise HTTPException(403, "Timesheet already submitted for this cycle")

    # Build entries with IDs
    new_entries = []
    for e in req.entries:
        entry = dict(e)
        entry["id"] = entry.get("id") or str(ObjId())
        entry["updated_time"] = now_iso
        if not entry.get("created_time"):
            entry["created_time"] = now_iso
        new_entries.append(entry)

    if temp_doc:
        # Replace this week's data in the existing draft
        existing_data = temp_doc.get("Data", [])
        # Remove old entries for this week period
        updated_data = [wk for wk in existing_data if req.week_period not in wk]
        if new_entries:
            updated_data.append({req.week_period: new_entries})
        timesheet_temp_collection.update_one(
            {"_id": temp_doc["_id"]},
            {"$set": {
                "Data": updated_data,
                "updated_time": now_iso,
                "metadata": req.metadata or temp_doc.get("metadata", {}),
            }}
        )
    else:
        doc = {
            "employeeId": current_user,
            "cycle_id": req.cycle_id,
            "cycle_label": req.cycle_label,
            "Data": [{req.week_period: new_entries}] if new_entries else [],
            "submitted": False,
            "created_time": now_iso,
            "updated_time": now_iso,
            "metadata": req.metadata or {},
        }
        timesheet_temp_collection.insert_one(doc)

    return {"success": True, "message": f"Week '{req.week_period}' saved as draft"}


@app.get("/timesheet/draft/{employee_id}")
async def get_timesheet_draft(
    employee_id: str,
    cycle_id: str,
    current_user: str = Depends(get_current_user),
):
    """Load draft for a specific employee + cycle."""
    if employee_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    doc = timesheet_temp_collection.find_one({
        "employeeId": current_user,
        "cycle_id": cycle_id,
    })
    if not doc:
        return {"draft": None, "submitted": False}

    doc["_id"] = str(doc["_id"])
    return {"draft": doc, "submitted": doc.get("submitted", False)}


@app.get("/timesheet/submission-status/{employee_id}")
async def get_submission_status(
    employee_id: str,
    current_user: str = Depends(get_current_user),
):
    """Returns submission status for all cycles for this employee."""
    if employee_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    docs = list(timesheet_temp_collection.find(
        {"employeeId": current_user},
        {"cycle_id": 1, "cycle_label": 1, "submitted": 1, "updated_time": 1}
    ))
    result = {}
    for d in docs:
        result[d["cycle_id"]] = {
            "submitted": d.get("submitted", False),
            "cycle_label": d.get("cycle_label", ""),
            "updated_time": d.get("updated_time", ""),
        }
    return {"status": result}


@app.post("/timesheet/submit")
async def submit_timesheet(
    req: TimesheetSubmitRequest,
    current_user: str = Depends(get_current_user),
):
    """
    Final submit: move data from Timesheet_temp → Timesheet_data.
    Marks the temp doc as submitted (locked from further edits).
    """
    from bson import ObjectId as ObjId
    import hashlib, json as _json

    now_iso = datetime.utcnow().isoformat()

    temp_doc = timesheet_temp_collection.find_one({
        "employeeId": current_user,
        "cycle_id": req.cycle_id,
    })
    if not temp_doc:
        raise HTTPException(404, "No draft found for this cycle")
    if temp_doc.get("submitted"):
        raise HTTPException(400, "Already submitted")

    # Check deadline
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    try:
        cycle_doc = payroll_cycles_collection.find_one({"_id": ObjId(req.cycle_id)})
        if cycle_doc:
            dl = datetime.strptime(
                f"{cycle_doc['deadline_date']} {cycle_doc['deadline_time']}", "%Y-%m-%d %H:%M"
            )
            if datetime.now(ist) > ist.localize(dl):
                raise HTTPException(403, "Submission deadline has passed")
    except HTTPException:
        raise
    except Exception:
        pass

    meta = temp_doc.get("metadata", {})
    emp_id = current_user

    def _hash(entry):
        key = {k: entry.get(k, "") for k in [
            "date", "location", "projectStartTime", "projectEndTime",
            "client", "project", "projectCode", "reportingManagerEntry",
            "activity", "projectHours", "billable", "remarks",
            "lunchTime", "travelTime",
        ]}
        return hashlib.sha256(_json.dumps(key, sort_keys=True).encode()).hexdigest()

    # Load existing main doc
    from backend.database import timesheets_collection, pending_collection, approved_collection, rejected_collection
    existing_doc = timesheets_collection.find_one({"employeeId": emp_id})
    existing_data = existing_doc.get("Data", []) if existing_doc else []

    existing_hashes = set()
    for wk in existing_data:
        for _, wk_entries in wk.items():
            for entry in wk_entries:
                existing_hashes.add(_hash(entry))

    # Merge temp data into main
    merged = existing_data.copy()
    added = 0
    for wk_obj in temp_doc.get("Data", []):
        for week_name, entries in wk_obj.items():
            filtered = []
            for e in entries:
                h = _hash(e)
                if h not in existing_hashes:
                    filtered.append(e)
                    existing_hashes.add(h)
                    added += 1
            if not filtered:
                continue
            found = False
            for ex_wk in merged:
                if week_name in ex_wk:
                    ex_wk[week_name].extend(filtered)
                    found = True
                    break
            if not found:
                merged.append({week_name: filtered})

    # Recalc totals
    total = billable_hrs = non_billable_hrs = 0.0
    for wk in merged:
        for _, wk_entries in wk.items():
            for e in wk_entries:
                try:
                    hrs = float(e.get("projectHours", 0))
                except Exception:
                    hrs = 0.0
                total += hrs
                if e.get("billable") == "Yes":
                    billable_hrs += hrs
                elif e.get("billable") == "No":
                    non_billable_hrs += hrs

    payload = {
        "employeeId": emp_id,
        "employeeName": meta.get("employeeName", ""),
        "designation": meta.get("designation", ""),
        "gender": meta.get("gender", ""),
        "partner": meta.get("partner", ""),
        "reportingManager": meta.get("reportingManager", ""),
        "Data": merged,
        "hits": meta.get("hits", ""),
        "misses": meta.get("misses", ""),
        "feedback_hr": meta.get("feedback_hr", ""),
        "feedback_it": meta.get("feedback_it", ""),
        "feedback_crm": meta.get("feedback_crm", ""),
        "feedback_others": meta.get("feedback_others", ""),
        "idle_time": meta.get("idle_time", ""),
        "idle_time_status": meta.get("idle_time_status", ""),
        "idle_time_hours": meta.get("idle_time_hours", ""),
        "idle_time_reason": meta.get("idle_time_reason", ""),
        "updated_time": now_iso,
        "totalHours": round(total, 2),
        "totalBillableHours": round(billable_hrs, 2),
        "totalNonBillableHours": round(non_billable_hrs, 2),
        "cycle_id": req.cycle_id,
        "cycle_label": req.cycle_label,
        "submitted_at": now_iso,
    }

    if existing_doc:
        timesheets_collection.update_one({"employeeId": emp_id}, {"$set": payload})
    else:
        payload["created_time"] = now_iso
        timesheets_collection.insert_one(payload)

    # Mark temp as submitted
    timesheet_temp_collection.update_one(
        {"_id": temp_doc["_id"]},
        {"$set": {"submitted": True, "submitted_at": now_iso}}
    )

    # Update Pending collection
    try:
        emp_doc = employee_details_collection.find_one({"EmpID": emp_id})
        if emp_doc:
            mgr_code = emp_doc.get("ReportingEmpCode", "").strip().upper()
            mgr_name = emp_doc.get("ReportingEmpName", "Unknown")
            if mgr_code:
                approved_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_id}})
                rejected_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_id}})
                from backend.timesheet.router import add_or_create
                add_or_create(pending_collection, mgr_code, mgr_name, emp_id)
    except Exception as e:
        print(f"Error updating Pending: {e}")

    return {"success": True, "message": "Timesheet submitted successfully", "added": added}


# ─────────────────────────────────────────────────────────────────────────────
# Excel Upload Endpoint
# ─────────────────────────────────────────────────────────────────────────────

class ExcelTimesheetEntry(BaseModel):
    employeeId: str
    employeeName: str
    designation: str
    gender: str
    partner: str
    reportingManager: str
    weekPeriod: str
    date: str
    location: str
    projectStartTime: str
    projectEndTime: str
    client: str
    project: str
    projectCode: str
    reportingManagerEntry: str
    activity: str
    projectHours: str
    billable: str
    lunchTime: Optional[str] = ""
    travelTime: Optional[str] = ""
    remarks: str
    hits: Optional[str] = ""
    misses: Optional[str] = ""
    feedback_hr: Optional[str] = ""
    feedback_it: Optional[str] = ""
    feedback_crm: Optional[str] = ""
    feedback_others: Optional[str] = ""
    idle_time: Optional[str] = ""
    idle_time_status: Optional[str] = ""
    idle_time_hours: Optional[str] = ""
    idle_time_reason: Optional[str] = ""


@app.post("/save_timesheets")
async def save_timesheets_from_excel(
    entries: list[ExcelTimesheetEntry],
    current_user: str = Depends(get_current_user)
):
    """
    Save timesheets uploaded from Excel.
    Groups entries by employee → payroll cycle → week period.
    Handles conditional lunch/travel time fields based on payroll cycle config.
    """
    if not entries:
        raise HTTPException(400, "No entries provided")

    now_iso = datetime.utcnow().isoformat()
    
    # Group entries by employee
    by_employee = {}
    for entry in entries:
        emp_id = entry.employeeId.strip().upper()
        if emp_id not in by_employee:
            by_employee[emp_id] = {
                "employeeName": entry.employeeName,
                "designation": entry.designation,
                "gender": entry.gender,
                "partner": entry.partner,
                "reportingManager": entry.reportingManager,
                "hits": entry.hits,
                "misses": entry.misses,
                "feedback_hr": entry.feedback_hr,
                "feedback_it": entry.feedback_it,
                "feedback_crm": entry.feedback_crm,
                "feedback_others": entry.feedback_others,
                "idle_time": entry.idle_time,
                "idle_time_status": entry.idle_time_status,
                "idle_time_hours": entry.idle_time_hours,
                "idle_time_reason": entry.idle_time_reason,
                "weeks": {}
            }
        
        week = entry.weekPeriod
        if week not in by_employee[emp_id]["weeks"]:
            by_employee[emp_id]["weeks"][week] = []
        
        # Build entry dict
        entry_dict = {
            "id": str(ObjectId()),
            "date": entry.date,
            "location": entry.location,
            "projectStartTime": entry.projectStartTime,
            "projectEndTime": entry.projectEndTime,
            "client": entry.client,
            "project": entry.project,
            "projectCode": entry.projectCode,
            "reportingManagerEntry": entry.reportingManagerEntry,
            "activity": entry.activity,
            "projectHours": entry.projectHours,
            "billable": entry.billable,
            "remarks": entry.remarks,
            "created_time": now_iso,
            "updated_time": now_iso,
        }
        
        # Add lunch/travel time if provided (will be included in all uploads)
        if entry.lunchTime:
            entry_dict["lunchTime"] = entry.lunchTime
        if entry.travelTime:
            entry_dict["travelTime"] = entry.travelTime
        
        by_employee[emp_id]["weeks"][week].append(entry_dict)
    
    # Determine payroll cycle from week period (use first entry's week)
    # For now, we'll need to match the week period to an existing cycle
    # This is a simplified approach - you may need to enhance this logic
    
    from backend.database import timesheets_collection
    from backend.timesheet.router import _get_or_create_payroll, _upsert_week, recalc_payroll_totals
    
    saved_count = 0
    
    for emp_id, emp_data in by_employee.items():
        # Find or create employee document
        doc = timesheets_collection.find_one({"employeeId": emp_id})
        
        # For Excel upload, we need to determine which cycle these entries belong to
        # We'll try to match the week period to an existing live cycle
        # If no match, we'll create a generic cycle
        
        # Get all live cycles
        live_cycles = list(payroll_cycles_collection.find({"status": "live"}))
        
        # Try to match week period to a cycle
        # This is simplified - you may want more sophisticated matching
        cycle_id = None
        cycle_label = None
        
        if live_cycles:
            # Use the first live cycle
            cycle = live_cycles[0]
            cycle_id = str(cycle["_id"])
            cycle_label = cycle.get("cycle_label", "")
        else:
            # No live cycle - create a generic one or raise error
            raise HTTPException(400, "No active payroll cycle found. Please create a payroll cycle first.")
        
        if doc:
            payrolls = doc.get("payrolls", [])
        else:
            payrolls = []
        
        # Get or create payroll for this cycle
        payroll = _get_or_create_payroll(payrolls, cycle_id, cycle_label)
        
        # Add weeks and entries
        for week_period, week_entries in emp_data["weeks"].items():
            _upsert_week(payroll, week_period, week_entries)
        
        # Update metadata
        payroll["metadata"] = {
            "hits": emp_data.get("hits", ""),
            "misses": emp_data.get("misses", ""),
            "feedback_hr": emp_data.get("feedback_hr", ""),
            "feedback_it": emp_data.get("feedback_it", ""),
            "feedback_crm": emp_data.get("feedback_crm", ""),
            "feedback_others": emp_data.get("feedback_others", ""),
            "idle_time": emp_data.get("idle_time", ""),
            "idle_time_status": emp_data.get("idle_time_status", ""),
            "idle_time_hours": emp_data.get("idle_time_hours", ""),
            "idle_time_reason": emp_data.get("idle_time_reason", ""),
        }
        
        # Recalculate totals
        p_total, p_billable, p_non_billable = recalc_payroll_totals(payroll)
        payroll["totalHours"] = p_total
        payroll["totalBillableHours"] = p_billable
        payroll["totalNonBillableHours"] = p_non_billable
        
        # Mark as submitted
        payroll["submitted"] = True
        payroll["submitted_at"] = now_iso
        
        # Save to database
        payload = {
            "employeeId": emp_id,
            "employeeName": emp_data["employeeName"],
            "designation": emp_data["designation"],
            "gender": emp_data["gender"],
            "partner": emp_data["partner"],
            "reportingManager": emp_data["reportingManager"],
            "payrolls": payrolls,
            "updated_time": now_iso,
        }
        
        if doc:
            timesheets_collection.update_one(
                {"employeeId": emp_id},
                {"$set": payload}
            )
        else:
            payload["created_time"] = now_iso
            timesheets_collection.insert_one(payload)
        
        saved_count += 1
    
    return {
        "success": True,
        "message": f"Successfully uploaded timesheets for {saved_count} employee(s)",
        "employees_processed": saved_count
    }

# ─────────────────────────────────────────────────────────────────────────────
# Legacy URL aliases
# ─────────────────────────────────────────────────────────────────────────────

from backend.timesheet.router import (
    get_employees, get_clients, get_employee_projects, check_reporting_manager,
    get_employee_timesheet_for_manager, get_pending, get_approved, get_rejected,
    approve_timesheet, reject_timesheet, approve_all,
    get_timesheets, update_timesheet, delete_timesheet,
    get_project_plan_status,
)

# Legacy save — redirect to new draft endpoint (kept for Excel upload compatibility)
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
app.add_api_route("/get_project_plan_status/{project_code}",    get_project_plan_status,            methods=["GET"])
