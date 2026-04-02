"""
Supplement Estimate Parser — Extracts material specs from IFC supplement JSON.

Maps supplement line items to material categories for the profit margin sheet.
The supplement is the source of truth for what's in scope.
"""

import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("profit-margin")

WORKSPACE = Path(__file__).parent.parent.parent


# ── Line Item Classification ──────────────────────────────────

def classify_line_item(desc: str) -> Optional[dict]:
    """
    Classify a supplement line item into a material/labor category.
    Returns dict with category + any extracted details, or None if not material-related.
    """
    d = desc.lower()
    
    # Shingles
    if "comp. shingle rfg" in d or "shingle roofing" in d:
        shingle_type = "Certainteed Landmark"  # default
        if "laminated" in d:
            shingle_type = "Certainteed Landmark"  # laminated = architectural/dimensional
        elif "3-tab" in d or "3 tab" in d:
            shingle_type = "Certainteed XT25"
        return {"category": "shingle", "inferred_product": shingle_type}
    
    # Tear off (same SQ as shingles but measured, no waste)
    if "tear off" in d and "shingle" in d:
        return {"category": "tearoff"}
    
    # Underlayment / felt
    if "roofing felt" in d or "underlayment" in d or "synthetic" in d:
        return {"category": "underlayment"}
    
    # Starter
    if "starter" in d:
        return {"category": "starter"}
    
    # Ridge cap
    if "hip" in d and "ridge" in d and "cap" in d:
        return {"category": "ridge_cap"}
    
    # Ice & water
    if "ice" in d and "water" in d:
        return {"category": "ice_water"}
    
    # Vents
    if "vent" in d and "ridge" in d:
        return {"category": "ridge_vent"}
    if "turbine" in d:
        return {"category": "vent", "vent_type": "turbine"}
    if "turtle" in d:
        return {"category": "vent", "vent_type": "turtle"}
    if "power vent" in d:
        return {"category": "vent", "vent_type": "power_vent"}
    if "exhaust cap" in d:
        return {"category": "exhaust_cap"}
    
    # Pipe jacks
    if "pipe jack" in d or "flashing - pipe" in d:
        return {"category": "pipe_jack"}
    
    # Drip edge
    if "drip edge" in d:
        return {"category": "drip_edge"}
    
    # Step flashing
    if "step flash" in d:
        return {"category": "step_flashing"}
    
    # Valley metal
    if "valley" in d and "metal" in d:
        return {"category": "valley_metal"}
    
    # Counterflashing
    if "counterflash" in d or "apron flash" in d:
        return {"category": "counterflashing"}
    
    # Steep charges
    if "steep" in d:
        return {"category": "steep_charge"}
    
    # High roof
    if "high roof" in d or "2 stories" in d:
        return {"category": "high_roof"}
    
    # Paint
    if "prime" in d and "paint" in d:
        return {"category": "paint"}
    
    # Dumpster
    if "dumpster" in d:
        return {"category": "dumpster"}
    
    return None


# ── Supplement Scope Extractor ────────────────────────────────

