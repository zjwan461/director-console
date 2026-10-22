#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# ---------------------------------------------------------------
# 解释器：优先仓库里的 .venv（install.py 建的），其次 $PYTHON，最后 python3/python
# ---------------------------------------------------------------
PY="${PYTHON:-}"
if [ -z "$PY" ] && [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
fi
# Windows 上（Git Bash / MSYS）venv 的路径是 .venv/Scripts/python.exe
if [ -z "$PY" ] && [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
fi
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY="python3"; else PY="python"; fi
fi

if ! "$PY" -c "import sys" >/dev/null 2>&1; then
  echo "[错误] 找不到能用的 Python：$PY"
  echo "        先跑一次 install.py，或用 PYTHON 环境变量指定解释器，例如："
  echo "          PYTHON=/root/miniconda3/envs/dc/bin/python bash start.sh"
  exit 1
fi

# ---------------------------------------------------------------
# 端口占用检查（常见坑：上一次的进程没退干净，新进程绑定失败一闪而过）
# ---------------------------------------------------------------
port_pid() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnpH 'sport = :6006' 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:6006 -sTCP:LISTEN 2>/dev/null | head -n1
  fi
}

PORT_PID="$(port_pid || true)"
if [ -n "${PORT_PID}" ]; then
  echo "[错误] 6006 已被 PID ${PORT_PID} 占用，再启动会绑定失败。"
  echo "        结束它： kill ${PORT_PID}"
  exit 1
fi

if ! "$PY" -c "import fastapi, uvicorn, sqlalchemy, alembic" >/dev/null 2>&1; then
  echo "[1/2] 安装后端依赖到 $PY ..."
  "$PY" -m pip install -r backend/requirements.txt
fi

if [ ! -f web/dist/index.html ]; then
  echo "[2/2] 首次构建前端..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo
echo "解释器: $PY"
echo "导演台启动中: http://127.0.0.1:6006"
echo "关掉这个窗口 / Ctrl+C 就停服务。"
echo
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 6006 --app-dir backend
