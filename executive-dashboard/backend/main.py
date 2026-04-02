"""
Sup Executive Dashboard — FastAPI Backend
Serves Vue PWA frontend + auth + dashboard API + chat.
"""
import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

# Load env
WORKSPACE = Path(__file__).resolve().parent.parent
load_dotenv(WORKSPACE / ".env")

from backend.auth import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
    exchange_code, create_jwt, verify_jwt, get_current_user, get_redirect_uri
)
from backend.dashboard import router as dashboard_router
from backend.chat import router as chat_router

app = FastAPI(title="Sup Executive Dashboard", version="1.0.0")

# Include API routes
app.include_router(dashboard_router)
app.include_router(chat_router)

# ── Auth endpoints ──────────────────────────────────────────────

@app.get("/auth/config")
async def auth_config():
    """Return OAuth config for frontend (client ID only, no secrets)."""
    return {"client_id": GOOGLE_CLIENT_ID}


@app.post("/auth/google")
async def auth_google(request: Request):
    """Exchange Google auth code for JWT."""
    body = await request.json()
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    redirect_uri = body.get("redirect_uri", get_redirect_uri(request))
    user_info = await exchange_code(code, redirect_uri)
    token = create_jwt(user_info)

    response = JSONResponse({"ok": True, "user": {
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "picture": user_info.get("picture"),
    }})
    response.set_cookie(
        key="sup_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@app.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    """Get current user info from JWT."""
    return {
        "email": user.get("sub"),
        "name": user.get("name"),
        "picture": user.get("picture"),
    }


@app.post("/auth/logout")
async def auth_logout():
    """Clear auth cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie("sup_token")
    return response


# ── Health check ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "sup-executive-dashboard"}


# ── Serve Vue frontend (must be last) ──────────────────────────

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve Vue SPA — all non-API routes return index.html."""
        file_path = FRONTEND_DIST / path
        if file_path.is_file():
            return HTMLResponse(file_path.read_text())
        return HTMLResponse((FRONTEND_DIST / "index.html").read_text())
else:
    @app.get("/")
    async def no_frontend():
        return HTMLResponse("<h1>Frontend not built yet</h1><p>Run <code>cd frontend && npm run build</code></p>")
