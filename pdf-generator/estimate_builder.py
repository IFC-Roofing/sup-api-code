"""
estimate_builder.py — The AI brain. Takes all parsed data, outputs estimate.json.

Logic:
1. Copy INS line items into IFC estimate (same qty, same items)
2. Add missing items per @ifc game plan + standard checklist
3. Look up unit prices from pricelist
4. Calculate all math (remove, replace, tax, o&p, total)
5. Write F9 notes for all added/adjusted items

Input: dict from data_pipeline.run()
Output: estimate.json (full structured estimate)
"""

import os
import sys
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv
from data_pipeline import lookup_price

ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

F9_MATRIX_PATH = Path(__file__).parent / "f9_matrix.json"


def _load_f9_matrix() -> list[dict]:
    try:
        with open(F9_MATRIX_PATH) as f:
            return json.load(f)
    except Exception:
        return []


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TX_TAX_RATE = 0.0825
OP_RATE = 0.20
PRICE_LIST_CODE = "TXDF8X_APR26"


# ─── Math Helpers ──────────────────────────────────────────────────────────────

def calc_line_item(qty: float, remove_rate: float, replace_rate: float, is_material: bool, is_bid: bool = False) -> dict:
    """Calculate all fields for a single line item.
    
    Bid items: retail is wholesale marked up 30%, O&P is charged on top as usual.
    This is by design — wholesale→retail markup is IFC's margin, O&P is the
    standard GC overhead charged to insurance on all items.
    """
    remove = round(qty * remove_rate, 2) if not is_bid else 0.0
    replace = round(qty * replace_rate, 2)
    tax = round(replace * TX_TAX_RATE, 2) if (is_material and not is_bid) else 0.0
    op = round((remove + replace) * OP_RATE, 2)
    total = round(remove + replace + tax + op, 2)
    return {"remove": remove, "replace": replace, "tax": tax, "op": op, "total": total}


def round_up_to_third_sq(sq: float) -> float:
    """Round UP to nearest 1/3 SQ (0.33... increment)."""
    thirds = math.ceil(sq * 3) / 3
    return round(thirds, 2)


def apply_waste(base_sq: float, waste_pct: float) -> float:
    """Apply waste percentage and round up to nearest 1/3 SQ."""
    with_waste = base_sq * (1 + waste_pct / 100)
    return round_up_to_third_sq(with_waste)


# ─── Section Ordering ──────────────────────────────────────────────────────────

# ─── Gutter Section Builder (deterministic, no AI) ────────────────────────────

def _build_gutter_section(gutter_measurements: dict, ins_data: dict, pricelist: dict) -> dict | None:
    """
    Build the Gutters section deterministically from bid measurements + pricelist.
    Compares bid LF vs INS LF and uses whichever is higher.
    Returns a fully-calculated section dict, or None if no gutter data.
    """
    if not gutter_measurements:
        return None

    bid_gutter_lf = gutter_measurements.get("gutter_lf", 0)
    bid_downspout_lf = gutter_measurements.get("downspout_lf", 0)
    splashguards = gutter_measurements.get("splashguards", 0)

    if bid_gutter_lf == 0 and bid_downspout_lf == 0:
        return None

    # Sum INS gutter/downspout LF across all sections
    ins_gutter_lf = 0
    ins_downspout_lf = 0
    if ins_data:
        for ins_item in ins_data.get("line_items", []):
            desc_lower = (ins_item.get("description") or "").lower()
            qty = float(ins_item.get("quantity") or ins_item.get("qty") or 0)
            unit = (ins_item.get("unit") or "").upper()
            if unit != "LF":
                continue
            if any(kw in desc_lower for kw in ["gutter", "seamless"]):
                if "downspout" not in desc_lower:
                    ins_gutter_lf += qty
            if "downspout" in desc_lower or "down spout" in desc_lower:
                ins_downspout_lf += qty

    # Use whichever source gives higher LF
    final_gutter_lf = max(bid_gutter_lf, ins_gutter_lf)
    final_downspout_lf = max(bid_downspout_lf, ins_downspout_lf)
    source_gutter = "adjusted" if ins_gutter_lf > 0 else "added"
    source_downspout = "adjusted" if ins_downspout_lf > 0 else "added"

    print(f"[estimate_builder] Gutter section: bid={bid_gutter_lf}/{bid_downspout_lf} LF, INS={ins_gutter_lf}/{ins_downspout_lf} LF → using {final_gutter_lf}/{final_downspout_lf} LF")
    if splashguards:
        print(f"[estimate_builder] Gutter section: {splashguards} splashguards from bid")

    # Look up pricelist rates
    def _get_rate(desc_key: str) -> dict:
        for key, val in pricelist.items():
            if desc_key.lower() in key:
                return val
        return {"remove": 0.0, "replace": 0.0, "is_material": True}

    line_items = []
    section_totals = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}

    def _add_item(desc, qty, unit, pricing, source):
        math_result = calc_line_item(qty, pricing.get("remove", 0), pricing.get("replace", 0), pricing.get("is_material", True))
        item = {
            "num": 0,
            "description": desc,
            "qty": float(qty),
            "unit": unit,
            "remove_rate": pricing.get("remove", 0),
            "replace_rate": pricing.get("replace", 0),
            **math_result,
            "is_material": True,
            "is_bid": False,
            "source": source,
            "ins_item_num": None,
            "ins_total": None,
            "f9": "",
            "photo_anchor": "",
            "sub_name": "",
            "prebuilt": True,  # protect from QA agent description changes
        }
        line_items.append(item)
        for k in section_totals:
            section_totals[k] = round(section_totals[k] + math_result[k], 2)

    if final_gutter_lf > 0:
        _add_item('R&R Gutter / downspout - aluminum - up to 5"', final_gutter_lf, "LF",
                  _get_rate('gutter / downspout - aluminum - up to 5'), source_gutter)

    if final_downspout_lf > 0:
        pricing = _get_rate("downspout - aluminum")
        if pricing.get("replace", 0) == 0:
            pricing = _get_rate('gutter / downspout - aluminum - up to 5')
        _add_item("R&R Downspout - aluminum", final_downspout_lf, "LF", pricing, source_downspout)

    if splashguards > 0:
        _add_item("R&R Gutter splash guard", splashguards, "EA",
                  _get_rate("gutter splash guard"), "added")

    if not line_items:
        return None

    return {
        "name": "Gutters",
        "coverage": "Dwelling",
        "line_items": line_items,
        "totals": section_totals,
    }


# ─── Section Ordering ──────────────────────────────────────────────────────────

# Sections matching these keywords get pinned in this exact order.
# Anything not matched is sorted by section total (descending) between
# the last matched "normal" section and the "tail" sections (debris, general, o&p).
SECTION_ORDER_HEAD = [
    "dwelling roof", "roof covering", "roof1", "roofing",
    "detached garage roof", "garage roof",
    "gutters",
]

SECTION_ORDER_TAIL = [
    "debris removal", "general", "labor minimums applied", "o&p",
]


def section_sort_key(section: dict) -> tuple:
    """
    Returns a sort tuple (group, sub_key) where:
      group 0 = head sections (fixed order)
      group 1 = middle sections (sorted by total descending)
      group 2 = tail sections (fixed order)
    """
    name_lower = section["name"].lower()

    # Check head (roof, gutters — always first)
    for i, keyword in enumerate(SECTION_ORDER_HEAD):
        if keyword in name_lower:
            return (0, i)

    # Check tail (debris, general, o&p — always last)
    for i, keyword in enumerate(SECTION_ORDER_TAIL):
        if keyword in name_lower:
            return (2, i)

    # Everything else: sort by total descending (negate for descending)
    total = section.get("totals", {}).get("total", 0) or 0
    return (1, -total)


# ─── F9 Generators ─────────────────────────────────────────────────────────────

def f9_left_out(description: str, qty: float, unit: str, total: float, ev_evidence: str = "", tech_justification: str = "") -> str:
    lines = [
        f"The Insurance report left out the {description}.",
        f"We are requesting {qty} {unit}.",
        f"1. Xactimate total cost is ${total:,.2f}.",
    ]
    if ev_evidence:
        lines.append(f"   a. {ev_evidence}")
    if tech_justification:
        lines.append(f"   b. {tech_justification}")
    lines.append(f"   {'b' if ev_evidence and not tech_justification else 'c' if ev_evidence and tech_justification else 'a'}. Please see attached Photo Report showing damage to the {description.lower()}.")
    return "\n".join(lines)


def f9_bid_item(description: str, amount: float, sub_name: str, damage_type: str = "damage",
                area: str = "", ins_line_items: list = None) -> str:
    area_str = area or description.lower()
    if ins_line_items:
        # INS has partial coverage — reference their line items
        ins_refs = ", ".join(str(i) for i in ins_line_items)
        lines = [
            f"Our line item covers Insurance line item(s) {ins_refs}.",
            f"Hail damage was identified during inspection on the {area_str}.",
            f"1. Please see attached Photo Report for documentation of hail impacts.",
            f"2. Our sub bid cost is ${amount:,.2f}. Please see attached {sub_name} bid.",
        ]
    else:
        # INS has nothing for this trade — left out entirely
        lines = [
            f"The Insurance report left out the {description}.",
            f"Hail damage was identified during inspection on the {area_str}.",
            f"1. Please see attached Photo Report for documentation of hail impacts.",
            f"2. Our sub bid cost is ${amount:,.2f}. Please see attached {sub_name} bid.",
        ]
    return "\n".join(lines)


def f9_op_boilerplate(trades: list[str]) -> str:
    trades_str = ", ".join(trades) if trades else "multiple trades"
    return f"""For decades we have vetted, managed, trained and warrantied subcontractors for roofing, gutters, painting, fencing, siding etc. due to storm restoration in the DFW area.

We charge a minimum 20% overhead and profit above the subcontractors cost as we act as the single point of contact for all subcontractors' trade complexities, plus cover all their liability and warranty for our clients.

Project Requires General Contracting
This project involves coordination of multiple trades including {trades_str}. Per industry standards and Xactimate guidelines, O&P is warranted whenever three or more trades are involved and coordinated by a general contractor.

As the general contractor, IFC Contracting Solutions is responsible for all trade scheduling, quality control, warranty claims, and homeowner communication across all scopes of work. This management function justifies the standard 20% O&P charge."""


# ─── Standard Checklist Items ──────────────────────────────────────────────────

STANDARD_CHECKLIST = [
    {"description": "Drip edge", "unit": "LF", "ev_field": "eaves_rakes_lf", "section": "Dwelling Roof"},
    {"description": "Starter strip shingles", "unit": "LF", "ev_field": "eaves_lf", "section": "Dwelling Roof"},
    {"description": "Hip / Ridge cap shingles", "unit": "LF", "ev_field": "ridges_hips_lf", "section": "Dwelling Roof"},
    {"description": "Valley metal", "unit": "LF", "ev_field": "valleys_lf", "section": "Dwelling Roof"},
    {"description": "Step flashing", "unit": "LF", "ev_field": "step_flashing_lf", "section": "Dwelling Roof"},
    {"description": "Counter flashing / apron", "unit": "LF", "ev_field": "flashing_lf", "section": "Dwelling Roof"},
]


# ─── AI Builder ────────────────────────────────────────────────────────────────

