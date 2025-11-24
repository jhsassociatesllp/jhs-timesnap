# from fastapi import FastAPI, HTTPException, Depends, status, Request
# from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
# from pydantic import BaseModel
# from passlib.context import CryptContext
# from pymongo import MongoClient
# from fastapi import Body
# import os
# import re
# from dotenv import load_dotenv
# from db import *
# from fastapi import APIRouter
# from datetime import datetime, timedelta
# import jwt

# load_dotenv()

# # ---------------- JWT CONFIG ----------------
# SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
# ALGORITHM = "HS256"
# ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour

# # ---------------- PASSWORD HASHER ----------------
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b", bcrypt__rounds=12)

# # ---------------- FRONTEND PATH ----------------
# frontend_path = os.path.join(os.path.dirname(__file__), "static")
# print("Frontend path:", frontend_path)
# if os.path.exists(frontend_path):
#     print("Files in frontend:", os.listdir(frontend_path))
# else:
#     print(f"Frontend directory not found at: {frontend_path}")

# admin_router = APIRouter()


# # ---------------- MODELS ----------------
# class AdminLoginRequest(BaseModel):
#     userid: str
#     password: str

# class AdminRegisterRequest(BaseModel):
#     userid: str
#     password: str


# # ---------------- JWT FUNCTIONS ----------------
# def create_access_token(data: dict, expires_delta: timedelta = None):
#     """Create JWT access token"""
#     to_encode = data.copy()
#     expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
#     to_encode.update({"exp": expire})
#     token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
#     return token

def verify_token(token: str):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        userid = payload.get("sub")
        if userid is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return userid
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# def get_current_admin(request: Request):
#     """Check JWT from cookies"""
#     token = request.cookies.get("access_token")
#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")
#     userid = verify_token(token)
#     return userid


# # ---------------- ROUTES ----------------
# @admin_router.get("/admin", response_class=FileResponse)
# async def admin_page():
#     return FileResponse(os.path.join(frontend_path, "admin.html"))


# @admin_router.post("/admin-login")
# async def admin_login(request: AdminLoginRequest):
#     userid = request.userid.strip().upper()
#     password = request.password

#     if not userid or not password:
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin ID and password are required")

#     # Find admin in MongoDB
#     admin = admin_details_collection.find_one({"userid": userid})
#     if not admin:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

#     # Verify password
#     if not pwd_context.verify(password, admin["password"]):
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

#     # ✅ Create JWT token
#     access_token = create_access_token(data={"sub": userid})

#     # ✅ Send as HTTP-only cookie
#     response = JSONResponse(content={"success": True, "message": "Login successful", "redirect": "/admin-dashboard"})
#     response.set_cookie(
#         key="access_token",
#         value=access_token,
#         httponly=True,
#         max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
#         samesite="Lax"
#     )

#     return response



# @admin_router.get("/admin-dashboard", response_class=FileResponse)
# async def admin_dashboard(request: Request):
#     try:
#         get_current_admin(request)  # ✅ Protect route
#         return FileResponse(os.path.join(frontend_path, "dashboard.html"))
#     except HTTPException:
#         return RedirectResponse(url="/admin")


# @admin_router.get("/admin-logout")
# async def logout():
#     """Logout and clear session cookie"""
#     response = RedirectResponse(url="/admin")
#     response.delete_cookie("access_token")
#     return response


# @admin_router.post("/update-par-status")
# async def update_par_status(request: Request):
#     """Update PAR status for the given admin (Protected)"""
#     userid = get_current_admin(request)  # ✅ Protect route
#     body = await request.json()
#     new_status = body.get("new_status")

#     if new_status not in ["enable", "disable"]:
#         raise HTTPException(status_code=400, detail="Invalid status value")

#     admin = admin_details_collection.find_one({"userid": userid})
#     if not admin:
#         raise HTTPException(status_code=404, detail="Admin not found")

#     current_status = admin.get("par_status", "disable")
#     if current_status == new_status:
#         return {"message": f"PAR already {new_status}", "par_status": current_status}

#     admin_details_collection.update_one(
#         {"userid": userid},
#         {"$set": {"par_status": new_status}}
#     )

