"""
Sup API — External supplement service for IFC platform integration.

This is the bridge between the IFC Rails app and the Sup AI pipeline.
The IFC app calls these endpoints via HTTP; this service runs the Python
pipeline and returns structured results.

Deployable on: local dev, VPS, Docker, Railway, Fly.io — anywhere Python runs.

Endpoints:
    POST /v1/estimate      → Generate supplement PDF (with learning integration)
    POST /v1/markup        → Run bid markup analysis
    POST /v1/precall       → Generate pre-call script data
    POST /v1/calling       → Generate carrier call script data
    POST /v1/review        → Run QA review on supplement
    POST /v1/profit-margin → Generate itemized profit margin Google Sheet

    POST /v1/track_response → Track insurance response for learning
    GET  /v1/insights       → Dashboard insights summary
    GET  /v1/intelligence   → Strategy intelligence + recommendations
    GET  /v1/pricelists     → List available pricelists
    POST /v1/pricelists     → Register new pricelist
    GET  /v1/projects/{id}/pricelists → Project pricelist history
    GET  /v1/seasonal       → Seasonal pattern analysis
    GET  /v1/adjusters/{name} → Adjuster-specific patterns

    GET  /v1/health        → Service health check

Auth: Bearer token via SUP_API_KEY env var.
"""

import os
import re
import sys
import json
import asyncio
import hashlib
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Depends, Header, Request, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Env vars ───────────────────────────────────────────────────
# Load sup-api-code/.env BEFORE reading any os.environ values. Without this,
# local uvicorn runs (which don't inherit a repo-specific shell env) see
# SUP_API_KEY / ANTHROPIC_API_KEY / SUP_WORKSPACE as empty and every request
# 500s with "SUP_API_KEY not configured on server".
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Learning imports ───────────────────────────────────────────
from learning_service import learning_service
from enhanced_learning import enhanced_learning
from pricelist_manager import pricelist_manager

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sup-api")

# ── Paths ──────────────────────────────────────────────────────
# NOTE: The three-up walk from sup-api/main.py lands correctly on the live server
# (/opt/sup-repo/) but is off by one level locally. Override via SUP_WORKSPACE env
# (see .env) to point at .../sup-api-code/ when running uvicorn on a laptop.
WORKSPACE = Path(os.environ.get("SUP_WORKSPACE", str(Path(__file__).parent.parent.parent)))
PDF_GENERATOR = WORKSPACE / "tools" / "pdf-generator"
SKILLS_DIR = WORKSPACE / "tools" / "skills"
BID_MARKUP = WORKSPACE / "tools" / "bid-markup"
VENV_PYTHON = str(PDF_GENERATOR / ".venv" / "bin" / "python")

# ── Auth ───────────────────────────────────────────────────────
API_KEY = os.environ.get("SUP_API_KEY", "")
IS_PRODUCTION = os.environ.get("SUP_ENV", "development") == "production"

# ── Rate Limiting ──────────────────────────────────────────────
RATE_LIMITS = {
    "/v1/estimate": 3,
    "/v1/estimate-from-payload": 3,
    "/v1/markup": 10,
    "/v1/precall": 10,
    "/v1/calling": 10,
    "/v1/review": 10,
    "/v1/profit-margin": 10,
    # Learning reads: 10/min
    "/v1/insights": 10,
    "/v1/intelligence": 10,
    "/v1/pricelists:GET": 10,
    "/v1/seasonal": 10,
    "/v1/adjusters": 10,
    "/v1/projects/pricelists": 10,
    # Learning writes: 5/min
    "/v1/track_response": 5,
    "/v1/pricelists:POST": 5,
}
_request_log: dict[str, list[datetime]] = defaultdict(list)

# ── Active Request Tracking (dedup) ───────────────────────────
_active_requests: dict[str, asyncio.Event] = {}

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="Sup API",
    version="0.3.0",
    description="External supplement AI service for IFC Contracting Solutions — with learning system",
    docs_url="/docs" if not IS_PRODUCTION else None,
    redoc_url=None,
)