def build_estimate(pipeline_data: dict) -> dict:
    """
    Core function. Takes pipeline_data, calls AI, returns estimate dict.
    """
    import anthropic

    project = pipeline_data["project"]
    notes = pipeline_data["notes"]
    ins_data = pipeline_data["ins_data"]
    ev_data = pipeline_data["ev_data"]
    pricelist = pipeline_data["pricelist"]
    lastname = pipeline_data["lastname"]

    # Build project meta
    today = date.today().strftime("%-m/%d/%Y")
    claims = pipeline_data.get("claims", {})
    address = pipeline_data.get("address", {})
    insured_name = project.get("name", "") or _extract_insured_name(project, ins_data)
    # Format as "Last, First" for the estimate
    name_parts = insured_name.split()
    if len(name_parts) >= 2:
        formatted_name = f"{name_parts[-1]}, {' '.join(name_parts[:-1])}"
    else:
        formatted_name = insured_name
    firstname = pipeline_data.get("firstname", "") or name_parts[0] if name_parts else "UNKNOWN"
    estimate_name = f"{lastname}_{firstname}".upper()

    meta = {
        "estimate_name": estimate_name,
        "claim_number": claims.get("claim_number") or _extract_field(ins_data, "claim_number", "") or _extract_field(ins_data, "member_number", ""),
        "policy_number": claims.get("policy_number") or _extract_field(ins_data, "policy_number", ""),
        "policy_holder": formatted_name,
        "address": address.get("street") or address.get("full") or _extract_field(ins_data, "property_address", "") or _extract_field(ins_data, "address", ""),
        "date_of_loss": _format_date_us(claims.get("date_of_loss") or _extract_field(ins_data, "date_of_loss", "")),
        "date_inspected": _format_date_us(_extract_field(ins_data, "date_inspected", "")),
        "date_received": _format_date_us(_extract_field(ins_data, "date_received", "")),
        "date_entered": today,
        "price_list": PRICE_LIST_CODE,
        "type_of_loss": _extract_field(ins_data, "type_of_loss", "") or _extract_field(ins_data, "cause_of_loss", "") or "Wind/Hail",
        "city": address.get("city") or _extract_city(ins_data, project),
        "state": address.get("state", "TX"),
        "zip": address.get("zip") or _extract_zip(ins_data, project),
        "insurance_company": claims.get("insurance_company", "") or _extract_field(ins_data, "carrier", "") or _extract_field(ins_data, "insurance_company", ""),
        "adjuster": _extract_field(ins_data, "claim_rep", "") or _extract_field(ins_data, "adjuster", "") or _extract_field(ins_data, "estimator", ""),
        "client_email": (project.get("contact") or {}).get("email", "") or _extract_field(ins_data, "insured_email", "") or _extract_field(ins_data, "email", ""),
        "deductible": _extract_field(ins_data, "deductible", "") or str((ins_data.get("totals") or {}).get("deductible", "") or ""),
    }

    # Prepare context for AI
    bids = pipeline_data.get("bids", [])

    # Pre-filter: remove INS items for trades covered by sub bids
    ins_data_filtered = _filter_ins_for_bids(ins_data, bids)

    ins_items_text = _format_ins_items(ins_data_filtered)
    ev_text = _format_ev_data(ev_data)
    ifc_notes      = "\n---\n".join(notes["ifc"]) or "(no @ifc notes found)"
    supp_notes     = "\n---\n".join(notes["supplement"]) or "(no @supplement notes)"
    momentum_notes = "\n---\n".join(notes.get("momentum", [])) or ""
    untagged_notes = "\n---\n".join(notes.get("untagged", [])) or ""
    convo_history_text = _format_conversation_history(pipeline_data.get("conversation_history") or {})
    pricelist_sample = _format_pricelist_sample(pricelist)
    bids_text = _format_bids(bids)
    f9_matrix = _load_f9_matrix()
    # F9 templates are no longer included in the Opus prompt — F9 generation
    # is handled by a separate post-processor (_generate_f9s) for better quality.
    f9_text = ""  # kept as variable for backward compat in condensation logic
    corrections = pipeline_data.get("prior_corrections", [])
    corrections_text = _format_corrections(corrections)
    itel_text = pipeline_data.get('itel_data') or '(no ITEL report found)'
    gutter_measurements = pipeline_data.get('gutter_measurements')
    gutter_text = _format_gutter_measurements(gutter_measurements)

    # Pre-build gutter section deterministically (no AI)
    from data_pipeline import load_pricelist
    print(f"[estimate_builder] Gutter measurements received: {gutter_measurements}")
    prebuilt_gutter = _build_gutter_section(gutter_measurements, ins_data, load_pricelist())
    print(f"[estimate_builder] Gutter pre-builder result: {'YES (' + str(len(prebuilt_gutter['line_items'])) + ' items)' if prebuilt_gutter else 'None'}")
    if prebuilt_gutter:
        for item in prebuilt_gutter['line_items']:
            print(f"[estimate_builder] Gutter item: {item['description']} = {item['qty']} {item['unit']}")
    if prebuilt_gutter:
        gutter_prompt_text = "GUTTERS ARE PRE-BUILT. Do NOT include any gutter, downspout, or splashguard line items in your response. The Gutters section will be injected automatically after your response. Skip all gutter-related items entirely."
    else:
        gutter_prompt_text = gutter_text

    prompt = f"""You are Sup, an AI supplement builder for IFC Roofing. Your job is to build a complete insurance supplement estimate.

## PROJECT
Insured: {insured_name}
Address: {meta['address']}
Estimate Name: {estimate_name}
Date of Loss: {meta['date_of_loss']}
Price List: {PRICE_LIST_CODE}

## INTERNAL STRATEGY — for deciding WHAT to include only. NEVER reference in F9 notes.
{ifc_notes}

{supp_notes}
{f"## PROJECT HISTORY (momentum notes — context only)" + chr(10) + momentum_notes if momentum_notes else ""}
{f"## ADDITIONAL CONVO NOTES (untagged — may contain gameplan or strategy)" + chr(10) + untagged_notes if untagged_notes else ""}
{convo_history_text}

## EAGLEVIEW MEASUREMENTS
{ev_text}

## ITEL REPORT (Shingle Specification)
{itel_text}

RULE: If the ITEL report specifies a shingle type, year, or product (e.g. '40-year architectural'), ALL shingle line items MUST use that specification. The ITEL report is the authoritative source for what was on the roof pre-loss. Override the INS shingle type if it differs from ITEL.

## INSURANCE ESTIMATE ITEMS (copy these, then add what's missing)
{ins_items_text}

## PRICELIST (sample — use for pricing)
{pricelist_sample}

## SUB BIDS (already marked up 30% wholesale → retail)
{bids_text}

## GUTTER MEASUREMENTS
{gutter_prompt_text}

{corrections_text}

## YOUR TASK
Build a complete IFC supplement estimate as a JSON object following this EXACT structure:

{{
  "sections": [
    {{
      "name": "Section Name",
      "coverage": "Dwelling",  // "Dwelling" | "Other Structures" | "Contents"
      "line_items": [
        {{
          "description": "Item description",
          "qty": 0.0,
          "unit": "SQ",
          "remove_rate": 0.0,   // per unit from pricelist
          "replace_rate": 0.0,  // per unit from pricelist
          "is_material": true,  // false for labor-only items
          "is_bid": false,      // true for subcontractor bid items
          "source": "ins",      // "ins" | "added" | "adjusted"
          "ins_item_num": null, // insurance item number if source=adjusted
          "ins_total": null,    // insurance total if source=adjusted
          "f9": "",             // ALWAYS leave empty (""). F9 notes are generated by a separate post-processor.
          "photo_anchor": "",   // slug for future photo injection
          "sub_name": ""        // subcontractor name if is_bid=true
        }}
      ]
    }}
  ]
}}

## LESSONS FROM REAL JOBS (apply these — they come from auditing actual supplements)
- If INS quantity > IFC quantity on ANY line item → use INS quantity or higher. Never leave ours lower — INS may notice and reduce theirs.
- Cross-reference INS line items against what we're building. If INS has something we don't, include it (source="ins").
- Steep charges: Apply ONLY to the steep portion of the roof (facets ≥ 10/12 pitch). Check the PITCH DISTRIBUTION in EagleView. Add waste % to steep SQ only. ~50/50 fight on waste but worth including.
- High roof charges on waste SQ: same logic as steep — always include on the applicable portion.
- Xactimate vs bid: use whichever pays more. Gutters = Xactimate almost always wins. Fence/pergola with power wash + stain = bid only (no good Xactimate codes).
- GUTTERS — ALWAYS USE XACTIMATE, NEVER BID: Gutters are ALWAYS billed as individual Xactimate line items (R&R Gutter/downspout, etc.), NOT as a single bid item. The gutter sub bid is used ONLY as a measurement source (LF of gutter, LF of downspouts, miters). Use those measurements with Xactimate pricelist rates. Xactimate almost always pays significantly more than the marked-up bid.
- GUTTER SOURCE PRIORITY — MAXIMIZE SCOPE: Compare total gutter/downspout LF from TWO sources: (A) our bid measurements, and (B) INS per-elevation gutter lines summed across all elevations. Use WHICHEVER SOURCE gives higher total LF. If INS per-elevation totals are higher → keep the INS elevation gutter/downspout lines in their respective elevation sections (source="ins") and do NOT create a separate Gutters section. If our bid measurements are higher → create a Gutters section using bid measurements and do NOT duplicate gutter lines in elevations. NEVER include both — that double-counts. The goal is to maximize the gutter scope without requesting the same LF twice.
- D&R costs absorbed by Xactimate margin — don't separately line-item D&R when using Xactimate pricing for a trade.
- Chimney bid = cap/chase ONLY. Always add separate Xactimate chimney flashing line item alongside chimney bids. Chimney items go in the ROOF section (Dwelling Roof), NOT a separate "Chimney" section.
- One bid can cover multiple scopes (doors + fence + siding). Each scope = separate bid line item in its matching section.
- F9 NEGLIGIBLE THRESHOLD (1%): If the quantity difference between INS and IFC is less than 1% of the INS quantity, do NOT write an F9 for that item. The difference is too small to justify arguing. Just use the INS quantity as-is (source="ins"). Example: INS says 94.33 SQ and EV says 94.50 SQ → difference is 0.18% → no F9, use INS qty.
- Pricelist price differences are NOT worth an F9. Only write F9s for quantity/scope disputes.
- SHINGLE FELT RULE: For the main shingle line item, match whatever description INS used ("with felt" or "without felt"). Do NOT fight over this — it's a minor difference not worth an F9. If INS didn't specify either way, default to "w/ felt". The goal is to avoid generating an F9 over a felt/no-felt distinction.
- ⚠️ F9 DOLLAR COMPARISONS BANNED: NEVER write "Per Xactimate pricing costs $X while Insurance report is $Y" or "The difference is $X." in F9 notes. This draws the adjuster's attention to pricing differences which we do NOT want. F9s must argue QUANTITY and SCOPE only. Say "We are requesting X [unit] based on EagleView measurements" — do NOT mention dollar amounts, cost differences, or compare our total vs INS total. The ONLY dollar amount allowed in an F9 is the total cost of a bid item ("Our sub bid cost is $X").
- When INS pays more than our bid on a trade, keep their higher amount — don't adjust down.
- Domino effect: roof tear-off justifies flashing, starter, IWS. Include all flashing types affected by tear-off.
- STEP FLASHING: Always use domino effect argument, NOT hail damage. During tear-off, existing step flashing is disturbed and cannot be reused. New step flashing must be installed for a proper weather-tight seal. This is the default F9 — never claim hail damage on step flashing.
- APRON/COUNTER FLASHING: Same as step flashing — always use domino effect argument, NOT hail damage. During tear-off, existing apron flashing is disturbed and cannot be reused. New apron flashing must be installed to maintain a proper weather-tight seal. Never claim "hail damage to the flashing" for apron/counter flashing.
- HIP/RIDGE CAP: Match the product type to what's on the roof. If the main shingles are LAMINATED → use "Hip / Ridge cap - Standard profile - composition shingles" (the manufactured ridge cap). If 3-tab shingles → use "Hip / Ridge cap - cut from 3 tab - composition shingles". Check the INS estimate and EV to determine which shingle type is dominant. Do NOT default to 3-tab cut when the roof has laminated shingles.
- LINE ITEM DESCRIPTIONS: Always use the EXACT description from our pricelist. Never invent compound names or add parenthetical clarifications. The description must match exactly what appears in the Xactimate pricelist.
  Common mistakes to avoid:
  - Counter/apron flashing → use "R&R Counterflashing - Apron flashing" (NOT "R&R Drip edge/gutter apron")
  - Drip edge → use "Drip edge" or "R&R Drip edge" (NOT "R&R Drip edge/gutter apron")
  - Pipe jack → use "Flashing - pipe jack" or "R&R Flashing - pipe jack" (check pricelist)
  - Hip/ridge → use "Hip / Ridge cap - Standard profile - composition shingles" for laminated roofs, "Hip / Ridge cap - cut from 3 tab" for 3-tab roofs
- DUMPSTER / DEBRIS REMOVAL: If INS includes a dumpster/debris/haul-off line item, KEEP IT as-is (source="ins"). Do not change the description or argue for a different item. Debris removal labor is already included in our tear-off pricing, so this is free money. Include it in the supplement so INS doesn't remove it. Do NOT write an F9 for dumpster/debris — just copy INS's line item exactly.
- BID vs INS COMPARISON: Before replacing INS line items with a bid, compare the TOTAL value. If INS is already paying roughly the same amount (within ~10-15%) as our marked-up bid for that trade, just use the INS line items as-is (source="ins"). The bid was a reference — no need to fight for a bid replacement when INS already covers it. Only use the bid as a replacement when it's significantly higher than what INS is paying, or when INS has zero coverage for that trade.
- WINDOW SCREENS: If INS has individual window screen items across different elevations (Left Elevation, Front Elevation, etc.), keep them in their respective sections as-is (source="ins"). Only use a window bid when the bid is significantly higher than the total INS is paying for all screens combined. Don't collapse individual elevation items into a single bid item.
- HVAC/AC ITEMS: If INS has an HVAC item (e.g. "Comb and straighten a/c condenser fins") AND we have an HVAC bid that's higher, use the bid. Place the bid in the same section/elevation as the INS HVAC item. Reference the INS line number in the F9.

## ⚠️ CRITICAL: READ ALL CARRIER NOTES ON INS LINE ITEMS
Lines marked with "⚠️ CARRIER NOTE:" contain critical information about what is BUNDLED into that line item.
- If a carrier note says a line item "includes material and labor for starter course" or "includes cap shingles" → that component is NOT missing. It is bundled into that line item.
- DO NOT write an F9 claiming the component was "left out" or "forgotten" when the carrier explicitly bundled it.
- Instead, argue for SEPARATION: the bundled component is a different material installed at a different rate, so it should be a separate line item for accurate pricing. Bundling it leads to inaccurate material and labor estimates.
- Example: If INS line 5 says "includes material and labor for starter course" → do NOT write "The insurance report left out the Starter." Instead write: "Starter is a different material installed at a different rate than field shingles. Bundling starter into the shingle line item leads to inaccurate material estimates. We are requesting starter as a separate line item per Xactimate standards."
- ALWAYS read every carrier note before deciding whether an item is missing vs bundled.

## RULES
1. COPY all INS items first (source="ins"). Keep same qty. Update pricing to current pricelist.
   CRITICAL: source="ins" items MUST have f9="" (empty string). NEVER write an F9 for an item where we are using the insurance quantity as-is. F9s are only for items we are ADDING (source="added") or ADJUSTING the quantity (source="adjusted"). Writing an F9 on an insurance item using their own numbers makes no sense — there is nothing to argue.
   EXCEPTION: If a SUB BID exists for a trade, DO NOT copy any INS items from that trade's section.
   Drop ALL of them. The bid item REPLACES the entire INS scope for that trade.
   Example: @fence bid → drop all fence INS items. Use only the bid.
   Exception within exception: items clearly outside the bid scope (supervision, cleanup, painting) may stay.
   NOTE: Gutters are NOT bid items — they are always Xactimate line items. See GUTTER MEASUREMENTS section and gutter rule in lessons.
   REMOVE VALUES: Only items that describe REMOVAL or R&R (Remove & Replace) should have a non-zero "remove" value. Pure installation/material items (shingles, felt, starter, steep charges, paint, etc.) have remove=0. Tear-off is the ONLY shingle-related item with a remove component. Do NOT add remove costs to shingle install, felt, or other material-only line items.
2. ADD missing items per @ifc notes + standard checklist (drip edge, starter strip, hip/ridge cap, valley metal, step flashing, counter flashing, HIGH ROOF charges).
   HIGH ROOF CHARGES: Check the EagleView for number of stories. If 2+ stories, ALWAYS add:
   - "Remove Additional charge for high roof (2 stories or greater)" — qty = measured SQ (tear-off)
   - "Additional charge for high roof (2 stories or greater)" — qty = suggested SQ (with waste)
   These are commonly missed by insurance. Write F9 referencing EagleView showing stories/high roof.
   EVEN IF EagleView doesn't explicitly say stories: if the @ifc notes, convo context, or property details suggest a 2+ story home, add high roof charges. When in doubt and the roof is large (40+ SQ), include them — it's better to include and have insurance remove them than to miss the money.
3. ADJUST qty for items where INS is wrong (source="adjusted") — use EV measurements.
   IMPORTANT: If INS qty > EV qty for any item, use INS qty (don't reduce below what INS already gives us).
   STEEP/HIGH ROOF CHARGES: These apply ONLY to the steep portion of the roof (see PITCH DISTRIBUTION in EagleView). The add/install lines use steep measured SQ × (1 + waste%) = steep suggested SQ. The remove lines use steep measured SQ only. If INS used total roof SQ for steep, adjust DOWN to steep-only SQ. Write an F9 explaining the steep area calculation referencing EagleView pitch distribution.
4. Use EagleView measurements for all roof quantities.
5. Quantity rules by item type:
   - TEAR-OFF qty = MEASURED SQ (no waste) — removing what's there.
   - SHINGLES = SUGGESTED SQ from EV (includes waste).
   - ROOFING FELT = MEASURED SQ (same as tear-off) — felt covers the deck, waste is minimal.
   - STARTER STRIP = DRIP EDGE length (eaves + rakes LF) — starter runs along the full drip edge.
   - STEEP CHARGE (add/install, NOT remove): Apply ONLY to the steep portion of the roof, NOT the entire roof. Check the PITCH DISTRIBUTION section in EagleView data — it shows exactly how many SQ are at each pitch. Only facets at 10/12 or steeper qualify for steep charges. Calculate: steep measured SQ × (1 + waste%) = steep suggested SQ. Remove steep = steep measured SQ. Add steep = steep suggested SQ. NEVER use total roof SQ for steep charges unless 100% of the roof is steep.
   - STEEP CHARGES ON WASTE SQ: The add/install steep charge qty should equal the steep SUGGESTED SQ (steep measured × (1 + waste%)). This means steep charges DO apply to the waste portion. Remove steep = steep measured SQ only. Add steep = steep suggested SQ (with waste). Example: if steep measured = 50 SQ and waste = 13%, add steep = 50 × 1.13 = 56.5 SQ.
   - HIGH ROOF CHARGE (add/install, NOT remove): same as steep — apply only to applicable portion. Remove = measured SQ. Add = suggested SQ (with waste).
   - ALL OTHER material items (hip/ridge, valley, etc.) = use EV measurements as given.
   - ROUND all EV linear measurements DOWN to nearest whole number for insurance presentation (e.g., 11.5 LF → 11 LF, 3.17 LF → 3 LF, 297.25 LF → 297 LF). Do NOT round SQ values — keep those at EV precision.
6. O&P = 20% per line (10% overhead + 10% profit). When 3+ trades are involved, add an explicit "O&P" section at the end with a $0 placeholder line item (qty=1, replace_rate=0, remove_rate=0, replace=0, remove=0, tax=0, op=0, total=0) — this is a SIGNAL LINE ONLY, not an actual charge. ALL O&P is already baked into each line item's O&P column. The O&P line item must have ALL monetary values set to ZERO. The description must be EXACTLY "Overhead and Profit" — nothing else. Justification belongs in the F9 note only.
7. Tax = 8.25% on materials only. Labor items: tax = 0.
8. Bid items: remove=0, tax=0, replace=bid retail_total, qty=1 EA, is_bid=true.
   CRITICAL: The sub_name field must be the REAL contractor/company name (e.g. "Grizzly Fence & Patio", "Seamless Gutter Co"). NEVER use the property address, a generic trade label, or placeholder text as the sub_name. If the real sub name is unknown, use just the trade name (e.g. "Gutters", "HVAC", "Chimney") — do NOT combine it with the address or use "ADDRESS" as a prefix.
   - Description format: "{{sub_name}} (Bid Item)" e.g. "Hi-Tech Copper & Metals (Bid Item)", "Grizzly Fence & Patio (Bid Item)". Use the REAL company name from the bid PDF, not the trade label or property address.
   - Place each bid item in the section matching its trade (@fence → Fence, @gutter → Gutters, @metal → specialty section, etc.)
   - sub_name field = the subcontractor company name
   - F9 notes for bid items are generated by a separate post-processor. Leave f9="" on bid items too.
   - CHIMNEY BIDS: The chimney bid covers the chase cover and cap ONLY — it does NOT include chimney flashing.
     You MUST also add a separate Xactimate line item "R&R Chimney flashing - average (32" x 36")" at pricelist pricing
     in the same section, with source="added" and an F9 note explaining flashing is required alongside the chimney work.
9. DO NOT write F9 notes. Leave f9="" on ALL items. F9 notes are generated by a separate post-processor after your response.
   Focus entirely on correct structure, quantities, sources, and pricing.
10. Sort sections: Roof first, then Gutters, then remaining trades by total (highest first), then Debris/General/O&P last.
    Within Dwelling Roof: shingle tear-off (Remove) and shingle replace MUST be the first two items, followed by drip edge, felt, valley, starter, then remaining items. Pair every Remove item immediately before its matching replace/install item.
11. Group "Labor Minimums Applied" items in their own section.
12. If 3+ trades: add O&P line item at end with ALL amounts = $0 (replace_rate=0, remove_rate=0, replace=0, remove=0, tax=0, op=0, total=0) and boilerplate F9. This is a signal line — never put actual dollar amounts on it.
13. retail_total in SUB BIDS is the price to request from insurance — use it directly as the replace value.
14. Include photo_anchor slug for every item (lowercase, hyphen-separated).
15. Multiple bids with the same @trade tag = different scopes, include ALL of them as separate bid items.
16. For @other bids: use the SCOPE/DESCRIPTION field as the item description. Place them in the section that matches their scope (e.g. "Copper Bay Window" → Elevations, "Dormer" → Dwelling Roof, "Pillars" → appropriate specialty section).
17. Use EagleView STRUCTURE #1 measurements for Dwelling Roof. Use STRUCTURE #2 measurements for Detached Garage Roof. Never mix them.
18. Do NOT add a pricelist update line item — we handle pricelist updates on the backend.

## SECTION ORDER
Dwelling Roof (includes chimney cap/flashing, skylight, pipe jacks — anything on the main roof) → Detached Garage Roof → Elevations → Gutters → Windows → Fence/Siding → Specialty → Interior → Debris Removal → General → Labor Minimums Applied → O&P
NOTE: Chimney items (cap, flashing) belong in the Dwelling Roof section, NOT a separate "Chimney" section.

Respond with ONLY the JSON object. No markdown, no explanation."""

    # Pre-condense if prompt is too large (> ~50K chars ≈ 12K tokens)
    prompt_len = len(prompt)
    print(f"[estimate_builder] Prompt size: {prompt_len:,} chars (~{prompt_len // 4:,} tokens)")
    if prompt_len > 50000:
        print("[estimate_builder] Large prompt detected — condensing INS items to save tokens...")
        condensed_ins = _format_ins_items_condensed(ins_data)
        prompt = prompt.replace(ins_items_text, condensed_ins)
        prompt_len = len(prompt)
        print(f"[estimate_builder] Condensed prompt: {prompt_len:,} chars (~{prompt_len // 4:,} tokens)")

    print("[estimate_builder] Calling AI to build estimate...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=300.0)

    def _call_ai(p):
        import time
        last_err = None
        for attempt in range(1, 4):  # 3 attempts
            try:
                resp = client.messages.create(
                    model="claude-opus-4-7",
                    max_tokens=16000,
                    messages=[{"role": "user", "content": p}]
                )
                text = resp.content[0].text.strip()
                if text.startswith("```"):
                    text = re.sub(r"^```[a-z]*\n?", "", text)
                    text = re.sub(r"\n?```$", "", text)
                return text, resp.stop_reason
            except (anthropic.InternalServerError, anthropic.APIStatusError) as e:
                last_err = e
                # 529 = overloaded, 500 = internal error — both are retryable
                status = getattr(e, 'status_code', 0)
                wait = 15 * attempt
                print(f"[estimate_builder] Anthropic {status} on attempt {attempt} — retrying in {wait}s...")
                time.sleep(wait)
            except anthropic.APITimeoutError as e:
                last_err = e
                wait = 10 * attempt
                print(f"[estimate_builder] Anthropic timeout on attempt {attempt} — retrying in {wait}s...")
                time.sleep(wait)
        raise last_err

    raw, stop_reason = _call_ai(prompt)

    # If truncated, trim the INS items context and retry
    if stop_reason == "max_tokens":
        print("[estimate_builder] Response truncated — retrying with condensed INS context...")
        condensed_ins = _format_ins_items_condensed(ins_data)
        prompt2 = prompt.replace(ins_items_text, condensed_ins)
        raw, stop_reason = _call_ai(prompt2)
        if stop_reason == "max_tokens":
            print("[estimate_builder] WARNING: Still truncated after condensing — attempting JSON repair...")

    # Attempt to close unclosed JSON if still truncated
    if stop_reason == "max_tokens" and not raw.rstrip().endswith("}"):
        raw = _repair_truncated_json(raw)

    print("[estimate_builder] Parsing AI response...")
    ai_result = json.loads(raw)

    # Post-process: calculate all math, enrich items
    sections = []
    item_counter = 1
    for section in ai_result.get("sections", []):
        processed_items = []
        section_totals = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}

        for item in section.get("line_items", []):
            qty = float(item.get("qty", 0) or 0)
            remove_rate = float(item.get("remove_rate", 0) or 0)
            replace_rate = float(item.get("replace_rate", 0) or 0)
            is_material = bool(item.get("is_material", True))
            is_bid = bool(item.get("is_bid", False))

            desc = item.get("description", "")

            # Safety net: if non-bid item has 0 rates, look up from pricelist
            if not is_bid and replace_rate == 0 and remove_rate == 0 and qty > 0:
                pricing = lookup_price(desc)
                if pricing and pricing.get("replace", 0) > 0:
                    remove_rate = pricing["remove"]
                    replace_rate = pricing["replace"]
                    is_material = pricing.get("is_material", is_material)
                    print(f"[estimate_builder] Pricelist fallback: '{desc}' rates were 0 → remove={remove_rate}, replace={replace_rate}")

            # Safety net: "Remove" items should have remove rate, not replace rate
            # Opus sometimes puts all cost in replace_rate even for remove-only items
            if not is_bid and desc.lower().startswith("remove ") and remove_rate == 0 and replace_rate > 0:
                pricing = lookup_price(desc)
                if pricing and pricing.get("remove", 0) > 0 and pricing.get("replace", 0) == 0:
                    print(f"[estimate_builder] Rate column fix: '{desc}' — swapping replace_rate {replace_rate} to remove_rate {pricing['remove']}")
                    remove_rate = pricing["remove"]
                    replace_rate = 0.0
                    is_material = pricing.get("is_material", is_material)

            math = calc_line_item(qty, remove_rate, replace_rate, is_material, is_bid)

            processed_item = {
                "num": item_counter,
                "description": item.get("description", ""),
                "qty": qty,
                "unit": item.get("unit", "EA"),
                "remove_rate": remove_rate,
                "replace_rate": replace_rate,
                "remove": math["remove"],
                "replace": math["replace"],
                "tax": math["tax"],
                "op": math["op"],
                "total": math["total"],
                "is_material": is_material,
                "is_bid": is_bid,
                "source": item.get("source", "added"),
                "ins_item_num": item.get("ins_item_num"),
                "ins_total": item.get("ins_total"),
                "f9": item.get("f9", ""),
                "photo_anchor": item.get("photo_anchor", ""),
                "sub_name": item.get("sub_name", ""),
            }

            for k in ["remove", "replace", "tax", "op", "total"]:
                section_totals[k] = round(section_totals[k] + processed_item[k], 2)

            processed_items.append(processed_item)
            item_counter += 1

        sections.append({
            "name": section.get("name", ""),
            "coverage": section.get("coverage", "Dwelling"),
            "line_items": processed_items,
            "totals": section_totals,
        })

    # Inject pre-built gutter section (replaces any AI-generated gutter section)
    if prebuilt_gutter:
        sections = [s for s in sections if "gutter" not in s["name"].lower()]
        sections.append(prebuilt_gutter)
        print(f"[estimate_builder] Injected pre-built Gutters section ({len(prebuilt_gutter['line_items'])} items)")

    # Sort sections
    sections.sort(key=section_sort_key)

    # Grand totals
    grand = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}
    coverage_totals = {"Dwelling": 0.0, "Other Structures": 0.0, "Contents": 0.0}
    for s in sections:
        for k in grand:
            grand[k] = round(grand[k] + s["totals"][k], 2)
        cov = s.get("coverage", "Dwelling")
        coverage_totals[cov] = round(coverage_totals.get(cov, 0.0) + s["totals"]["total"], 2)

    # Re-number items sequentially
    num = 1
    for s in sections:
        for item in s["line_items"]:
            item["num"] = num
            num += 1

    # Post-process: zero out O&P signal line (AI sometimes puts amounts on it)
    _fix_op_signal_line(sections)

    # Post-process: fix known description mistakes
    _fix_descriptions(sections)

    # Post-process: upgrade install-only items to R&R on tear-off jobs
    _enforce_rr_on_tearoff(sections)

    # Post-process: remove duplicate bid items
    _dedup_bid_items(sections)

    # Post-process: strip gutter/downspout items Opus duplicated outside the Gutters section
    _strip_duplicate_gutter_items(sections)

    # Post-process: inject any missing bids the AI dropped
    _inject_missing_bids(sections, bids)

    # Post-process: inject chimney flashing on tear-off jobs with chimneys
    _inject_chimney_flashing(sections, pipeline_data.get("ins_data", {}))

    # Post-process: inject paint companion items for pipe jacks and vents
    _inject_paint_companions(sections)

    # Post-process: fix steep charge quantities (add steep must include waste)
    _fix_steep_waste(sections, pipeline_data.get("ev_data", {}))

    # Post-process: enforce INS qty floor (our qty must never be below INS qty)
    _enforce_ins_qty_floor(sections, pipeline_data.get("ins_data", {}))

    # Post-process: pair remove + replace items adjacent within each section
    _pair_remove_replace(sections)

    # Post-process: enforce O&P section is truly last
    _enforce_op_last(sections)

    # Post-process: re-number items sequentially after all adds/removes
    num = 1
    for s in sections:
        for item in s["line_items"]:
            item["num"] = num
            num += 1

    # Post-process: map INS line numbers to our items (for F9 references)
    # MUST run before _strip_agreement_f9s so ins_qty is populated
    _map_ins_line_nums(sections, pipeline_data.get("ins_data", {}))

    # Post-process: strip F9s from items where our qty matches INS qty (agreement)
    _strip_agreement_f9s(sections)

    # Post-process: generate F9 notes (template selection + Sonnet fill)
    _generate_f9s(sections, f9_matrix, pipeline_data)

    # Post-process: force-overwrite bid F9s with deterministic version
    # Opus sometimes writes F9s for bid items despite being told not to,
    # and uses the total (with O&P) instead of the replace value.
    _force_bid_f9s(sections, pipeline_data.get("bids", []))

    # Post-process: strip dollar comparisons from F9 notes (safety net)
    _strip_f9_dollar_comparisons(sections)

    # Post-process: flag F9s with missing INS line references (e.g. "covers Insurance line item We are...")
    _fix_f9_missing_ins_refs(sections)

    # Post-process: strip F9s from source="ins" items (safety net)
    for s in sections:
        for item in s["line_items"]:
            if item.get("source") == "ins" and item.get("f9"):
                print(f"[estimate_builder] Stripped F9 from INS item: {item.get('description', '')}")
                item["f9"] = ""

    # Final re-number after F9 generation (in case F9 post-processors added items)
    num = 1
    for s in sections:
        for item in s["line_items"]:
            item["num"] = num
            num += 1

    # Recalculate section + grand totals after all post-processing
    grand = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}
    coverage_totals = {"Dwelling": 0.0, "Other Structures": 0.0, "Contents": 0.0}
    for s in sections:
        s_totals = {"remove": 0.0, "replace": 0.0, "tax": 0.0, "op": 0.0, "total": 0.0}
        for item in s["line_items"]:
            for k in s_totals:
                s_totals[k] = round(s_totals[k] + item.get(k, 0.0), 2)
        s["totals"] = s_totals
        for k in grand:
            grand[k] = round(grand[k] + s_totals[k], 2)
        cov = s.get("coverage", "Dwelling")
        coverage_totals[cov] = round(coverage_totals.get(cov, 0.0) + s_totals["total"], 2)

    estimate = {
        **meta,
        "sections": sections,
        "line_item_total": grand["total"],
        "tax_total": grand["tax"],
        "op_total": grand["op"],
        "remove_total": grand["remove"],
        "replace_total": grand["replace"],
        "rcv_total": grand["total"],
        "coverage_split": coverage_totals,
    }

    return estimate


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _pair_remove_replace(sections: list):
    """
    Post-process: within each section, move 'Remove ...' items to be immediately
    before their matching replace/install counterpart.
    
    Matching logic: strip 'Remove ' prefix from description, then fuzzy-match
    against other items in the same section.
    """
    import re as _re

    def _norm(desc: str) -> str:
        d = desc.lower().strip()
        d = _re.sub(r'^remove\s+', '', d)
        d = _re.sub(r'^r&r\s+', '', d)
        d = _re.sub(r'^detach\s*&\s*reset\s+', '', d)
        d = _re.sub(r'[^a-z0-9 ]', '', d)
        return _re.sub(r'\s+', ' ', d).strip()

    moved = 0
    for section in sections:
        items = section.get("line_items", [])
        if len(items) < 2:
            continue

        # Find all remove items and their intended partners
        i = 0
        while i < len(items):
            desc = items[i].get("description", "")
            if not desc.lower().startswith("remove "):
                i += 1
                continue

            remove_norm = _norm(desc)
            # Look for matching replace item (not already adjacent)
            best_j = None
            best_score = 0
            for j in range(len(items)):
                if j == i:
                    continue
                other_desc = items[j].get("description", "")
                if other_desc.lower().startswith("remove "):
                    continue  # skip other remove items
                other_norm = _norm(other_desc)
                if not other_norm or not remove_norm:
                    continue
                # Check word overlap
                r_words = set(remove_norm.split())
                o_words = set(other_norm.split())
                overlap = len(r_words & o_words)
                min_len = min(len(r_words), len(o_words))
                if min_len > 0:
                    score = overlap / min_len
                    if score > best_score and score >= 0.6:
                        best_score = score
                        best_j = j

            if best_j is not None and best_j != i + 1:
                # Move remove item to just before its partner
                remove_item = items.pop(i)
                # Adjust index after pop
                insert_at = best_j if best_j > i else best_j
                items.insert(insert_at, remove_item)
                print(f"[estimate_builder] Paired: '{desc}' moved before '{items[insert_at + 1]['description']}'")
                moved += 1
                # Don't increment i — re-check this position
                continue

            i += 1

    if moved:
        print(f"[estimate_builder] Remove/replace pairing: moved {moved} item(s)")