def extract_roof_scope(estimate: dict) -> dict:
    """
    Extract full roof material scope from the supplement estimate JSON.
    Returns a structured dict with all material quantities + specs.
    """
    scope = {
        # Quantities (from supplement line items)
        "shingle_sq": 0,        # SQ with waste (install)
        "tearoff_sq": 0,        # SQ measured (no waste)
        "underlayment_sq": 0,   # matches shingle SQ
        "starter_lf": 0,
        "ridge_cap_lf": 0,
        "drip_edge_lf": 0,
        "valley_metal_lf": 0,
        "step_flashing_lf": 0,
        "counterflashing_lf": 0,
        "ice_water_sf": 0,
        "ridge_vent_lf": 0,
        
        # Counts
        "pipe_jacks": 0,
        "turbines": 0,
        "turtle_vents": 0,
        "power_vents": 0,
        "exhaust_caps": 0,
        "dumpsters": 0,
        
        # Inferred specs
        "shingle_type": None,
        "vent_type": None,       # "ridge_vent", "turbine", "turtle", "power_vent"
        "has_steep": False,
        "has_high_roof": False,
        "pitch": None,
        
        # Structures
        "structures": {},        # {name: {shingle_sq, tearoff_sq, ...}}
        
        # Raw items for reference
        "all_roof_items": [],
    }
    
    for section in estimate.get("sections", []):
        section_name = section.get("name", "")
        
        # Only process roof sections
        is_roof = any(k in section_name.lower() for k in [
            "dwelling roof", "garage roof", "detached garage", "flat roof", "metal roof"
        ])
        
        if not is_roof:
            continue
        
        structure = section_name
        struct_scope = {
            "shingle_sq": 0, "tearoff_sq": 0, "starter_lf": 0,
            "ridge_cap_lf": 0, "drip_edge_lf": 0,
        }
        
        for item in section.get("line_items", []):
            desc = item.get("description", "")
            qty = item.get("qty", 0)
            unit = item.get("unit", "")
            is_bid = item.get("is_bid", False)
            
            # Skip bid items — they don't affect material quantities
            if is_bid:
                continue
            
            cls = classify_line_item(desc)
            if not cls:
                continue
            
            cat = cls["category"]
            
            if cat == "shingle":
                scope["shingle_sq"] += qty
                struct_scope["shingle_sq"] = qty
                if cls.get("inferred_product") and not scope["shingle_type"]:
                    scope["shingle_type"] = cls["inferred_product"]
            
            elif cat == "tearoff":
                scope["tearoff_sq"] += qty
                struct_scope["tearoff_sq"] = qty
            
            elif cat == "underlayment":
                scope["underlayment_sq"] += qty
            
            elif cat == "starter":
                scope["starter_lf"] += qty
                struct_scope["starter_lf"] = qty
            
            elif cat == "ridge_cap":
                scope["ridge_cap_lf"] += qty
                struct_scope["ridge_cap_lf"] = qty
            
            elif cat == "drip_edge":
                scope["drip_edge_lf"] += qty
                struct_scope["drip_edge_lf"] = qty
            
            elif cat == "valley_metal":
                scope["valley_metal_lf"] += qty
            
            elif cat == "step_flashing":
                scope["step_flashing_lf"] += qty
            
            elif cat == "counterflashing":
                scope["counterflashing_lf"] += qty
            
            elif cat == "ice_water":
                scope["ice_water_sf"] += qty
            
            elif cat == "ridge_vent":
                scope["ridge_vent_lf"] += qty
                scope["vent_type"] = "ridge_vent"
            
            elif cat == "vent":
                vtype = cls.get("vent_type", "")
                if vtype == "turbine":
                    scope["turbines"] += int(qty)
                elif vtype == "turtle":
                    scope["turtle_vents"] += int(qty)
                elif vtype == "power_vent":
                    scope["power_vents"] += int(qty)
                if not scope["vent_type"]:
                    scope["vent_type"] = vtype
            
            elif cat == "exhaust_cap":
                scope["exhaust_caps"] += int(qty)
            
            elif cat == "pipe_jack":
                scope["pipe_jacks"] += int(qty)
            
            elif cat == "steep_charge":
                scope["has_steep"] = True
            
            elif cat == "high_roof":
                scope["has_high_roof"] = True
            
            elif cat == "dumpster":
                scope["dumpsters"] += int(qty)
            
            scope["all_roof_items"].append({
                "section": section_name,
                "description": desc,
                "qty": qty,
                "unit": unit,
                "category": cat,
            })
        
        scope["structures"][structure] = struct_scope
    
    return scope


def extract_trade_bids(estimate: dict) -> dict:
    """
    Extract bid items per trade from the supplement.
    Returns {trade_name: [{description, qty, total}, ...]}.
    """
    bids = {}
    for section in estimate.get("sections", []):
        section_name = section.get("name", "")
        for item in section.get("line_items", []):
            if item.get("is_bid", False):
                if section_name not in bids:
                    bids[section_name] = []
                bids[section_name].append({
                    "description": item["description"],
                    "qty": item["qty"],
                    "unit": item["unit"],
                    "total": item.get("total", 0),
                    "sub_name": item.get("sub_name", ""),
                })
    return bids


