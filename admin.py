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

# def verify_token(token: str):
#     """Verify JWT token"""
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         userid = payload.get("sub")
#         if userid is None:
#             raise HTTPException(status_code=401, detail="Invalid token")
#         return userid
#     except jwt.ExpiredSignatureError:
#         raise HTTPException(status_code=401, detail="Session expired. Please login again.")
#     except jwt.InvalidTokenError:
#         raise HTTPException(status_code=401, detail="Invalid token")

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


# @admin_router.post("/create-admin")
# async def create_admin(request: AdminRegisterRequest):
#     userid = request.userid.strip().upper()
#     password = request.password

#     # Validation
#     if len(password) < 8:
#         raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
#     if not re.search(r"[A-Z]", password):
#         raise HTTPException(status_code=400, detail="Must include uppercase letter")
#     if not re.search(r"[a-z]", password):
#         raise HTTPException(status_code=400, detail="Must include lowercase letter")
#     if not re.search(r"\d", password):
#         raise HTTPException(status_code=400, detail="Must include number")
#     if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
#         raise HTTPException(status_code=400, detail="Must include special character")

#     # Check if admin exists
#     existing_admin = admin_details_collection.find_one({"userid": userid})
#     if existing_admin:
#         raise HTTPException(status_code=400, detail="Admin already exists")

#     hashed_password = pwd_context.hash(password)
#     admin_details_collection.insert_one({
#         "userid": userid,
#         "password": hashed_password,
#         "par_status": "disable"
#     })

#     return {"success": True, "message": f"Admin {userid} created successfully!"}


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


# ---------------- JWT FUNCTIONS ----------------
def create_access_token(data: dict, expires_delta: timedelta = None):
    """Generate JWT token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        userid = payload.get("sub")
        if userid is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return userid
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
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

    # ✅ Create JWT access token
    access_token = create_access_token(data={"sub": userid})

    return {
        "success": True,
        "message": "Login successful",
        "access_token": access_token,
        "userid": userid
    }

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