def _enforce_op_last(sections: list):
    """
    Post-process: ensure the O&P section is the very last section.
    Moves it to the end if it's not already there.
    """
    op_idx = None
    for i, section in enumerate(sections):
        name_lower = section["name"].lower()
        if "o&p" in name_lower or name_lower in ("overhead", "overhead & profit", "overhead and profit"):
            op_idx = i
            break
    if op_idx is not None and op_idx != len(sections) - 1:
        op_section = sections.pop(op_idx)
        sections.append(op_section)
        print(f"[estimate_builder] Moved O&P section to last position")


def _strip_agreement_f9s(sections: list):
    """
    Post-process: for items tagged source='adjusted' where our qty matches INS qty
    (within 1%), downgrade to source='ins' and strip the F9. These are agreement items.
    """
    for section in sections:
        for item in section.get("line_items", []):
            if item.get("source") != "adjusted":
                continue
            ins_qty = item.get("ins_qty", 0)
            our_qty = item.get("qty", 0)
            if ins_qty and our_qty:
                diff_pct = abs(our_qty - ins_qty) / ins_qty if ins_qty else 0
                if diff_pct < 0.01:  # < 1% difference = agreement
                    if item.get("f9"):
                        print(f"[estimate_builder] Stripped F9 from agreement item (diff {diff_pct:.2%}): {item.get('description', '')}")
                        item["f9"] = ""
                    item["source"] = "ins"


