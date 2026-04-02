"""
Profit Margin Calculator — Itemized trade-level profit margin sheet generator.

Pulls project data from IFC API + pricing from the master pricing sheet,
parses supplement estimate for exact material scope (all structures),
creates a dynamic Google Sheet with dropdowns + formulas.

Usage:
    python calculate.py "<project_name>"
    python calculate.py --project-id 5128

Output:
    JSON with sheet URL (printed to stdout)
"""

import os
import sys
import json
import logging
import requests
from pathlib import Path

# Add parent dirs to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent / "pdf-generator"))

from google.oauth2 import service_account
from googleapiclient.discovery import build as google_build

from data_pipeline import (
    fetch_project,
    fetch_action_trackers,
    find_project_folder,
    extract_claims,
    extract_address,
    IFC_API_TOKEN,
    IFC_BASE_URL,
)
from supplement_parser import get_project_scope
from sheet_builder import build_sheet

# ── Config ─────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.parent.parent
CREDS_FILE = WORKSPACE / "google-drive-key.json"
PRICING_SHEET_ID = "1S_Wj2nF0YGJyWaz0RDu_UGyCBO1dq7IneSfwv_zfGlw"
SHARED_DRIVE_ID = "0ANY__SN6vAmeUk9PVA"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("profit-margin")


# ── Google API helpers ─────────────────────────────────────────

def get_creds(scopes):
    return service_account.Credentials.from_service_account_file(
        str(CREDS_FILE).with_subject('sup@ifcroofing.com'), scopes=scopes
    )


def get_sheets_service():
    creds = get_creds(["https://www.googleapis.com/auth/spreadsheets"])
    return google_build("sheets", "v4", credentials=creds)


# ── Pricing Sheet Reader ──────────────────────────────────────

def read_pricing_sheet():
    """Read all tabs from the master pricing sheet."""
    service = get_sheets_service()
    result = {}

    tabs = {
        "materials": "'Materials Pricing'!A1:Z100",
        "labor": "'Roof Labor Pricing'!A1:Z50",
        "gutters": "'Gutters Pricing'!A1:Z50",
        "upgrades": "'Upgrades & Additional Out-of-pocket Costs'!A1:Z50",
    }

    for key, range_str in tabs.items():
        data = service.spreadsheets().values().get(
            spreadsheetId=PRICING_SHEET_ID, range=range_str
        ).execute()
        result[key] = data.get("values", [])

    return result


def parse_price(val) -> float:
    """Parse a price string like '$9,774.12' or '103.98' to float."""
    if not val:
        return 0.0
    val = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ── IFC API Data ──────────────────────────────────────────────

CREWS = ["H&R", "G5", "Achilles"]


def fetch_flow_trade_status(project_id: int) -> list:
    """Fetch action trackers (flow cards) for the project."""
    return fetch_action_trackers(project_id)


def tag_to_trade_name(tag: str) -> str:
    """Convert @tag to human-readable trade name."""
    mapping = {
        "@shingle_roof": "Roof (Shingle)",
        "@garage": "Detached Garage Roof",
        "@detach_garage_roof": "Detached Garage Roof",
        "@flatroof": "Flat Roof",
        "@metalroof": "Metal Roof",
        "@gutter": "Gutters",
        "@chimney": "Chimney",
        "@chimney_cap": "Chimney Cap",
        "@skylight": "Skylight",
        "@woodfence": "Wood Fence",
        "@ironfence": "Iron Fence",
        "@fence": "Fence",
        "@window": "Windows",
        "@screen": "Screens",
        "@siding": "Siding",
        "@paint": "Paint",
        "@drywall": "Drywall",
        "@interior": "Interior",
        "@pergola": "Pergola",
        "@gazebo": "Gazebo",
        "@shed": "Shed",
        "@patio_cover": "Patio Cover",
        "@carport": "Carport",
        "@other": "Other",
    }
    return mapping.get(tag, tag.replace("@", "").replace("_", " ").title())


