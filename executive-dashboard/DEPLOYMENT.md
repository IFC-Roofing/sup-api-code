# Deployment Guide

Complete deployment guide for IFC Executive Dashboard to sup.ifcroofing.com.

## Prerequisites

- Ubuntu 20.04+ server
- Domain: sup.ifcroofing.com pointing to server IP
- Root or sudo access
- Python 3.10+
- Node.js 18+
- Nginx
- Git

## Step 1: Server Setup

### Install dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install -y python3.10 python3.10-venv python3-pip

# Install Node.js 18
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install Nginx
sudo apt install -y nginx

# Install certbot for SSL
sudo apt install -y certbot python3-certbot-nginx

# Install git if not present
sudo apt install -y git
```

## Step 2: Clone and Deploy Code

### Clone repository

```bash
# Create deployment directory
sudo mkdir -p /opt/executive-dashboard
sudo chown $USER:$USER /opt/executive-dashboard

# Clone repo (or copy files)
cd /opt/executive-dashboard
# ... copy your code here
```

### Backend setup

```bash
cd /opt/executive-dashboard/backend

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
nano .env  # Edit with your credentials
```

### Frontend build

```bash
cd /opt/executive-dashboard/frontend

# Install dependencies
npm install

# Create .env file
cp .env.example .env
nano .env  # Edit with your credentials

# Build for production
npm run build

# Verify dist/ directory created
ls -la dist/
```

## Step 3: Google OAuth Configuration

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create/select project
3. Enable Google+ API
4. Create OAuth 2.0 credentials:
   - Type: Web application
   - Name: IFC Executive Dashboard
   - Authorized JavaScript origins:
     - `https://sup.ifcroofing.com`
   - Authorized redirect URIs:
     - `https://sup.ifcroofing.com/auth/callback`
5. Copy Client ID and Secret to backend/.env

## Step 4: Environment Configuration

### Backend .env

```env
# Google OAuth
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx

# JWT Secret (generate with: openssl rand -hex 32)
JWT_SECRET=your_random_secret_here

# IFC API
IFC_API_URL=https://omni.ifc.shibui.ar
IFC_API_TOKEN=your_ifc_api_token_here

# Optional: OpenClaw
OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=your_token_here
```

### Frontend .env

```env
VITE_GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
VITE_OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
VITE_OPENCLAW_GATEWAY_TOKEN=your_token_here
```

## Step 5: Systemd Service

### Create service file

```bash
sudo cp /opt/executive-dashboard/deploy/systemd-dashboard.service /etc/systemd/system/ifc-dashboard.service
```

### Edit service file if paths differ

```bash
sudo nano /etc/systemd/system/ifc-dashboard.service
```

Update `WorkingDirectory`, `Environment`, and `ExecStart` paths if needed.

### Enable and start service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable ifc-dashboard

# Start service
sudo systemctl start ifc-dashboard

# Check status
sudo systemctl status ifc-dashboard

# View logs
sudo journalctl -u ifc-dashboard -f
```

## Step 6: Nginx Configuration

### Copy nginx config

```bash
sudo cp /opt/executive-dashboard/deploy/nginx.conf /etc/nginx/sites-available/sup.ifcroofing.com
sudo ln -s /etc/nginx/sites-available/sup.ifcroofing.com /etc/nginx/sites-enabled/
```

### Test configuration

```bash
sudo nginx -t
```

### Reload nginx

```bash
sudo systemctl reload nginx
```

## Step 7: SSL Certificate

### Generate Let's Encrypt certificate

```bash
sudo certbot --nginx -d sup.ifcroofing.com
```

Follow prompts:
- Enter email
- Agree to terms
- Choose to redirect HTTP to HTTPS (recommended)

### Auto-renewal

Certbot auto-renewal is enabled by default. Test with:

```bash
sudo certbot renew --dry-run
```

## Step 8: Firewall

```bash
# Allow HTTP, HTTPS, and SSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp

# Enable firewall
sudo ufw enable
sudo ufw status
```

## Step 9: Verify Deployment

1. Visit https://sup.ifcroofing.com
2. Should see login screen with Google OAuth button
3. Log in with @ifcroofing.com or @ifccontracting.com email
4. Verify all widgets load correctly
5. Test chat functionality
6. Check browser console for errors

## Monitoring & Maintenance

### Check service status

```bash
sudo systemctl status ifc-dashboard
```

### View logs

```bash
# Application logs
sudo journalctl -u ifc-dashboard -f

