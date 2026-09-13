#!/bin/bash
# SentinelEdge start script
# Run from the sentineledge/ root directory.

set -e
echo "═══════════════════════════════════════════"
echo "  SentinelEdge — Starting up"
echo "═══════════════════════════════════════════"

# Navigate to script directory (works from anywhere)
cd "$(dirname "$0")"

# Ensure required directories exist
mkdir -p logs database

# Activate virtualenv (create it first if missing)
if [ ! -d "venv" ]; then
  echo "[setup] Creating Python virtual environment..."
  python3 -m venv venv
  echo "[setup] Installing backend dependencies..."
  source venv/bin/activate
  pip install --quiet -r backend/requirements.txt
else
  source venv/bin/activate
fi

# Build the React frontend
echo "[web] Building frontend..."
cd frontend-web
npm install --silent
npm run build
cd ..

# Copy built assets into backend/static for FastAPI to serve
echo "[web] Copying dist to backend/static..."
rm -rf backend/static
cp -r frontend-web/dist backend/static

# Set Python path
export PYTHONPATH="$(pwd)/backend"

# Start the FastAPI server
echo "[server] Starting FastAPI on 0.0.0.0:8000..."
echo "[server] Logs → logs/sentineledge.log"
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --log-level info \
  2>&1 | tee -a logs/sentineledge.log