def get_trade_financials(trackers: list) -> list:
    """
    Extract per-trade financial data from action trackers.
    Returns list of dicts with trade info.
    """
    trades = []
    for t in trackers:
        tag = t.get("tag", "") or t.get("content", "")
        if not tag or tag in ["@general", "@op", "@overhead", "@ifc"]:
            continue

        doing_status = t.get("doing_the_work_status")
        doing = str(doing_status).lower() in ("yes", "true", "1") if doing_status else False
        emoji = t.get("supplement_status_emoji", "")
        if not doing and emoji in ["👍", "💰", "👏"]:
            doing = True

        ins_rcv = parse_price(t.get("latest_rcv_rcv", 0))
        supp_rcv = parse_price(t.get("retail_exactimate_bid", 0))
        sub_bid = parse_price(t.get("original_sub_bid_price", 0))
        nrd = parse_price(t.get("latest_rcv_non_recoverable_depreciation", 0))
        op_ins = parse_price(t.get("latest_rcv_op", 0))
        op_supp = parse_price(t.get("op_from_ifc_supplement", 0))

        if supp_rcv == 0:
            supp_rcv = ins_rcv  # fallback

        trades.append({
            "tag": tag,
            "trade_name": tag_to_trade_name(tag),
            "doing": doing,
            "emoji": emoji,
            "ins_rcv": ins_rcv,
            "ins_rcv_total": ins_rcv + op_ins,
            "supp_rcv": supp_rcv,
            "supp_rcv_total": supp_rcv + op_supp,
            "sub_bid_cost": sub_bid,
            "nrd": nrd,
            "is_roof": tag in ["@shingle_roof", "@garage", "@detach_garage_roof", "@flatroof", "@metalroof"],
            "raw": t,
        })

    return trades


# ── EV Measurements ───────────────────────────────────────────

def get_ev_measurements(project_id: int, project_name: str = "") -> dict:
    """
    Get EagleView measurements. Priority:
    1. Local cache (.pipeline_cache/ev_{id}.json)
    2. Download from Drive + parse + cache
    Returns dict with sq_off, sq_on, waste_pct, eaves_rakes_lf, etc.
    """
    cache_dir = WORKSPACE / ".pipeline_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / f"ev_{project_id}.json"

    # 1. Check local cache
    if cache_path.exists():
        with open(cache_path) as f:
            logger.info(f"EV loaded from cache: {cache_path.name}")
            return json.load(f)

    # Try any matching cache file
    for cf in cache_dir.glob(f"*{project_id}*.json"):
        try:
            with open(cf) as f:
                data = json.load(f)
            if "ev_measurements" in data:
                return data["ev_measurements"]
            if "sq_off" in data or "total_sq" in data:
                return data
        except (json.JSONDecodeError, KeyError):
            continue

    # 2. Download EV PDF from Drive and parse it
    if project_name:
        ev_data = _fetch_ev_from_drive(project_id, project_name)
        if ev_data:
            # Cache it for next time
            with open(cache_path, "w") as f:
                json.dump(ev_data, f, indent=2)
            logger.info(f"EV cached: {cache_path.name}")
            return ev_data

    logger.warning(f"No EV measurements found for project {project_id}")
    return {}


