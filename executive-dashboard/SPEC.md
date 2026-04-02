# Executive Dashboard — Sup PWA

## Overview
Executive dashboard PWA for IFC Roofing leadership. Installable on phone, visually polished, modular widget system. Will Merrifield is the primary user — he's visual and will add requests over time.

## Tech Stack
- **Frontend:** Vue 3 + Vite + Tailwind CSS + Chart.js
- **Backend:** FastAPI (Python) — extends existing Sup API on sup.ifcroofing.com
- **Auth:** Google OAuth 2.0 (restricted to @ifcroofing.com and @ifccontracting.com)
- **PWA:** Vite PWA plugin (manifest.json, service worker, installable)

## URL Structure
- `sup.ifcroofing.com` → Dashboard (Vue SPA)
- `sup.ifcroofing.com/v1/...` → Existing Sup API (untouched)

## Auth Flow
1. User hits sup.ifcroofing.com → Google OAuth login screen
2. Backend validates Google token, checks email domain (@ifcroofing.com or @ifccontracting.com)
3. Issues JWT session token (httpOnly cookie)
4. Frontend uses JWT for all API calls
5. Logout endpoint clears cookie

## Design
- **Dark theme** — dark slate/charcoal background, clean cards
- Professional, modern executive dashboard feel
- Cards with subtle shadows, rounded corners
- IFC branding (logo, colors)
- Fully responsive — mobile-first since Will wants it on his phone
- Smooth transitions/animations

## MVP Widgets (modular card system)
Each widget is a Vue component. Easy to add/remove/rearrange.

1. **Pipeline Funnel** — visual funnel or horizontal bar showing job counts by status (Office Hands → Sent → Response → Appraisal → Capped Out). Pull from IFC API project statuses.

2. **Revenue Snapshot** — cards showing:
   - Total RCV in active pipeline
   - Capped out this month ($)
   - Capped out this week ($)
   - Average GP%

3. **Recent Activity Feed** — timeline of what Sup has been doing:
   - Estimates generated
   - Bids marked up
   - Reviews completed
   - Pull from IFC API action history or Sup API logs

4. **Jobs Needing Attention** — flagged items:
   - Jobs missing bids
   - Jobs missing photos  
   - Jobs waiting on insurance response > X days
   - Jobs in Office Hands for too long

5. **Chat with Sup** — collapsible chat panel, connects to OpenClaw gateway /v1/chat/completions

## Backend Endpoints (new)
- `POST /auth/google` — Google OAuth callback, issues JWT
- `GET /auth/me` — current user info
- `POST /auth/logout` — clear session
- `GET /api/dashboard/pipeline` — pipeline status counts
- `GET /api/dashboard/revenue` — revenue snapshot data
- `GET /api/dashboard/activity` — recent Sup activity
- `GET /api/dashboard/attention` — jobs needing attention

## File Structure
```
tools/executive-dashboard/
├── SPEC.md
├── backend/
│   ├── main.py          (FastAPI app — auth + dashboard API endpoints)
│   ├── auth.py          (Google OAuth + JWT logic)
│   ├── dashboard.py     (Dashboard data endpoints)
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── public/
│   │   ├── ifc_logo.png
│   │   └── icons/       (PWA icons — 192x192, 512x512)
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── router.js
│       ├── stores/      (Pinia stores)
│       ├── components/
│       │   ├── LoginScreen.vue
│       │   ├── DashboardLayout.vue
│       │   ├── widgets/
│       │   │   ├── PipelineFunnel.vue
│       │   │   ├── RevenueSnapshot.vue
│       │   │   ├── ActivityFeed.vue
│       │   │   ├── AttentionItems.vue
│       │   │   └── ChatWidget.vue
│       │   └── common/
│       │       ├── WidgetCard.vue
│       │       └── LoadingSpinner.vue
│       └── styles/
│           └── tailwind.css
└── deploy/
    └── nginx.conf       (nginx config snippet)
```

## Deployment
- Build frontend: `npm run build` → produces dist/
- Backend serves dist/ as static files
- Same nginx reverse proxy as existing Sup API
- sup.ifcroofing.com root → dashboard
- sup.ifcroofing.com/v1 → existing Sup API

## Google OAuth Setup
Will need:
- Google Cloud Console project with OAuth 2.0 credentials
- Authorized redirect URI: https://sup.ifcroofing.com/auth/callback
- Client ID + Client Secret in .env

## Environment Variables (new)
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET  
- JWT_SECRET (random string for signing tokens)
