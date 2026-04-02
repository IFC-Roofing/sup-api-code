"""
Google OAuth 2.0 + JWT auth for Executive Dashboard.
Restricted to @ifcroofing.com and @ifccontracting.com domains.
"""
import os
import time
import httpx
from jose import jwt, JWTError
from fastapi import HTTPException, Request, Depends
from fastapi.responses import JSONResponse

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

ALLOWED_DOMAINS = {"ifcroofing.com", "ifccontracting.com"}
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def get_redirect_uri(request: Request) -> str:
    """Build redirect URI from request (handles proxied requests)."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.hostname)
    return f"{scheme}://{host}/auth/callback"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens and user info."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Exchange code for access token
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to exchange code")
        tokens = token_resp.json()

        # Get user info
        userinfo_resp = await client.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        })
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to get user info")
        return userinfo_resp.json()


def create_jwt(user_info: dict) -> str:
    """Create JWT from Google user info."""
    email = user_info.get("email", "")
    domain = email.split("@")[-1] if "@" in email else ""

    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail=f"Domain {domain} not allowed")

    payload = {
        "sub": email,
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "iat": int(time.time()),
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify and decode JWT. Returns payload or raises."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(request: Request) -> dict:
    """Dependency: extract user from JWT cookie or Authorization header."""
    token = request.cookies.get("sup_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_jwt(token)
