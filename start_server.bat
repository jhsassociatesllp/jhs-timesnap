@echo off
cd /d "%~dp0"
echo Current folder: %cd%
echo.
call venv\Scripts\activate.bat
uvicorn main:app --reload --port 8001
pause
