from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from passlib.context import CryptContext
from pymongo import MongoClient
import os
import re
from dotenv import load_dotenv
from db import *
from fastapi import APIRouter

load_dotenv()

class AdminLoginRequest(BaseModel):
    userid: str
    password: str

class AdminRegisterRequest(BaseModel):
    userid: str
    password: str

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b", bcrypt__rounds=12)


# Define frontend path
frontend_path = os.path.join(os.path.dirname(__file__), "static")
print("Frontend path:", frontend_path)
if os.path.exists(frontend_path):
    print("Files in frontend:", os.listdir(frontend_path))
else:
    print(f"Frontend directory not found at: {frontend_path}")

admin_router = APIRouter()

@admin_router.get("/admin", response_class=FileResponse)
async def admin_page():
    return FileResponse(os.path.join(frontend_path, "admin.html"))

@admin_router.post("/admin-login")
async def admin_login(request: AdminLoginRequest):
    userid = request.userid.strip().upper()
    password = request.password

    if not userid or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin ID and password are required")

    # Find admin in MongoDB
    admin = admin_details_collection.find_one({"userid": userid})
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

    # Verify password
    if not pwd_context.verify(password, admin["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Admin ID or Password")

    return {"success": True, "message": "Login successful", "redirect": "/admin-dashboard"}

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
        "password": hashed_password
    })

    return {"success": True, "message": f"Admin {userid} created successfully!"}

@admin_router.get("/admin-dashboard", response_class=FileResponse)
async def admin_dashboard():
    return FileResponse(os.path.join(frontend_path, "dashboard.html"))


