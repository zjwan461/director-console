#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import fastapi, uvicorn, sqlalchemy, alembic" >/dev/null 2>&1; then
  echo "[1/2] 安装后端依赖到 $PYTHON ..."
  "$PYTHON" -m pip install -r backend/requirements.txt
fi

if [ ! -f web/dist/index.html ]; then
  echo "[2/2] 首次构建前端..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

echo
echo "导演台启动中: http://127.0.0.1:6006"
exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 6006 --app-dir backend
