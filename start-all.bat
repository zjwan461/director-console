@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "ComfyUI" /D "D:\ComfyUI" "D:\ComfyUI\.venv\Scripts\python.exe" main.py --listen 127.0.0.1 --port 8188
timeout /t 5 >nul
"E:\workspaces\ai\director-console\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 6006 --app-dir backend
