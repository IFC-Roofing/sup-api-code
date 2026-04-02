#!/bin/bash
# Sup Mission Control — Start Server
# Usage: bash tools/mission-control/start.sh

cd "$(dirname "$0")"

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "Creating venv..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q fastapi uvicorn httpx python-dotenv google-auth google-auth-oauthlib google-api-python-client
else
  source .venv/bin/activate
fi

echo "Starting Sup Mission Control on http://localhost:8080"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