def _fetch_ev_from_drive(project_id: int, project_name: str) -> dict:
    """Download EagleView PDF from project's Drive folder, parse it, return measurements."""
    import tempfile
    from data_pipeline import find_project_folder, search_drive_file, download_drive_file
    from parse_eagleview import parse_eagleview

    # Find the project folder in Drive
    # We need to reconstruct a minimal project dict for find_project_folder
    headers = {"Authorization": f"Bearer {IFC_API_TOKEN}"}
    r = requests.get(f"{IFC_BASE_URL}/projects/{project_id}", headers=headers)
    r.raise_for_status()
    project = r.json()
    if "project" in project:
        project = project["project"]

    folder_id = find_project_folder(project)
    if not folder_id:
        logger.warning("No Drive folder found for EV search")
        return {}

    # Search for EagleView PDF
    lastname = project_name.strip().split()[-1] if project_name else ""
    ev_file_id = None
    for pattern in [f"{lastname}_EagleView", f"{lastname.upper()}_EagleView", "EagleView"]:
        ev_file_id = search_drive_file(pattern, folder_id)
        if ev_file_id:
            break

    if not ev_file_id:
        logger.warning(f"No EagleView PDF found in Drive for {project_name}")
        return {}

    # Download and parse
    with tempfile.TemporaryDirectory() as td:
        ev_pdf_path = os.path.join(td, "eagleview.pdf")
        logger.info(f"Downloading EagleView from Drive...")
        download_drive_file(ev_file_id, ev_pdf_path)
        logger.info(f"Parsing EagleView...")
        raw = parse_eagleview(ev_pdf_path)
        ev_data = _normalize_ev(raw)
        logger.info(f"EV measurements: {ev_data}")
        return ev_data


def _normalize_ev(raw: dict) -> dict:
    """
    Flatten the nested parse_eagleview output into the simple dict
    that sheet_builder expects: sq_on, sq_off, eaves_rakes_lf, etc.
    """
    rs = raw.get("roofing_summary", {})
    all_s = rs.get("all_structures", {})
    lengths = raw.get("lengths", {})
    struct_lengths = all_s.get("lengths", {})

    def _best(key):
        return struct_lengths.get(key) or lengths.get(key) or rs.get(key) or 0

    # Measured SQ (0% waste)
    measured_sq = rs.get("measured_sq") or 0
    # Suggested SQ (with waste)
    suggested_sq = rs.get("suggested_sq") or 0
    waste_pct = rs.get("suggested_waste_pct") or 0

    # Pitch — check structures for predominant pitch
    pitch = 0
    for s in rs.get("structures", []):
        p = s.get("predominant_pitch") or s.get("pitch") or 0
        if p > pitch:
            pitch = p
    if not pitch:
        pitch = all_s.get("predominant_pitch", 0)

    eaves = _best("eaves_lf") or _best("eaves_starter_lf")
    rakes = _best("rakes_lf")
    ridges = _best("ridges_lf")
    hips = _best("hips_lf")
    hip_ridge = rs.get("ridges_hips_lf") or (ridges + hips)

    return {
        "total_sq": measured_sq,
        "measured_sq": measured_sq,
        "sq_off": measured_sq,
        "sq_on": suggested_sq,
        "suggested_sq": suggested_sq,
        "waste_pct": waste_pct,
        "pitch": pitch,
        "eaves_lf": eaves,
        "rakes_lf": rakes,
        "eaves_rakes_lf": (eaves or 0) + (rakes or 0),
        "drip_edge_lf": _best("drip_edge_lf") or ((eaves or 0) + (rakes or 0)),
        "hip_ridge_lf": hip_ridge,
        "ridges_lf": ridges,
        "hips_lf": hips,
        "valleys_lf": _best("valleys_lf"),
        "step_flashing_lf": _best("step_flashing_lf"),
        "flashing_lf": _best("flashing_lf"),
        "ridge_vent_lf": 0,  # EV doesn't measure this
    }


# ── Labor Cost Parser ─────────────────────────────────────────

def parse_labor_costs(labor_rows: list, sq: float, pitch: int) -> dict:
    """
    Parse roof labor pricing tab. Returns {crew: {base_rate, steep_adder, total_rate, total_cost}}.
    """
    crew_cols = {"H&R": 3, "G5": 5, "Achilles": 7}
    costs = {}

    for crew_name, rate_col in crew_cols.items():
        base_rate = 0
        steep_adder = 0

        for row in labor_rows:
            if len(row) <= rate_col:
                continue
            category = (row[1] if len(row) > 1 else "").strip().lower()
            rate_str = (row[rate_col] if len(row) > rate_col else "").strip()
            if not rate_str:
                continue
            rate = parse_price(rate_str)

            if "field square" in category:
                base_rate = rate
            elif category == f"{pitch}/12":
                steep_adder = rate

        total_rate = base_rate + steep_adder
        costs[crew_name] = {
            "base_rate": base_rate,
            "steep_adder": steep_adder,
            "total_rate": total_rate,
            "total_cost": round(total_rate * sq, 2),
        }

    return costs