#     return {"message": f"PAR status updated to {new_status}", "par_status": new_status}


from fastapi import FastAPI, HTTPException, status, Request, Body
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from passlib.context import CryptContext
from datetime import datetime, timedelta
import os, re, jwt
from dotenv import load_dotenv
from db import *
from fastapi import APIRouter
from datetime import datetime, timedelta, timezone

load_dotenv()

# ---------------- JWT CONFIG ----------------
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour

# ---------------- PASSWORD HASHER ----------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

frontend_path = os.path.join(os.path.dirname(__file__), "static")
admin_router = APIRouter()

# ---------------- MODELS ----------------
class AdminLoginRequest(BaseModel):
    userid: str
    password: str

class AdminRegisterRequest(BaseModel):
    userid: str
    password: str


#---------------- JWT FUNCTIONS ----------------
def create_access_token(data: dict, expires_delta: timedelta = None):
    """JWT create kare, 1 ghante ke liye valid."""
    to_encode = data.copy()
    expire_dt = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    # timestamp integer me convert
    to_encode.update({"exp": int(expire_dt.timestamp())})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    print(f"🕒 Token created for {data.get('sub')} | Expires at: {expire_dt.isoformat()}")
    return token



def verify_token(token: str):
    """JWT verify kare aur userid return kare."""
    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        userid = payload.get("sub") or payload.get("userid")
        if not userid:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return userid
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------- ROUTES ----------------
@admin_router.get("/admin", response_class=FileResponse)
async def admin_page():
    return FileResponse(os.path.join(frontend_path, "admin.html"))