def _fix_op_signal_line(sections: list):
    """
    Post-process: force the O&P signal line to $0 across the board.
    AI sometimes puts actual dollar amounts on it despite being told not to.
    O&P is already baked into each line item's O&P column — the O&P section
    line is just a signal to insurance that O&P is warranted.
    """
    for section in sections:
        if section["name"].lower() not in ("o&p", "overhead", "overhead & profit", "overhead and profit"):
            continue
        for item in section["line_items"]:
            desc = item.get("description", "").lower().strip()
            if desc == "overhead and profit":
                had_amounts = item.get("replace_rate", 0) != 0 or item.get("replace", 0) != 0 or item.get("total", 0) != 0
                item["qty"] = 1.0
                item["remove_rate"] = 0.0
                item["replace_rate"] = 0.0
                item["remove"] = 0.0
                item["replace"] = 0.0
                item["tax"] = 0.0
                item["op"] = 0.0
                item["total"] = 0.0
                item["is_material"] = False
                item["is_bid"] = False
                if had_amounts:
                    print(f"[estimate_builder] ⚠️  Zeroed O&P signal line — AI had put amounts on it")


def _fix_descriptions(sections: list):
    """
    Post-process: correct known AI description mistakes to match pricelist names.
    This runs AFTER the AI generates the estimate, as a safety net.
    """
    CORRECTIONS = {
        # key: lowercased substring to match → corrected description
        "drip edge/gutter apron": "R&R Counterflashing - Apron flashing",
        "gutter apron (counter": "R&R Counterflashing - Apron flashing",
        "counter/apron flashing": "R&R Counterflashing - Apron flashing",
        "counterflashing - apron": None,  # Already correct, skip
    }
    import re as _re
    for section in sections:
        for item in section.get("line_items", []):
            desc_lower = item.get("description", "").lower()
            for pattern, correction in CORRECTIONS.items():
                if pattern in desc_lower and correction is not None:
                    old = item["description"]
                    item["description"] = correction
                    print(f"[estimate_builder] Fixed description: '{old}' → '{correction}'")
                    break

            # Detect ADDRESS_ prefix
            desc_lower = item.get("description", "").lower()
            if desc_lower.startswith("address_"):
                old = item["description"]
                # Strip ADDRESS_ prefix and clean up
                cleaned = item["description"][8:].strip()  # remove "ADDRESS_"
                item["description"] = f"{cleaned} (Bid Item)" if "(Bid Item)" not in cleaned else cleaned
                print(f"[estimate_builder] Fixed placeholder: '{old}' → '{item['description']}'")

            # Strip ALL "(Bid Item)" variants from description — the HTML template adds it via is_bid flag
            import re as _re_bid
            old_desc = item.get("description", "")
            cleaned_desc = _re_bid.sub(r'\s*\(\s*[Bb]id\s+[Ii]tem\s*\)', '', old_desc).strip()
            if cleaned_desc != old_desc:
                item["description"] = cleaned_desc
                print(f"[estimate_builder] Stripped '(Bid Item)' from description: '{old_desc}' → '{cleaned_desc}'")

            # Detect street address in bid item descriptions
            if item.get("is_bid") and _re.search(r'\d+\s+[A-Z][a-z]+\s+(Trail|St|Ave|Blvd|Dr|Ln|Rd|Way|Ct|Pl|Circle|Pkwy)', item.get("description", "")):
                print(f"[estimate_builder] ⚠️ WARNING: Bid item description contains street address: '{item['description']}' — needs manual review")


def _enforce_rr_on_tearoff(sections: list):
    """
    Post-process: on tear-off jobs, upgrade install-only items to R&R where the
    pricelist has an R&R variant with a remove rate.

    On a full tear-off, items like drip edge, hip/ridge, pipe jack, valley metal,
    exhaust caps, turbine vents, chimney chase, and counterflashing are REMOVED
    during tear-off and REPLACED with new material. The R&R variant captures both
    the remove labor and the replace cost. Using install-only leaves remove = $0,
    which is money left on the table.

    Only runs on sections containing a tear-off line item (shingle or laminated).
    Skips bid items, already-R&R items, and items that have no R&R pricelist match.
    """
    # Items that should be R&R on tear-off jobs.
    # Key: keyword to match in description (lowercased)
    # Value: pricelist lookup key for the R&R variant (or None to auto-search)
    RR_CANDIDATES = {
        "drip edge":       "R&R Drip edge",
        "hip / ridge":     None,  # multiple variants — match by full description
        "hip/ridge":       None,
        "valley metal":    "R&R Valley metal",
        "pipe jack":       None,  # lead vs standard variants
        "flashing - pipe": None,
        "exhaust cap":     None,  # multiple sizes
        "turbine":         "R&R Roof vent - turbine type",
        "turtle type":     None,  # plastic vs metal
        "roof vent":       None,
        "chimney chase":   "R&R Fireplace - chimney chase cover - sheet metal",
        "chimney flashing": None,
        "counterflashing":  "R&R Counterflashing - Apron flashing",
        "apron flashing":   "R&R Counterflashing - Apron flashing",
        "continuous ridge vent": "R&R Continuous ridge vent - shingle-over style",
        "gutter / downspout": "R&R Gutter / downspout - aluminum - up to 5\"",
        "rain diverter":    "R&R Flashing - rain diverter",
        "gable cornice":    None,
        "window screen":    None,
    }

    for section in sections:
        items = section.get("line_items", [])

        # Check if this section has a tear-off item
        has_tearoff = any(
            "tear off" in item.get("description", "").lower()
            for item in items
        )
        if not has_tearoff:
            continue

        for item in items:
            if item.get("is_bid"):
                continue

            desc = item.get("description", "")
            desc_lower = desc.lower()

            # Skip if already R&R (has remove rate > 0)
            if item.get("remove_rate", 0) > 0:
                continue

            # Skip tear-off itself, shingles, felt, steep, high roof, starter, paint, permit, dumpster
            # Note: "comp. shingle" and "comp shingle" catch field shingles but NOT "hip/ridge cap - composition shingles"
            skip_keywords = ["tear off", "comp. shingle", "comp shingle", "3 tab", "lam.",
                             "laminated comp", "felt", "underlayment", "steep", "high roof",
                             "additional charge", "starter", "paint", "seal", "prime", "permit",
                             "dumpster", "dump trailer", "labor minimum", "overhead", "satellite",
                             "o&p", "ice and water"]
            if any(sk in desc_lower for sk in skip_keywords):
                continue

            # Find matching R&R candidate
            matched_lookup = None
            for keyword, lookup_key in RR_CANDIDATES.items():
                if keyword in desc_lower:
                    matched_lookup = lookup_key
                    break
            else:
                continue  # Not a candidate for R&R upgrade

            # Look up R&R variant in pricelist
            rr_pricing = None
            if matched_lookup:
                rr_pricing = lookup_price(matched_lookup)

            if not rr_pricing:
                # Auto-search: prepend "R&R" to current description
                rr_pricing = lookup_price(f"R&R {desc}")

            if not rr_pricing:
                # Try without any prefix, just searching for R&R variant with same keywords
                # Extract core description words (skip "R&R", "Remove and replace", etc.)
                core = desc_lower.replace("r&r ", "").replace("remove and replace ", "").strip()
                rr_pricing = lookup_price(f"R&R {core.title()}")

            if not rr_pricing or rr_pricing.get("remove", 0) <= 0:
                continue  # No R&R variant found or it has no remove rate

            # Upgrade to R&R
            old_desc = desc
            old_remove_rate = item.get("remove_rate", 0)
            old_replace_rate = item.get("replace_rate", 0)

            item["description"] = rr_pricing["description"]
            item["remove_rate"] = rr_pricing["remove"]
            item["replace_rate"] = rr_pricing["replace"]
            item["unit"] = rr_pricing.get("unit", item.get("unit", ""))
            item["is_material"] = rr_pricing.get("is_material", item.get("is_material", False))

            # Recalculate math with new rates
            new_math = calc_line_item(
                item["qty"],
                item["remove_rate"],
                item["replace_rate"],
                item["is_material"],
                item.get("is_bid", False),
            )
            item.update(new_math)

            added_value = round(item["qty"] * rr_pricing["remove"], 2)
            print(f"[estimate_builder] R&R upgrade: '{old_desc}' → '{rr_pricing['description']}' "
                  f"(added remove ${rr_pricing['remove']:.2f}/unit × {item['qty']} = +${added_value:,.2f})")


