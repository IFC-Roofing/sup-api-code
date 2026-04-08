"""
Dashboard data endpoints — pipeline, revenue, activity, attention items.
All data pulled from IFC API with caching to handle API instability.
"""
import os
import time
import logging
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from backend.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

IFC_API_BASE = os.getenv("IFC_API_BASE", "https://omni.ifc.shibui.ar")
IFC_API_TOKEN = os.getenv("IFC_API_TOKEN", "")

# ── Simple in-memory cache ──────────────────────────────────────
# Stale-while-revalidate: serve cached data when API is down

_cache: dict[str, dict] = {}  # key -> {"data": ..., "ts": epoch}
CACHE_TTL = 300  # 5 min fresh
CACHE_STALE_TTL = 3600  # 1 hour stale OK


def _cache_get(key: str):
    entry = _cache.get(key)
    if not entry:
        return None, False
    age = time.time() - entry["ts"]
    if age < CACHE_TTL:
        return entry["data"], True  # fresh
    if age < CACHE_STALE_TTL:
        return entry["data"], False  # stale but usable
    return None, False  # expired


def _cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


# ── IFC API field mapping ───────────────────────────────────────
# IFC API uses record_status (uppercase) for pipeline status

STAGE_DISPLAY = {
    "LEAD": "Lead",
    "SIGNED": "Signed",
    "REP HANDS": "Rep Hands",
    "REP_HANDS": "Rep Hands",
    "INSPECTED": "Inspected",
    "INSPECTION_SCHEDULED": "Inspection Scheduled",
    "INSPECTION SCHEDULED": "Inspection Scheduled",
    "INSPECTION_COMPLETE": "Inspection Complete",
    "INSPECTION COMPLETE": "Inspection Complete",
    "CLAIM_FILED": "Claim Filed",
    "CLAIM FILED": "Claim Filed",
    "OFFICE_HANDS": "Office Hands",
    "OFFICE HANDS": "Office Hands",
    "SUPPLEMENT_SENT": "Supplement Sent",
    "SUPPLEMENT SENT": "Supplement Sent",
    "RESPONSE_RECEIVED": "Response Received",
    "RESPONSE RECEIVED": "Response Received",
    "APPRAISAL": "Appraisal",
    "APPROVED": "Approved",
    "IN_PRODUCTION": "In Production",
    "IN PRODUCTION": "In Production",
    "CAPPED_OUT": "Capped Out",
    "CAPPED OUT": "Capped Out",
}

PIPELINE_ORDER = [
    "Lead", "Signed", "Rep Hands", "Inspected",
    "Inspection Scheduled", "Inspection Complete",
    "Claim Filed", "Office Hands", "Supplement Sent", "Response Received",
    "Appraisal", "Approved", "In Production", "Capped Out",
]


def ifc_headers():
    return {"Authorization": f"Bearer {IFC_API_TOKEN}"}


def _get_status(project: dict) -> str:
    raw = project.get("record_status") or project.get("status") or "Unknown"
    return STAGE_DISPLAY.get(raw.upper().strip(), raw.replace("_", " ").title())


async def _fetch_all_projects(timeout: float = 15) -> list:
    """Fetch all projects with pagination. Per-page kept small for API stability."""
    cache_key = "all_projects"
    cached, fresh = _cache_get(cache_key)
    if fresh:
        return cached

    per_page = 25  # Small pages — IFC API chokes on large ones
    all_projects = []
    page = 1
    max_pages = 300  # 25 × 300 = 7500 projects max

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            while page <= max_pages:
                r = await client.get(
                    f"{IFC_API_BASE}/projects",
                    headers=ifc_headers(),
                    params={"per_page": per_page, "page": page},
                )
                r.raise_for_status()
                data = r.json()

                if isinstance(data, dict):
                    projects = data.get("data", data.get("projects", []))
                    total_pages = data.get("total_pages", 1)
                elif isinstance(data, list):
                    projects = data
                    total_pages = 1
                else:
                    break

                all_projects.extend(projects)

                if page >= total_pages or not projects:
                    break
                page += 1

        _cache_set(cache_key, all_projects)
        return all_projects

    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
        logger.error(f"IFC API error on page {page}: {e}")
        # Return stale cache if available
        if cached is not None:
            logger.warning(f"Serving stale cache ({len(cached)} projects)")
            return cached
        raise HTTPException(
            status_code=504,
            detail="IFC API is temporarily unavailable. Please try again in a few minutes.",
        )


@router.get("/pipeline")
async def pipeline(user: dict = Depends(get_current_user)):
    """Job counts by status for pipeline funnel."""
    projects = await _fetch_all_projects()

    status_counts: dict[str, int] = {}
    for p in projects:
        status = _get_status(p)
        status_counts[status] = status_counts.get(status, 0) + 1

    result = []
    seen = set()
    for stage in PIPELINE_ORDER:
        count = status_counts.get(stage, 0)
        if count > 0:
            result.append({"stage": stage, "count": count})
        seen.add(stage)

    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        if status not in seen and count > 0:
            result.append({"stage": status, "count": count})

    return {"pipeline": result, "total": len(projects)}


