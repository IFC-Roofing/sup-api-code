"""
Dashboard data endpoints — pipeline, revenue, activity, attention items.
All data pulled from IFC API.
"""
import os
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

IFC_API_BASE = os.getenv("IFC_API_BASE", "https://omni.ifc.shibui.ar")
IFC_API_TOKEN = os.getenv("IFC_API_TOKEN", "")


def ifc_headers():
    return {"Authorization": f"Bearer {IFC_API_TOKEN}"}


@router.get("/pipeline")
async def pipeline(user: dict = Depends(get_current_user)):
    """Job counts by status for pipeline funnel."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{IFC_API_BASE}/projects", headers=ifc_headers(),
                             params={"per_page": 1000})
        r.raise_for_status()
        projects = r.json()

    # Handle both list and paginated response
    if isinstance(projects, dict):
        projects = projects.get("data", projects.get("projects", []))

    # Count by status
    status_counts = {}
    for p in projects:
        status = p.get("status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    # Define pipeline stages in order
    pipeline_stages = [
        "New Lead", "Signed", "Inspection Scheduled", "Inspection Complete",
        "Claim Filed", "Office Hands", "Supplement Sent", "Response Received",
        "Appraisal", "Approved", "In Production", "Capped Out"
    ]

    result = []
    for stage in pipeline_stages:
        count = status_counts.pop(stage, 0)
        if count > 0:
            result.append({"stage": stage, "count": count})

    # Add any remaining statuses not in our predefined list
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            result.append({"stage": status, "count": count})

    return {"pipeline": result, "total": len(projects)}


@router.get("/revenue")
async def revenue(user: dict = Depends(get_current_user)):
    """Revenue snapshot — RCV in pipeline, capped out this week/month."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{IFC_API_BASE}/projects", headers=ifc_headers(),
                             params={"per_page": 1000})
        r.raise_for_status()
        projects = r.json()

    if isinstance(projects, dict):
        projects = projects.get("data", projects.get("projects", []))

    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pipeline_rcv = 0.0
    capped_this_week = 0.0
    capped_this_month = 0.0
    total_gp_pct = []

    for p in projects:
        rcv = float(p.get("collected_rcv") or p.get("rcv") or 0)
        status = p.get("status", "")
        gp_pct = p.get("gross_profit_pct") or p.get("gp_pct")

        if status == "Capped Out":
            # Check cap out date
            cap_date_str = p.get("capped_out_at") or p.get("updated_at") or ""
            try:
                cap_date = datetime.fromisoformat(cap_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if cap_date >= week_ago:
                    capped_this_week += rcv
                if cap_date >= month_start:
                    capped_this_month += rcv
            except (ValueError, AttributeError):
                pass
            if gp_pct:
                total_gp_pct.append(float(gp_pct))
        else:
            pipeline_rcv += rcv

    avg_gp = sum(total_gp_pct) / len(total_gp_pct) if total_gp_pct else 0.0

    return {
        "pipeline_rcv": round(pipeline_rcv, 2),
        "capped_this_week": round(capped_this_week, 2),
        "capped_this_month": round(capped_this_month, 2),
        "avg_gp_pct": round(avg_gp, 1),
    }


@router.get("/activity")
async def activity(user: dict = Depends(get_current_user)):
    """Recent Sup activity — estimates, markups, reviews."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Pull recent posts tagged with sup activity
        r = await client.get(f"{IFC_API_BASE}/posts", headers=ifc_headers(),
                             params={"user": "sup", "per_page": 20})
        r.raise_for_status()
        posts = r.json()

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

    return {"activities": activities}


@router.get("/attention")
async def attention(user: dict = Depends(get_current_user)):
    """Jobs needing attention — stuck, missing items, overdue."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{IFC_API_BASE}/projects", headers=ifc_headers(),
                             params={"per_page": 1000})
        r.raise_for_status()
        projects = r.json()

    if isinstance(projects, dict):
        projects = projects.get("data", projects.get("projects", []))

    now = datetime.now()
    items = []

    for p in projects:
        status = p.get("status", "")
        name = p.get("name", p.get("insured_name", "Unknown"))
        project_id = p.get("id")
        updated = p.get("updated_at", "")

        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
            days_stale = (now - updated_dt).days
        except (ValueError, AttributeError):
            days_stale = 0

        # Flag jobs stuck in Office Hands > 3 days
        if status == "Office Hands" and days_stale > 3:
            items.append({
                "project_id": project_id,
                "project_name": name,
                "issue": "Stuck in Office Hands",
                "detail": f"{days_stale} days without update",
                "severity": "high" if days_stale > 7 else "medium",
            })

        # Flag jobs waiting on insurance response > 14 days
        if status in ("Supplement Sent", "Response Received") and days_stale > 14:
            items.append({
                "project_id": project_id,
                "project_name": name,
                "issue": "Awaiting insurance response",
                "detail": f"{days_stale} days since last update",
                "severity": "high" if days_stale > 21 else "medium",
            })

    # Sort by severity (high first), then days
    severity_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: severity_order.get(x["severity"], 2))

    return {"items": items[:20]}