@admin_router.post("/admin-login")
async def admin_login(request: AdminLoginRequest):
    userid = request.userid.strip().upper()
    password = request.password

    if not userid or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin ID and password are required")

    admin = admin_details_collection.find_one({"userid": userid})
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

    if not pwd_context.verify(password, admin["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

    # 1 ghante ke liye valid token
    access_token = create_access_token(data={"sub": userid}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    # Response + HTTP-only cookie
    resp = JSONResponse(
        content={
            "success": True,
            "message": "Login successful",
            "access_token": access_token,
            "userid": userid
        }
    )
    print(f"Returning response: {resp}")
    # resp.set_cookie(
    #     key="admin_token",
    #     value=access_token,
    #     httponly=True,
    #     max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    #     samesite="Lax"
    # )
    return resp

@admin_router.post("/create-admin")
async def create_admin(request: AdminRegisterRequest):
    userid = request.userid.strip().upper()
    password = request.password

    # Validation
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=400, detail="Must include uppercase letter")
    if not re.search(r"[a-z]", password):
        raise HTTPException(status_code=400, detail="Must include lowercase letter")
    if not re.search(r"\d", password):
        raise HTTPException(status_code=400, detail="Must include number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(status_code=400, detail="Must include special character")

    # Check if admin exists
    existing_admin = admin_details_collection.find_one({"userid": userid})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")

    hashed_password = pwd_context.hash(password)
    admin_details_collection.insert_one({
        "userid": userid,
        "password": hashed_password,
        "par_status": "disable"
    })

    return {"success": True, "message": f"Admin {userid} created successfully!"}


@admin_router.get("/admin-logout")
async def logout():
    """Logout and clear session cookie"""
    response = RedirectResponse(url="/admin")
    response.delete_cookie("access_token")
    return response

@admin_router.get("/admin-dashboard", response_class=FileResponse)
async def admin_dashboard():
    return FileResponse(os.path.join(frontend_path, "dashboard.html"))


# @admin_router.post("/update-par-status")
# async def update_par_status(request: Request):
#     """Protected route: check token manually"""
#     data = await request.json()
#     token = data.get("token")
#     new_status = data.get("new_status")

#     if not token:
#         raise HTTPException(status_code=401, detail="Token required")

#     userid = verify_token(token)

#     if new_status not in ["enable", "disable"]:
#         raise HTTPException(status_code=400, detail="Invalid status")

#     admin = admin_details_collection.find_one({"userid": userid})
#     if not admin:
#         raise HTTPException(status_code=404, detail="Admin not found")

#     admin_details_collection.update_one(
#         {"userid": userid},
#         {"$set": {"par_status": new_status}}
#     )

#     return {"message": f"PAR status updated to {new_status}"}

@admin_router.post("/update-par-status")
async def update_par_status(request: Request):
    """Globally update PAR status"""
    data = await request.json()
    token = data.get("token")
    new_status = data.get("new_status")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    # Verify token for security but ignore specific userid when updating
    verify_token(token)

    if new_status not in ["enable", "disable"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # ✅ Update single global record
    admin_details_collection.update_one({}, {"$set": {"par_status": new_status}}, upsert=True)

    return {"message": f"PAR status updated to {new_status}"}

@admin_router.post("/get-par-status")
async def get_par_status(request: Request):
    """Fetch current PAR status (Protected with JWT token)"""
    data = await request.json()
    token = data.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    userid = verify_token(token)  # ✅ validate JWT

    # Fetch from MongoDB
    admin = admin_details_collection.find_one({"userid": userid})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    par_status = admin.get("par_status", "disable")

    return {"par_status": par_status}


# @admin_router.get("/get-par-current-status")
# async def get_par_current_status(request: Request):
#     """
#     Returns the global PAR status (used by Reporting Manager's timesheet app).
#     """
#     try:
#         admin = admin_details_collection.find_one({}, {"par_status": 1})
#         if not admin:
#             return {"par_status": "disable"}
#         return {"par_status": admin.get("par_status", "disable")}
#     except Exception as e:
#         print("Error fetching PAR status:", e)
#         return {"par_status": "disable"}


# @admin_router.get("/get-par-current-status")
# async def get_par_current_status():
#     """
#     Returns the current payroll period (start_date → end_date) 
#     for all users – used by employee timesheet to auto-generate week dropdowns.
#     """
#     try:
#         admin = admin_details_collection.find_one({}, {"_id": 0, "payroll_status": 1})
#         if not admin or "payroll_status" not in admin:
#             # fallback: default payroll (21st → 20th)
#             today = datetime.now()
#             if today.day >= 21:
#                 start = datetime(today.year, today.month, 21)
#                 if today.month == 12:
#                     end = datetime(today.year + 1, 1, 20)
#                 else:
#                     end = datetime(today.year, today.month + 1, 20)
#             else:
#                 if today.month == 1:
#                     start = datetime(today.year - 1, 12, 21)
#                 else:
#                     start = datetime(today.year, today.month - 1, 21)
#                 end = datetime(today.year, today.month, 20)

#             return {
#                 "start": start.strftime("%Y-%m-%d"),
#                 "end": end.strftime("%Y-%m-%d"),
#                 "source": "default"
#             }

#         payroll = admin["payroll_status"]
#         return {
#             "start": payroll.get("start_date"),
#             "end": payroll.get("end_date"),
#             "source": "db"
#         }

#     except Exception as e:
#         print("❌ Error fetching current payroll period:", e)
#         return {"start": None, "end": None, "source": "error"}

@admin_router.get("/get-par-current-status")
async def get_par_current_status():
    """
    Returns both:
    1️⃣ Global PAR status (enable/disable)
    2️⃣ Current Payroll period (start_date → end_date)
    Used by Timesheet (for Reporting Manager & week dropdowns)
    """
    try:
        admin = admin_details_collection.find_one({}, {"_id": 0, "par_status": 1, "payroll_status": 1})

        # -------------- PAR STATUS --------------
        par_status = admin.get("par_status", "disable") if admin else "disable"

        # -------------- PAYROLL PERIOD --------------
        if not admin or "payroll_status" not in admin:
            # fallback: default payroll 21st → 20th
            today = datetime.now()
            if today.day >= 21:
                start = datetime(today.year, today.month, 21)
                if today.month == 12:
                    end = datetime(today.year + 1, 1, 20)
                else:
                    end = datetime(today.year, today.month + 1, 20)
            else:
                if today.month == 1:
                    start = datetime(today.year - 1, 12, 21)
                else:
                    start = datetime(today.year, today.month - 1, 21)
                end = datetime(today.year, today.month, 20)

            start_date = start.strftime("%Y-%m-%d")
            end_date = end.strftime("%Y-%m-%d")
            source = "default"
        else:
            payroll = admin.get("payroll_status", {})
            start_date = payroll.get("start_date")
            end_date = payroll.get("end_date")
            source = "db"

        return {
            "par_status": par_status,
            "start": start_date,
            "end": end_date,
            "source": source
        }

    except Exception as e:
        print("❌ Error fetching PAR & Payroll data:", e)
        return {
            "par_status": "disable",
            "start": None,
            "end": None,
            "source": "error"
        }


@admin_router.post("/update-payroll-status")
async def update_payroll_status(request: Request):
    """Update payroll start & end dates"""
    data = await request.json()
    token = data.get("token")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    userid = verify_token(token)

    admin = admin_details_collection.find_one({"userid": userid})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    # ✅ Store payroll details as nested object
    payroll_data = {
        "status": "Active",
        "start_date": start_date,
        "end_date": end_date
    }

    admin_details_collection.update_one(
        {"userid": userid},
        {"$set": {"payroll_status": payroll_data}}
    )

    return {"message": "Payroll updated successfully", "payroll_status": payroll_data}


@admin_router.post("/get-payroll-status")
async def get_payroll_status(request: Request):
    """Fetch current payroll status and dates"""
    data = await request.json()
    token = data.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    userid = verify_token(token)

    admin = admin_details_collection.find_one({"userid": userid})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    payroll = admin.get("payroll_status", {})

    # ✅ Extract nested info (safe defaults)
    status = payroll.get("status", "Inactive")
    start_date = payroll.get("start_date", "")
    end_date = payroll.get("end_date", "")

    return {
        "payroll_status": status,
        "start_date": start_date,
        "end_date": end_date
    }

@admin_router.get("/get-current-payroll")
async def get_current_payroll():
    """Return current payroll period for all users."""
    admin = admin_details_collection.find_one({}, {"_id": 0, "payroll_status": 1})
    if not admin or "payroll_status" not in admin:
        return {"start_date": None, "end_date": None}
    return admin["payroll_status"]


# @admin_router.get("/admin/stats")
# async def admin_stats():
#     """
#     Admin Dashboard Stats:
#     1. Total Employees
#     2. Total Filled Employees
#     3. Total Not Filled Employees
#     4. Reporting Manager Wise Filled & Not Filled
#     """

#     # 1️⃣ Get all employees
#     all_employees = list(employee_details_collection.find({}, {"EmpID": 1, "ReportingEmpCode": 1, "ReportingEmpName": 1, "_id": 0}))
#     total_employees = len(all_employees)

#     # 2️⃣ Get employees who filled timesheets
#     filled_docs = list(timesheets_collection.find({}, {"employeeId": 1, "_id": 0}))
#     filled_emp_ids = {doc["employeeId"] for doc in filled_docs}
#     total_filled = len(filled_emp_ids)

#     # 3️⃣ Not filled employees
#     all_emp_ids = {e["EmpID"] for e in all_employees}
#     not_filled_emp_ids = all_emp_ids - filled_emp_ids
#     total_not_filled = len(not_filled_emp_ids)

#     # 4️⃣ Reporting Manager Wise Breakdown
#     manager_map = {}

#     for emp in all_employees:
#         emp_id = emp["EmpID"]
#         mgr_code = emp.get("ReportingEmpCode", "").strip().upper()
#         mgr_name = emp.get("ReportingEmpName", "Unknown")

#         if not mgr_code:
#             continue  # skip employees without manager

#         if mgr_code not in manager_map:
#             manager_map[mgr_code] = {
#                 "managerName": mgr_name,
#                 "filled": [],
#                 "not_filled": []
#             }

#         if emp_id in filled_emp_ids:
#             manager_map[mgr_code]["filled"].append(emp_id)
#         else:
#             manager_map[mgr_code]["not_filled"].append(emp_id)

#     return {
#         "success": True,
#         "summary": {
#             "totalEmployees": total_employees,
#             "totalFilled": total_filled,
#             "totalNotFilled": total_not_filled
#         },
#         "managerWise": manager_map
#     }


@admin_router.post("/admin/analysis-stats")
async def admin_analysis_stats(request: Request):
    """
    Admin Analytics:
    - Total Employees
    - Total Filled Employees
    - Total Not Filled Employees
    - Reporting Manager-wise filled / not-filled with employee details
    """
    data = await request.json()
    token = data.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    # ✅ Validate admin token
    userid = verify_token(token)

    # 1️⃣ Load all employees (code, name, manager mapping)
    employees = list(employee_details_collection.find({}, {"_id": 0}))
    emp_map = {}

    for emp in employees:
        emp_code = (emp.get("EmpID") or emp.get("empid") or emp.get("EmployeeCode") or "").strip().upper()
        if not emp_code:
            continue

        emp_name = (
            emp.get("Emp Name")
            or emp.get("EmployeeName")
            or emp.get("Name")
            or emp.get("EmployeeFullName")
            or ""
        )

        mgr_code = (emp.get("ReportingEmpCode") or emp.get("ManagerCode") or "").strip().upper()
        mgr_name = (
            emp.get("ReportingEmpName")
            or emp.get("ManagerName")
            or ""
        )

        emp_map[emp_code] = {
            "name": emp_name,
            "managerCode": mgr_code,
            "managerName": mgr_name
        }

    all_emp_ids = set(emp_map.keys())
    total_employees = len(all_emp_ids)

    # 2️⃣ Fetch employees who have timesheet entries (filled)
    filled_docs = timesheets_collection.find(
        {"employeeId": {"$in": list(all_emp_ids)}},
        {"_id": 0, "employeeId": 1}
    )
    filled_emp_ids = {
        doc["employeeId"].strip().upper()
        for doc in filled_docs
        if doc.get("employeeId")
    }

    total_filled = len(filled_emp_ids)
    not_filled_emp_ids = all_emp_ids - filled_emp_ids
    total_not_filled = len(not_filled_emp_ids)

    # 3️⃣ Manager-wise breakdown
    manager_stats = {}

    for emp_code, info in emp_map.items():
        mgr_code = info["managerCode"]
        mgr_name = info["managerName"] or "Unknown"

        if not mgr_code:
            # If you want unassigned manager bucket, handle here
            continue

        if mgr_code not in manager_stats:
            manager_stats[mgr_code] = {
                "reportingManagerCode": mgr_code,
                "reportingManagerName": mgr_name,
                "filledEmployees": [],
                "notFilledEmployees": []
            }

        bucket = (
            manager_stats[mgr_code]["filledEmployees"]
            if emp_code in filled_emp_ids
            else manager_stats[mgr_code]["notFilledEmployees"]
        )

        bucket.append({
            "empCode": emp_code,
            "empName": info["name"]
        })

    # 4️⃣ Convert to list + totals
    manager_list = []
    for mgr_code, data_obj in manager_stats.items():
        filled_list = data_obj["filledEmployees"]
        not_filled_list = data_obj["notFilledEmployees"]

        manager_list.append({
            "reportingManagerCode": data_obj["reportingManagerCode"],
            "reportingManagerName": data_obj["reportingManagerName"],
            "totalEmployees": len(filled_list) + len(not_filled_list),
            "totalFilled": len(filled_list),
            "totalNotFilled": len(not_filled_list),
            "filledEmployees": filled_list,
            "notFilledEmployees": not_filled_list
        })

    result = {
        "success": True,
        "summary": {
            "totalEmployees": total_employees,
            "totalFilledEmployees": total_filled,
            "totalNotFilledEmployees": total_not_filled
        },
        "managerWise": manager_list
    }
    print("Response")
    print(result)
    return result


@admin_router.post("/admin/par-stats")
async def admin_par_stats(request: Request):
    """
    PAR Control Stats (Admin):

    - For each ReportingEmpCode:
        * pending / approved / rejected employees (code + name)
        * counts + total unique employees under that manager
    - Uses Pending, Approved, Rejected collections ONLY (Option A).
    """
    data = await request.json()
    token = data.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    # ✅ Validate admin token (we don't care which admin, just that it's valid)
    verify_token(token)

    # 1️⃣ Build EmpCode → EmpName map
    employees = list(employee_details_collection.find({}, {"_id": 0}))
    emp_name_map = {}

    for emp in employees:
        emp_code = (
            emp.get("EmpID")
            or emp.get("empid")
            or emp.get("EmployeeCode")
            or ""
        )
        emp_code = emp_code.strip().upper()
        if not emp_code:
            continue

        emp_name = (
            emp.get("Emp Name")
            or emp.get("EmployeeName")
            or emp.get("Name")
            or emp.get("EmployeeFullName")
            or ""
        )

        emp_name_map[emp_code] = emp_name

    def enrich_employee_codes(codes):
        """Convert list of emp codes → [{empCode, empName}]"""
        result = []
        for raw in codes or []:
            code = (raw or "").strip().upper()
            if not code:
                continue
            result.append({
                "empCode": code,
                "empName": emp_name_map.get(code, "")
            })
        return result

    manager_stats = {}

    def add_from_collection(collection, bucket_key: str):
        """
        bucket_key ∈ {"pendingEmployees", "approvedEmployees", "rejectedEmployees"}
        """
        docs = collection.find({}, {"_id": 0, "ReportingEmpCode": 1, "ReportingEmpName": 1, "EmployeesCodes": 1})
        for doc in docs:
            mgr_code = (doc.get("ReportingEmpCode") or "").strip().upper()
            if not mgr_code:
                continue

            mgr_name = doc.get("ReportingEmpName") or ""

            if mgr_code not in manager_stats:
                manager_stats[mgr_code] = {
                    "reportingEmpCode": mgr_code,
                    "reportingEmpName": mgr_name,
                    "pendingEmployees": [],
                    "approvedEmployees": [],
                    "rejectedEmployees": []
                }
            else:
                # If name is empty in cache but present here, update it
                if mgr_name and not manager_stats[mgr_code]["reportingEmpName"]:
                    manager_stats[mgr_code]["reportingEmpName"] = mgr_name

            employees_list = enrich_employee_codes(doc.get("EmployeesCodes", []))
            manager_stats[mgr_code][bucket_key].extend(employees_list)

    # 2️⃣ Load from Pending / Approved / Rejected
    add_from_collection(pending_collection, "pendingEmployees")
    add_from_collection(approved_collection, "approvedEmployees")
    add_from_collection(rejected_collection, "rejectedEmployees")

    # 3️⃣ Build summary + final list
    total_pending = 0
    total_approved = 0
    total_rejected = 0
    all_unique_emp_codes = set()
    manager_list = []

    for mgr_code, info in manager_stats.items():
        pending_codes = {e["empCode"] for e in info["pendingEmployees"]}
        approved_codes = {e["empCode"] for e in info["approvedEmployees"]}
        rejected_codes = {e["empCode"] for e in info["rejectedEmployees"]}

        total_pending_mgr = len(pending_codes)
        total_approved_mgr = len(approved_codes)
        total_rejected_mgr = len(rejected_codes)

        all_codes_mgr = pending_codes | approved_codes | rejected_codes
        total_emps_mgr = len(all_codes_mgr)

        total_pending += total_pending_mgr
        total_approved += total_approved_mgr
        total_rejected += total_rejected_mgr
        all_unique_emp_codes |= all_codes_mgr

        manager_list.append({
            "reportingEmpCode": info["reportingEmpCode"],
            "reportingEmpName": info["reportingEmpName"],
            "totalPending": total_pending_mgr,
            "totalApproved": total_approved_mgr,
            "totalRejected": total_rejected_mgr,
            "totalEmployees": total_emps_mgr,
            "pendingEmployees": info["pendingEmployees"],
            "approvedEmployees": info["approvedEmployees"],
            "rejectedEmployees": info["rejectedEmployees"],
        })

    return {
        "success": True,
        "summary": {
            "totalManagers": len(manager_list),
            "totalPendingEmployees": total_pending,
            "totalApprovedEmployees": total_approved,
            "totalRejectedEmployees": total_rejected,
            "totalUniqueEmployees": len(all_unique_emp_codes)
        },
        "managerWise": manager_list
    }
