# IFC Executive Dashboard

A modern, mobile-first PWA executive dashboard for IFC Roofing leadership. Built with Vue 3, FastAPI, and Tailwind CSS.

![IFC Logo](ifc_logo.png)

## Features

- **Google OAuth Authentication** - Restricted to @ifcroofing.com and @ifccontracting.com domains
- **Real-time Pipeline Dashboard** - Visual funnel showing job counts by status
- **Revenue Insights** - Total RCV, monthly/weekly capped amounts, average GP%
- **Activity Feed** - Recent Sup actions and project updates
- **Attention Alerts** - Flagged items needing immediate action
- **Chat with Sup** - AI assistant powered by OpenClaw gateway
- **PWA Support** - Installable on mobile devices, works offline
- **Dark Theme** - Professional, executive-focused design
- **Auto-refresh** - Updates every 5 minutes automatically

## Tech Stack

### Frontend
- Vue 3 (Composition API)
- Vite (build tool)
- Tailwind CSS (styling)
- Pinia (state management)
- Axios (HTTP client)
- Chart.js (future enhancements)
- Vite PWA (progressive web app)

### Backend
- FastAPI (Python web framework)
- Google OAuth 2.0 (authentication)
- JWT (session tokens)
- httpx (async HTTP client)
- IFC API integration

## Project Structure

```
executive-dashboard/
├── backend/                 # FastAPI backend
│   ├── main.py             # Main app, routes, static serving
│   ├── auth.py             # Google OAuth + JWT logic
│   ├── dashboard.py        # Dashboard data endpoints
│   ├── requirements.txt    # Python dependencies
│   └── .env.example        # Environment variables template
├── frontend/               # Vue 3 frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── widgets/    # Dashboard widgets
│   │   │   ├── common/     # Reusable components
│   │   │   ├── LoginScreen.vue
│   │   │   └── DashboardLayout.vue
│   │   ├── stores/         # Pinia stores
│   │   ├── styles/         # Tailwind CSS
│   │   ├── App.vue
│   │   ├── main.js
│   │   └── router.js
│   ├── public/
│   │   ├── ifc_logo.png
│   │   └── icons/          # PWA icons
│   ├── package.json
│   ├── vite.config.js
│   └── .env.example
├── deploy/                 # Deployment configs
│   ├── nginx.conf          # Nginx configuration
│   └── systemd-dashboard.service
├── SPEC.md                 # Product specification
└── README.md              # This file
```

## Setup Instructions

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm or yarn
- Google Cloud Console project with OAuth 2.0 credentials

### Backend Setup

1. Navigate to backend directory:
   ```bash
   cd backend
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create `.env` file from template:
   ```bash
   cp .env.example .env
   ```

5. Configure environment variables in `.env`:
   ```env
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   JWT_SECRET=$(openssl rand -hex 32)
   IFC_API_URL=https://omni.ifc.shibui.ar
   IFC_API_TOKEN=your_ifc_api_token
   ```

6. Run development server:
   ```bash
   python main.py
   # Or with uvicorn directly:
   uvicorn main:app --reload --port 8091
   ```

### Frontend Setup

1. Navigate to frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Create `.env` file from template:
   ```bash
   cp .env.example .env
   ```

4. Configure environment variables in `.env`:
   ```env
   VITE_GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   VITE_OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
   VITE_OPENCLAW_GATEWAY_TOKEN=your_token
   ```

5. Generate PWA icons (optional):
   ```bash
   npm install -g pwa-asset-generator
   pwa-asset-generator public/ifc_logo.png public/icons --icon-only --background "#0f172a" --padding "10%"
   ```

6. Run development server:
   ```bash
   npm run dev
   ```

7. Build for production:
   ```bash
   npm run build
   ```

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized JavaScript origins: `https://sup.ifcroofing.com`
   - Authorized redirect URIs: `https://sup.ifcroofing.com/auth/callback`
5. Copy Client ID and Client Secret to `.env` files

## Deployment

### Production Build

1. Build frontend:
   ```bash
   cd frontend
   npm run build
   ```

2. The backend automatically serves `frontend/dist/` as static files.

### Nginx Configuration

1. Copy nginx config:
   ```bash
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/sup.ifcroofing.com
   sudo ln -s /etc/nginx/sites-available/sup.ifcroofing.com /etc/nginx/sites-enabled/
   ```

2. Test and reload nginx:
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

### Systemd Service

1. Copy service file:
   ```bash
   sudo cp deploy/systemd-dashboard.service /etc/systemd/system/ifc-dashboard.service
   ```

2. Update paths in service file to match your deployment location.

3. Enable and start service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable ifc-dashboard
   sudo systemctl start ifc-dashboard
   sudo systemctl status ifc-dashboard
   ```

### SSL Certificate

Use certbot for Let's Encrypt SSL:
```bash
sudo certbot --nginx -d sup.ifcroofing.com
```

## Development

### Running Both Servers

Terminal 1 (Backend):
```bash
cd backend
source venv/bin/activate
python main.py
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Frontend dev server (http://localhost:5173) will proxy API requests to backend (http://localhost:8091).

### Adding New Widgets

1. Create new widget component in `frontend/src/components/widgets/`
2. Add backend endpoint in `backend/dashboard.py` if needed
3. Add route in `backend/main.py` if needed
4. Import and use widget in `DashboardLayout.vue`

## API Endpoints

### Authentication
- `POST /auth/google` - Google OAuth login
- `GET /auth/me` - Get current user
- `POST /auth/logout` - Logout

### Dashboard
- `GET /api/dashboard/pipeline` - Pipeline funnel data
- `GET /api/dashboard/revenue` - Revenue snapshot
- `GET /api/dashboard/activity` - Recent activity feed
- `GET /api/dashboard/attention` - Jobs needing attention

### Health
- `GET /api/health` - Health check

## Environment Variables

### Backend (.env)
- `GOOGLE_CLIENT_ID` - Google OAuth client ID
- `GOOGLE_CLIENT_SECRET` - Google OAuth client secret
- `JWT_SECRET` - Secret for JWT token signing
- `IFC_API_URL` - IFC API base URL
- `IFC_API_TOKEN` - IFC API bearer token
- `OPENCLAW_GATEWAY_URL` - OpenClaw gateway URL (optional)
- `OPENCLAW_GATEWAY_TOKEN` - OpenClaw auth token (optional)

### Frontend (.env)
- `VITE_GOOGLE_CLIENT_ID` - Google OAuth client ID
- `VITE_OPENCLAW_GATEWAY_URL` - OpenClaw gateway URL
- `VITE_OPENCLAW_GATEWAY_TOKEN` - OpenClaw auth token

## Security

- Google OAuth restricted to @ifcroofing.com and @ifccontracting.com domains
- JWT session tokens with httpOnly cookies
- HTTPS enforced in production
- CORS configured for production domain
- Security headers (HSTS, X-Frame-Options, etc.)

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## License

Proprietary - IFC Roofing & Contracting

## Support

For issues or feature requests, contact the development team.
