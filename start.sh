#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "[1/3] 创建 Python 虚拟环境..."
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate
echo "[2/3] 安装后端依赖..."
pip install -q -r backend/requirements.txt

if [ ! -f web/dist/index.html ]; then
  echo "[3/3] 首次构建前端..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo
echo "导演台启动中: http://127.0.0.1:6200"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 6200 --app-dir backend
