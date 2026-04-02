# Sup AI — Deployment Request for Dev Team

## What We Need

### 1. A Linux Server
- **Ubuntu 22+** (or any Linux with Python 3.11+)
- **2GB RAM**, 20GB storage
- **Ports:** 8090 (API), 22 (SSH)
- Can be a VPS, Docker host, or existing server with capacity

### 2. Domain / Subdomain
- Something like `sup.ifcroofing.com` pointing to the server
- SSL certificate (Let's Encrypt is fine)

### 3. SSH Access
- We need SSH access to deploy and maintain the service
- Public key will be provided separately

### 4. Two Environment Variables in Rails
After we deploy the service, add these to the Rails app's `.env`:
```
SUP_API_URL=https://sup.ifcroofing.com
SUP_API_KEY=<we will generate this>
```

### 5. Run One Command in Rails
```bash
rake sup_external:setup
```
This registers 5 AI tools in the database and links them to the supplement chat tab. Takes 10 seconds.

---

## What This Does

The Sup AI microservice handles supplement intelligence:
- **Generates supplement PDFs** with AI-driven estimates and F9 justifications
- **Learns from outcomes** — tracks what works per carrier, adjuster, strategy, season
- **Recommends approaches** — provides data-driven intelligence for each supplement
- **Manages pricelists** — ensures version consistency across supplement iterations

### Architecture
```
IFC Rails App                         Sup AI Server (NEW)
┌─────────────┐     HTTPS/JSON       ┌─────────────────┐
│ SUP chat tab │ ──────────────────→  │ FastAPI service  │
│ (existing)   │                      │ Learning engine  │
│              │ ←──────────────────  │ PDF pipeline     │
│ 5 AI tools   │  {pdf, intelligence} │ SQLite DB        │
└─────────────┘                       └─────────────────┘
```

**Zero changes to the Rails codebase.** The 5 tool files are already committed. They just need the URL to point to.

---

## What We Handle (No Dev Team Work)

- All code deployment and updates
- Learning algorithm maintenance
- PDF generation pipeline
- Bug fixes and improvements
- API key management
- Service monitoring

## What Dev Team Handles (One-Time)

- Provision the server
- Point a subdomain to it
- Add 2 env vars to Rails
- Run `rake sup_external:setup`

**Estimated dev team time: 1-2 hours total.**

---

## Server Setup (We Do This)

Once we have SSH access, we handle:

1. Install Python 3.11 + system dependencies
2. Deploy the Sup API service
3. Configure systemd for auto-restart
4. Set up nginx reverse proxy + SSL
5. Configure all API keys and credentials
6. Test end-to-end integration
7. Ongoing maintenance and updates

---

## Timeline

| Step | Who | Time |
|------|-----|------|
| Provision server + subdomain | Dev team | 1 hour |
| Deploy Sup AI service | Us | 2-3 hours |
| Add env vars + run rake task | Dev team | 15 min |
| End-to-end testing | Us | 1 hour |
| **Total** | | **~1 day** |

## Questions?

Reach out to Alvaro — he can walk through any technical details.
