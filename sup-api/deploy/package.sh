#!/bin/bash
# Sup AI — Create deployment package
# Creates a tar.gz with everything needed for server deployment.
#
# Usage: bash tools/sup-api/deploy/package.sh
# Output: ~/sup-deploy-package.tar.gz

set -e

WORKSPACE="/Users/IFCSUP/.openclaw/workspace"
OUTPUT="$HOME/sup-deploy-package"

echo "🏗️  Creating Sup AI deployment package..."

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"

# ── Sup API service ────────────────────────────────────
echo "  Copying sup-api..."
mkdir -p "$OUTPUT/tools/sup-api/deploy"
cp "$WORKSPACE/tools/sup-api/main.py" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/learning_service.py" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/enhanced_learning.py" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/pricelist_manager.py" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/requirements.txt" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/start.sh" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/Dockerfile" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/README.md" "$OUTPUT/tools/sup-api/"
cp "$WORKSPACE/tools/sup-api/DEPLOYMENT_REQUEST.md" "$OUTPUT/tools/sup-api/"
cp -r "$WORKSPACE/tools/sup-api/deploy/"* "$OUTPUT/tools/sup-api/deploy/"

# ── PDF Generator ──────────────────────────────────────
echo "  Copying pdf-generator..."
mkdir -p "$OUTPUT/tools/pdf-generator/assets"
mkdir -p "$OUTPUT/tools/pdf-generator/templates"
cp "$WORKSPACE/tools/pdf-generator/"*.py "$OUTPUT/tools/pdf-generator/"
cp "$WORKSPACE/tools/pdf-generator/f9_matrix.json" "$OUTPUT/tools/pdf-generator/" 2>/dev/null || true
cp "$WORKSPACE/tools/pdf-generator/assets/"* "$OUTPUT/tools/pdf-generator/assets/" 2>/dev/null || true
cp "$WORKSPACE/tools/pdf-generator/templates/"* "$OUTPUT/tools/pdf-generator/templates/" 2>/dev/null || true

# ── Skills ─────────────────────────────────────────────
echo "  Copying skills..."
mkdir -p "$OUTPUT/tools/skills/prompts"
cp "$WORKSPACE/tools/skills/"*.py "$OUTPUT/tools/skills/" 2>/dev/null || true
cp "$WORKSPACE/tools/skills/prompts/"*.md "$OUTPUT/tools/skills/prompts/" 2>/dev/null || true

# ── Profit Margin ──────────────────────────────────────
echo "  Copying profit-margin..."
mkdir -p "$OUTPUT/tools/profit-margin"
cp "$WORKSPACE/tools/profit-margin/"*.py "$OUTPUT/tools/profit-margin/" 2>/dev/null || true

# ── Bid Markup ─────────────────────────────────────────
echo "  Copying bid-markup..."
mkdir -p "$OUTPUT/tools/bid-markup"
cp "$WORKSPACE/tools/bid-markup/"*.py "$OUTPUT/tools/bid-markup/" 2>/dev/null || true

# ── File Puller ─────────────────────────────────────────
echo "  Copying file-puller..."
mkdir -p "$OUTPUT/tools/file-puller"
cp "$WORKSPACE/tools/file-puller/"*.py "$OUTPUT/tools/file-puller/" 2>/dev/null || true

# ── Parsers ────────────────────────────────────────────
echo "  Copying parsers..."
mkdir -p "$OUTPUT/tools/parsers"
cp "$WORKSPACE/tools/parsers/"*.py "$OUTPUT/tools/parsers/" 2>/dev/null || true

# ── Root files (NO credentials) ───────────────────────
echo "  Copying config templates..."
cp "$WORKSPACE/tools/sup-api/deploy/env-template" "$OUTPUT/.env.template"

# ── Create tar.gz ──────────────────────────────────────
echo "  Creating archive..."
cd "$HOME"
tar -czf sup-deploy-package.tar.gz -C sup-deploy-package .

SIZE=$(du -sh "$HOME/sup-deploy-package.tar.gz" | cut -f1)
echo ""
echo "✅ Package created: ~/sup-deploy-package.tar.gz ($SIZE)"
echo ""
echo "To deploy:"
echo "  1. scp ~/sup-deploy-package.tar.gz server:/tmp/"
echo "  2. ssh server 'mkdir -p /opt/sup && tar -xzf /tmp/sup-deploy-package.tar.gz -C /opt/sup'"
echo "  3. ssh server 'bash /opt/sup/tools/sup-api/deploy/server-setup.sh'"