# ── Estimate Finder ───────────────────────────────────────────

def find_estimate_json(project_id: int, project_name: str = "") -> Optional[dict]:
    """
    Find the most recent estimate JSON for a project.
    Checks: pipeline cache → pdf-generator directory.
    """
    # Check pipeline cache first
    cache_dir = WORKSPACE / ".pipeline_cache"
    if cache_dir.exists():
        # Try exact match
        for pattern in [f"estimate_{project_id}.json", f"*{project_id}*estimate*.json"]:
            matches = list(cache_dir.glob(pattern))
            if matches:
                with open(matches[0]) as f:
                    data = json.load(f)
                if "sections" in data:
                    logger.info(f"Found estimate in cache: {matches[0].name}")
                    return data
    
    # Check pdf-generator directory
    gen_dir = WORKSPACE / "tools" / "pdf-generator"
    if gen_dir.exists() and project_name:
        # Files are named like ISBELL_estimate.json
        last_name = project_name.split()[-1].upper() if project_name else ""
        for pattern in [f"{last_name}_estimate.json", f"*{last_name}*estimate*.json"]:
            matches = list(gen_dir.glob(pattern))
            if matches:
                with open(matches[0]) as f:
                    data = json.load(f)
                if "sections" in data:
                    logger.info(f"Found estimate: {matches[0].name}")
                    return data
    
    logger.warning(f"No estimate JSON found for project {project_id} ({project_name})")
    return None


# ── Main API ──────────────────────────────────────────────────

def get_project_scope(project_id: int, project_name: str = "") -> dict:
    """
    Get full project scope from supplement estimate.
    Returns roof scope + trade bids + metadata.
    """
    estimate = find_estimate_json(project_id, project_name)
    
    if not estimate:
        return {
            "found": False,
            "error": "No supplement estimate found",
            "roof_scope": None,
            "trade_bids": None,
        }
    
    roof_scope = extract_roof_scope(estimate)
    trade_bids = extract_trade_bids(estimate)
    
    return {
        "found": True,
        "estimate_name": estimate.get("estimate_name", ""),
        "rcv_total": estimate.get("rcv_total", 0),
        "roof_scope": roof_scope,
        "trade_bids": trade_bids,
        "sections": [s["name"] for s in estimate.get("sections", [])],
    }


if __name__ == "__main__":
    import sys
    
    # Quick test
    scope = get_project_scope(4965, "Chris Isbell")
    
    if scope["found"]:
        rs = scope["roof_scope"]
        print(f"Estimate: {scope['estimate_name']}")
        print(f"RCV Total: ${scope['rcv_total']:,.2f}")
        print(f"\nRoof Scope:")
        print(f"  Shingle type: {rs['shingle_type']}")
        print(f"  Shingle SQ: {rs['shingle_sq']}")
        print(f"  Tearoff SQ: {rs['tearoff_sq']}")
        print(f"  Starter LF: {rs['starter_lf']}")
        print(f"  Ridge Cap LF: {rs['ridge_cap_lf']}")
        print(f"  Drip Edge LF: {rs['drip_edge_lf']}")
        print(f"  Valley Metal LF: {rs['valley_metal_lf']}")
        print(f"  Step Flashing LF: {rs['step_flashing_lf']}")
        print(f"  Ice & Water SF: {rs['ice_water_sf']}")
        print(f"  Ridge Vent LF: {rs['ridge_vent_lf']}")
        print(f"  Pipe Jacks: {rs['pipe_jacks']}")
        print(f"  Vent Type: {rs['vent_type']}")
        print(f"  Turbines: {rs['turbines']}, Turtles: {rs['turtle_vents']}")
        print(f"  Steep: {rs['has_steep']}, High Roof: {rs['has_high_roof']}")
        print(f"  Structures: {list(rs['structures'].keys())}")
        
        print(f"\nTrade Bids:")
        for trade, items in scope["trade_bids"].items():
            for b in items:
                print(f"  [{trade}] {b['description']}: ${b['total']:,.2f}")
    else:
        print(f"Error: {scope['error']}")
