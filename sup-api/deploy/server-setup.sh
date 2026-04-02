#!/bin/bash
# Sup AI — Server Setup Script
# Run this on a fresh Ubuntu 22+ server after SSH access is granted.
#
# Usage: bash server-setup.sh
# Assumes: root or sudo access, Ubuntu 22+

set -e

echo "🏗️  Sup AI — Server Setup"
echo "========================="
echo ""

# ── System Dependencies ────────────────────────────────────
echo "1/6 Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.11 python3.11-venv python3.11-dev \
    build-essential \
    libgobject-2.0-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    fonts-liberation \
    nginx \
    certbot python3-certbot-nginx \
    git \
    curl

echo "✅ System dependencies installed"

# ── Create Sup User & Directory ────────────────────────────
echo ""
echo "2/6 Setting up sup user and directory..."
sudo useradd -m -s /bin/bash sup 2>/dev/null || echo "   sup user already exists"
sudo mkdir -p /opt/sup
sudo chown sup:sup /opt/sup

echo "✅ Directory ready: /opt/sup"

# ── Deploy Code ────────────────────────────────────────────
echo ""
echo "3/6 Deploying Sup AI code..."

# This assumes the deployment package has been copied to /tmp/sup-deploy/
if [ -d "/tmp/sup-deploy" ]; then
    sudo cp -r /tmp/sup-deploy/* /opt/sup/
    sudo chown -R sup:sup /opt/sup
    echo "✅ Code deployed from /tmp/sup-deploy/"
else
    echo "⚠️  /tmp/sup-deploy/ not found. Copy deployment package first:"
    echo "   scp -r sup-deploy-package/ server:/tmp/sup-deploy/"
fi

# ── Python Virtual Environment ─────────────────────────────
echo ""
echo "4/6 Setting up Python environment..."

sudo -u sup bash -c '
    cd /opt/sup/tools/sup-api
    python3.11 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo "   sup-api deps installed"
'

# Also set up pdf-generator venv
sudo -u sup bash -c '
    cd /opt/sup/tools/pdf-generator
    python3.11 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip -q
    pip install weasyprint jinja2 anthropic google-api-python-client google-auth PyMuPDF requests python-dotenv -q
    echo "   pdf-generator deps installed"
'

echo "✅ Python environments ready"

# ── Systemd Service ────────────────────────────────────────
echo ""
echo "5/6 Setting up systemd service..."

sudo tee /etc/systemd/system/sup-api.service > /dev/null << 'EOF'
[Unit]
Description=Sup AI Microservice
After=network.target

[Service]
Type=simple
User=sup
Group=sup
WorkingDirectory=/opt/sup/tools/sup-api
EnvironmentFile=/opt/sup/.env
ExecStart=/opt/sup/tools/sup-api/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8090 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sup-api

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sup-api
echo "✅ Systemd service configured"

# ── Nginx Reverse Proxy ───────────────────────────────────
echo ""
echo "6/6 Setting up nginx reverse proxy..."

DOMAIN="${SUP_DOMAIN:-sup.ifcroofing.com}"

sudo tee /etc/nginx/sites-available/sup-api > /dev/null << EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Long timeout for estimate generation (5-10 min)
        proxy_read_timeout 660;
        proxy_connect_timeout 10;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/sup-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "✅ Nginx configured for ${DOMAIN}"

# ── Summary ────────────────────────────────────────────────
echo ""
echo "==============================="
echo "🏗️  Server Setup Complete!"
echo "==============================="
echo ""
echo "Next steps:"
echo "  1. Copy .env file:        scp .env server:/opt/sup/.env"
echo "  2. Copy credentials:      scp google-drive-key.json server:/opt/sup/"
echo "  3. Start the service:     sudo systemctl start sup-api"
echo "  4. Check status:          sudo systemctl status sup-api"
echo "  5. Test health:           curl http://localhost:8090/v1/health"
echo "  6. Setup SSL:             sudo certbot --nginx -d ${DOMAIN}"
echo ""
echo "Logs: journalctl -u sup-api -f"
echo ""
