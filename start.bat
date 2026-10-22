@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem 解释器：优先仓库里的 .venv（install.py 建的），其次 %PYTHON%，最后 PATH 里的 python
rem 注意：PATH 里的 python 可能是「应用商店占位程序」，一跑就 9009 退出
rem ---------------------------------------------------------------
set "PY=%PYTHON%"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if "%PY%"=="" set "PY=python"

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo [错误] 找不到能用的 Python：%PY%
  echo        PATH 里的 python 可能是应用商店的占位程序（运行会直接退出 9009）。
  echo        先跑一次 install.py，或用 PYTHON 环境变量指向真正的解释器，例如：
  echo          set PYTHON=D:\conda\envs\dc\python.exe
  pause
  exit /b 1
)

rem ---------------------------------------------------------------
rem 端口占用检查（常见坑：上一次的进程没退干净，新进程绑定失败一闪而过）
rem ---------------------------------------------------------------
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":6006" ^| findstr "LISTENING"') do (
  echo [错误] 6006 已被 PID %%p 占用，再启动会绑定失败。
  echo        结束它： taskkill /PID %%p /T /F
  pause
  exit /b 1
)

"%PY%" -c "import fastapi, uvicorn, sqlalchemy, alembic" >nul 2>&1
if errorlevel 1 (
  echo [1/2] 安装后端依赖 ...
  "%PY%" -m pip install -r backend\requirements.txt || goto :err
)

if not exist "web\dist\index.html" (
  echo [2/2] 首次构建前端 ...
  pushd web
  call npm install --no-audit --no-fund || goto :err
  call npm run build || goto :err
  popd
)

echo.
echo 解释器: %PY%
echo 导演台: http://127.0.0.1:6006
echo 关掉这个窗口就停服务。
echo.
cd backend
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 6006
goto :eof

:err
echo.
echo 启动失败，看上面的报错。
pause
exit /b 1
