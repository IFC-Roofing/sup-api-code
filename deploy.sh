#!/bin/bash
# Sup AI — Deploy from GitHub
# Usage: bash deploy.sh
#
# Pulls latest from GitHub on the server, syncs to working directories,
# preserves venvs and credentials, restarts the service.

set -e

SERVER="root@sup.ifcroofing.com"
REPO_DIR="/opt/sup-repo"
WORK_DIR="/opt/sup-repo/tools"

echo "🏗️  Deploying Sup AI from GitHub..."

# Pull latest code on server
echo "  Pulling latest from GitHub..."
ssh -o BatchMode=yes $SERVER "cd $REPO_DIR && git pull origin main"

# Sync repo files → working directories (where venvs + systemd point)
echo "  Syncing to working directories..."
ssh -o BatchMode=yes $SERVER bash -s <<'REMOTE'
set -e
REPO="/opt/sup-repo"
WORK="/opt/sup-repo/tools"

# sup-api: sync all .py files
for f in "$REPO"/sup-api/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/sup-api/$(basename "$f")"
done

# pdf-generator: sync all .py and .json files
for f in "$REPO"/pdf-generator/*.py "$REPO"/pdf-generator/*.json; do
    [ -f "$f" ] && cp "$f" "$WORK/pdf-generator/$(basename "$f")"
done

# pdf-generator templates + assets
[ -d "$REPO/pdf-generator/templates" ] && cp -r "$REPO/pdf-generator/templates/"* "$WORK/pdf-generator/templates/" 2>/dev/null || true
[ -d "$REPO/pdf-generator/assets" ] && cp -r "$REPO/pdf-generator/assets/"* "$WORK/pdf-generator/assets/" 2>/dev/null || true

# skills
for f in "$REPO"/skills/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/skills/$(basename "$f")"
done
[ -d "$REPO/skills/prompts" ] && cp -r "$REPO/skills/prompts/"* "$WORK/skills/prompts/" 2>/dev/null || true

# bid-markup
for f in "$REPO"/bid-markup/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/bid-markup/$(basename "$f")"
done

# profit-margin
for f in "$REPO"/profit-margin/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/profit-margin/$(basename "$f")"
done

# file-puller
for f in "$REPO"/file-puller/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/file-puller/$(basename "$f")"
done

# parsers
for f in "$REPO"/parsers/*.py; do
    [ -f "$f" ] && cp "$f" "$WORK/parsers/$(basename "$f")"
done

# Also sync to /opt/sup/tools/sup-api/ (where systemd points)
cp "$WORK/sup-api/main.py" /opt/sup/tools/sup-api/main.py

# Fix ownership
chown -R sup:sup "$WORK" /opt/sup/tools/sup-api/main.py
REMOTE

# Restart service
echo "  Restarting sup-api..."
ssh -o BatchMode=yes $SERVER "systemctl restart sup-api"

# Health check
echo "  Health check..."
sleep 2
HEALTH=$(ssh -o BatchMode=yes $SERVER "curl -s https://sup.ifcroofing.com/v1/health")
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "FAILED")

if [ "$STATUS" = "ok" ]; then
    echo ""
    echo "✅ Deploy complete. Server healthy."
else
    echo ""
    echo "❌ Deploy complete but health check failed!"
    echo "$HEALTH"
    exit 1
fi