ALLOWED_ORIGINS = os.environ.get("SUP_CORS_ORIGINS", "http://localhost:8080,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Models ─────────────────────────────────────────────────────

class EstimateRequest(BaseModel):
    project_name: Optional[str] = Field(None, description="Project name — required for api-fetch, optional if project dict provided")
    project_id: Optional[int] = Field(None, description="IFC project ID for flow card updates")
    skip_upload: bool = Field(False, description="Skip Google Drive upload")
    version: Optional[str] = Field(None, description="Supplement version (e.g. '1.0')")
    notes: Optional[str] = Field(None, description="Special instructions for generation")
    carrier: Optional[str] = Field(None, description="Insurance carrier name for learning")
    adjuster_name: Optional[str] = Field(None, description="Adjuster name for tracking")
    adjuster_id: Optional[str] = Field(None, description="Adjuster ID for tracking")
    pricelist_override: Optional[str] = Field(None, description="Manual pricelist override code")
    # Payload mode — if present, skip IFC API fetch and use this data directly
    project: Optional[dict] = Field(None, description="Project details (id, name, address, drive_folder_id)")
    claim: Optional[dict] = Field(None, description="Claim info (number, carrier, adjuster)")
    flow_cards: Optional[List[dict]] = Field(None, description="Flow card / action tracker data")
    insurance_estimate: Optional[dict] = Field(None, description="Parsed insurance estimate content")
    eagleview_report: Optional[dict] = Field(None, description="Parsed EagleView report content")
    bid_pdfs: Optional[dict] = Field(None, description="Extracted bid PDF text per trade tag")
    bid_pdf_content: Optional[dict] = Field(None, description="Alias for bid_pdfs (IFC app field name)")
    op_tracker: Optional[dict] = Field(None, description="O&P tracker data")
    pricelist_tracker: Optional[dict] = Field(None, description="Pricelist tracker data")
    existing_supplements: Optional[dict] = Field(None, description="Existing supplement versions")
    file_readiness: Optional[dict] = Field(None, description="File readiness status from IFC app")

class MarkupRequest(BaseModel):
    project_name: str = Field(..., description="Project name")

class PrecallRequest(BaseModel):
    project_name: Optional[str] = Field(None, description="Project name")
    project_id: Optional[int] = Field(None, description="IFC project ID")

class CallingRequest(BaseModel):
    project_name: Optional[str] = Field(None, description="Project name")
    project_id: Optional[int] = Field(None, description="IFC project ID")

class ReviewRequest(BaseModel):
    project_name: Optional[str] = Field(None, description="Project name")
    project_id: Optional[int] = Field(None, description="IFC project ID")

class ProfitMarginRequest(BaseModel):
    project_name: Optional[str] = Field(None, description="Project name")
    project_id: Optional[int] = Field(None, description="IFC project ID")

class TrackResponseRequest(BaseModel):
    event_id: int = Field(..., description="Supplement event ID from generation")
    approved_items: List[dict] = Field(default_factory=list, description="List of approved items with strategy/amount")
    denied_items: List[dict] = Field(default_factory=list, description="List of denied items with strategy/reason")
    adjuster_name: Optional[str] = Field(None, description="Adjuster who responded")

class RegisterPricelistRequest(BaseModel):
    code: str = Field(..., description="Pricelist code (e.g. 'TXDF8X_MAR26')")
    date: str = Field(..., description="Pricelist date (YYYY-MM-DD)")
    region: str = Field("TX", description="Region code")
    description: Optional[str] = Field(None, description="Human-readable description")
    sheet_tab: Optional[str] = Field(None, description="Google Sheet tab name")


class EstimateResponse(BaseModel):
    success: bool
    pdf_url: Optional[str] = None
    total_rcv: Optional[str] = None
    trade_count: Optional[int] = None
    f9_count: Optional[int] = None
    flow_package: Optional[dict] = None
    estimate_json_path: Optional[str] = None
    intelligence_provided: Optional[list] = None
    pricelist_used: Optional[str] = None
    pricelist_reason: Optional[str] = None
    event_id: Optional[int] = None
    error: Optional[str] = None
    request_id: Optional[str] = None

class EstimateFromPayloadRequest(BaseModel):
    """Full project data payload from IFC platform — bypasses IFC API fetch."""
    project: dict = Field(..., description="Project details (id, name, address, status, drive_folder_id)")
    claim: dict = Field(default_factory=dict, description="Claim info (number, carrier, adjuster)")
    flow_cards: List[dict] = Field(default_factory=list, description="Flow card / action tracker data")
    op_tracker: dict = Field(default_factory=dict, description="O&P tracker data")
    pricelist_tracker: dict = Field(default_factory=dict, description="Pricelist tracker data")
    insurance_estimate: dict = Field(default_factory=dict, description="Parsed insurance estimate content")
    eagleview_report: dict = Field(default_factory=dict, description="Parsed EagleView report content")
    bid_pdfs: dict = Field(default_factory=dict, description="Extracted bid PDF text per trade tag")
    existing_supplements: dict = Field(default_factory=dict, description="Previous supplement versions")
    conversation_history: dict = Field(
        default_factory=dict,
        description=(
            "AI-distilled 5-field summary of all project chat rooms produced by Rails "
            "(strategy, scope_changes, estimate_instructions, carrier_behavior, context)."
        ),
    )
    version: Optional[str] = Field(None, description="Supplement version (e.g. '1.0')")
    skip_upload: bool = Field(False, description="Skip Google Drive upload")
    pricelist_override: Optional[str] = Field(None, description="Manual pricelist override code")

class EditRequest(BaseModel):
    project_name: str = Field(..., description="Project name (e.g. 'Rose Brock')")
    edits: List[dict] = Field(..., description="List of edit actions (see edit_estimate.py for format)")
    skip_upload: bool = Field(False, description="Skip Google Drive re-upload")

class EditResponse(BaseModel):
    success: bool
    pdf_url: Optional[str] = None
    total_rcv: Optional[str] = None
    edit_results: Optional[List[str]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None

class ReviewCommentsRequest(BaseModel):
    project_name: str = Field(..., description="Project name (e.g. 'Rose Brock')")
    file_id: Optional[str] = Field(None, description="Specific Drive file ID (auto-detected if omitted)")
    dry_run: bool = Field(False, description="Preview edits without applying")

class ReviewCommentsResponse(BaseModel):
    success: bool
    comments_processed: Optional[int] = None
    edits_applied: Optional[int] = None
    edits_failed: Optional[int] = None
    failed_edit_details: Optional[List[dict]] = None
    edit_results: Optional[List[str]] = None
    pdf_url: Optional[str] = None
    message: Optional[str] = None
    edits: Optional[List[dict]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None

class SkillResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    request_id: Optional[str] = None


# ── Auth dependency ────────────────────────────────────────────

async def verify_api_key(authorization: str = Header(...)):
    """Verify Bearer token matches SUP_API_KEY."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="SUP_API_KEY not configured on server")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:]
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# ── Rate Limiting ──────────────────────────────────────────────

def check_rate_limit(endpoint: str):
    """Simple per-endpoint rate limiter. Raises 429 if exceeded."""
    limit = RATE_LIMITS.get(endpoint)
    if not limit:
        return

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=1)
    _request_log[endpoint] = [t for t in _request_log[endpoint] if t > cutoff]

    if len(_request_log[endpoint]) >= limit:
        logger.warning(f"Rate limit hit: {endpoint} ({limit}/min)")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {limit} requests per minute for {endpoint}",
        )
    _request_log[endpoint].append(now)


# ── Request ID & Dedup ─────────────────────────────────────────

def make_request_id(endpoint: str, key_data: str) -> str:
    raw = f"{endpoint}:{key_data}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ── Helpers ────────────────────────────────────────────────────

async def run_script(cmd: list[str], cwd: str = None, timeout: int = 300, env_extra: dict = None) -> dict:
    """Run a Python script asynchronously and capture output."""
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or str(WORKSPACE),
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Script timed out after {timeout}s",
        }

    return {
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def parse_estimate_output(stdout: str) -> dict:
    """Extract structured data from generate.py stdout."""
    result = {}

    for line in stdout.splitlines():
        if "drive.google.com" in line:
            match = re.search(r"https://drive\.google\.com/[^\s]+", line)
            if match:
                result["pdf_url"] = match.group(0)
        if "RCV Total:" in line:
            match = re.search(r"RCV Total:\s*\$\s*([\d,]+\.?\d*)", line)
            if match:
                result["total_rcv"] = f"${match.group(1).strip()}"
        if "Sections:" in line:
            match = re.search(r"Sections:\s*(\d+)", line)
            if match:
                result["trade_count"] = int(match.group(1))
        if "Total items:" in line:
            match = re.search(r"Total items:\s*(\d+)", line)
            if match:
                result["item_count"] = int(match.group(1))
        if "Cards:" in line:
            match = re.search(r"Cards:\s*(\d+)", line)
            if match:
                result["card_count"] = int(match.group(1))

    f9_count = len(re.findall(r'\bF9\b', stdout, re.IGNORECASE))
    if f9_count > 0:
        result["f9_count"] = f9_count

    return result


def parse_strategies_from_output(stdout: str) -> list:
    """Parse strategies detected from generate.py output."""
    strategies = set()
    for line in stdout.splitlines():
        lower = line.lower()
        if "steep" in lower:
            strategies.add("steep_on_waste")
        if "fence" in lower:
            strategies.add("full_fence_scope")
        if "o&p" in lower:
            strategies.add("O&P")
        if "f9" in lower:
            strategies.add("f9_notes")
    return list(strategies)


def parse_amount(amount_str: str) -> float:
    """Parse dollar amount string to float."""
    if not amount_str or amount_str == "Unknown":
        return 0.0
    cleaned = re.sub(r"[$,\s]", "", str(amount_str))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def normalize_project_name(name: str) -> str:
    cleaned = re.sub(
        r'^(?:Test\s+)?(?:Project|IFC)\s*[-–—:]\s*',
        '',
        name.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned.strip() or name.strip()


def get_project_prefix(project_name: str) -> str:
    name = normalize_project_name(project_name).strip()
    parts = name.split()
    if len(parts) <= 1:
        prefix = parts[0] if parts else "UNKNOWN"
    else:
        prefix = "_".join(parts[1:])
    prefix = prefix.upper().replace("'", "")
    prefix = re.sub(r"[^A-Z0-9_]", "_", prefix)
    prefix = re.sub(r"_+", "_", prefix).strip("_")
    return prefix or "UNKNOWN"


def parse_skill_output(stdout: str) -> dict:
    try:
        return json.loads(stdout.strip())
    except json.JSONDecodeError:
        pass
    lines = stdout.strip().splitlines()
    json_buffer = ""
    for line in reversed(lines):
        json_buffer = line + "\n" + json_buffer
        try:
            return json.loads(json_buffer.strip())
        except json.JSONDecodeError:
            continue
    return {"raw_output": stdout.strip()}


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — Pipeline
# ══════════════════════════════════════════════════════════════

@app.post("/v1/estimate", response_model=EstimateResponse, dependencies=[Depends(verify_api_key)])
async def generate_estimate(req: EstimateRequest, request: Request):
    """
    Generate a supplement PDF estimate — with learning integration.

    Before generating: queries learned patterns for carrier + strategies.
    After generating: tracks the generation event in learning DB.
    Returns intelligence_provided + event_id in response.
    """
    check_rate_limit("/v1/estimate")

    # Resolve project_name: explicit field > project.name > error
    has_payload = req.project is not None
    mode = "payload" if has_payload else "api-fetch"
    raw_name = req.project_name or (req.project.get("name") if req.project else None)
    if not raw_name:
        return EstimateResponse(success=False, error="project_name or project.name is required")
    project_name = normalize_project_name(raw_name)
    request_id = make_request_id("/v1/estimate", project_name)
    carrier = req.carrier or (req.claim.get("carrier") if req.claim else None) or "Unknown"
    version = req.version or (req.project.get("version") if req.project else None) or "1.0"

    logger.info(f"[{request_id}] Estimate requested: '{project_name}' (carrier={carrier}, version={version}, mode={mode})")

    # Dedup
    if request_id in _active_requests:
        logger.warning(f"[{request_id}] Duplicate request — already in progress, waiting...")
        try:
            await asyncio.wait_for(_active_requests[request_id].wait(), timeout=920)
        except asyncio.TimeoutError:
            pass
        return EstimateResponse(
            success=False,
            error="A generation for this project was already in progress. Check Drive for results.",
            request_id=request_id,
        )

    _active_requests[request_id] = asyncio.Event()

    try:
        # ── LEARNING: Pre-generation intelligence ──────────
        strategies = ["steep_on_waste", "full_fence_scope", "O&P"]
        learned_intelligence = {}
        if carrier != "Unknown":
            learned_intelligence = learning_service.get_learned_patterns(carrier, strategies)
            logger.info(f"[{request_id}] Providing {len(learned_intelligence)} learned insights for {carrier}")

        # ── PRICELIST: Use active Google Sheet pricelist ───
        selected_pricelist = req.pricelist_override or "Pricelist"
        pricelist_reason = "override" if req.pricelist_override else "active sheet tab"
        logger.info(f"[{request_id}] Pricelist: {selected_pricelist} ({pricelist_reason})")

        # ── Build command ──────────────────────────────────
        env_extra = {
            "SELECTED_PRICELIST": selected_pricelist or "",
            "PRICELIST_REASON": pricelist_reason or "",
        }
        if learned_intelligence:
            env_extra["LEARNED_INTELLIGENCE"] = json.dumps({
                "type": "recommendations",
                "carrier": carrier,
                "insights": learned_intelligence,
                "note": "These are suggestions based on historical data, not mandatory rules",
            })
            env_extra["CARRIER_CONTEXT"] = carrier

        if has_payload:
            # Payload mode: convert IFC data → pipeline_data, use --from-pipeline
            pipeline_data = _convert_payload_to_pipeline_data(req)
            pipeline_json_path = PDF_GENERATOR / f"_payload_{request_id}.json"
            with open(pipeline_json_path, "w") as f:
                json.dump(pipeline_data, f, indent=2)

            cmd = [VENV_PYTHON, "-u", str(PDF_GENERATOR / "generate.py"),
                   "--from-pipeline", str(pipeline_json_path)]
            logger.info(f"[{request_id}] Using payload mode — pipeline data saved to {pipeline_json_path}")
        else:
            # Fallback: Sup fetches from IFC API
            cmd = [VENV_PYTHON, "-u", str(PDF_GENERATOR / "generate.py"), project_name]

        if req.skip_upload:
            cmd.append("--skip-upload")
        if req.version:
            cmd.extend(["--version", req.version])

        result = await run_script(cmd, cwd=str(PDF_GENERATOR), timeout=900, env_extra=env_extra)

        # Clean up temp payload file
        if has_payload:
            try:
                pipeline_json_path.unlink(missing_ok=True)
            except Exception:
                pass

        if not result["success"]:
            logger.error(f"[{request_id}] Pipeline failed (exit {result['exit_code']}): {result['stderr'][:200]}")
            return EstimateResponse(
                success=False,
                error=f"Pipeline failed (exit {result['exit_code']}): {result['stderr'][:500]}",
                request_id=request_id,
            )

        # Log key pipeline diagnostics on success
        for line in result["stdout"].splitlines():
            if any(kw in line for kw in ["[gutter_bid]", "[estimate_builder] Gutter", "[estimate_builder] Injected", "[estimate_builder] Paired", "[estimate_builder] Stripped", "[pipeline] Sub name", "[pipeline] ⚠", "[pipeline] ✅ Gutter", "No Original Bids", "Tokens:", "Pricelist enforcement"]):
                logger.info(f"[{request_id}] {line.strip()}")

        parsed = parse_estimate_output(result["stdout"])
        strategies_used = parse_strategies_from_output(result["stdout"])

        # Load flow package
        flow_package = None
        try:
            prefix = get_project_prefix(project_name)
            flow_path = PDF_GENERATOR / f"{prefix}_flow_package.json"
            if flow_path.exists():
                with open(flow_path) as f:
                    flow_package = json.load(f)
        except Exception as e:
            logger.warning(f"[{request_id}] Could not load flow package: {e}")

        # ── LEARNING: Track generation event ───────────────
        event_id = None
        total_rcv_str = parsed.get("total_rcv") or (
            f"${flow_package['rcv_total']:,.2f}" if flow_package and flow_package.get("rcv_total") else "0"
        )
        total_rcv = parse_amount(total_rcv_str)

        if req.project_id:
            event_id = learning_service.track_supplement_generation(
                project_id=req.project_id,
                project_name=project_name,
                carrier=carrier,
                strategies=strategies_used or strategies,
                amount_requested=total_rcv,
                adjuster_name=req.adjuster_name,
                adjuster_id=req.adjuster_id,
            )

        logger.info(f"[{request_id}] Estimate complete: RCV={total_rcv_str}, event_id={event_id}")

        return EstimateResponse(
            success=True,
            pdf_url=parsed.get("pdf_url"),
            total_rcv=total_rcv_str if total_rcv_str != "0" else None,
            trade_count=parsed.get("trade_count") or (
                len(flow_package.get("cards", [])) if flow_package else None
            ),
            f9_count=parsed.get("f9_count"),
            flow_package=flow_package,
            intelligence_provided=list(learned_intelligence.keys()) if learned_intelligence else None,
            pricelist_used=selected_pricelist,
            pricelist_reason=pricelist_reason,
            event_id=event_id,
            request_id=request_id,
        )

    finally:
        event = _active_requests.pop(request_id, None)
        if event:
            event.set()


def _convert_payload_to_pipeline_data(req) -> dict:
    """
    Convert IFC platform payload format → pipeline_data dict that
    estimate_builder.build_estimate() expects.
    Works with EstimateRequest (payload fields optional).
    """
    project = req.project or {}
    claim = req.claim or {}
    project_name = project.get("name") or getattr(req, "project_name", "UNKNOWN")
    lastname = project_name.strip().split()[-1].upper() if project_name else "UNKNOWN"

    # Insurance estimate → ins_data
    ins_data = {}
    ins_est = getattr(req, "insurance_estimate", None) or {}
    ins_content = ins_est.get("content", "") if isinstance(ins_est, dict) else ""
    if ins_content:
        ins_data = {"raw_markdown": ins_content, "items": []}

    # EagleView → ev_data
    ev_data = {}
    ev_report = getattr(req, "eagleview_report", None) or {}
    ev_content = ev_report.get("content", "") if isinstance(ev_report, dict) else ""
    if ev_content:
        ev_data = {"raw_markdown": ev_content}

    # Flow cards → action_trackers
    # Map IFC payload field names → pipeline field names
    action_trackers = []
    flow_cards = getattr(req, "flow_cards", None) or []
    for card in flow_cards:
        action_trackers.append({
            "id": card.get("id"),
            "tag": card.get("tag", ""),
            "original_sub_bid_price": card.get("original_sub_bid") or card.get("original_sub_bid_price"),
            "retail_exactimate_bid": card.get("retail_exactimate_bid"),
            "latest_rcv_rcv": card.get("latest_rcv_rcv"),
            "latest_rcv_op": card.get("latest_rcv_op"),
            "doing_the_work_status": card.get("doing_the_work") or card.get("doing_the_work_status"),
            "production_status": card.get("production_status"),
            "trade_status": card.get("trade_status") or card.get("supplement_status"),
            "supplement_notes": card.get("supplement_notes"),
            "subcontractor": card.get("subcontractor"),
        })

    # Bids — payload typically skips these (bid_pdf_content: {skipped: true})
    # Pipeline fetches bids from Drive in generate.py payload enrichment step
    bids = []
    bid_pdfs = getattr(req, "bid_pdfs", None) or getattr(req, "bid_pdf_content", None) or {}
    if isinstance(bid_pdfs, dict) and not bid_pdfs.get("skipped"):
        for tag, content in bid_pdfs.items():
            bid_text = content.get("content", "") if isinstance(content, dict) else str(content)
            if bid_text:
                matching_card = next((c for c in flow_cards if c.get("tag") == tag), {})
                bids.append({
                    "tag": tag,
                    "wholesale": matching_card.get("original_sub_bid", 0),
                    "retail": matching_card.get("retail_exactimate_bid", 0),
                    "text": bid_text,
                    "source": "payload",
                })

    # Claims
    claims = {
        "claim_number": claim.get("claim_number") or claim.get("number", ""),
        "insurance_company": claim.get("carrier") or claim.get("company", ""),
        "date_of_loss": claim.get("date_of_loss", ""),
        "adjuster_name": claim.get("adjuster_name", ""),
    }

    # Address
    address_str = project.get("address", "")
    address = {"full": address_str}

    # Drive folder
    drive_link = project.get("google_drive_link", "") or project.get("drive_folder_id", "")
    project_folder_id = drive_link.split("/")[-1] if "/" in drive_link else drive_link

    # Conversation history: 5-field summary distilled from all project chat rooms by Rails
    # (Supplements::SummarizeConversationContext). Missing on api-fetch-mode EstimateRequest,
    # present on EstimateFromPayloadRequest. Always normalized to the canonical 5-field shape
    # so downstream renderers (estimate_builder._format_conversation_history) never branch on nulls.
    conversation_history = _normalize_conversation_history(
        getattr(req, "conversation_history", None) or {}
    )

    return {
        "project": project,
        "project_id": project.get("id"),
        "project_folder_id": project_folder_id or None,
        "lastname": lastname,
        "firstname": project_name.split()[0] if project_name and " " in project_name else "",
        "notes": {"ifc": [], "supplement": [], "momentum": [], "untagged": []},
        "conversation_history": conversation_history,
        "claims": claims,
        "address": address,
        "ins_data": ins_data,
        "ins_by_tag": {},
        "ev_data": ev_data,
        "action_trackers": action_trackers,
        "bids": bids,
        "pricelist": {},
        "prior_corrections": [],
        "itel_data": None,
        "gutter_measurements": None,
        "op_tracker": getattr(req, "op_tracker", None) or {},
        "pricelist_tracker": getattr(req, "pricelist_tracker", None) or {},
        "existing_supplements": getattr(req, "existing_supplements", None) or {},
    }


# Canonical 5-field shape produced by Rails Supplements::SummarizeConversationContext.
# Authored by Alvaro (Slack 2026-04-12).
CONVERSATION_HISTORY_FIELDS = (
    "strategy",
    "scope_changes",
    "estimate_instructions",
    "carrier_behavior",
    "context",
)


def _normalize_conversation_history(raw: dict) -> dict:
    """Guarantee the 5-field shape regardless of what Rails sent.

    Missing or non-string values become empty strings so the downstream prompt
    renderer never has to branch on nulls.
    """
    raw = raw or {}
    return {field: (str(raw.get(field, "")) if raw.get(field) else "") for field in CONVERSATION_HISTORY_FIELDS}







@app.post("/v1/estimate-from-payload", response_model=EstimateResponse, dependencies=[Depends(verify_api_key)])
async def estimate_from_payload(req: EstimateFromPayloadRequest, request: Request):
    """
    Generate a supplement PDF from pre-assembled project data.

    The IFC platform pushes all project data (insurance estimate, EagleView,
    bids, claims, flow cards) as a JSON payload — the pipeline skips IFC API
    fetching and goes straight to estimate building.

    This is the hybrid approach: IFC owns the data, Sup API owns the rendering.
    """
    check_rate_limit("/v1/estimate-from-payload")

    project_name = req.project.get("name", "UNKNOWN")
    project_id = req.project.get("id")
    carrier = req.claim.get("carrier", "Unknown")
    version = req.version or "1.0"

    request_id = make_request_id("/v1/estimate-from-payload", project_name)
    logger.info(f"[{request_id}] Estimate-from-payload: '{project_name}' (carrier={carrier}, version={version})")

    # Dedup
    if request_id in _active_requests:
        logger.warning(f"[{request_id}] Duplicate request — already in progress, waiting...")
        try:
            await asyncio.wait_for(_active_requests[request_id].wait(), timeout=620)
        except asyncio.TimeoutError:
            pass
        return EstimateResponse(
            success=False,
            error="A generation for this project was already in progress. Check Drive for results.",
            request_id=request_id,
        )

    _active_requests[request_id] = asyncio.Event()

    try:
        # ── LEARNING: Pre-generation intelligence ──────────
        strategies = ["steep_on_waste", "full_fence_scope", "O&P"]
        learned_intelligence = {}
        if carrier != "Unknown":
            learned_intelligence = learning_service.get_learned_patterns(carrier, strategies)
            logger.info(f"[{request_id}] Providing {len(learned_intelligence)} learned insights for {carrier}")

        # ── PRICELIST ──────────────────────────────────────
        selected_pricelist = req.pricelist_override or "Pricelist"
        pricelist_reason = "override" if req.pricelist_override else "active sheet tab"

        # ── Save raw IFC payload for debugging ─────────────
        raw_payload_path = PDF_GENERATOR / f"_raw_payload_{request_id}.json"
        with open(raw_payload_path, "w") as f:
            json.dump(req.dict(), f, indent=2, default=str)
        logger.info(f"[{request_id}] Raw IFC payload saved to {raw_payload_path}")

        # ── Convert IFC payload → pipeline_data JSON ───────
        pipeline_data = _convert_payload_to_pipeline_data(req)
        pipeline_json_path = PDF_GENERATOR / f"_payload_{request_id}.json"
        with open(pipeline_json_path, "w") as f:
            json.dump(pipeline_data, f, indent=2)

        # ── Build command ──────────────────────────────────
        cmd = [VENV_PYTHON, "-u", str(PDF_GENERATOR / "generate.py"),
               "--from-pipeline", str(pipeline_json_path)]
        if req.skip_upload:
            cmd.append("--skip-upload")
        cmd.extend(["--version", version])

        env_extra = {
            "SELECTED_PRICELIST": selected_pricelist or "",
            "PRICELIST_REASON": pricelist_reason or "",
        }
        if learned_intelligence:
            env_extra["LEARNED_INTELLIGENCE"] = json.dumps({
                "type": "recommendations",
                "carrier": carrier,
                "insights": learned_intelligence,
                "note": "These are suggestions based on historical data, not mandatory rules",
            })
            env_extra["CARRIER_CONTEXT"] = carrier

        result = await run_script(cmd, cwd=str(PDF_GENERATOR), timeout=900, env_extra=env_extra)

        # Clean up temp file
        try:
            pipeline_json_path.unlink(missing_ok=True)
        except Exception:
            pass

        if not result["success"]:
            logger.error(f"[{request_id}] Pipeline failed (exit {result['exit_code']})\nSTDERR: {result['stderr'][-2000:]}\nSTDOUT tail: {result['stdout'][-500:]}")
            return EstimateResponse(
                success=False,
                error=f"Pipeline failed (exit {result['exit_code']}): {result['stderr'][:500]}",
                request_id=request_id,
            )

        # Log key pipeline diagnostics on success
        for line in result["stdout"].splitlines():
            if any(kw in line for kw in ["[gutter_bid]", "[estimate_builder] Gutter", "[estimate_builder] Injected", "[estimate_builder] Paired", "[estimate_builder] Stripped", "[pipeline] Sub name", "[pipeline] ⚠", "[pipeline] ✅ Gutter", "No Original Bids", "Tokens:", "Pricelist enforcement"]):
                logger.info(f"[{request_id}] {line.strip()}")

        parsed = parse_estimate_output(result["stdout"])
        strategies_used = parse_strategies_from_output(result["stdout"])

        # Load flow package
        flow_package = None
        try:
            lastname = pipeline_data.get("lastname", "UNKNOWN")
            flow_path = PDF_GENERATOR / f"{lastname}_flow_package.json"
            if flow_path.exists():
                with open(flow_path) as f:
                    flow_package = json.load(f)
        except Exception as e:
            logger.warning(f"[{request_id}] Could not load flow package: {e}")

        # ── LEARNING: Track generation event ───────────────
        event_id = None
        total_rcv_str = parsed.get("total_rcv") or (
            f"${flow_package['rcv_total']:,.2f}" if flow_package and flow_package.get("rcv_total") else "0"
        )
        total_rcv = parse_amount(total_rcv_str)

        if project_id:
            event_id = learning_service.track_supplement_generation(
                project_id=project_id,
                project_name=project_name,
                carrier=carrier,
                strategies=strategies_used or strategies,
                amount_requested=total_rcv,
                adjuster_name=req.claim.get("adjuster_name"),
                adjuster_id=None,
            )

        logger.info(f"[{request_id}] Estimate complete: RCV={total_rcv_str}, event_id={event_id}")

        return EstimateResponse(
            success=True,
            pdf_url=parsed.get("pdf_url"),
            total_rcv=total_rcv_str if total_rcv_str != "0" else None,
            trade_count=parsed.get("trade_count") or (
                len(flow_package.get("cards", [])) if flow_package else None
            ),
            f9_count=parsed.get("f9_count"),
            flow_package=flow_package,
            intelligence_provided=list(learned_intelligence.keys()) if learned_intelligence else None,
            pricelist_used=selected_pricelist,
            pricelist_reason=pricelist_reason,
            event_id=event_id,
            request_id=request_id,
        )

    finally:
        event = _active_requests.pop(request_id, None)
        if event:
            event.set()


@app.post("/v1/edit", response_model=EditResponse, dependencies=[Depends(verify_api_key)])
async def edit_estimate(req: EditRequest, request: Request):
    """Surgically edit an existing estimate and re-render PDF."""
    check_rate_limit("/v1/estimate")
    project_name = normalize_project_name(req.project_name)
    request_id = make_request_id("/v1/edit", project_name)
    logger.info(f"[{request_id}] Edit requested: '{project_name}' with {len(req.edits)} edit(s)")

    try:
        # Resolve project prefix (uppercase last name)
        prefix = get_project_prefix(project_name)

        # Shell out to pdf-generator venv (has all pipeline deps)
        cmd = [
            VENV_PYTHON, "-u", str(PDF_GENERATOR / "edit_estimate.py"),
            prefix, "--api", "--project-name", project_name,
        ]
        if req.skip_upload:
            cmd.append("--skip-upload")

        # Pass edits via stdin
        edits_json = json.dumps(req.edits)
        env = {**os.environ}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PDF_GENERATOR),
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=edits_json.encode()), timeout=300
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return EditResponse(success=False, error="Edit timed out after 300s", request_id=request_id)

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[:500]
            logger.error(f"[{request_id}] Edit failed (exit {proc.returncode}): {error_msg}")
            return EditResponse(success=False, error=f"Edit failed: {error_msg}", request_id=request_id)

        result = parse_skill_output(stdout.decode("utf-8", errors="replace"))

        logger.info(f"[{request_id}] Edit complete: RCV={result.get('total_rcv')}, edits={len(req.edits)}")

        return EditResponse(
            success=result.get("success", False),
            pdf_url=result.get("pdf_url"),
            total_rcv=result.get("total_rcv"),
            edit_results=result.get("edit_results"),
            request_id=request_id,
        )

    except Exception as e:
        logger.error(f"[{request_id}] Edit error: {e}")
        return EditResponse(success=False, error=str(e), request_id=request_id)


@app.post("/v1/review-comments", response_model=ReviewCommentsResponse, dependencies=[Depends(verify_api_key)])
async def review_comments(req: ReviewCommentsRequest, request: Request):
    """Read Drive comments on a supplement PDF, translate to edits, apply, and re-upload."""
    check_rate_limit("/v1/estimate")
    project_name = normalize_project_name(req.project_name)
    request_id = make_request_id("/v1/review-comments", project_name)
    logger.info(f"[{request_id}] Review comments requested: '{project_name}' (dry_run={req.dry_run})")

    try:
        # Shell out to pdf-generator venv (has google libs) instead of direct import
        cmd = [VENV_PYTHON, "-u", str(PDF_GENERATOR / "comment_reader.py"), project_name]
        if req.file_id:
            cmd.extend(["--file-id", req.file_id])
        if req.dry_run:
            cmd.append("--dry-run")

        script_result = await run_script(cmd, cwd=str(PDF_GENERATOR), timeout=300)

        if not script_result["success"]:
            logger.error(f"[{request_id}] Review comments failed: {script_result['stderr'][:200]}")
            return ReviewCommentsResponse(
                success=False,
                error=f"Review comments failed: {script_result['stderr'][:500]}",
                request_id=request_id,
            )

        result = parse_skill_output(script_result["stdout"])

        edits_failed = result.get("edits_failed", 0)
        if edits_failed:
            logger.warning(f"[{request_id}] Comments processed with {edits_failed} FAILED edit(s): {result.get('failed_edit_details', [])}")
        else:
            logger.info(f"[{request_id}] Comments processed: {result.get('comments_processed', 0)} → {result.get('edits_applied', 0)} edits")

        return ReviewCommentsResponse(
            success=result.get("success", False),
            comments_processed=result.get("comments_processed"),
            edits_applied=result.get("edits_applied"),
            edits_failed=edits_failed or None,
            failed_edit_details=result.get("failed_edit_details") or None,
            edit_results=result.get("edit_results"),
            pdf_url=result.get("pdf_url"),
            message=result.get("message"),
            edits=result.get("edits"),
            request_id=request_id,
        )

    except Exception as e:
        logger.error(f"[{request_id}] Review comments error: {e}")
        return ReviewCommentsResponse(success=False, error=str(e), request_id=request_id)


@app.post("/v1/markup", response_model=SkillResponse, dependencies=[Depends(verify_api_key)])
async def run_markup(req: MarkupRequest, request: Request):
    """Run bid markup analysis for a project."""
    check_rate_limit("/v1/markup")
    project_name = normalize_project_name(req.project_name)
    request_id = make_request_id("/v1/markup", project_name)
    logger.info(f"[{request_id}] Markup requested: '{project_name}'")

    cmd = [VENV_PYTHON, str(BID_MARKUP / "markup_bids.py"), "drive", project_name]
    result = await run_script(cmd, cwd=str(BID_MARKUP), timeout=120)

    if not result["success"]:
        logger.error(f"[{request_id}] Markup failed: {result['stderr'][:200]}")
        return SkillResponse(success=False, error=f"Markup failed: {result['stderr'][:500]}", request_id=request_id)

    logger.info(f"[{request_id}] Markup complete")
    return SkillResponse(success=True, data=parse_skill_output(result["stdout"]), request_id=request_id)


@app.post("/v1/precall", response_model=SkillResponse, dependencies=[Depends(verify_api_key)])
async def run_precall(req: PrecallRequest, request: Request):
    """Generate pre-supplement call script data."""
    check_rate_limit("/v1/precall")
    request_id = make_request_id("/v1/precall", str(req.project_name or req.project_id))
    logger.info(f"[{request_id}] Precall requested: name='{req.project_name}' id={req.project_id}")

    cmd = [VENV_PYTHON, str(SKILLS_DIR / "precall.py")]
    if req.project_id:
        cmd.extend(["--id", str(req.project_id)])
    elif req.project_name:
        cmd.append(normalize_project_name(req.project_name))
    else:
        raise HTTPException(status_code=400, detail="project_name or project_id required")

    result = await run_script(cmd, cwd=str(SKILLS_DIR), timeout=180)
    if not result["success"]:
        error_msg = (result["stderr"] or result["stdout"] or "Unknown error").strip()
        logger.error(f"[{request_id}] Precall failed: {error_msg[:200]}")
        return SkillResponse(success=False, error=f"Precall failed: {error_msg[:500]}", request_id=request_id)

    stdout = result["stdout"].strip()
    if stdout.startswith("STOP:"):
        return SkillResponse(success=False, error=stdout, request_id=request_id)

    logger.info(f"[{request_id}] Precall complete")
    return SkillResponse(success=True, data=parse_skill_output(stdout), request_id=request_id)


@app.post("/v1/calling", response_model=SkillResponse, dependencies=[Depends(verify_api_key)])
async def run_calling(req: CallingRequest, request: Request):
    """Generate carrier call script data."""
    check_rate_limit("/v1/calling")
    request_id = make_request_id("/v1/calling", str(req.project_name or req.project_id))
    logger.info(f"[{request_id}] Calling requested: name='{req.project_name}' id={req.project_id}")

    cmd = [VENV_PYTHON, str(SKILLS_DIR / "calling.py")]
    if req.project_id:
        cmd.extend(["--id", str(req.project_id)])
    elif req.project_name:
        cmd.append(normalize_project_name(req.project_name))
    else:
        raise HTTPException(status_code=400, detail="project_name or project_id required")

    result = await run_script(cmd, cwd=str(SKILLS_DIR), timeout=180)
    if not result["success"]:
        error_msg = (result["stderr"] or result["stdout"] or "Unknown error").strip()
        logger.error(f"[{request_id}] Calling failed: {error_msg[:200]}")
        return SkillResponse(success=False, error=f"Calling failed: {error_msg[:500]}", request_id=request_id)

    stdout = result["stdout"].strip()
    if stdout.startswith("STOP:"):
        return SkillResponse(success=False, error=stdout, request_id=request_id)

    logger.info(f"[{request_id}] Calling complete")
    return SkillResponse(success=True, data=parse_skill_output(stdout), request_id=request_id)


@app.post("/v1/review", response_model=SkillResponse, dependencies=[Depends(verify_api_key)])
async def run_review(req: ReviewRequest, request: Request):
    """Run final QA review on a supplement."""
    check_rate_limit("/v1/review")
    request_id = make_request_id("/v1/review", str(req.project_name or req.project_id))
    logger.info(f"[{request_id}] Review requested: name='{req.project_name}' id={req.project_id}")

    cmd = [VENV_PYTHON, str(SKILLS_DIR / "review.py")]
    if req.project_id:
        cmd.extend(["--id", str(req.project_id)])
    elif req.project_name:
        cmd.append(normalize_project_name(req.project_name))
    else:
        raise HTTPException(status_code=400, detail="project_name or project_id required")

    result = await run_script(cmd, cwd=str(SKILLS_DIR), timeout=180)
    if not result["success"]:
        error_msg = (result["stderr"] or result["stdout"] or "Unknown error").strip()
        logger.error(f"[{request_id}] Review failed: {error_msg[:200]}")
        return SkillResponse(success=False, error=f"Review failed: {error_msg[:500]}", request_id=request_id)

    stdout = result["stdout"].strip()
    if stdout.startswith("STOP:"):
        return SkillResponse(success=False, error=stdout, request_id=request_id)

    logger.info(f"[{request_id}] Review complete")
    return SkillResponse(success=True, data=parse_skill_output(stdout), request_id=request_id)


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — Profit Margin
# ══════════════════════════════════════════════════════════════

PROFIT_MARGIN = WORKSPACE / "tools" / "profit-margin"

@app.post("/v1/profit-margin", response_model=SkillResponse, dependencies=[Depends(verify_api_key)])
async def run_profit_margin(req: ProfitMarginRequest, request: Request):
    """Generate an itemized profit margin Google Sheet for a project."""
    check_rate_limit("/v1/profit-margin")
    request_id = make_request_id("/v1/profit-margin", str(req.project_name or req.project_id))
    logger.info(f"[{request_id}] Profit margin requested: name='{req.project_name}' id={req.project_id}")

    cmd = [VENV_PYTHON, str(PROFIT_MARGIN / "calculate.py")]
    if req.project_id:
        cmd.extend(["--project-id", str(req.project_id)])
    elif req.project_name:
        cmd.append(normalize_project_name(req.project_name))
    else:
        raise HTTPException(status_code=400, detail="project_name or project_id required")

    result = await run_script(cmd, cwd=str(PROFIT_MARGIN), timeout=120)
    if not result["success"]:
        error_msg = (result["stderr"] or result["stdout"] or "Unknown error").strip()
        logger.error(f"[{request_id}] Profit margin failed: {error_msg[:200]}")
        return SkillResponse(success=False, error=f"Profit margin failed: {error_msg[:500]}", request_id=request_id)

    logger.info(f"[{request_id}] Profit margin complete")
    return SkillResponse(success=True, data=parse_skill_output(result["stdout"]), request_id=request_id)


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — Learning System
# ══════════════════════════════════════════════════════════════

@app.post("/v1/track_response", dependencies=[Depends(verify_api_key)])
async def track_response(req: TrackResponseRequest, request: Request):
    """Track insurance response for learning."""
    check_rate_limit("/v1/track_response")
    request_id = make_request_id("/v1/track_response", str(req.event_id))
    logger.info(f"[{request_id}] Tracking response for event {req.event_id}")

    try:
        total_approved = 0.0
        for item in req.approved_items:
            total_approved += float(item.get("amount", 0))
        for item in req.denied_items:
            total_approved += float(item.get("approved_amount", 0))

        learning_service.track_insurance_response(
            event_id=req.event_id,
            approved_items=req.approved_items,
            denied_items=req.denied_items,
            total_approved=total_approved,
            adjuster_name=req.adjuster_name,
        )

        logger.info(f"[{request_id}] Response tracked: total_approved=${total_approved:,.2f}")
        return {
            "success": True,
            "message": "Response tracked successfully",
            "total_approved": total_approved,
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"[{request_id}] Failed to track response: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to track response: {str(e)}")


@app.get("/v1/insights", dependencies=[Depends(verify_api_key)])
async def get_insights(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    carrier: Optional[str] = Query(None, description="Filter by carrier"),
):
    """Get learning insights for team dashboard."""
    check_rate_limit("/v1/insights")
    request_id = make_request_id("/v1/insights", f"days={days}")
    logger.info(f"[{request_id}] Insights requested: days={days}, carrier={carrier}")

    insights = learning_service.get_insights_summary(days)

    if carrier:
        carrier_patterns = learning_service.get_learned_patterns(carrier, [])
        insights["carrier_specific"] = carrier_patterns

    insights["request_id"] = request_id
    return insights


@app.get("/v1/intelligence", dependencies=[Depends(verify_api_key)])
async def get_strategy_intelligence(
    request: Request,
    carrier: str = Query(..., description="Carrier name"),
    strategy: Optional[List[str]] = Query(None, description="Strategies to analyze (repeatable)"),
):
    """Get comprehensive strategy intelligence and recommendations."""
    check_rate_limit("/v1/intelligence")
    request_id = make_request_id("/v1/intelligence", carrier)
    logger.info(f"[{request_id}] Intelligence requested: carrier={carrier}")

    strategies = strategy or ["steep_on_waste", "full_fence_scope", "O&P"]
    intelligence = enhanced_learning.get_comprehensive_intelligence(carrier, strategies)

    return {
        "success": True,
        "intelligence": intelligence,
        "note": "These are recommendations based on historical data, not mandatory rules",
        "request_id": request_id,
    }


@app.get("/v1/pricelists", dependencies=[Depends(verify_api_key)])
async def list_pricelists(
    request: Request,
    region: str = Query("TX", description="Region code"),
):
    """Get all available pricelists."""
    check_rate_limit("/v1/pricelists:GET")
    request_id = make_request_id("/v1/pricelists:GET", region)
    logger.info(f"[{request_id}] Pricelists requested: region={region}")

    pricelists = pricelist_manager.list_available_pricelists(region)
    latest = pricelist_manager.get_latest_pricelist(region)

    return {
        "success": True,
        "pricelists": pricelists,
        "latest_pricelist": latest,
        "region": region,
        "request_id": request_id,
    }


@app.post("/v1/pricelists", dependencies=[Depends(verify_api_key)])
async def register_pricelist(req: RegisterPricelistRequest, request: Request):
    """Register a new pricelist."""
    check_rate_limit("/v1/pricelists:POST")
    request_id = make_request_id("/v1/pricelists:POST", req.code)
    logger.info(f"[{request_id}] Registering pricelist: {req.code}")

    pricelist_manager.register_available_pricelist(
        code=req.code,
        date=req.date,
        region=req.region,
        description=req.description,
        sheet_tab=req.sheet_tab,
    )

    return {
        "success": True,
        "message": f"Pricelist {req.code} registered successfully",
        "request_id": request_id,
    }


@app.get("/v1/projects/{project_id}/pricelists", dependencies=[Depends(verify_api_key)])
async def get_project_pricelist_history(project_id: int, request: Request):
    """Get pricelist usage history for a project."""
    check_rate_limit("/v1/projects/pricelists")
    request_id = make_request_id("/v1/projects/pricelists", str(project_id))
    logger.info(f"[{request_id}] Project pricelist history: project_id={project_id}")

    history = pricelist_manager.get_project_pricelist_history(project_id)
    return {
        "success": True,
        "project_id": project_id,
        "pricelist_history": history,
        "request_id": request_id,
    }


@app.get("/v1/seasonal", dependencies=[Depends(verify_api_key)])
async def get_seasonal_patterns(
    request: Request,
    carrier: str = Query(..., description="Carrier name"),
):
    """Get seasonal pattern analysis for a carrier."""
    check_rate_limit("/v1/seasonal")
    request_id = make_request_id("/v1/seasonal", carrier)
    logger.info(f"[{request_id}] Seasonal patterns requested: carrier={carrier}")

    patterns = learning_service.get_seasonal_patterns(carrier)
    patterns["request_id"] = request_id
    return patterns


@app.get("/v1/adjusters/{adjuster_name}", dependencies=[Depends(verify_api_key)])
async def get_adjuster_patterns(adjuster_name: str, request: Request):
    """Get patterns for a specific adjuster."""
    check_rate_limit("/v1/adjusters")
    request_id = make_request_id("/v1/adjusters", adjuster_name)
    logger.info(f"[{request_id}] Adjuster patterns requested: {adjuster_name}")

    patterns = learning_service.get_adjuster_patterns(adjuster_name)
    patterns["request_id"] = request_id
    return patterns


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — Knowledge Base
# ══════════════════════════════════════════════════════════════

KNOWLEDGE_BASE_PATH = WORKSPACE / "mission-control" / "workspace" / "knowledge-base.md"

# Parse knowledge base into searchable sections on startup
_knowledge_sections: dict[str, dict] = {}

def _load_knowledge_base():
    """Parse knowledge-base.md into searchable sections."""
    global _knowledge_sections
    if not KNOWLEDGE_BASE_PATH.exists():
        logger.warning(f"Knowledge base not found at {KNOWLEDGE_BASE_PATH}")
        return

    content = KNOWLEDGE_BASE_PATH.read_text()
    sections = {}
    current_h2 = None
    current_h3 = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_h2:
                key = f"{current_h2}|{current_h3}" if current_h3 else current_h2
                sections[key.lower()] = {
                    "section": current_h2,
                    "subsection": current_h3,
                    "content": "\n".join(current_content).strip(),
                }
            current_h2 = line[3:].strip()
            current_h3 = None
            current_content = []
        elif line.startswith("### "):
            # Save previous subsection
            if current_h2 and current_content:
                key = f"{current_h2}|{current_h3}" if current_h3 else current_h2
                sections[key.lower()] = {
                    "section": current_h2,
                    "subsection": current_h3,
                    "content": "\n".join(current_content).strip(),
                }
            current_h3 = line[4:].strip()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_h2:
        key = f"{current_h2}|{current_h3}" if current_h3 else current_h2
        sections[key.lower()] = {
            "section": current_h2,
            "subsection": current_h3,
            "content": "\n".join(current_content).strip(),
        }

    _knowledge_sections = sections
    logger.info(f"Knowledge base loaded: {len(sections)} sections")

# Load on startup
_load_knowledge_base()


@app.get("/v1/knowledge", dependencies=[Depends(verify_api_key)])
async def get_knowledge(
    request: Request,
    topic: Optional[str] = Query(None, description="Filter by topic keyword (e.g. 'allstate', 'fence', 'o&p', 'f9')"),
    carrier: Optional[str] = Query(None, description="Filter by carrier name"),
    trade: Optional[str] = Query(None, description="Filter by trade (e.g. 'roof', 'gutters', 'fence', 'chimney')"),
    full: bool = Query(False, description="Return entire knowledge base (no filtering)"),
):
    """
    Query the supplement knowledge base — 53 lessons learned from real job reviews.
    
    Use to get strategic advice on carriers, trades, F9 strategy, and workflow tips.
    Filter by topic, carrier, or trade to get relevant lessons.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    if not _knowledge_sections:
        _load_knowledge_base()

    if not _knowledge_sections:
        return {"success": False, "error": "Knowledge base not loaded", "request_id": request_id}

    if full:
        return {
            "success": True,
            "sections": list(_knowledge_sections.values()),
            "total": len(_knowledge_sections),
            "request_id": request_id,
        }

    # Build search terms
    search_terms = []
    if topic:
        search_terms.extend(topic.lower().split())
    if carrier:
        search_terms.append(carrier.lower())
    if trade:
        search_terms.append(trade.lower())

    if not search_terms:
        # No filters — return section summaries
        summaries = [
            {"section": v["section"], "subsection": v["subsection"]}
            for v in _knowledge_sections.values()
        ]
        return {
            "success": True,
            "message": "No filter provided. Pass topic=, carrier=, or trade= to search. Pass full=true for everything.",
            "available_sections": summaries,
            "total": len(summaries),
            "request_id": request_id,
        }

    # Search sections by keyword match
    results = []
    for key, section in _knowledge_sections.items():
        full_text = f"{section['section']} {section['subsection'] or ''} {section['content']}".lower()
        if any(term in full_text for term in search_terms):
            results.append(section)

    return {
        "success": True,
        "query": {"topic": topic, "carrier": carrier, "trade": trade},
        "sections": results,
        "total": len(results),
        "request_id": request_id,
    }


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — Health
# ══════════════════════════════════════════════════════════════

@app.get("/v1/health")
async def health():
    """Service health check — no auth required."""
    checks = {
        "status": "ok",
        "version": "0.3.0",
        "timestamp": datetime.utcnow().isoformat(),
        "learning_enabled": True,
    }

    if not IS_PRODUCTION:
        checks.update({
            "workspace_exists": WORKSPACE.exists(),
            "pdf_generator_exists": PDF_GENERATOR.exists(),
            "venv_python_exists": Path(VENV_PYTHON).exists(),
            "skills_dir_exists": SKILLS_DIR.exists(),
            "api_key_configured": bool(API_KEY),
            "learning_db_path": str(learning_service.db_path),
            "learning_db_exists": learning_service.db_path.exists(),
        })
        if not all([WORKSPACE.exists(), Path(VENV_PYTHON).exists(), bool(API_KEY)]):
            checks["status"] = "degraded"
    else:
        healthy = WORKSPACE.exists() and Path(VENV_PYTHON).exists() and bool(API_KEY)
        checks["status"] = "ok" if healthy else "degraded"

    return checks


# ── Error handler ──────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error" if IS_PRODUCTION else f"Internal server error: {str(exc)}",
        },
    )
