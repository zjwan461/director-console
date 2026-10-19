@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist "backend\.venv" (
  echo [1/3] Creating Python venv...
  python -m venv backend\.venv || goto :err
)
call backend\.venv\Scripts\activate.bat
echo [2/3] Installing backend dependencies...
python -m pip install -q -r backend\requirements.txt || goto :err
if not exist "web\dist\index.html" (
  echo [3/3] Building frontend for the first time...
  pushd web
  call npm install --no-audit --no-fund || goto :err
  call npm run build || goto :err
  popd
)
echo.
echo Director Console: http://127.0.0.1:6200
echo Close this window to stop the service.
echo.
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 6200
goto :eof
:err
echo.
echo Startup failed. Check the errors above.
pause