# ── Main Entry Point ──────────────────────────────────────────

def run(project_name: str = None, project_id: int = None) -> dict:
    """
    Main entry point. Fetches all data, calculates costs, creates dynamic sheet.
    Returns {"success": True, "sheet_url": "...", "project": "..."}.
    """

    # 1. Fetch project from IFC API
    if project_name:
        project = fetch_project(project_name)
    elif project_id:
        headers = {"Authorization": f"Bearer {IFC_API_TOKEN}"}
        r = requests.get(f"{IFC_BASE_URL}/projects/{project_id}", headers=headers)
        r.raise_for_status()
        project = r.json()
        if "project" in project:
            project = project["project"]
    else:
        return {"success": False, "error": "project_name or project_id required"}

    pid = project.get("id")
    pname = project.get("name", "Unknown")
    logger.info(f"Project: {pname} (ID: {pid})")

    # 2. Fetch flow cards (trade status + financials)
    trackers = fetch_flow_trade_status(pid)
    trades = get_trade_financials(trackers)

    active_count = len([t for t in trades if t["doing"]])
    logger.info(f"Trades: {len(trades)} total, {active_count} active")

    if active_count == 0:
        return {
            "success": False,
            "error": "No active trades found. Flow cards may not be set up yet.",
        }

    # 3. Get EV measurements (checks cache first, then pulls from Drive)
    ev = get_ev_measurements(pid, pname)

    # 4. Read master pricing sheet
    pricing = read_pricing_sheet()

    # 5. Parse labor costs (needed by sheet_builder for formula references)
    sq_on = ev.get("sq_on", ev.get("suggested_sq", 0))
    pitch = ev.get("pitch", ev.get("predominant_pitch", 0))
    labor_costs = parse_labor_costs(pricing["labor"], sq_on, pitch)

    # 6. Get supplement scope (material quantities from our estimate)
    #    This gives us exact quantities per structure instead of raw EV
    scope_result = get_project_scope(pid, pname)
    roof_scope = None
    if scope_result["found"]:
        roof_scope = scope_result["roof_scope"]
        structures = list(roof_scope.get("structures", {}).keys())
        logger.info(f"Supplement scope found — structures: {structures}")
        logger.info(f"  Shingle SQ: {roof_scope['shingle_sq']}, "
                     f"Tearoff SQ: {roof_scope['tearoff_sq']}, "
                     f"Starter LF: {roof_scope['starter_lf']}")
    else:
        logger.warning(f"No supplement estimate found — using raw EV measurements")

    # 7. Create dynamic sheet (dropdowns + formulas)
    sheet_url = build_sheet(
        project_name=pname,
        trades=trades,
        pricing_data=pricing,
        ev_data=ev,
        labor_data_parsed=labor_costs,
        roof_scope=roof_scope,
    )

    result = {
        "success": True,
        "sheet_url": sheet_url,
        "project": pname,
        "project_id": pid,
        "trades_active": active_count,
        "has_ev": bool(ev),
        "has_supplement_scope": scope_result["found"],
        "structures": list(roof_scope["structures"].keys()) if roof_scope else [],
        "warnings": [],
    }

    if not ev:
        result["warnings"].append("No EagleView data — roof material costs may be incomplete")
    if not scope_result["found"]:
        result["warnings"].append("No supplement estimate — using raw EV for quantities")

    logger.info(f"Sheet created: {sheet_url}")
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate profit margin sheet")
    parser.add_argument("project_name", nargs="?", help="Project name to search")
    parser.add_argument("--project-id", type=int, help="Project ID (alternative to name)")

    args = parser.parse_args()

    if not args.project_name and not args.project_id:
        print("Usage: python calculate.py \"Project Name\" or --project-id 1234")
        sys.exit(1)

    run(project_name=args.project_name, project_id=args.project_id)