@router.get("/revenue")
async def revenue(user: dict = Depends(get_current_user)):
    """Revenue snapshot.

    NOTE: IFC /projects endpoint has no financial fields (RCV, GP).
    Returns project counts as a proxy until action_tracker integration.
    """
    projects = await _fetch_all_projects()

    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active_count = 0
    capped_this_week = 0
    capped_this_month = 0
    total_capped = 0

    for p in projects:
        status = _get_status(p)
        date_change_str = p.get("date_status_change") or p.get("updated_at") or ""

        if status == "Capped Out":
            total_capped += 1
            try:
                cap_date = datetime.fromisoformat(
                    date_change_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if cap_date >= week_ago:
                    capped_this_week += 1
                if cap_date >= month_start:
                    capped_this_month += 1
            except (ValueError, AttributeError):
                pass
        elif status not in ("Lead", "Unknown"):
            active_count += 1

    return {
        # Financial fields — $0 until we integrate action_trackers
        "pipeline_rcv": 0,
        "capped_this_week": 0,
        "capped_this_month": 0,
        "avg_gp_pct": 0,
        # Project counts (supplementary)
        "_active_projects": active_count,
        "_capped_this_week_count": capped_this_week,
        "_capped_this_month_count": capped_this_month,
        "_total_capped": total_capped,
        "_note": "RCV/GP data not on /projects endpoint — needs action_tracker integration",
    }


@router.get("/activity")
async def activity(user: dict = Depends(get_current_user)):
    """Recent Sup activity — estimates, markups, reviews."""
    cache_key = "activity"
    cached, fresh = _cache_get(cache_key)
    if fresh:
        return {"activities": cached}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{IFC_API_BASE}/posts",
                headers=ifc_headers(),
                params={"user": "sup", "per_page": 20},
            )
            r.raise_for_status()
            posts = r.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
        logger.error(f"IFC API error fetching posts: {e}")
        if cached is not None:
            return {"activities": cached}
        raise HTTPException(status_code=504, detail="IFC API temporarily unavailable")

    if isinstance(posts, dict):
        posts = posts.get("data", posts.get("post_notes", []))

    activities = []
    for post in posts[:20]:
        activities.append({
            "id": post.get("id"),
            "project_name": post.get("project_name", ""),
            "project_id": post.get("project_id"),
            "content": post.get("content", post.get("body", ""))[:200],
            "created_at": post.get("created_at", ""),
            "tags": post.get("tags", []),
        })

    _cache_set(cache_key, activities)
    return {"activities": activities}


@router.get("/attention")
async def attention(user: dict = Depends(get_current_user)):
    """Jobs needing attention — stuck, missing items, overdue."""
    projects = await _fetch_all_projects()

    now = datetime.now()
    items = []

    for p in projects:
        status = _get_status(p)
        name = p.get("name", p.get("insured_name", "Unknown"))
        project_id = p.get("id")
        updated = p.get("updated_at", "")

        try:
            updated_dt = datetime.fromisoformat(
                updated.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            days_stale = (now - updated_dt).days
        except (ValueError, AttributeError):
            days_stale = 0

        if status == "Office Hands" and days_stale > 3:
            items.append({
                "project_id": project_id,
                "project_name": name,
                "issue": "Stuck in Office Hands",
                "detail": f"{days_stale} days without update",
                "severity": "high" if days_stale > 7 else "medium",
            })

        if status in ("Supplement Sent", "Response Received") and days_stale > 14:
            items.append({
                "project_id": project_id,
                "project_name": name,
                "issue": "Awaiting insurance response",
                "detail": f"{days_stale} days since last update",
                "severity": "high" if days_stale > 21 else "medium",
            })

    severity_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: severity_order.get(x["severity"], 2))

    return {"items": items[:20]}


@router.get("/stats")
async def stats(user: dict = Depends(get_current_user)):
    """Combined stats endpoint — pipeline + attention in one call.
    More efficient for the frontend than separate requests.
    """
    projects = await _fetch_all_projects()

    now = datetime.now()
    status_counts: dict[str, int] = {}
    attention_items = []

    for p in projects:
        status = _get_status(p)
        status_counts[status] = status_counts.get(status, 0) + 1

        # Attention logic
        name = p.get("name", "Unknown")
        updated = p.get("updated_at", "")
        try:
            updated_dt = datetime.fromisoformat(
                updated.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            days_stale = (now - updated_dt).days
        except (ValueError, AttributeError):
            days_stale = 0

        if status == "Office Hands" and days_stale > 3:
            attention_items.append({
                "project_id": p.get("id"),
                "project_name": name,
                "issue": "Stuck in Office Hands",
                "detail": f"{days_stale}d",
                "severity": "high" if days_stale > 7 else "medium",
            })
        elif status in ("Supplement Sent", "Response Received") and days_stale > 14:
            attention_items.append({
                "project_id": p.get("id"),
                "project_name": name,
                "issue": "Awaiting INS response",
                "detail": f"{days_stale}d",
                "severity": "high" if days_stale > 21 else "medium",
            })

    # Pipeline
    pipeline_result = []
    seen = set()
    for stage in PIPELINE_ORDER:
        count = status_counts.get(stage, 0)
        if count > 0:
            pipeline_result.append({"stage": stage, "count": count})
        seen.add(stage)
    for st, ct in sorted(status_counts.items(), key=lambda x: -x[1]):
        if st not in seen and ct > 0:
            pipeline_result.append({"stage": st, "count": ct})

    severity_order = {"high": 0, "medium": 1, "low": 2}
    attention_items.sort(key=lambda x: severity_order.get(x["severity"], 2))

    return {
        "pipeline": pipeline_result,
        "total_projects": len(projects),
        "attention": attention_items[:20],
        "status_counts": status_counts,
    }
