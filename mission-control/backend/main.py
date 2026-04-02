"""
Sup Mission Control — Backend
FastAPI server that bridges frontend to IFC API, Drive, and OpenClaw Gateway.
"""
import os
import json
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from dotenv import load_dotenv

# Load env from workspace root
WORKSPACE = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(WORKSPACE / ".env")

IFC_API_BASE = "https://omni.ifc.shibui.ar"
IFC_API_TOKEN = os.getenv("IFC_API_TOKEN", "")
OPENCLAW_GW = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "4f01cf3f3407f090ed8c9c1f61248d1330e54c02665d9753")
GOOGLE_CREDS_PATH = WORKSPACE / "google-drive-key.json"

app = FastAPI(title="Sup Mission Control", version="0.1.0")

# ── IFC API proxy ──────────────────────────────────────────────

def ifc_headers():
    return {"Authorization": f"Bearer {IFC_API_TOKEN}"}

@app.get("/api/projects/search")
async def search_projects(q: str = Query(..., min_length=1)):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{IFC_API_BASE}/projects", params={"search": q}, headers=ifc_headers())
        r.raise_for_status()
        return r.json()

@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{IFC_API_BASE}/projects/{project_id}", headers=ifc_headers())
        r.raise_for_status()
        return r.json()

@app.get("/api/projects/{project_id}/posts")
async def get_posts(project_id: int):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{IFC_API_BASE}/posts", params={"project_id": project_id}, headers=ifc_headers())
        r.raise_for_status()
        return r.json()

@app.get("/api/projects/{project_id}/flow")
async def get_flow(project_id: int):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{IFC_API_BASE}/action_trackers", params={"project_id": project_id}, headers=ifc_headers())
        r.raise_for_status()
        return r.json()

@app.get("/api/tasks")
async def get_tasks():
    """Get supplement-relevant projects. Uses known project names for demo."""
    # Demo: pull a few known projects to populate the task list
    demo_names = ["Nick Schmidt", "Robin Engle", "Rose Brock", "Chris Isbell", "Brian Steffek"]
    all_projects = []
    
    async with httpx.AsyncClient(timeout=15) as c:
        for name in demo_names:
            try:
                r = await c.get(f"{IFC_API_BASE}/projects", 
                              params={"search": name}, headers=ifc_headers())
                if r.status_code == 200:
                    data = r.json()
                    for p in data.get("projects", []):
                        if name.lower() in p.get("name", "").lower():
                            all_projects.append(p)
                            break
            except Exception:
                continue
    
    return {"projects": all_projects}

# ── Drive API ──────────────────────────────────────────────────

def get_drive_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(
        str(GOOGLE_CREDS_PATH),
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)

@app.get("/api/drive/list/{folder_id}")
async def list_drive_folder(folder_id: str):
    try:
        drive = get_drive_service()
        results = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType,webViewLink)",
            pageSize=100
        ).execute()
        return {"files": results.get("files", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── OpenClaw Chat proxy ───────────────────────────────────────

@app.post("/api/chat")
async def chat_proxy(request: Request):
    """Proxy chat to OpenClaw Gateway's Chat Completions endpoint."""
    body = await request.json()
    
    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Build the OpenClaw request
    payload = {
        "model": "openclaw:dashboard",
        "messages": body.get("messages", []),
        "stream": body.get("stream", False),
        "user": body.get("user", "mission-control"),
    }
    
    # Skills like @calling/@estimate can take 3-5 min (API calls + AI generation)
    CHAT_TIMEOUT = httpx.Timeout(connect=10, read=300, write=10, pool=10)
    
    if body.get("stream"):
        async def stream_response():
            async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as c:
                async with c.stream("POST", f"{OPENCLAW_GW}/v1/chat/completions",
                                     json=payload, headers=headers) as r:
                    async for line in r.aiter_lines():
                        if line:
                            yield line + "\n"
        return StreamingResponse(stream_response(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as c:
            r = await c.post(f"{OPENCLAW_GW}/v1/chat/completions",
                           json=payload, headers=headers)
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            return r.json()

# ── Estimate Edit ──────────────────────────────────────────────

@app.post("/api/estimate/edit")
async def edit_estimate(request: Request):
    """Apply edits to an existing estimate.json and re-render."""
    body = await request.json()
    prefix = body.get("prefix")
    edits = body.get("edits", [])
    
    if not prefix or not edits:
        raise HTTPException(status_code=400, detail="prefix and edits required")
    
    import subprocess
    edits_json = json.dumps(edits)
    pdf_gen = WORKSPACE / "tools" / "pdf-generator"
    
    result = subprocess.run(
        [str(pdf_gen / ".venv" / "bin" / "python"), str(pdf_gen / "edit_estimate.py"), prefix, edits_json],
        capture_output=True, text=True, cwd=str(pdf_gen), timeout=60
    )
    
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


# ── Decision Logging ──────────────────────────────────────────

@app.post("/api/decisions/log")
async def log_decision(request: Request):
    """Log a supplement decision to the Google Sheet."""
    body = await request.json()
    required = ["project_name", "project_id", "trade", "decision", "ordered_by"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    import subprocess
    decisions_dir = WORKSPACE / "tools" / "decisions"
    
    result = subprocess.run(
        [str(WORKSPACE / "tools" / "pdf-generator" / ".venv" / "bin" / "python"),
         str(decisions_dir / "log_decision.py"),
         body["project_name"], str(body["project_id"]), body["trade"],
         body["decision"], body["ordered_by"]],
        capture_output=True, text=True, cwd=str(decisions_dir), timeout=15
    )
    
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


# ── Health ─────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "ifc_api": bool(IFC_API_TOKEN),
        "openclaw_gw": OPENCLAW_GW,
        "drive_creds": GOOGLE_CREDS_PATH.exists(),
    }

# ── Serve frontend ────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
