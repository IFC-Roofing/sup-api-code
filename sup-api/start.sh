#!/bin/bash
# Sup API — Start server
# Usage: bash tools/sup-api/start.sh [--prod]
#
# ENV vars:
#   SUP_API_KEY       — Required. Bearer token for auth.
#   SUP_WORKSPACE     — Optional. Defaults to ../../ (the openclaw workspace root).
#   SUP_PORT          — Optional. Defaults to 8090.
#   SUP_ENV           — Optional. "development" (default) or "production".
#   SUP_CORS_ORIGINS  — Optional. Comma-separated allowed origins.
#
# Required for pipeline (must be in workspace .env or exported):
#   ANTHROPIC_API_KEY — For AI estimate generation
#   IFC_TOKEN         — For IFC API data access
#   GOOGLE_API_KEY    — For insurance PDF parsing (Gemini vision)
#   google-drive-key.json — Service account key in workspace root

set -e

cd "$(dirname "$0")"

# Load workspace .env if it exists
WORKSPACE="${SUP_WORKSPACE:-$(cd ../.. && pwd)}"
if [ -f "$WORKSPACE/.env" ]; then
    set -a
    source "$WORKSPACE/.env"
    set +a
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "Creating venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    source .venv/bin/activate
fi

PORT="${SUP_PORT:-8090}"

# Check required env vars
if [ -z "$SUP_API_KEY" ]; then
    echo "⚠️  WARNING: SUP_API_KEY not set. All authenticated endpoints will fail."
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  WARNING: ANTHROPIC_API_KEY not set. Estimate generation will fail."
fi

if [ -z "$IFC_TOKEN" ]; then
    echo "⚠️  WARNING: IFC_TOKEN not set. Data pipeline will fail."
fi

# Production vs Development mode
if [ "$1" = "--prod" ] || [ "$SUP_ENV" = "production" ]; then
    export SUP_ENV=production
    echo "🏗️  Starting Sup API (PRODUCTION) on http://0.0.0.0:$PORT"
    echo "   Health: http://localhost:$PORT/v1/health"
    echo ""
    python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers 2
else
    export SUP_ENV=development
    echo "🏗️  Starting Sup API (DEV) on http://0.0.0.0:$PORT"
    echo "   Health: http://localhost:$PORT/v1/health"
    echo "   Docs:   http://localhost:$PORT/docs"
    echo ""
    python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
fi
