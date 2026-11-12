@echo off
echo Starting LENS Backend Server on http://localhost:8003...
cd /d "%~dp0"
..\..\taxora\backend\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8003 --reload