def _fix_steep_waste(sections: list, ev_data: dict):
    """
    Post-process: ALWAYS assert correct waste on steep and high roof ADD charges.
    Remove steep = steep measured SQ (paired remove item qty).
    Add steep   = steep measured × (1 + waste%).
    
    Does NOT rely on "are they the same?" — always recalculates and corrects
    if our add qty differs from what it should be by more than 0.01 SQ.
    Also ensures shingles use suggested SQ (not measured).
    """
    rs = ev_data.get("roofing_summary", {})
    waste_pct = rs.get("suggested_waste_pct")
    if not waste_pct:
        measured = rs.get("measured_sq")
        suggested = rs.get("suggested_sq")
        if measured and suggested and float(measured) > 0:
            waste_pct = round((float(suggested) / float(measured) - 1) * 100, 1)
    # Try per-structure data if top-level is empty
    if not waste_pct:
        for struct in rs.get("structures", []):
            if struct.get("suggested_waste_pct"):
                waste_pct = struct["suggested_waste_pct"]
                break
            sm = struct.get("measured_squares")
            ss = struct.get("suggested_squares")
            if sm and ss and float(sm) > 0:
                waste_pct = round((float(ss) / float(sm) - 1) * 100, 1)
                break
    # Last resort: infer from shingle tear-off vs install qty in the estimate itself
    if not waste_pct:
        for section in sections:
            tearoff_qty = None
            shingle_qty = None
            for item in section.get("line_items", []):
                dl = item.get("description", "").lower()
                if "tear off" in dl and "shingle" in dl:
                    tearoff_qty = item.get("qty", 0)
                elif ("comp. shingle" in dl or "composition shingle" in dl) and "remove" not in dl and "tear" not in dl and "ridge" not in dl and "hip" not in dl:
                    shingle_qty = item.get("qty", 0)
            if tearoff_qty and shingle_qty and shingle_qty > tearoff_qty:
                inferred = round((shingle_qty / tearoff_qty - 1) * 100, 1)
                if inferred >= 3:  # < 3% means Opus just used INS qty, not real waste
                    waste_pct = inferred
                    print(f"[estimate_builder] Inferred waste % from tear-off vs shingles: {waste_pct}%")
                    break
                else:
                    print(f"[estimate_builder] Tear-off vs shingles diff only {inferred}% — too low to be real waste, skipping")
    # Absolute last resort: use industry standard 13%
    if not waste_pct:
        waste_pct = 13
        print(f"[estimate_builder] No waste % found anywhere — using industry default {waste_pct}%")

    waste_mult = 1 + float(waste_pct) / 100
    suggested_sq = rs.get("suggested_sq")
    measured_sq = rs.get("measured_sq")

    for section in sections:
        items = section.get("line_items", [])

        # Find tear-off / shingle remove qty (needed for high roof assertion)
        tearoff_qty_local = None
        for _item in items:
            _dl = _item.get("description", "").lower()
            if ("tear off" in _dl and "shingle" in _dl) or ("remove" in _dl and ("comp. shingle" in _dl or "composition shingle" in _dl or "laminated" in _dl) and "ridge" not in _dl and "hip" not in _dl):
                tearoff_qty_local = _item.get("qty", 0)
                break

        # ── Steep charges ─────────────────────────────────────
        for item in items:
            desc_lower = item.get("description", "").lower()

            if "additional charge for steep" in desc_lower and "remove" not in desc_lower:
                # Find the matching remove steep at the same slope range
                remove_item = next(
                    (r for r in items
                     if "remove additional charge for steep" in r.get("description", "").lower()
                     and _same_slope_range(desc_lower, r.get("description", "").lower())),
                    None
                )
                if remove_item and remove_item.get("qty", 0) > 0:
                    remove_qty = remove_item["qty"]
                    expected_add = round(remove_qty * waste_mult, 2)
                    actual_add = item.get("qty", 0)
                    if abs(actual_add - expected_add) > 0.01:
                        item["qty"] = expected_add
                        new_math = calc_line_item(expected_add, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", False), item.get("is_bid", False))
                        item.update(new_math)
                        print(f"[estimate_builder] Fixed steep waste: '{item['description']}' qty {actual_add} → {expected_add} SQ (waste {waste_pct}%)")

            # ── High roof charges ─────────────────────────────
            # High roof REMOVE = tear-off qty (full measured roof, not INS)
            if "remove additional charge for high" in desc_lower:
                if tearoff_qty_local and abs(item.get("qty", 0) - tearoff_qty_local) > 0.01:
                    old_qty = item["qty"]
                    item["qty"] = tearoff_qty_local
                    new_math = calc_line_item(tearoff_qty_local, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", False), item.get("is_bid", False))
                    item.update(new_math)
                    print(f"[estimate_builder] Fixed high roof remove: '{item['description']}' qty {old_qty} → {tearoff_qty_local} SQ (must match tear-off)")

            # High roof ADD = tear-off × waste
            if "additional charge for high" in desc_lower and "remove" not in desc_lower:
                remove_item = next(
                    (r for r in items
                     if "remove additional charge for high" in r.get("description", "").lower()),
                    None
                )
                if remove_item and remove_item.get("qty", 0) > 0:
                    remove_qty = remove_item["qty"]
                    expected_add = round(remove_qty * waste_mult, 2)
                    actual_add = item.get("qty", 0)
                    if abs(actual_add - expected_add) > 0.01:
                        item["qty"] = expected_add
                        new_math = calc_line_item(expected_add, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", False), item.get("is_bid", False))
                        item.update(new_math)
                        print(f"[estimate_builder] Fixed high roof waste: '{item['description']}' qty {actual_add} → {expected_add} SQ (waste {waste_pct}%)")

        # ── Shingles: assert suggested SQ ────────────────────
        # Find tear-off qty as the measured SQ baseline
        tearoff_qty = None
        for item in items:
            dl = item.get("description", "").lower()
            if "tear off" in dl and "shingle" in dl:
                tearoff_qty = item.get("qty", 0)
                break

        # Felt = measured SQ (same as tear-off, no waste)
        if tearoff_qty:
            for item in items:
                dl = item.get("description", "").lower()
                if "roofing felt" in dl or "synthetic underlayment" in dl:
                    actual = item.get("qty", 0)
                    if abs(actual - tearoff_qty) > 0.1:
                        item["qty"] = tearoff_qty
                        new_math = calc_line_item(tearoff_qty, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", True), item.get("is_bid", False))
                        item.update(new_math)
                        print(f"[estimate_builder] Fixed felt qty: '{item['description']}' qty {actual} → {tearoff_qty} SQ (felt = tear-off, no waste)")

        for item in items:
            desc_lower = item.get("description", "").lower()
            if ("comp. shingle" in desc_lower or "composition shingle" in desc_lower) and "remove" not in desc_lower and "tear" not in desc_lower and "ridge" not in desc_lower and "hip" not in desc_lower:
                actual = item.get("qty", 0)
                # Path 1: Use EV suggested SQ if available
                if suggested_sq and measured_sq:
                    expected = float(suggested_sq)
                    if abs(actual - float(measured_sq)) < 0.5 and abs(actual - expected) > 0.1:
                        item["qty"] = expected
                        new_math = calc_line_item(expected, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", True), item.get("is_bid", False))
                        item.update(new_math)
                        print(f"[estimate_builder] Fixed shingle waste: '{item['description']}' qty {actual} → {expected} SQ (suggested SQ from EV)")
                # Path 2: No EV data — compute from tear-off × waste
                elif tearoff_qty and tearoff_qty > 0:
                    expected = round(tearoff_qty * waste_mult, 2)
                    if actual < expected - 0.1:
                        item["qty"] = expected
                        new_math = calc_line_item(expected, item.get("remove_rate", 0), item.get("replace_rate", 0), item.get("is_material", True), item.get("is_bid", False))
                        item.update(new_math)
                        print(f"[estimate_builder] Fixed shingle waste: '{item['description']}' qty {actual} → {expected} SQ (tear-off {tearoff_qty} × {waste_pct}% waste)")


def _same_slope_range(desc1: str, desc2: str) -> bool:
    """Check if two steep charge descriptions refer to the same slope range."""
    import re as _re
    pattern = r'(\d+/12)'
    slopes1 = set(_re.findall(pattern, desc1))
    slopes2 = set(_re.findall(pattern, desc2))
    return bool(slopes1 & slopes2) or (not slopes1 and not slopes2)


def _enforce_ins_qty_floor(sections: list, ins_data: dict):
    """
    Post-process: if INS qty > our qty on any matched line item, bump ours up to INS qty.
    Rule: never leave our quantity lower than what INS already approved.
    INS may notice and reduce their number to match ours.

    Matching strategy: fuzzy description match between our items and INS items.
    Only applies to source='ins' or source='adjusted' items (not 'added' — those are new items
    INS doesn't have, so there's no INS qty to compare against).
    Bid items are also excluded — bid totals, not qtys, are what matter there.
    """
    ins_items = ins_data.get("items", []) or ins_data.get("line_items", [])
    if not ins_items:
        return

    # Build a fast lookup: normalized description → ins qty (float)
    import re as _re
    def _norm(s: str) -> str:
        s = s.lower().strip()
        s = _re.sub(r'\s+', ' ', s)
        s = s.replace('r&r ', '').replace('remove and replace ', '')
        s = _re.sub(r'[^a-z0-9 ]', '', s)
        return s

    # Build two maps: section-scoped (preferred) and global (fallback)
    # Key: (norm_section, norm_desc) → (qty, unit, original_desc)
    # For global: norm_desc → list of (qty, unit, section)
    ins_qty_map_sectioned: dict = {}
    ins_qty_map_global: dict = {}  # norm_desc → list of (qty, unit, section)
    for ins_item in ins_items:
        desc = ins_item.get("description", "")
        raw_qty = ins_item.get("qty") or ins_item.get("quantity")
        unit = ins_item.get("unit", "")
        section = ins_item.get("section", "") or ins_item.get("room", "")
        if not desc or raw_qty is None:
            continue
        try:
            qty = float(str(raw_qty).replace(",", ""))
        except (ValueError, TypeError):
            continue
        norm_desc = _norm(desc)
        norm_sec = _norm(section) if section else ""
        if norm_desc:
            ins_qty_map_sectioned[(norm_sec, norm_desc)] = (qty, unit, desc)
            if norm_desc not in ins_qty_map_global:
                ins_qty_map_global[norm_desc] = []
            ins_qty_map_global[norm_desc].append((qty, unit, norm_sec))

    if not ins_qty_map_sectioned and not ins_qty_map_global:
        return

    fixed = 0
    for section in sections:
        our_section_norm = _norm(section.get("name", ""))

        for item in section.get("line_items", []):
            # Skip bid items and newly added items (no INS counterpart)
            if item.get("is_bid") or item.get("source") == "added":
                continue

            our_desc_norm = _norm(item.get("description", ""))
            if not our_desc_norm:
                continue

            ins_match = None

            # Strategy 1: section-scoped exact match (most reliable — prevents cross-section contamination)
            ins_match = ins_qty_map_sectioned.get((our_section_norm, our_desc_norm))

            # Strategy 2: global match — only if there's exactly ONE INS item with this description
            # (if description appears in multiple sections like two roof structures, skip it —
            # we can't determine which section maps to which without context)
            if not ins_match:
                our_words = set(our_desc_norm.split())
                for desc_norm, entries in ins_qty_map_global.items():
                    desc_words = set(desc_norm.split())
                    overlap = len(our_words & desc_words)
                    min_len = min(len(our_words), len(desc_words))
                    if min_len > 0 and overlap / min_len >= 0.7:
                        if len(entries) == 1:
                            # Exactly one INS item — safe to match
                            qty, unit, _ = entries[0]
                            ins_match = (qty, unit, desc_norm)
                        # Multiple entries = ambiguous (two structures, two elevations, etc.) — skip
                        break

            if not ins_match:
                continue

            ins_qty, ins_unit, ins_orig_desc = ins_match
            our_qty = item.get("qty", 0)

            # Only compare when units are compatible (both SQ, both LF, both EA, etc.)
            our_unit = item.get("unit", "").upper()
            ins_unit_upper = ins_unit.upper() if ins_unit else ""
            if ins_unit_upper and our_unit and ins_unit_upper != our_unit:
                continue  # unit mismatch — don't compare

            if ins_qty > our_qty + 0.01:  # +0.01 tolerance for float noise
                old_qty = our_qty
                item["qty"] = ins_qty
                # Recalculate math
                new_math = calc_line_item(
                    ins_qty,
                    item.get("remove_rate", 0),
                    item.get("replace_rate", 0),
                    item.get("is_material", True),
                    item.get("is_bid", False),
                )
                item.update(new_math)
                # If this was source='ins' (using their number), keep source='ins' — no F9 needed
                # If source='adjusted' — they were already arguing for more — now we match INS minimum
                print(f"[estimate_builder] INS floor: '{item['description']}' qty {old_qty} → {ins_qty} {ins_unit_upper} (INS had higher)")
                fixed += 1

    if fixed:
        print(f"[estimate_builder] INS qty floor applied to {fixed} item(s)")


def _map_ins_line_nums(sections: list, ins_data: dict):
    """
    Post-process: map each estimate item to matching INS line numbers using
    fuzzy description matching. Populates 'ins_item_nums' (list of INS line numbers)
    and 'ins_qty' (the INS quantity) on each item.
    """
    import re as _re
    ins_items = ins_data.get("items", []) or ins_data.get("line_items", [])
    if not ins_items:
        return

    def _norm(s: str) -> str:
        s = s.lower().strip()
        s = _re.sub(r'\s+', ' ', s)
        s = s.replace('r&r ', '').replace('remove and replace ', '').replace('detach & reset ', '')
        s = _re.sub(r'[^a-z0-9 ]', '', s)
        return s

    # Build INS lookup: list of (norm_desc, line_number, qty, unit, section, original_desc, carrier_note)
    ins_lookup = []
    for ins_item in ins_items:
        desc = ins_item.get("description", "")
        line_num = ins_item.get("line_number")
        raw_qty = ins_item.get("qty") or ins_item.get("quantity")
        unit = ins_item.get("unit", "")
        section = ins_item.get("section", "")
        carrier_note = ins_item.get("notes", "") or ""
        try:
            qty = float(str(raw_qty).replace(",", "")) if raw_qty else 0
        except (ValueError, TypeError):
            qty = 0
        ins_lookup.append((_norm(desc), line_num, qty, unit, section, desc, carrier_note))

    mapped_count = 0
    for section in sections:
        for item in section.get("line_items", []):
            if item.get("source") == "ins":
                continue  # INS items don't need INS line mapping for F9s

            our_norm = _norm(item.get("description", ""))
            our_words = set(our_norm.split())
            if not our_words:
                continue

            matching_ins = []
            for ins_norm, ins_num, ins_qty, ins_unit, ins_sec, ins_desc, ins_note in ins_lookup:
                ins_words = set(ins_norm.split())
                if not ins_words:
                    continue
                overlap = len(our_words & ins_words)
                min_len = min(len(our_words), len(ins_words))
                if min_len > 0 and overlap / min_len >= 0.6:
                    matching_ins.append({
                        "ins_num": ins_num,
                        "ins_qty": ins_qty,
                        "ins_unit": ins_unit,
                        "ins_desc": ins_desc,
                        "ins_note": ins_note,
                    })

            if matching_ins:
                item["ins_item_nums"] = [m["ins_num"] for m in matching_ins if m["ins_num"]]
                item["ins_qty"] = matching_ins[0]["ins_qty"]
                # Carry carrier notes so F9 generator can use them
                carrier_notes = [m["ins_note"] for m in matching_ins if m.get("ins_note")]
                if carrier_notes:
                    item["ins_carrier_notes"] = carrier_notes
                mapped_count += 1
            else:
                item["ins_item_nums"] = []
                item["ins_qty"] = 0

            # Also check: does ANY INS carrier note mention this item? (bundled-into-another-item case)
            # E.g., shingle line says "includes starter" → starter's F9 should argue separation
            if not item.get("ins_carrier_notes"):
                desc_keywords = [w for w in our_norm.split() if len(w) > 3]
                bundled_notes = []
                for ins_norm, ins_num, ins_qty, ins_unit, ins_sec, ins_desc, ins_note in ins_lookup:
                    if ins_note and desc_keywords:
                        note_lower = ins_note.lower()
                        if any(kw in note_lower for kw in desc_keywords):
                            bundled_notes.append(f"INS#{ins_num} ({ins_desc}): {ins_note}")
                if bundled_notes:
                    item["ins_carrier_notes"] = bundled_notes

    print(f"[estimate_builder] INS line nums mapped on {mapped_count} item(s)")


def _select_f9_template(item: dict, f9_matrix: list) -> str:
    """
    Deterministically select the best F9 template for an item based on:
      - source (added→FORGOT, adjusted→QUANTITY)
      - is_bid → BID template
      - category matching (description → f9_matrix category)
    Returns the raw template text with placeholders, or empty string if no match.
    """
    source = item.get("source", "")
    is_bid = item.get("is_bid", False)
    desc_lower = item.get("description", "").lower()

    if source == "ins":
        return ""  # No F9 for INS items

    # Determine scenario keyword
    if is_bid:
        scenario_keywords = ["bid", "replacing"]
    elif source == "added":
        scenario_keywords = ["forget", "forgot", "left out"]
    elif source == "adjusted":
        scenario_keywords = ["quantity"]
    else:
        scenario_keywords = ["forget", "forgot", "left out"]

    # Determine category from description
    CATEGORY_MAP = {
        "Dry-in & Shingles": ["shingle", "comp.", "composition", "starter", "felt", "underlayment", "ice", "water", "3 tab", "flat roof", "roll roofing", "synthetic", "tar paper"],
        "Roof Complexities": ["steep", "high roof", "stories", "additional charge"],
        "Roof Components": ["drip edge", "valley", "step flash", "counter flash", "apron flash", "pipe jack", "flashing", "hip", "ridge cap", "ridge", "vent", "attic vent", "exhaust", "turbine", "satellite"],
        "Gutters": ["gutter", "downspout", "miter", "elbow", "end cap", "splash"],
        "Chimney Cap": ["chimney", "chase cover"],
        "Fence (Wood)": ["fence", "picket", "stain", "power wash"],
        "Fence (Iron)": ["iron fence", "wrought iron"],
        "Windows & Screens": ["window", "screen", "glass"],
        "Garage": ["garage door", "garage"],
        "Pergolas, Gazebos, Patios & Beams": ["pergola", "gazebo", "patio", "beam", "arbor"],
        "Metal Roof Features": ["turret", "copper", "metal pan", "balcony"],
        "Pool": ["pool", "coping"],
        "Stucco": ["stucco"],
        "Siding": ["siding", "hardie"],
        "Interior": ["interior", "drywall", "ceiling"],
        "O&P": ["o&p", "overhead", "profit"],
        "Misc": ["permit", "building permit"],
    }

    matched_cat = None
    for cat, keywords in CATEGORY_MAP.items():
        if any(kw in desc_lower for kw in keywords):
            matched_cat = cat
            break

    # Search f9_matrix for best matching template
    best_template = None
    best_score = 0

    for entry in f9_matrix:
        entry_cat = entry.get("category", "")
        entry_scenario = entry.get("scenario", "").lower()
        entry_item = entry.get("line_item", "").lower()
        f9 = entry.get("f9", "")

        if not f9:
            continue

        score = 0

        # Category match
        if matched_cat and entry_cat == matched_cat:
            score += 3
        elif matched_cat and any(kw in entry_cat.lower() for kw in matched_cat.lower().split()):
            score += 1

        # Scenario match
        if any(kw in entry_scenario for kw in scenario_keywords):
            score += 2

        # Item name overlap with description
        entry_words = set(entry_item.split()) - {"the", "a", "an", "-", "&", "of"}
        desc_words = set(desc_lower.split()) - {"the", "a", "an", "-", "&", "of", "r&r", "remove"}
        if entry_words and desc_words:
            word_overlap = len(entry_words & desc_words) / max(len(entry_words), 1)
            score += word_overlap * 2

        if score > best_score:
            best_score = score
            best_template = f9

    return best_template or ""


def _generate_f9s(sections: list, f9_matrix: list, pipeline_data: dict):
    """
    Post-process: generate F9 notes for all added/adjusted items.
    
    1. Select template deterministically (source + category → template)
    2. Batch all items needing F9s into one Sonnet call to fill templates with real values
    """
    ev_data = pipeline_data.get("ev_data", {})
    bids = pipeline_data.get("bids", [])

    # Collect items that need F9s
    items_needing_f9 = []
    for section in sections:
        for item in section.get("line_items", []):
            if item.get("source") in ("added", "adjusted") and not item.get("f9"):
                template = _select_f9_template(item, f9_matrix)
                items_needing_f9.append({
                    "item": item,
                    "template": template,
                    "section_name": section.get("name", ""),
                })

    if not items_needing_f9:
        print("[estimate_builder] No items need F9 generation")
        return

    print(f"[estimate_builder] Generating F9s for {len(items_needing_f9)} item(s)...")

    # Build the Sonnet prompt
    ev_summary = ""
    rs = ev_data.get("roofing_summary", {})
    if rs:
        ev_summary = f"Measured SQ: {rs.get('measured_sq', '?')}, Suggested SQ: {rs.get('suggested_sq', '?')}, "
        ev_summary += f"Waste: {rs.get('suggested_waste_pct', '?')}%, "
        ev_summary += f"Ridges+Hips: {rs.get('ridges_hips_lf', '?')} LF, Valleys: {rs.get('valleys_lf', '?')} LF, "
        ev_summary += f"Drip Edge: {rs.get('drip_edge_lf', '?')} LF, Step Flashing: {rs.get('step_flashing_lf', '?')} LF"

    items_block = []
    for i, entry in enumerate(items_needing_f9):
        item = entry["item"]
        ins_nums = item.get("ins_item_nums", [])
        ins_qty = item.get("ins_qty", 0)
        additional = round(item["qty"] - ins_qty, 2) if ins_qty else item["qty"]

        carrier_notes = item.get("ins_carrier_notes", [])

        block = {
            "index": i,
            "line_num": item.get("num", "?"),
            "description": item["description"],
            "qty": item["qty"],
            "unit": item.get("unit", "EA"),
            "source": item.get("source"),
            "is_bid": item.get("is_bid", False),
            "sub_name": item.get("sub_name", ""),
            "total": item.get("total", 0),
            "section": entry["section_name"],
            "ins_line_nums": ins_nums,
            "ins_qty": ins_qty,
            "additional_qty": additional,
            "template": entry["template"][:500] if entry["template"] else "(no template — write from scratch)",
        }

        # Include carrier notes if they exist — critical for bundled item arguments
        if carrier_notes:
            block["carrier_notes"] = carrier_notes

        # Add bid context if applicable
        if item.get("is_bid"):
            # sub_bid_cost = replace value (retail, no O&P) — matches the marked-up bid attachment
            block["sub_bid_cost"] = item.get("replace", item.get("replace_rate", 0))
            print(f"[estimate_builder] BID F9 DEBUG: desc={item.get('description')} sub_bid_cost={block['sub_bid_cost']} replace={item.get('replace')} total={item.get('total')} op={item.get('op')}")
            # Always remove total for bid items to prevent AI using O&P-inflated number
            block.pop("total", None)
            if bids:
                for bid in bids:
                    if item.get("sub_name") and item["sub_name"].lower() in bid.get("sub_name", "").lower():
                        block["bid_scope"] = bid.get("scope", "")
                        block["bid_line_items"] = bid.get("bid_line_items_text", "")
                        break

        items_block.append(block)

    prompt = f"""You are writing F9 notes for an insurance supplement estimate. F9 notes justify line items to the insurance adjuster.

## EAGLEVIEW DATA
{ev_summary}

## ITEMS NEEDING F9 NOTES
{json.dumps(items_block, indent=2)}

## F9 WRITING RULES

### HARD RULES (never break these)
1. NEVER include dollar amounts EXCEPT for bid items ("Our sub bid cost is $X").
2. NEVER use template placeholders ($____, XX, "Put the amount here").
3. NEVER reference internal IFC language (@ifc, @supplement, "game plan", internal strategy).
4. NEVER describe charges as physical objects ("damage to the additional charge for steep").
5. Every numbered point MUST have a complete sentence.
6. Always include the correct qty, unit, and INS line number references where applicable.

### TONE & APPROACH
- Write like a professional supplement coordinator, not a robot filling in blanks.
- The template is a STARTING POINT — use its structure and proven arguments, but adapt the language to fit the specific situation. If the template doesn't fit well (e.g., carrier bundled the item, or the context is unusual), write a better argument from scratch.
- Be factual and confident, not combative or defensive. State what we're requesting and why.
- Keep F9s concise but complete — 3-6 sentences typical.

### STANDARD PATTERNS (use as defaults, adapt when context demands it)
- source="adjusted" with ins_line_nums: Reference which INS line item(s) we cover, state the additional qty we're requesting, and justify with EagleView or scope evidence.
- source="added" with no INS match: State that INS left this out, what we're requesting, and why it's needed (EagleView, domino effect, pre-loss condition, etc.).
- is_bid=true: The default argument for bid items is HAIL DAMAGE. These trades (fence, windows, garage doors, siding, etc.) are being supplemented because of hail hits documented in the photo report. The F9 should: (1) state that hail damage was identified during inspection, (2) direct the adjuster to the attached photo report for evidence of hail impacts, (3) write "Our sub bid cost is $X" where X is EXACTLY the `sub_bid_cost` value from the item data — do NOT add O&P, do NOT multiply by 1.2, do NOT use any other number. Copy it verbatim. (4) reference the attached bid. Keep it short — the photo report does the heavy lifting. Do NOT write long explanations about what the bid covers or the scope of work. If INS has partial coverage, reference their line items.

### CONTEXT-SPECIFIC ARGUMENTS
- PAINT / PRIME items on roof fixtures (pipe jacks, vents, roof jacks): Use PRE-LOSS CONDITION argument, NOT rust/weather resistance. The F9 should state: these fixtures were painted prior to the loss (pre-loss condition). During roof replacement, the existing paint is damaged/disturbed. We are requesting prime & paint to restore the fixture to its pre-loss condition. Direct the adjuster to the photo report for pre-loss condition documentation. Do NOT mention rust prevention, weather resistance, or UV protection — insurance doesn't care about that.
- Step flashing / apron flashing: ALWAYS use domino effect (tear-off disturbs existing, cannot be reused). Never claim hail damage on flashing.
- Steep charges: Reference EagleView pitch distribution showing the steep portion.
- High roof charges: Reference EagleView showing 2+ story structure.
- CARRIER NOTES: If an item has "carrier_notes", INS bundled this component into another line item. Do NOT write "left out" — argue for SEPARATION: this is a different material installed at a different rate, bundling leads to inaccurate estimates, requesting as a separate line item per Xactimate standards. Tailor the separation argument to the specific materials involved.
- When EagleView measurements support our qty, always cite EagleView as evidence.
- When arguing for items the carrier explicitly denied or bundled, address their specific reasoning rather than using generic language.

## OUTPUT
Return a JSON object mapping index → F9 text:
{{
  "0": "The insurance report left out the Starter...",
  "1": "Our line item 14 covers insurance line items 7, 12..."
}}

Respond with ONLY the JSON object. No markdown, no explanation."""

    try:
        import anthropic
        import time

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

        raw = None
        for attempt in range(1, 4):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=12000,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = resp.content[0].text.strip()
                if resp.stop_reason == "max_tokens":
                    print(f"[estimate_builder] F9 gen: response truncated at max_tokens ({len(raw)} chars) — will attempt JSON repair")
                break
            except (anthropic.InternalServerError, anthropic.APIStatusError) as e:
                wait = 15 * attempt
                print(f"[estimate_builder] F9 gen: Anthropic {getattr(e,'status_code',0)} on attempt {attempt} — retrying in {wait}s...")
                time.sleep(wait)
            except anthropic.APITimeoutError:
                print(f"[estimate_builder] F9 gen: timeout on attempt {attempt} — retrying...")
                time.sleep(10)

        if not raw:
            print("[estimate_builder] ⚠️  F9 generation failed after 3 attempts — using fallback templates")
            _generate_f9s_fallback(items_needing_f9)
            return

        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        try:
            f9_map = json.loads(raw)
        except json.JSONDecodeError:
            # Attempt repair: find last complete key-value pair
            print(f"[estimate_builder] F9 gen: JSON parse failed, attempting repair...")
            # Find last complete "idx": "text" pair by finding last complete string value
            last_quote = raw.rfind('"')
            if last_quote > 0:
                # Walk backwards to find a complete entry
                candidate = raw[:last_quote + 1] + "\n}"
                try:
                    f9_map = json.loads(candidate)
                    print(f"[estimate_builder] F9 gen: repaired — recovered {len(f9_map)} F9s")
                except json.JSONDecodeError:
                    print(f"[estimate_builder] ⚠️  F9 gen: repair failed — using fallback templates")
                    _generate_f9s_fallback(items_needing_f9)
                    return
            else:
                print(f"[estimate_builder] ⚠️  F9 gen: no recoverable JSON — using fallback templates")
                _generate_f9s_fallback(items_needing_f9)
                return

        applied = 0
        for idx_str, f9_text in f9_map.items():
            idx = int(idx_str)
            if 0 <= idx < len(items_needing_f9):
                items_needing_f9[idx]["item"]["f9"] = f9_text
                applied += 1

        print(f"[estimate_builder] F9s generated: {applied}/{len(items_needing_f9)} items")

    except Exception as e:
        print(f"[estimate_builder] ⚠️  F9 generation failed ({type(e).__name__}: {e}) — using fallback templates")
        _generate_f9s_fallback(items_needing_f9)


def _generate_f9s_fallback(items_needing_f9: list):
    """Fallback: fill F9s from templates with basic substitution (no AI)."""
    for entry in items_needing_f9:
        item = entry["item"]
        template = entry["template"]
        if not template:
            # Generate minimal F9
            if item.get("source") == "added":
                item["f9"] = f"The insurance report left out the {item['description']}.\n\nWe are requesting {item['qty']} {item.get('unit', 'EA')}.\n\n1. Please see attached EagleView for measurements."
            elif item.get("source") == "adjusted":
                ins_nums = item.get("ins_item_nums", [])
                ins_ref = ", ".join(str(n) for n in ins_nums) if ins_nums else "N/A"
                item["f9"] = f"Our line item {item.get('num', '?')} covers insurance line item(s) {ins_ref}.\n\nWe are requesting {item['qty']} {item.get('unit', 'EA')}.\n\n1. Please see attached EagleView for measurements."
            continue

        # Basic template fill
        f9 = template
        f9 = f9.replace("XX LF", f"{item['qty']} LF").replace("XX SQ", f"{item['qty']} SQ")
        f9 = f9.replace("X LF", f"{item['qty']} LF").replace("X SQ", f"{item['qty']} SQ")
        f9 = re.sub(r'\$XX\.?\w*', f"${item.get('total', 0):,.2f}", f9)
        item["f9"] = f9
    print(f"[estimate_builder] F9 fallback: filled {len(items_needing_f9)} template(s) with basic substitution")


def _strip_f9_dollar_comparisons(sections: list):
    """Post-process: remove dollar comparison language from F9 notes."""
    import re as _re
    patterns = [
        r'The difference is \$[\d,]+\.?\d*\.?\s*',
        r'(?:Per )?Xactimate (?:pricing[,.]?\s*)?(?:this )?(?:total )?costs?\s*\$[\d,]+\.?\d*\.?\s*(?:[Ww]hile in [Ii]nsurance report (?:it )?cost(?:s|ed)?\s*(?:is\s*)?\$[\d,]+\.?\d*\.?\s*)?',
        r'[Ww]hile in [Ii]nsurance report (?:it )?cost(?:s|ed)?\s*(?:is\s*)?\$[\d,]+\.?\d*\.?\s*',
        r'Per Xactimate pricing[,.]?\s*(?:this )?costs?\s*\$[\d,]+\.?\d*\s*[Ww]hile\s*(?:in )?[Ii]nsurance report\s*(?:is|cost(?:s|ed)?\s*(?:is)?)\s*\$[\d,]+\.?\d*\.?\s*',
    ]
    fixed = 0
    for section in sections:
        for item in section.get("line_items", []):
            f9 = item.get("f9", "")
            if not f9:
                continue
            original = f9
            for pat in patterns:
                f9 = _re.sub(pat, '', f9)
            # Clean up empty numbered points
            f9 = _re.sub(r'\d+\.\s*\n', '', f9)
            f9 = _re.sub(r'\n{3,}', '\n\n', f9)
            f9 = f9.strip()
            if f9 != original:
                item["f9"] = f9
                fixed += 1
    if fixed:
        print(f"[estimate_builder] Stripped dollar comparisons from {fixed} F9 note(s)")


def _fix_f9_missing_ins_refs(sections: list):
    """Post-process: detect F9s where 'covers Insurance line item' has no number."""
    import re as _re
    fixed = 0
    for section in sections:
        for item in section.get("line_items", []):
            f9 = item.get("f9", "")
            if not f9:
                continue
            # Pattern: "covers Insurance line item(s)" followed by a period, space+uppercase, or newline — no number
            # Good: "covers Insurance line item(s) 10, 11."  Bad: "covers Insurance line item We are..."
            match = _re.search(
                r'covers Insurance line item(?:\(s\))?\s*([^0-9\n])',
                f9
            )
            if match:
                desc = item.get("description", "")
                line_num = item.get("_our_line_num", "")
                print(f"[estimate_builder] ⚠️  F9 missing INS line ref for: {desc}")
                # We can't auto-fix the number (don't know which INS item maps), 
                # but we can flag it clearly so Vanessa catches it
                # Replace the broken pattern with a placeholder that's obvious
                f9 = _re.sub(
                    r'(covers Insurance line item(?:\(s\))?)\s+(?=[A-Z])',
                    r'\1 [##]. ',
                    f9
                )
                item["f9"] = f9
                fixed += 1
    if fixed:
        print(f"[estimate_builder] Flagged {fixed} F9(s) with missing INS line references (marked [##])")


def _inject_missing_bids(sections: list, bids: list):
    """
    Safety net: verify every bid from the pipeline appears in the estimate.
    If the AI dropped a bid, inject it with correct math and F9.
    """
    if not bids:
        return

    # Collect all bid-related content in the estimate (by sub_name or trade tag)
    estimate_text = ""
    for s in sections:
        estimate_text += s.get("name", "").lower() + " "
        for item in s.get("line_items", []):
            estimate_text += (item.get("description", "") + " " + item.get("sub_name", "") + " ").lower()

    # Map trade tags to section names
    TAG_TO_SECTION = {
        "@arbor": "Arbor", "@pergola": "Pergola", "@fence": "Fence",
        "@woodfence": "Fence", "@window": "Windows", "@chimney": "Chimney",
        "@sheetrock": "Interior", "@hvac": "HVAC", "@packout": "Pack Out",
        "@flat_roof": "Flat Roof", "@metal": "Metal Work", "@siding": "Siding",
        "@paint": "Painting", "@interior": "Interior", "@skylight": "Skylight",
        "@pool": "Pool", "@garage_door": "Garage Door", "@other": "Other",
    }

    all_nums = [item.get("num", 0) for s in sections for item in s.get("line_items", [])]
    next_num = max(all_nums) + 1 if all_nums else 1

    for bid in bids:
        sub_name = bid.get("sub_name", "")
        trade = bid.get("trade", "")
        retail = bid.get("retail_total", 0)

        # Check if this bid is already in the estimate
        # Match by sub_name or trade tag appearing in any item description/sub_name
        sub_lower = sub_name.lower()
        trade_word = trade.lstrip("@").replace("_", " ").lower()

        found = False
        for s in sections:
            for item in s.get("line_items", []):
                item_text = (item.get("description", "") + " " + item.get("sub_name", "")).lower()
                if (sub_lower and sub_lower in item_text) or (trade_word and trade_word in s.get("name", "").lower()):
                    found = True
                    break
            if found:
                break

        if found:
            continue

        # Bid is missing — inject it
        section_name = TAG_TO_SECTION.get(trade, trade.lstrip("@").replace("_", " ").title())

        # Find or create the section
        target_section = None
        for s in sections:
            if section_name.lower() in s["name"].lower():
                target_section = s
                break

        if not target_section:
            target_section = {"name": section_name, "line_items": []}
            # Insert before O&P/Debris
            op_idx = next((i for i, s in enumerate(sections) if s["name"].lower() in ("o&p", "overhead", "overhead & profit", "overhead and profit")), None)
            if op_idx is not None:
                sections.insert(op_idx, target_section)
            else:
                sections.append(target_section)

        # Build the bid line item
        scope = bid.get("scope", "") or section_name
        op = round(retail * OP_RATE, 2)
        total = round(retail + op, 2)

        f9 = f9_bid_item(
            description=scope,
            amount=retail,  # replace value (retail, no O&P) — matches marked-up bid attachment
            sub_name=sub_name,
        )

        new_item = {
            "num": next_num,
            "description": f"{sub_name} (Bid Item)",
            "qty": 1.0,
            "unit": "EA",
            "remove_rate": 0.0,
            "replace_rate": retail,
            "remove": 0.0,
            "replace": retail,
            "tax": 0.0,
            "op": op,
            "total": total,
            "is_material": False,
            "is_bid": True,
            "source": "added",
            "ins_item_num": None,
            "ins_total": 0.0,
            "f9": f9,
            "photo_anchor": "",
            "sub_name": sub_name,
        }

        target_section["line_items"].append(new_item)
        next_num += 1
        print(f"[estimate_builder] ⚠️  Injected missing bid: {sub_name} ({trade}) → '{section_name}' — ${retail:,.2f} retail + ${op:,.2f} O&P = ${total:,.2f}")


def _dedup_bid_items(sections: list):
    """Remove duplicate items within the same section.
    For bids: same sub_name + same replace amount.
    For Xactimate items: same description + same qty + same rates."""
    for section in sections:
        items = section.get("line_items", [])
        seen_bids = set()
        seen_xact = set()
        deduped = []
        for item in items:
            if item.get("is_bid"):
                key = (item.get("sub_name", "").lower(), round(item.get("replace", 0), 2))
                if key in seen_bids:
                    print(f"[estimate_builder] Dedup: removed duplicate bid item '{item.get('description', '')}' (${item.get('replace', 0):,.2f}) in section '{section.get('name', '')}'")
                    continue
                seen_bids.add(key)
            else:
                key = (item.get("description", "").lower(), item.get("qty", 0), item.get("replace_rate", 0), item.get("remove_rate", 0))
                if key in seen_xact:
                    print(f"[estimate_builder] Dedup: removed duplicate Xactimate item '{item.get('description', '')}' ({item.get('qty', 0)} {item.get('unit', '')}) in section '{section.get('name', '')}'")
                    continue
                seen_xact.add(key)
            deduped.append(item)
        section["line_items"] = deduped


def _force_bid_f9s(sections: list, bids: list):
    """
    Force-overwrite F9 notes on bid items with the deterministic template.
    Opus sometimes writes bid F9s despite instructions to leave them empty,
    and uses the total (replace + O&P) instead of just the replace value.
    This ensures bid F9s always use the correct amount.
    """
    for section in sections:
        for item in section.get("line_items", []):
            if not item.get("is_bid"):
                continue

            sub_name = item.get("sub_name", "")
            replace_val = item.get("replace", item.get("replace_rate", 0))
            description = item.get("description", "")

            # Find matching bid for INS line context
            ins_line_items = None
            if bids:
                for bid in bids:
                    if sub_name and sub_name.lower() in bid.get("sub_name", "").lower():
                        ins_line_items = item.get("ins_item_nums", None)
                        break

            old_f9 = item.get("f9", "")
            item["f9"] = f9_bid_item(
                description=section.get("name", description),
                amount=replace_val,
                sub_name=sub_name,
                ins_line_items=ins_line_items,
            )
            if old_f9 and old_f9 != item["f9"]:
                print(f"[estimate_builder] BID F9 OVERWRITE: {sub_name} — old had '${old_f9.split('$')[1][:10] if '$' in old_f9 else '?'}', new uses ${replace_val:,.2f}")
            else:
                print(f"[estimate_builder] BID F9 SET: {sub_name} — ${replace_val:,.2f}")


def _strip_duplicate_gutter_items(sections: list):
    """
    Remove gutter/downspout/splash guard items that Opus duplicated outside the
    pre-built 'Gutters' section.  The deterministic gutter pre-builder is the
    single source of truth — any gutter lines the AI added elsewhere are dupes.
    """
    GUTTER_KEYWORDS = ["gutter", "downspout", "splash guard"]
    has_gutters_section = any(
        s.get("name", "").lower().strip() == "gutters" for s in sections
    )
    if not has_gutters_section:
        return  # no pre-built section → nothing to strip

    for section in sections:
        if section.get("name", "").lower().strip() == "gutters":
            continue  # keep the real section
        original = section.get("line_items", [])
        filtered = []
        for item in original:
            dl = item.get("description", "").lower()
            if any(kw in dl for kw in GUTTER_KEYWORDS) and not item.get("is_bid"):
                print(f"[estimate_builder] Stripped duplicate gutter item from '{section.get('name', '')}': '{item.get('description', '')}' {item.get('qty', 0)} {item.get('unit', '')}")
            else:
                filtered.append(item)
        if len(filtered) < len(original):
            section["line_items"] = filtered
            # Recalculate section totals
            for key in ["remove", "replace", "tax", "op", "total"]:
                section[key] = round(sum(i.get(key, 0) for i in filtered), 2)

    # Remove now-empty sections
    sections[:] = [s for s in sections if s.get("line_items")]


def _inject_paint_companions(sections: list):
    """
    Post-process: for pipe jacks and roof vents, inject 'Prime & paint' companion
    items if they don't already exist in the same section.

    Pre-loss condition: if the existing pipe jacks/vents were painted, the new ones
    must be primed and painted to restore to pre-loss condition. This is standard
    on virtually all residential roofs in DFW.

    Pairings:
      - Flashing - pipe jack (any variant) → Prime & paint roof jack (same EA qty)
      - Roof vent - turbine/turtle/exhaust → Prime & paint roof vent (same EA qty)
    
    Drip edge + paint trim and gutter + paint gutter are NOT handled here because
    Opus already adds them consistently.
    """
    COMPANIONS = [
        {
            "parent_keywords": ["pipe jack"],
            "parent_skip": ["prime", "paint"],  # Don't match existing paint items
            "companion_lookup": "Prime & paint roof jack",
            "companion_detect": "prime & paint roof jack",
        },
        {
            "parent_keywords": ["roof vent", "turbine", "turtle type", "exhaust cap"],
            "parent_skip": ["prime", "paint"],
            "companion_lookup": "Prime & paint roof vent",
            "companion_detect": "prime & paint roof vent",
        },
    ]

    for section in sections:
        items = section.get("line_items", [])
        section_text = " ".join(i.get("description", "").lower() for i in items)

        for companion_def in COMPANIONS:
            # Check if companion already exists in this section
            if companion_def["companion_detect"] in section_text:
                continue

            # Find parent item(s) — sum qty if multiple (e.g. 2 pipe jack lines)
            parent_qty = 0
            parent_unit = "EA"
            parent_desc = ""
            for item in items:
                desc_lower = item.get("description", "").lower()
                # Skip if it's a paint item itself
                if any(sk in desc_lower for sk in companion_def["parent_skip"]):
                    continue
                if any(kw in desc_lower for kw in companion_def["parent_keywords"]):
                    parent_qty += item.get("qty", 0)
                    parent_unit = item.get("unit", "EA")
                    parent_desc = item.get("description", "")

            if parent_qty <= 0:
                continue

            # Look up companion pricing
            pricing = lookup_price(companion_def["companion_lookup"])
            if not pricing:
                continue

            # Get next line number
            all_nums = [i.get("num", 0) for s in sections for i in s.get("line_items", [])]
            next_num = max(all_nums) + 1 if all_nums else 1

            math = calc_line_item(parent_qty, 0, pricing["replace"], False, False)

            new_item = {
                "num": next_num,
                "description": pricing["description"],
                "qty": parent_qty,
                "unit": parent_unit,
                "remove_rate": 0,
                "replace_rate": pricing["replace"],
                "is_material": False,
                "is_bid": False,
                "source": "added",
                "ins_item_num": None,
                "ins_total": 0.0,
                "f9": "",  # Generated by _generate_f9s
                "photo_anchor": "",
                "sub_name": "",
                **math,
            }

            # Insert right after the parent item
            insert_idx = len(items)
            for idx, item in enumerate(items):
                desc_lower = item.get("description", "").lower()
                if any(kw in desc_lower for kw in companion_def["parent_keywords"]) and \
                   not any(sk in desc_lower for sk in companion_def["parent_skip"]):
                    insert_idx = idx + 1

            items.insert(insert_idx, new_item)
            print(f"[estimate_builder] Paint companion: '{pricing['description']}' × {parent_qty} {parent_unit} "
                  f"→ '{section.get('name', '')}' — ${math['total']:,.2f} "
                  f"(companion for '{parent_desc}')")


def _inject_chimney_flashing(sections: list, ins_data: dict):
    """
    Post-process: on tear-off jobs, if any chimney-related item exists (in our estimate
    OR in the INS estimate) but no chimney flashing line item exists, inject one.

    Logic:
    - Chimney presence detected by: chimney chase cover, chimney cap, chimney bid,
      or any INS item mentioning "chimney"
    - Only on tear-off jobs (section has a tear-off line item)
    - Default size: average (32" x 36") — Vanessa adjusts if needed
    - F9: domino argument (tear-off disturbs flashing)
    - Placed in the same section as the chimney chase/cap, or in the roof section
    """
    # Check if chimney flashing already exists anywhere
    all_items_text = ""
    for s in sections:
        for item in s.get("line_items", []):
            all_items_text += item.get("description", "").lower() + " "

    if "chimney flashing" in all_items_text:
        return  # Already have it

    # Check if there's a tear-off job
    has_tearoff = False
    roof_section = None
    for s in sections:
        for item in s.get("line_items", []):
            if "tear off" in item.get("description", "").lower():
                has_tearoff = True
                roof_section = s
                break
        if has_tearoff:
            break

    if not has_tearoff:
        return

    # Detect chimney presence in our estimate
    chimney_in_estimate = any(
        kw in all_items_text
        for kw in ["chimney chase", "chimney cap", "chimney shroud"]
    )

    # Detect chimney presence in INS estimate
    chimney_in_ins = False
    ins_items = ins_data.get("items", []) or ins_data.get("line_items", [])
    for ins_item in ins_items:
        if "chimney" in (ins_item.get("description", "") or "").lower():
            chimney_in_ins = True
            break

    if not chimney_in_estimate and not chimney_in_ins:
        return  # No chimney evidence anywhere

    # Look up pricelist rates
    pricing = lookup_price('R&R Chimney flashing - average (32" x 36")')
    if not pricing:
        print("[estimate_builder] ⚠️ Chimney flashing pricelist lookup failed — skipping injection")
        return

    # Find the right section — prefer section with chimney items, fall back to roof
    target_section = roof_section
    for s in sections:
        section_text = " ".join(item.get("description", "").lower() for item in s.get("line_items", []))
        if "chimney" in section_text:
            target_section = s
            break

    if not target_section:
        return

    # Get next line number
    all_nums = [item.get("num", 0) for s in sections for item in s.get("line_items", [])]
    next_num = max(all_nums) + 1 if all_nums else 1

    math = calc_line_item(1.0, pricing["remove"], pricing["replace"], pricing.get("is_material", True), False)

    new_item = {
        "num": next_num,
        "description": pricing["description"],
        "qty": 1.0,
        "unit": pricing["unit"],
        "remove_rate": pricing["remove"],
        "replace_rate": pricing["replace"],
        "is_material": pricing.get("is_material", True),
        "is_bid": False,
        "source": "added",
        "ins_item_num": None,
        "ins_total": 0.0,
        "f9": "",  # Will be generated by _generate_f9s
        "photo_anchor": "",
        "sub_name": "",
        **math,
    }

    target_section["line_items"].append(new_item)
    source = "estimate" if chimney_in_estimate else "INS"
    print(f"[estimate_builder] Injected chimney flashing: {pricing['description']} "
          f"(chimney detected in {source}) → '{target_section.get('name', '')}' "
          f"— ${math['total']:,.2f}")


def _extract_insured_name(project: dict, ins_data: dict) -> str:
    for key in ["insured", "insured_name", "homeowner", "name", "title"]:
        val = ins_data.get(key) or project.get(key)
        if val:
            return str(val)
    return project.get("name", "Unknown")


def _format_date_us(val: str) -> str:
    """Convert ISO date (2026-01-23) to US format (1/23/2026). Pass through if already formatted or empty."""
    if not val:
        return val
    try:
        dt = datetime.strptime(val.strip(), "%Y-%m-%d")
        return dt.strftime("%-m/%d/%Y")
    except ValueError:
        return val


def _extract_field(data: dict, key: str, fallback: str = "") -> str:
    return str(data.get(key) or fallback or "")


def _extract_city(ins_data: dict, project: dict) -> str:
    for src in [ins_data, project]:
        for key in ["city", "property_city"]:
            val = src.get(key)
            if val:
                return str(val)
    addr = _extract_field(ins_data, "address", project.get("address", ""))
    # Try to parse "City, TX 76034" from address
    m = re.search(r",\s*([A-Za-z\s]+),\s*TX", addr)
    if m:
        return m.group(1).strip()
    return ""


def _extract_zip(ins_data: dict, project: dict) -> str:
    for src in [ins_data, project]:
        for key in ["zip", "zip_code", "postal_code"]:
            val = src.get(key)
            if val:
                return str(val)
    addr = _extract_field(ins_data, "address", project.get("address", ""))
    m = re.search(r"\b(\d{5})\b", addr)
    if m:
        return m.group(1)
    return ""


# Map @trade tags → section name keywords to identify which INS items to drop
TRADE_SECTION_KEYWORDS = {
    "@gutter":       ["gutter", "downspout"],
    "@gutters":      ["gutter", "downspout"],
    "@fence":        ["fence"],
    "@wood_fence":   ["fence"],
    "@iron_fence":   ["fence"],
    "@siding":       ["siding"],
    "@window":       ["window"],
    "@hvac":         ["hvac", "mechanical"],
    "@paint":        ["paint", "exterior paint"],
    "@chimney":      ["chimney"],
    "@skylight":     ["skylight"],
    "@deck":         ["deck"],
    "@concrete":     ["concrete", "flatwork"],
    "@pool":         ["pool"],
}


def _filter_ins_for_bids(ins_data: dict, bids: list) -> dict:
    """
    Mark INS items that are replaced by sub bids, but keep them in context
    so the AI can reference their line numbers in F9 notes.
    Returns a copy of ins_data with bid-replaced items tagged.

    Example: @gutter bid → tag gutter/downspout items as replaced_by_bid=true.
    """
    if not bids:
        return ins_data

    items = list(ins_data.get("items", []) or ins_data.get("line_items", []))
    if not items:
        return ins_data

    # Collect section/keyword patterns for all bid trades
    drop_keywords = set()
    bid_trades = {}
    for bid in bids:
        tag = (bid.get("trade") or "").lower()
        for kw in TRADE_SECTION_KEYWORDS.get(tag, []):
            drop_keywords.add(kw.lower())
            bid_trades[kw.lower()] = tag

    if not drop_keywords:
        return ins_data

    def _matches(item: dict) -> bool:
        desc    = (item.get("description", "") or "").lower()
        section = (item.get("section", "") or item.get("room", "") or "").lower()
        return any(kw in desc or kw in section for kw in drop_keywords)

    # Tag items as replaced by bid but keep them in context for F9 referencing
    for item in items:
        if _matches(item):
            item["replaced_by_bid"] = True

    dropped = [item for item in items if item.get("replaced_by_bid")]
    if dropped:
        print(f"[estimate_builder] Bid replacement: tagged {len(dropped)} INS item(s) as replaced by sub bids:")
        for item in dropped:
            print(f"  - [{item.get('section','')}] {item.get('description','')}")

    result = dict(ins_data)
    result["items"] = items  # Keep ALL items, just tagged
    return result


def _format_ins_items(ins_data: dict) -> str:
    items = ins_data.get("items", []) or ins_data.get("line_items", [])
    if not items:
        return "(no insurance items parsed)"
    lines = []
    for i, item in enumerate(items, 1):
        desc = item.get("description", "")
        qty = item.get("qty", "") or item.get("quantity", "")
        unit = item.get("unit", "")
        rcv = item.get("rcv", "") or item.get("total", "") or item.get("amount", "")
        section = item.get("section", "") or item.get("room", "")
        note = item.get("notes", "") or ""
        note_text = f"\n   ⚠️ CARRIER NOTE: {note}" if note else ""
        # Use original INS line number if available, otherwise fallback to sequential
        ins_line = item.get("line_number")
        line_label = f"INS#{ins_line}" if ins_line else f"#{i}"
        bid_tag = " [REPLACED BY BID — do NOT copy, but reference this line number in bid F9]" if item.get("replaced_by_bid") else ""
        lines.append(f"{line_label}. [{section}] {desc} — {qty} {unit} — RCV: ${rcv}{bid_tag}{note_text}")
    return "\n".join(lines)


def _append_pitch_distribution(lines: list, rs: dict):
    """
    Add pitch distribution breakdown from EagleView.
    This tells the AI exactly how many SQ are steep vs standard,
    so steep charges are applied only to the steep portion.
    """
    # Try all_structures first (single-structure homes), then per-structure
    all_pitches = {}
    all_s = rs.get("all_structures", {})
    if all_s.get("areas_per_pitch"):
        for p in all_s["areas_per_pitch"]:
            all_pitches[p["pitch"]] = p.get("area_sf", 0)
    else:
        for s in rs.get("structures", []):
            for p in s.get("areas_per_pitch", []):
                pitch = p.get("pitch", "")
                area = p.get("area_sf", 0)
                if pitch in all_pitches:
                    all_pitches[pitch] += area
                else:
                    all_pitches[pitch] = area

    if not all_pitches:
        return

    lines.append("\n=== ⚠️ PITCH DISTRIBUTION (Area by Pitch) — USE FOR STEEP CHARGES ===")
    lines.append("CRITICAL: Steep charges (10/12-12/12 and >12/12) apply ONLY to the SQ at those pitches, NOT the entire roof.")
    lines.append("Calculate steep SQ from this table. Apply waste % only to the steep portion.")

    total_area = sum(all_pitches.values())
    steep_area = 0
    for pitch, area in sorted(all_pitches.items(), key=lambda x: _pitch_to_float(x[0])):
        sq = area / 100
        pct = (area / total_area * 100) if total_area else 0
        is_steep = _pitch_to_float(pitch) >= 10
        steep_label = " ← STEEP" if is_steep else ""
        lines.append(f"  {pitch} pitch: {area:.1f} sq ft = {sq:.2f} SQ ({pct:.1f}%){steep_label}")
        if is_steep:
            steep_area += area

    steep_sq = steep_area / 100
    non_steep_sq = (total_area - steep_area) / 100
    lines.append(f"\n  STEEP portion (≥10/12): {steep_area:.1f} sq ft = {steep_sq:.2f} measured SQ")
    lines.append(f"  NON-STEEP portion (<10/12): {total_area - steep_area:.1f} sq ft = {non_steep_sq:.2f} measured SQ")
    lines.append(f"  → Remove steep charge qty = {steep_sq:.2f} SQ (measured, steep portion only)")
    lines.append(f"  → Add steep charge qty = apply waste % to {steep_sq:.2f} SQ (steep portion with waste)")


def _pitch_to_float(pitch_str: str) -> float:
    """Convert pitch string like '12/12' or '6/12' to a float (rise per 12 run)."""
    try:
        parts = pitch_str.split("/")
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def _format_ev_data(ev_data: dict) -> str:
    """Format EagleView data for AI context. Handles both flat and nested structures."""
    if not ev_data:
        return "(no EagleView data)"

    lines = []

    # Flat format (simple)
    flat_labels = {
        "area_sq": "Total Area (SQ)",
        "area_base_sq": "Base Area (SQ)",
        "waste_pct": "Suggested Waste %",
        "eaves_lf": "Eaves (LF)",
        "rakes_lf": "Rakes (LF)",
        "eaves_rakes_lf": "Eaves + Rakes (LF)",
        "ridges_lf": "Ridges (LF)",
        "hips_lf": "Hips (LF)",
        "ridges_hips_lf": "Ridges + Hips (LF)",
        "valleys_lf": "Valleys (LF)",
        "step_flashing_lf": "Step Flashing (LF)",
        "flashing_lf": "Flashing/Counterflashing (LF)",
        "predominant_pitch": "Predominant Pitch",
        "stories": "Stories ⚠️ ADD HIGH ROOF CHARGES IF 2+",
        "report_id": "Report ID",
    }
    for key, label in flat_labels.items():
        val = ev_data.get(key)
        if val is not None and val != "":
            lines.append(f"{label}: {val}")

    # Metadata
    meta = ev_data.get("metadata", {})
    if meta.get("report_id"):
        lines.append(f"Report ID: {meta['report_id']}")
    if meta.get("date"):
        lines.append(f"Report Date: {meta['date']}")

    # Roofing summary (nested structure from parse_eagleview)
    rs = ev_data.get("roofing_summary", {})
    all_str = rs.get("all_structures", {})

    # Top-level summary fields (added by updated parser)
    measured_sq_top  = rs.get("measured_sq")
    suggested_sq_top = rs.get("suggested_sq")
    suggested_pct_top = rs.get("suggested_waste_pct")

    if measured_sq_top or suggested_sq_top or rs.get("ridges_hips_lf"):
        lines.append("\n=== EagleView Measurements (All Structures) ===")
        lines.append("RULE: Use MEASURED SQ for tear-off AND felt. Use SUGGESTED SQ for shingles and other material items (starter, hip/ridge, etc.).")
        lines.append("FELT = MEASURED SQ (same as tear-off). Felt covers the deck in rolls with minimal waste — do NOT apply shingle waste % to felt.")
        if measured_sq_top:
            lines.append(f"Measured SQ (tear-off AND felt, no waste): {measured_sq_top}")
        if suggested_sq_top:
            lines.append(f"Suggested SQ at {suggested_pct_top}% waste: {suggested_sq_top}  ← USE THIS for shingles, starter, etc. NOT for felt.")
        if rs.get("ridges_hips_lf"):
            lines.append(f"Ridges + Hips (LF): {rs['ridges_hips_lf']}")
        if rs.get("valleys_lf"):
            lines.append(f"Valleys (LF): {rs['valleys_lf']}")
        if rs.get("drip_edge_lf"):
            lines.append(f"Drip Edge / Eaves+Rakes (LF): {rs['drip_edge_lf']}")
        if rs.get("eaves_lf") or rs.get("eaves_starter_lf"):
            lines.append(f"Eaves / Starter Strip (LF): {rs.get('eaves_lf') or rs.get('eaves_starter_lf')}")
        if rs.get("rakes_lf"):
            lines.append(f"Rakes (LF): {rs['rakes_lf']}")
        if rs.get("step_flashing_lf"):
            lines.append(f"Step Flashing (LF): {rs['step_flashing_lf']}  ← ADD this as a new line item if INS missed it")
        if rs.get("flashing_lf"):
            lines.append(f"Counter/Apron Flashing (LF): {rs['flashing_lf']}  ← ADD this as a new line item if INS missed it")
        if all_str.get("predominant_pitch"):
            lines.append(f"Predominant Pitch: {all_str['predominant_pitch']}")
        if all_str.get("total_facets"):
            lines.append(f"Total Facets: {all_str['total_facets']}")

    elif all_str:
        # Fallback to nested lengths if top-level fields not present
        lengths = all_str.get("lengths", {})
        if lengths:
            lines.append("\n=== EagleView Measurements (All Structures) ===")
            for k, v in lengths.items():
                if v:
                    lines.append(f"{k}: {v}")

    # Pitch distribution — CRITICAL for steep charge calculation (always append)
    _append_pitch_distribution(lines, rs)

    # Per-structure breakdown — Structure #1 = main house, Structure #2 = detached garage
    structures = rs.get("structures", [])
    if structures:
        labels = {0: "Structure #1 — MAIN HOUSE", 1: "Structure #2 — DETACHED GARAGE"}
        lines.append("\n=== EagleView Per-Structure Measurements ===")
        lines.append("RULE: Use MEASURED SQ for tear-off AND felt. Use SUGGESTED SQ for shingles and other materials (NOT felt).")
        lines.append("FELT = MEASURED SQ (same as tear-off). Felt covers the deck — minimal waste.")
        lines.append("USE EACH STRUCTURE for its respective section — do NOT mix them.")
        for i, s in enumerate(structures):
            label = labels.get(i, s["name"])
            m_sq  = s.get("measured_squares", 0)
            s_pct = s.get("suggested_waste_pct")
            s_sq  = s.get("suggested_squares")
            waste_line = f"Suggested waste: {s_pct}% → {s_sq} SQ" if s_pct else "Suggested waste: unknown"
            lines.append(f"\n  {label} | Pitch: {s.get('predominant_pitch','?')}")
            lines.append(f"    Tear-off SQ (measured, no waste): {m_sq}")
            lines.append(f"    {waste_line}  ← USE THIS for shingles, starter, etc. NOT for felt (felt = measured SQ).")
            for k, v in s.get("lengths", {}).items():
                if v:
                    lines.append(f"    {k}: {v}")

    # Summary area if available
    summary = ev_data.get("summary", {})
    if summary:
        lines.append("\n=== EV Summary ===")
        for k, v in summary.items():
            if v:
                lines.append(f"{k}: {v}")

    return "\n".join(lines) if lines else "(no EagleView measurements)"


def _format_conversation_history(history: dict) -> str:
    """Render the 5-field summary Rails built from all project chat rooms.

    Fields (all may be empty strings): strategy, scope_changes,
    estimate_instructions, carrier_behavior, context. Produced by
    Supplements::SummarizeConversationContext on the IFC platform side using
    Alvaro's prompt. Empty fields are omitted from output to keep the prompt
    tight. If every field is empty, returns "" so the section is skipped
    entirely (no empty header dangling in the prompt).
    """
    if not history or not isinstance(history, dict):
        return ""

    labels = [
        ("strategy",              "Strategy (current game plan)"),
        ("scope_changes",         "Scope Changes (overrides to flow cards)"),
        ("estimate_instructions", "Estimate Instructions (one-off directions for THIS run)"),
        ("carrier_behavior",      "Carrier Behavior (adjuster/carrier positions)"),
        ("context",               "Context (round, prior sends, what's pending)"),
    ]

    blocks = []
    for key, label in labels:
        value = (history.get(key) or "").strip()
        if value:
            blocks.append(f"**{label}:**\n{value}")

    if not blocks:
        return ""

    body = "\n\n".join(blocks)
    return (
        "## CONVERSATION CONTEXT (summarized from all project chat rooms)\n"
        "Use this for deciding WHAT to include and HOW to argue items. Treat it "
        "as the newest-wins source of truth for strategy. NEVER reference it in "
        "F9 notes (same rule as @ifc/@supplement).\n\n"
        f"{body}"
    )


def _format_bids(bids: list) -> str:
    """Format sub bid data for AI prompt."""
    if not bids:
        return "(no sub bids found — standard Xactimate pricing only)"
    lines = [
        "NOTE: Each bid below REPLACES the corresponding INS line items for that trade.",
        "Drop ALL INS items in that section and use the bid item instead.",
        "",
        "SUB NAME | TRADE TAG | SCOPE/DESCRIPTION | RETAIL (request from insurance)"
    ]
    for bid in bids:
        sub   = bid.get("sub_name", "Unknown")
        trade = bid.get("trade", "")
        # For @other cards, scope (content field) IS the description
        scope = bid.get("scope", "") or trade
        retail = bid.get("retail_total", 0)
        lines.append(f"{sub} | {trade} | {scope} | ${retail:,.2f}")
        if bid.get('bid_line_items_text'):
            lines.append(f'  → Bid PDF line items: {bid["bid_line_items_text"]}')
        if bid.get('supplement_notes'):
            lines.append(f'  → Supplement context: {bid["supplement_notes"]}')
    return "\n".join(lines)


def _format_gutter_measurements(gutter_data: dict) -> str:
    """Format gutter bid measurements for AI prompt."""
    if not gutter_data:
        return "(no gutter bid measurements available — use EagleView or INS measurements for gutters)"
    lines = [
        f"Source: {gutter_data.get('sub_name', 'Gutter bid')} (measurements only — do NOT use bid price)",
        f"Gutter LF: {gutter_data.get('gutter_lf', 0)}",
        f"Downspout LF: {gutter_data.get('downspout_lf', 0)}",
    ]
    if gutter_data.get("miters"):
        lines.append(f"Miters: {gutter_data['miters']}")
    if gutter_data.get("splashguards"):
        lines.append(f"Splashguards: {gutter_data['splashguards']}")
    for item in gutter_data.get("other_items", []):
        lines.append(f"{item['description']}: {item['qty']} {item['unit']}")
    lines.append("")
    lines.append("USE THESE MEASUREMENTS to build individual Xactimate gutter line items:")
    lines.append("  - R&R Gutter / downspout - aluminum - up to 5\" → use Gutter LF")
    lines.append("  - R&R Downspout - aluminum → use Downspout LF")
    lines.append("  - Splashguard - aluminum → use Splashguards count (EA) if present")
    lines.append("  - Miters → include if present")
    lines.append("DO NOT submit gutters as a single bid item. Build line-by-line Xactimate items.")
    return "\n".join(lines)


def _format_corrections(corrections: list) -> str:
    """Format reviewer corrections from previous estimate PDF for AI prompt."""
    if not corrections:
        return ""
    lines = ["=== REVIEWER CORRECTIONS FROM PREVIOUS ESTIMATE ===",
             "A human reviewer highlighted and commented on the previous version.",
             "You MUST address each correction below in this new estimate.",
             ""]
    for i, c in enumerate(corrections, 1):
        lines.append(f"Correction {i}:")
        if c.get("quoted_text"):
            # Truncate quoted text to keep prompt lean
            qt = c["quoted_text"][:300].replace("\n", " ").strip()
            lines.append(f"  Highlighted text: \"{qt}\"")
        lines.append(f"  Reviewer note: {c['comment']}")
        if c.get("replies"):
            for r in c["replies"]:
                lines.append(f"  Reply: {r}")
        lines.append("")
    return "\n".join(lines)


def _format_pricelist_sample(pricelist: dict, max_items: int = 60) -> str:
    """Format top pricelist items for AI context."""
    priority_keywords = [
        "shingle", "felt", "underlayment", "drip edge", "starter", "hip", "ridge",
        "valley", "step flashing", "counter flashing", "apron", "pipe jack",
        "gutter", "downspout", "guard", "labor minimum", "steep", "high roof",
        "debris", "dumpster", "supervision", "haul",
    ]
    lines = ["DESCRIPTION | UNIT | REMOVE | REPLACE"]
    shown = set()

    # Priority items first
    for kw in priority_keywords:
        for key, val in pricelist.items():
            if kw in key and key not in shown:
                lines.append(f"{val['description']} | {val['unit']} | ${val['remove']:.2f} | ${val['replace']:.2f}")
                shown.add(key)
                if len(lines) > max_items:
                    break

    # Fill remaining
    for key, val in pricelist.items():
        if key not in shown and len(lines) <= max_items:
            lines.append(f"{val['description']} | {val['unit']} | ${val['remove']:.2f} | ${val['replace']:.2f}")
            shown.add(key)

    return "\n".join(lines)


def _format_ins_items_condensed(ins_data: dict) -> str:
    """Condensed version of INS items — drops section/room, shorter format to save tokens."""
    items = ins_data.get("items", []) or ins_data.get("line_items", [])
    if not items:
        return "(no insurance items parsed)"
    lines = []
    for i, item in enumerate(items, 1):
        desc = item.get("description", "")
        qty = item.get("qty", "") or item.get("quantity", "")
        unit = item.get("unit", "")
        rcv = item.get("rcv", "") or item.get("total", "") or item.get("amount", "")
        lines.append(f"{i}. {desc} {qty} {unit} ${rcv}")
    return "\n".join(lines)


def _repair_truncated_json(raw: str) -> str:
    """
    Best-effort repair of a truncated JSON string.
    Handles: unclosed strings, trailing commas, unclosed brackets/objects.
    """
    text = raw.rstrip()

    # If we're inside an unclosed string, close it and truncate the bad value
    stack = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    # If truncated inside a string, close the string
    if in_string:
        text += '"'
        print(f"[estimate_builder] JSON repair: closed truncated string")

    # Remove trailing comma before closing brackets (invalid JSON)
    import re as _re
    text = _re.sub(r',\s*$', '', text)

    # Re-scan for unclosed brackets after string fix
    stack = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    # Close whatever's open
    closing = {"[": "]", "{": "}"}
    patch = ""
    for opener in reversed(stack):
        patch += closing[opener]

    repaired = text + patch
    if patch:
        print(f"[estimate_builder] JSON repair: appended '{patch}' to close {len(stack)} open bracket(s)")
    return repaired


if __name__ == "__main__":
    import sys
    from data_pipeline import run as pipeline_run

    project_name = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Rose Brock"
    pipeline_data = pipeline_run(project_name)
    estimate = build_estimate(pipeline_data)

    output_path = Path(__file__).parent / "estimate.json"
    with open(output_path, "w") as f:
        json.dump(estimate, f, indent=2)
    print(f"\n[estimate_builder] Saved to {output_path}")
    print(f"Total sections: {len(estimate['sections'])}")
    print(f"Line Item Total: ${estimate['line_item_total']:,.2f}")