# Nginx access logs
sudo tail -f /var/log/nginx/sup.ifcroofing.com.access.log

# Nginx error logs
sudo tail -f /var/log/nginx/sup.ifcroofing.com.error.log
```

### Restart service

```bash
sudo systemctl restart ifc-dashboard
```

### Update deployment

```bash
# Pull latest code
cd /opt/executive-dashboard
git pull  # or copy new files

# Rebuild frontend
cd frontend
npm install  # if package.json changed
npm run build

# Restart backend
sudo systemctl restart ifc-dashboard

# Clear nginx cache if needed
sudo systemctl reload nginx
```

## Troubleshooting

### Service won't start

```bash
# Check logs for errors
sudo journalctl -u ifc-dashboard -n 50

# Verify Python dependencies
cd /opt/executive-dashboard/backend
source venv/bin/activate
pip list

# Test manually
python main.py
```

### 502 Bad Gateway

- Check if backend service is running: `sudo systemctl status ifc-dashboard`
- Verify port 8091 is listening: `sudo netstat -tlnp | grep 8091`
- Check nginx config: `sudo nginx -t`

### OAuth errors

- Verify Google OAuth credentials in .env
- Check authorized redirect URIs in Google Console
- Ensure domain matches exactly (https://sup.ifcroofing.com)

### API errors

- Verify IFC_API_TOKEN is correct
- Check IFC API is accessible: `curl -H "Authorization: Bearer $IFC_API_TOKEN" https://omni.ifc.shibui.ar/projects`
- Review backend logs

### PWA not installing

- Verify HTTPS is working
- Check manifest.json is served correctly
- Verify service worker registered (browser dev tools)
- Icons must be present in /icons/

## Performance Optimization

### Enable gzip (already in nginx.conf)

Gzip compression is enabled for text assets.

### Cache static assets (already configured)

Static assets cached for 1 year with immutable cache-control.

### Database/API caching

Consider adding Redis for caching IFC API responses:

```bash
sudo apt install -y redis-server
pip install redis
```

Update backend code to cache frequently accessed data.

### CDN (optional)

For better global performance, consider CloudFlare or similar CDN.

## Backup Strategy

### Automated backups

```bash
# Create backup script
sudo nano /opt/backup-dashboard.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/backups/dashboard"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup .env files
cp /opt/executive-dashboard/backend/.env $BACKUP_DIR/backend-env-$DATE
cp /opt/executive-dashboard/frontend/.env $BACKUP_DIR/frontend-env-$DATE

# Backup configs
cp /etc/nginx/sites-available/sup.ifcroofing.com $BACKUP_DIR/nginx-$DATE.conf
cp /etc/systemd/system/ifc-dashboard.service $BACKUP_DIR/service-$DATE

# Keep only last 30 days
find $BACKUP_DIR -name "*.env" -mtime +30 -delete
find $BACKUP_DIR -name "*.conf" -mtime +30 -delete

echo "Backup completed: $DATE"
```

```bash
# Make executable
sudo chmod +x /opt/backup-dashboard.sh

# Add to crontab (daily at 2 AM)
sudo crontab -e
# Add line:
0 2 * * * /opt/backup-dashboard.sh
```

## Scaling Considerations

### Horizontal scaling

Use multiple uvicorn workers (already configured with --workers 4).

### Load balancing

For multiple servers, add nginx upstream:

```nginx
upstream dashboard_backend {
    server 127.0.0.1:8091;
    server 127.0.0.1:8092;
    # ...
}
```

### Database

Currently using IFC API. For local state, consider PostgreSQL.

## Security Checklist

- ✅ HTTPS enforced
- ✅ Security headers configured
- ✅ Google OAuth with domain restriction
- ✅ httpOnly cookies for JWT
- ✅ Firewall enabled
- ✅ Systemd service security hardening
- ✅ No sensitive data in git
- ✅ .env files protected (not in git)

## Support

For deployment issues, contact the development team or check logs as described above.
