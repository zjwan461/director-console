@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if "%PYTHON%"=="" set "PYTHON=python"

"%PYTHON%" -c "import fastapi, uvicorn, sqlalchemy, alembic" >nul 2>&1
if errorlevel 1 (
  echo [1/2] Installing backend dependencies into %PYTHON% ...
  "%PYTHON%" -m pip install -r backend\requirements.txt || goto :err
)

if not exist "web\dist\index.html" (
  echo [2/2] Building frontend for the first time...
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
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 6200
goto :eof

:err
echo.
echo Startup failed. Check the errors above.
pause
