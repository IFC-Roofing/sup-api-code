"""
qa_agent.py — AI-powered QA review + correction system for generated estimates.

Two-pass architecture:
  Pass 1: AI reviews estimate.json against source data, outputs structured corrections
  Pass 2: Deterministic Python applies corrections with full math recalculation
  Pass 3: AI rewrites F9 notes for items whose quantities changed

Usage:
  from qa_agent import qa_review
  corrected_estimate = qa_review(estimate, pipeline_data)
"""

import os
import sys
import json
import re
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from estimate_builder import calc_line_item, TX_TAX_RATE, OP_RATE, f9_left_out
from estimate_utils import refresh_totals
from data_pipeline import lookup_price, _guess_is_material

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
QA_MODEL = "claude-sonnet-4-6"
F9_MODEL = "claude-sonnet-4-6"


# ─── Pass 1: AI QA Review ─────────────────────────────────────────────────────

def _build_qa_prompt(estimate: dict, pipeline_data: dict) -> str:
    """Build the prompt for the QA reviewer AI."""
    
    # Format estimate for review
    estimate_lines = []
    for section in estimate.get("sections", []):
        estimate_lines.append(f"\n=== SECTION: {section['name']} ===")
        for item in section.get("line_items", []):
            flags = []
            if item.get("source"): flags.append(f"source={item['source']}")
            if item.get("is_bid"): flags.append("BID")
            if item.get("is_material"): flags.append("MATERIAL")
            
            estimate_lines.append(
                f"  Line {item['num']}: {item['description']} | "
                f"{item['qty']} {item.get('unit', 'EA')} | "
                f"remove_rate={item.get('remove_rate', 0)} replace_rate={item.get('replace_rate', 0)} | "
                f"remove={item.get('remove', 0)} replace={item.get('replace', 0)} "
                f"tax={item.get('tax', 0)} op={item.get('op', 0)} total={item.get('total', 0)} | "
                f"{' '.join(flags)}"
            )
            if item.get("f9"):
                # Show first 300 chars of F9
                f9_preview = item["f9"][:300].replace("\n", " \\n ")
                estimate_lines.append(f"    F9: {f9_preview}")
    
    estimate_text = "\n".join(estimate_lines)
    
    # Format EV data
    ev_data = pipeline_data.get("ev_data", {})
    rs = ev_data.get("roofing_summary", {})
    ev_lines = []
    if rs.get("measured_sq"): ev_lines.append(f"Measured SQ: {rs['measured_sq']}")
    if rs.get("suggested_sq"): ev_lines.append(f"Suggested SQ: {rs['suggested_sq']}")
    if rs.get("suggested_waste_pct"): ev_lines.append(f"Waste %: {rs['suggested_waste_pct']}")
    if rs.get("ridges_hips_lf"): ev_lines.append(f"Ridges+Hips LF: {rs['ridges_hips_lf']}")
    if rs.get("valleys_lf"): ev_lines.append(f"Valleys LF: {rs['valleys_lf']}")
    if rs.get("drip_edge_lf"): ev_lines.append(f"Drip Edge LF: {rs['drip_edge_lf']}")
    if rs.get("eaves_lf"): ev_lines.append(f"Eaves LF: {rs['eaves_lf']}")
    if rs.get("rakes_lf"): ev_lines.append(f"Rakes LF: {rs['rakes_lf']}")
    if rs.get("step_flashing_lf"): ev_lines.append(f"Step Flashing LF: {rs['step_flashing_lf']}")
    if rs.get("flashing_lf"): ev_lines.append(f"Counter/Apron Flashing LF: {rs['flashing_lf']}")
    
    # Pitch distribution
    all_str = rs.get("all_structures", {})
    if all_str.get("areas_per_pitch"):
        ev_lines.append("\nPitch Distribution:")
        total_area = sum(p.get("area_sf", 0) for p in all_str["areas_per_pitch"])
        for p in all_str["areas_per_pitch"]:
            pitch = p.get("pitch", "?")
            area = p.get("area_sf", 0)
            sq = area / 100
            is_steep = _pitch_to_float(pitch) >= 10
            label = " ← STEEP" if is_steep else ""
            ev_lines.append(f"  {pitch}: {sq:.2f} SQ{label}")
    
    # Per-structure
    for i, struct in enumerate(rs.get("structures", [])):
        label = "Main House" if i == 0 else f"Structure #{i+1}"
        ev_lines.append(f"\n{label}:")
        if struct.get("measured_squares"): ev_lines.append(f"  Measured SQ: {struct['measured_squares']}")
        if struct.get("suggested_squares"): ev_lines.append(f"  Suggested SQ: {struct['suggested_squares']}")
        if struct.get("suggested_waste_pct"): ev_lines.append(f"  Waste %: {struct['suggested_waste_pct']}")
        for k, v in struct.get("lengths", {}).items():
            if v: ev_lines.append(f"  {k}: {v}")
    
    # If no EV waste data, note the industry default was used
    if not rs.get("suggested_sq") and not rs.get("suggested_waste_pct"):
        no_ev_structures = not any(s.get("suggested_waste_pct") for s in rs.get("structures", []))
        if no_ev_structures:
            ev_lines.append("\n⚠️ NOTE: No EV waste data available. Post-processor applied 13% industry default waste.")
            ev_lines.append("Shingles, steep install, and high roof install quantities ALREADY include 13% waste.")
            ev_lines.append("DO NOT reduce these back to tear-off or INS quantities.")
    
    ev_text = "\n".join(ev_lines) if ev_lines else "(no EV data — 13% industry default waste was applied to shingles, steep install, and high roof install)"
    
    # Format INS items
    ins_data = pipeline_data.get("ins_data", {})
    ins_items = ins_data.get("items", []) or ins_data.get("line_items", [])
    ins_lines = []
    for item in ins_items:
        ins_num = item.get("line_number", "?")
        desc = item.get("description", "")
        qty = item.get("qty", "") or item.get("quantity", "")
        unit = item.get("unit", "")
        rcv = item.get("rcv", "") or item.get("total", "")
        section = item.get("section", "")
        ins_lines.append(f"INS#{ins_num} [{section}] {desc} — {qty} {unit} — RCV: ${rcv}")
    ins_text = "\n".join(ins_lines) if ins_lines else "(no INS items)"
    
    # Format bids
    bids = pipeline_data.get("bids", [])
    bid_lines = []
    for bid in bids:
        bid_lines.append(f"{bid.get('sub_name', '?')} | {bid.get('trade', '')} | ${bid.get('retail_total', 0):,.2f}")
    bid_text = "\n".join(bid_lines) if bid_lines else "(no bids)"
    
    # Format pricelist (key items only)
    pricelist = pipeline_data.get("pricelist", {})
    pl_lines = []
    priority_kw = ["shingle", "felt", "drip edge", "starter", "hip", "ridge", "valley",
                    "step flashing", "counter flashing", "apron", "pipe jack", "steep", "high roof",
                    "gutter", "downspout", "power attic", "exhaust", "roof vent", "satellite"]
    shown = set()
    for kw in priority_kw:
        for key, val in pricelist.items():
            if kw in key and key not in shown:
                pl_lines.append(f"{val['description']} | {val['unit']} | remove=${val['remove']:.2f} | replace=${val['replace']:.2f}")
                shown.add(key)
                if len(pl_lines) > 40:
                    break
    pricelist_text = "\n".join(pl_lines) if pl_lines else "(pricelist not available)"

    prompt = f"""You are a QA reviewer for insurance supplement estimates. Your job is to find EVERY error in this generated estimate.

## GENERATED ESTIMATE
{estimate_text}

## EAGLEVIEW MEASUREMENTS (source of truth for quantities)
{ev_text}

## INSURANCE ESTIMATE ITEMS (what insurance already approved)
{ins_text}

## SUB BIDS
{bid_text}

## XACTIMATE PRICELIST (correct rates)
{pricelist_text}

## MATH RULES
- remove = qty × remove_rate (0 for non-R&R items and bids)
- replace = qty × replace_rate
- tax = replace × 0.0825 (materials only; labor, bids, steep/high charges = 0)
- op = (remove + replace) × 0.20
- total = remove + replace + tax + op

## QUANTITY RULES
- Tear-off SQ = EV measured SQ (no waste)
- Shingles SQ = EV suggested SQ (with waste)
- Felt SQ = EV measured SQ (same as tear-off, no waste)
- Starter LF = Drip edge LF (eaves + rakes)
- Drip edge LF = eaves + rakes from EV
- Hip/Ridge cap LF = ridges + hips from EV
- Valley metal LF = valleys from EV
- Step flashing LF = step flashing from EV
- Steep charges: ONLY steep portion of roof (≥10/12 pitch). Remove = steep measured SQ. Install = steep measured SQ × (1 + waste%). Check PITCH DISTRIBUTION.
- High roof charges: Remove = measured SQ. Install = suggested SQ (with waste). Only if 2+ stories.
- Round LF values DOWN to nearest whole number. Keep SQ at EV precision.

## CHECK FOR THESE SPECIFIC ISSUES

1. **TEMPLATE PLACEHOLDERS** — F9 text containing: "Put the amount", "$____", "$XX", "XX LF", "XX SQ", "(Put the", any unfilled bracket/placeholder text. These are template leftovers that should have been filled with real numbers.

2. **BROKEN INS REFERENCES** — F9 text like "covers Insurance line item We are" or "covers insurance line item(s) We" — the INS line number is missing between "item" and the next sentence.

3. **NONSENSICAL F9 LANGUAGE** — F9 referencing Xactimate descriptions as physical objects: "damage to the remove additional charge for steep roof" or "showing damage to the additional charge". Charges aren't physical things.

4. **MISSING WASTE ON QUANTITIES** — Steep install, shingle, high roof install should include waste %. If steep remove = X and steep install = X (same number), waste wasn't applied to install.

5. **WRONG ITEM GOT THE QTY** — A measurement applied to the wrong line item (e.g., LF value on an SQ item, perimeter measurement on shingles instead of drip edge).

6. **MATH ERRORS** — qty × rate ≠ the stored amount. Or tax on labor items. Or missing O&P.

7. **D&R vs R&R MISMATCH** — Description says "Detach & reset" but F9 argues for "Remove and replace" (or vice versa). The description and F9 must agree on the action.

8. **DOLLAR AMOUNTS IN F9** — F9 notes containing "costs $X" or "the difference is $X" or "Per Xactimate pricing, this costs" (BANNED — except for bid item totals). Only allowed: "Our sub bid cost is $X".

9. **WRONG RATES** — replace_rate doesn't match what the pricelist says for that description. Check against the pricelist provided.

10. **source='ins' WITH F9** — Items copied from insurance (source='ins') should have f9="" (empty). If they have F9 text, that's wrong.

11. **MISSING STEEP SLOPE CATEGORIES** — EV pitch distribution shows both 7-9/12 AND >12/12 steep areas, but estimate only has one steep charge category. Both should be included.

12. **MISSING LINE ITEMS** — EV shows measurements for something (step flashing, valley, apron flashing) but it's not in the estimate at all.

13. **F9 NUMBERS DON'T MATCH ITEM** — F9 says "requesting 210 LF" but the line item qty is different. Or F9 says "additional X.XX" but the math (our qty - INS qty) doesn't equal that number.

14. **DO NOT UNDO WASTE ADJUSTMENTS** — If shingle install qty is HIGHER than tear-off qty (e.g., tear-off = 44.91 SQ, shingles = 50.75 SQ), that's waste applied correctly. Do NOT reduce shingles back to tear-off or INS qty. Same for steep install and high roof install — they should be HIGHER than their remove counterparts by the waste percentage. When EV suggested SQ is missing, a 10-15% difference from measured SQ is normal industry waste. Only flag if the difference is unreasonable (>25% or negative).

15. **DO NOT REDUCE QUANTITIES BELOW INS** — If our qty is higher than INS qty on ANY line item, that is intentional. NEVER suggest reducing our qty to match or go below INS. The INS qty is a FLOOR, not a ceiling. If INS approved 402.41 LF and we have 402.41 LF, that's correct — leave it alone even if EV shows a lower number. We always want at least what INS is paying for.

## OUTPUT FORMAT

Return a JSON array of corrections. Each correction:
{{
  "line_num": 14,
  "issue_type": "wrong_qty",  
  "error_description": "Steep install charge should include 13% waste. Currently 44.91 SQ same as remove, should be 50.75 SQ",
  "fix": {{
    "qty": 50.75,
    "description": null,
    "remove_rate": null,
    "replace_rate": null,
    "is_material": null,
    "f9": null,
    "action_change": null
  }}
}}

For missing items, use issue_type="missing_item":
{{
  "line_num": null,
  "issue_type": "missing_item",
  "error_description": "EV shows >12/12 steep area of 26.47 SQ but no steep >12/12 charges in estimate",
  "fix": {{
    "section": "Dwelling Roof",
    "description": "Additional charge for steep roof greater than 12/12 slope",
    "qty": 29.91,
    "source": "added"
  }}
}}

For F9 issues where the F9 needs full rewrite, set fix.f9 = "REWRITE_NEEDED" (will be handled by Pass 3).
For template placeholder issues, set fix.f9 = "REWRITE_NEEDED".

Only include fields in "fix" that need changing. Use null for fields that are fine.
IMPORTANT: The "fix" object must ALWAYS be a non-null dict. Even for observation-only issues, include at minimum {{}}.
For rate issues: always include the correct remove_rate and replace_rate in the fix.
For qty issues: always include the correct qty in the fix.
For description issues: always include the correct description in the fix.
If no issues found, return an empty array: []

Respond with ONLY the JSON array. No markdown, no explanation."""

    return prompt


def _run_qa_review(estimate: dict, pipeline_data: dict) -> list:
    """Pass 1: Call AI to review the estimate and return corrections."""
    import anthropic
    
    prompt = _build_qa_prompt(estimate, pipeline_data)
    
    print("[qa_agent] Pass 1: Running AI QA review...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=180.0)

    import time as _time
    last_err = None
    raw = None
    for attempt in range(1, 4):
        try:
            resp = client.messages.create(
                model=QA_MODEL,
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = resp.content[0].text.strip()
            break
        except (anthropic.InternalServerError, anthropic.APIStatusError) as e:
            last_err = e
            wait = 15 * attempt
            print(f"[qa_agent] Anthropic {getattr(e,'status_code',0)} on attempt {attempt} — retrying in {wait}s...")
            _time.sleep(wait)
        except anthropic.APITimeoutError as e:
            last_err = e
            print(f"[qa_agent] Timeout on attempt {attempt} — retrying...")
            _time.sleep(10)
    if raw is None:
        raise last_err
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    
    try:
        corrections = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[qa_agent] ⚠️  Failed to parse QA response: {e}")
        print(f"[qa_agent] Raw response (first 500 chars): {raw[:500]}")
        # Attempt JSON repair: find last complete object in array
        corrections = _repair_json_array(raw)
        if not corrections:
            return []
        print(f"[qa_agent] Repaired JSON: recovered {len(corrections)} correction(s) from truncated response")
    
    if not isinstance(corrections, list):
        print(f"[qa_agent] ⚠️  QA response is not a list, got {type(corrections)}")
        return []
    
    print(f"[qa_agent] Found {len(corrections)} issue(s)")
    for c in corrections:
        print(f"  → Line {c.get('line_num', '?')}: [{c.get('issue_type', '?')}] {c.get('error_description', '')[:100]}")
    
    return corrections


# ─── Pass 2: Deterministic Apply ──────────────────────────────────────────────

def _repair_json_array(raw: str) -> list:
    """Attempt to repair a truncated JSON array by finding the last complete object."""
    # Strategy: find positions of all complete objects (ending with "}")
    # and try parsing the array up to each one
    raw = raw.strip()
    if not raw.startswith("["):
        return []
    
    # Find all closing brace positions that could end an object
    last_good = None
    depth = 0
    in_string = False
    escape_next = False
    brace_positions = []
    
    for i, ch in enumerate(raw):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                brace_positions.append(i)
    
    # Try from the last complete object backwards
    for pos in reversed(brace_positions):
        candidate = raw[:pos + 1] + "\n]"
        try:
            result = json.loads(candidate)
            if isinstance(result, list) and len(result) > 0:
                return result
        except json.JSONDecodeError:
            continue
    
    return []


def _apply_corrections(estimate: dict, corrections: list, pipeline_data: dict) -> list:
    """Pass 2: Apply corrections to estimate with full math recalculation.
    Returns list of items that need F9 rewrites."""
    
    f9_rewrite_needed = []
    pricelist = pipeline_data.get("pricelist", {})
    
    # Build line_num → item lookup
    item_map = {}
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            item_map[item["num"]] = (section, item)
    
    for correction in corrections:
      try:
        line_num = correction.get("line_num")
        issue_type = correction.get("issue_type", "")
        fix = correction.get("fix", {})
        error_desc = correction.get("error_description", "")
        
        if not fix or not isinstance(fix, dict):
            # Auto-fix: if issue_type is wrong_rates and we have pricelist, look up correct rates
            if issue_type in ("wrong_rates", "wrong_rate", "wrong_description") and line_num in item_map:
                _, item_ref = item_map[line_num]
                desc = item_ref["description"]
                # Check if error suggests D&R → R&R upgrade
                if "r&r" in error_desc.lower() and ("detach" in desc.lower() or "d&r" in desc.lower()):
                    fix = {"action_change": "r&r"}
                    print(f"[qa_agent] Line {line_num}: auto-fixing D&R → R&R (AI provided no fix)")
                else:
                    pricing = lookup_price(desc)
                    if pricing and pricing.get("replace", 0) > 0:
                        fix = {"remove_rate": pricing["remove"], "replace_rate": pricing["replace"]}
                        print(f"[qa_agent] Line {line_num}: auto-fixing rates from pricelist (AI provided no fix)")
                    else:
                        print(f"[qa_agent] ⚠️  Line {line_num}: no fix and pricelist miss ({issue_type}: {error_desc[:80]}), skipping")
                        continue
            elif issue_type in ("wrong_qty", "math_error") and line_num in item_map:
                # For math errors, just recalculate with existing values
                _, item_ref = item_map[line_num]
                fix = {}  # Will trigger recalc
                print(f"[qa_agent] Line {line_num}: auto-recalculating ({issue_type})")
            else:
                print(f"[qa_agent] ⚠️  Line {line_num}: correction has no fix object ({issue_type}: {error_desc[:80]}), skipping")
                continue

        if issue_type == "missing_item":
            _handle_missing_item(estimate, fix, pricelist)
            continue
        
        if line_num is None:
            print(f"[qa_agent] ⚠️  Correction has no line_num ({issue_type}: {error_desc[:80]}), skipping")
            continue
        
        if line_num not in item_map:
            print(f"[qa_agent] ⚠️  Line {line_num} not found in estimate, skipping correction")
            continue
        
        section, item = item_map[line_num]
        old_qty = item.get("qty", 0)
        changed = False
        
        # Apply description change (must come before rate lookup)
        if fix.get("description"):
            old_desc = item["description"]
            item["description"] = fix["description"]
            print(f"[qa_agent] Line {line_num}: description '{old_desc}' → '{fix['description']}'")
            
            # Lookup new rates from pricelist
            pricing = lookup_price(fix["description"])
            if pricing:
                item["remove_rate"] = pricing["remove"]
                item["replace_rate"] = pricing["replace"]
                item["unit"] = pricing["unit"]
                item["is_material"] = pricing.get("is_material", _guess_is_material(fix["description"]))
                print(f"[qa_agent] Line {line_num}: updated rates from pricelist (remove={pricing['remove']}, replace={pricing['replace']}, unit={pricing['unit']})")
            changed = True
        
        # Apply action change (D&R → R&R or vice versa)
        if fix.get("action_change"):
            action = fix["action_change"]  # "r&r" or "d&r"
            desc = item["description"]
            if action.lower() == "r&r":
                # Add R&R prefix if not present
                if not desc.lower().startswith("r&r "):
                    new_desc = f"R&R {desc}" if "detach" not in desc.lower() else desc.replace("Detach & reset", "").strip()
                    # Try pricelist lookup with R&R
                    pricing = lookup_price(f"R&R {desc}") or lookup_price(desc)
                    if pricing:
                        item["description"] = pricing["description"]
                        item["remove_rate"] = pricing["remove"]
                        item["replace_rate"] = pricing["replace"]
                        item["unit"] = pricing["unit"]
                        item["is_material"] = pricing.get("is_material", _guess_is_material(pricing["description"]))
                        print(f"[qa_agent] Line {line_num}: action change → R&R, desc='{pricing['description']}', rates updated")
                    else:
                        print(f"[qa_agent] Line {line_num}: action change → R&R but pricelist lookup failed for '{desc}'")
                changed = True
        
        # Apply explicit rate changes
        if fix.get("remove_rate") is not None:
            try:
                item["remove_rate"] = float(fix["remove_rate"])
                changed = True
            except (ValueError, TypeError):
                print(f"[qa_agent] ⚠️  Line {line_num}: invalid remove_rate '{fix['remove_rate']}', skipping")
        if fix.get("replace_rate") is not None:
            try:
                item["replace_rate"] = float(fix["replace_rate"])
                changed = True
            except (ValueError, TypeError):
                print(f"[qa_agent] ⚠️  Line {line_num}: invalid replace_rate '{fix['replace_rate']}', skipping")
        if fix.get("is_material") is not None:
            item["is_material"] = bool(fix["is_material"])
            changed = True
        
        # Apply qty change — with INS floor guard
        if fix.get("qty") is not None:
            try:
                new_qty = float(fix["qty"])
            except (ValueError, TypeError):
                print(f"[qa_agent] ⚠️  Line {line_num}: invalid qty '{fix['qty']}', skipping")
                continue
            # INS floor guard: never reduce qty below what INS approved
            ins_qty = item.get("ins_qty") or 0
            if new_qty < old_qty and ins_qty > 0 and new_qty < ins_qty:
                print(f"[qa_agent] Line {line_num}: BLOCKED qty reduction {old_qty} → {new_qty} (INS floor: {ins_qty})")
            else:
                item["qty"] = new_qty
                print(f"[qa_agent] Line {line_num}: qty {old_qty} → {new_qty}")
                changed = True
        
        # Recalculate math if anything changed
        if changed:
            math = calc_line_item(
                item["qty"],
                item.get("remove_rate", 0),
                item.get("replace_rate", 0),
                item.get("is_material", True),
                item.get("is_bid", False)
            )
            item["remove"] = math["remove"]
            item["replace"] = math["replace"]
            item["tax"] = math["tax"]
            item["op"] = math["op"]
            item["total"] = math["total"]
            print(f"[qa_agent] Line {line_num}: recalculated → total=${item['total']:,.2f}")
        
        # Apply F9 change
        if fix.get("f9") is not None:
            if fix["f9"] == "REWRITE_NEEDED":
                f9_rewrite_needed.append(item)
            else:
                item["f9"] = fix["f9"]
                print(f"[qa_agent] Line {line_num}: F9 updated directly")
        
        # If qty changed and F9 exists but wasn't explicitly flagged, check if F9 references old qty
        if fix.get("qty") is not None and item.get("f9") and fix.get("f9") is None:
            old_qty_str = str(old_qty)
            if old_qty_str in item["f9"]:
                f9_rewrite_needed.append(item)
                print(f"[qa_agent] Line {line_num}: F9 references old qty {old_qty}, marking for rewrite")
      except Exception as e:
        print(f"[qa_agent] ⚠️  Error applying correction for line {correction.get('line_num', '?')} ({correction.get('issue_type', '?')}): {type(e).__name__}: {e}")
        continue
    
    # Refresh all totals
    _refresh_totals(estimate)
    
    return f9_rewrite_needed


def _handle_missing_item(estimate: dict, fix: dict, pricelist: dict):
    """Add a missing line item to the estimate."""
    description = fix.get("description", "")
    qty = float(fix.get("qty", 0))
    section_name = fix.get("section", "Dwelling Roof")
    source = fix.get("source", "added")
    
    if not description or not qty or qty <= 0:
        # Not a real missing item — likely a coverage/F9 review note
        print(f"[qa_agent] ⚠️  Missing item '{description[:60]}' has qty={qty} — treating as review note, skipping add")
        return
    
    # Lookup pricing
    pricing = lookup_price(description)
    if not pricing:
        print(f"[qa_agent] ⚠️  Pricelist miss for missing item '{description}', adding placeholder")
        unit = "EA"
        remove_rate = 0.0
        replace_rate = 0.0
        is_material = _guess_is_material(description)
        canonical_desc = description
    else:
        unit = pricing["unit"]
        remove_rate = pricing["remove"]
        replace_rate = pricing["replace"]
        is_material = pricing.get("is_material", _guess_is_material(description))
        canonical_desc = pricing["description"]
    
    math = calc_line_item(qty, remove_rate, replace_rate, is_material, False)
    
    # Find or create section
    sections = estimate.get("sections", [])
    target = None
    for s in sections:
        if section_name.lower() in s["name"].lower():
            target = s
            break
    
    if not target:
        target = {"name": section_name, "coverage": "Dwelling", "line_items": [], "totals": {}}
        # Insert before O&P
        op_idx = next((i for i, s in enumerate(sections) if s["name"].lower() in ("o&p", "overhead")), None)
        if op_idx is not None:
            sections.insert(op_idx, target)
        else:
            sections.append(target)
    
    # Next line number
    all_nums = [item.get("num", 0) for s in sections for item in s.get("line_items", [])]
    next_num = max(all_nums) + 1 if all_nums else 1
    
    # Generate basic F9 (will be rewritten in Pass 3 if needed)
    f9 = f9_left_out(canonical_desc, qty, unit, math["total"])
    
    new_item = {
        "num": next_num,
        "description": canonical_desc,
        "qty": qty,
        "unit": unit,
        "remove_rate": remove_rate,
        "replace_rate": replace_rate,
        "remove": math["remove"],
        "replace": math["replace"],
        "tax": math["tax"],
        "op": math["op"],
        "total": math["total"],
        "is_material": is_material,
        "is_bid": False,
        "source": source,
        "ins_item_num": None,
        "ins_total": 0.0,
        "f9": f9,
        "photo_anchor": canonical_desc.lower().replace(" ", "-").replace("/", "-")[:40],
        "sub_name": "",
    }
    
    # Duplicate check — skip if same description already exists in target section
    existing_descs = [item.get("description", "").lower().strip() for item in target.get("line_items", [])]
    if canonical_desc.lower().strip() in existing_descs:
        print(f"[qa_agent] ⚠️  Duplicate skip: '{canonical_desc}' already exists in '{section_name}'")
        return
    
    target["line_items"].append(new_item)
    print(f"[qa_agent] Added missing item: '{canonical_desc}' {qty} {unit} → ${math['total']:,.2f} in '{section_name}'")


def _refresh_totals(estimate: dict):
    """Recalculate all section totals and grand totals from line items."""
    refresh_totals(estimate)
    print(f"[qa_agent] Totals refreshed: RCV=${estimate.get('rcv_total', 0):,.2f}")


# ─── Pass 3: AI F9 Rewrite ────────────────────────────────────────────────────

def _rewrite_f9s(items: list, estimate: dict, pipeline_data: dict):
    """Pass 3: Rewrite F9 notes for items that need it."""
    if not items:
        print("[qa_agent] Pass 3: No F9 rewrites needed")
        return
    
    import anthropic
    
    # Build context for each item
    item_contexts = []
    ins_data = pipeline_data.get("ins_data", {})
    ins_items = ins_data.get("items", []) or ins_data.get("line_items", [])
    ev_data = pipeline_data.get("ev_data", {})
    
    for item in items:
        ctx = {
            "line_num": item["num"],
            "description": item["description"],
            "qty": item["qty"],
            "unit": item.get("unit", "EA"),
            "total": item.get("total", 0),
            "source": item.get("source", ""),
            "is_bid": item.get("is_bid", False),
            "sub_name": item.get("sub_name", ""),
            "ins_item_num": item.get("ins_item_num"),
            "ins_total": item.get("ins_total"),
            "old_f9": item.get("f9", ""),
        }
        
        # Find matching INS items for context
        matching_ins = []
        desc_words = set(item["description"].lower().split()) - {"r&r", "the", "a", "an", "of", "for", "-"}
        for ins_item in ins_items:
            ins_desc_words = set(ins_item.get("description", "").lower().split()) - {"r&r", "the", "a", "an", "of", "for", "-"}
            overlap = len(desc_words & ins_desc_words)
            if overlap >= 2 or (len(desc_words) <= 2 and overlap >= 1):
                matching_ins.append({
                    "ins_num": ins_item.get("line_number", "?"),
                    "description": ins_item.get("description", ""),
                    "qty": ins_item.get("qty", "") or ins_item.get("quantity", ""),
                    "unit": ins_item.get("unit", ""),
                })
        ctx["matching_ins_items"] = matching_ins
        item_contexts.append(ctx)
    
    prompt = f"""You are rewriting F9 notes for an insurance supplement estimate. F9 notes are justifications sent to the insurance adjuster.

## ITEMS THAT NEED F9 REWRITES
{json.dumps(item_contexts, indent=2)}

## EAGLEVIEW DATA (measurement source)
Measured SQ: {ev_data.get('roofing_summary', {}).get('measured_sq', '?')}
Suggested SQ: {ev_data.get('roofing_summary', {}).get('suggested_sq', '?')}
Waste %: {ev_data.get('roofing_summary', {}).get('suggested_waste_pct', '?')}

## F9 WRITING RULES

### HARD RULES (never break)
1. NEVER include dollar amounts except for bid items ("Our sub bid cost is $X").
2. NEVER use template placeholders ($____, XX, "Put the amount here").
3. NEVER reference internal IFC language (@ifc, @supplement, "game plan").
4. NEVER describe charges as physical objects ("damage to the additional charge").
5. Every numbered point MUST have a complete sentence.
6. Always include correct qty, unit, and INS line references where applicable.
7. Calculate the "additional" amount correctly: our qty minus INS qty = additional.

### TONE & APPROACH
- Write like a professional supplement coordinator. Factual, confident, concise.
- Use the old_f9 as a starting point when it exists, but fix issues and adapt to the updated quantities/context. Don't blindly copy — the old F9 may reference stale numbers.
- If the old F9 was bad (template placeholders, broken refs, wrong argument), write fresh.
- 3-6 sentences typical. Address the specific situation, not generic boilerplate.

### CONTEXT-SPECIFIC
- Step flashing / apron flashing: domino effect argument (tear-off disturbs existing). NOT hail damage.
- Steep charges: reference EagleView pitch distribution.
- High roof charges: reference EagleView stories.
- If carrier_notes exist on the item: argue SEPARATION, not "left out".

## OUTPUT
Return a JSON object mapping line_num → new F9 text:
{{
  "14": "The new F9 text for line 14...",
  "17": "The new F9 text for line 17..."
}}

Respond with ONLY the JSON object. No markdown, no explanation."""

    print(f"[qa_agent] Pass 3: Rewriting {len(items)} F9 note(s)...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)
    
    resp = client.messages.create(
        model=F9_MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    
    try:
        f9_map = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[qa_agent] ⚠️  Failed to parse F9 rewrite response: {e}")
        return
    
    # Apply rewrites
    item_by_num = {item["num"]: item for item in items}
    for line_str, new_f9 in f9_map.items():
        line_num = int(line_str)
        if line_num in item_by_num:
            item_by_num[line_num]["f9"] = new_f9
            print(f"[qa_agent] Line {line_num}: F9 rewritten ({len(new_f9)} chars)")
        else:
            print(f"[qa_agent] ⚠️  F9 rewrite for line {line_num} but item not in rewrite list")


# ─── Pitch helper (duplicated from estimate_builder to avoid circular imports) ─

def _pitch_to_float(pitch_str: str) -> float:
    try:
        parts = pitch_str.split("/")
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def qa_review(estimate: dict, pipeline_data: dict) -> dict:
    """
    Run full QA review on a generated estimate.
    
    Pass 1: AI finds issues
    Pass 2: Deterministic fixes + math recalc
    Pass 3: AI rewrites F9s that need updating
    
    Returns the corrected estimate (modified in place).
    """
    print("\n" + "="*60)
    print("[qa_agent] Starting QA review...")
    print("="*60)
    
    # Pass 1: AI review
    try:
        corrections = _run_qa_review(estimate, pipeline_data)
    except Exception as e:
        print(f"[qa_agent] ⚠️  Pass 1 failed ({type(e).__name__}: {e}) — skipping QA, estimate unchanged")
        return estimate
    
    if not corrections:
        print("[qa_agent] ✅ No issues found — estimate looks clean")
        return estimate
    
    # Pass 2: Apply corrections
    print(f"\n[qa_agent] Pass 2: Applying {len(corrections)} correction(s)...")
    try:
        f9_rewrite_items = _apply_corrections(estimate, corrections, pipeline_data)
    except Exception as e:
        print(f"[qa_agent] ⚠️  Pass 2 failed ({type(e).__name__}: {e}) — partial corrections may have applied")
        _refresh_totals(estimate)
        return estimate
    
    # Pass 3: Rewrite F9s
    if f9_rewrite_items:
        print(f"\n[qa_agent] Pass 3: {len(f9_rewrite_items)} F9(s) need rewriting...")
        try:
            _rewrite_f9s(f9_rewrite_items, estimate, pipeline_data)
        except Exception as e:
            print(f"[qa_agent] ⚠️  Pass 3 failed ({type(e).__name__}: {e}) — F9s may need manual review")
    
    # Final validation pass — check math on every item
    print("\n[qa_agent] Final validation...")
    errors = 0
    for section in estimate.get("sections", []):
        for item in section.get("line_items", []):
            expected = calc_line_item(
                item["qty"],
                item.get("remove_rate", 0),
                item.get("replace_rate", 0),
                item.get("is_material", True),
                item.get("is_bid", False)
            )
            for field in ["remove", "replace", "tax", "op", "total"]:
                if abs(item.get(field, 0) - expected[field]) > 0.01:
                    print(f"[qa_agent] ⚠️  Math mismatch on line {item['num']} ({item['description']}): {field} is {item[field]} but should be {expected[field]}")
                    item[field] = expected[field]
                    errors += 1
    
    if errors:
        print(f"[qa_agent] Fixed {errors} math mismatch(es) in final validation")
        _refresh_totals(estimate)
    
    print(f"\n[qa_agent] ✅ QA complete. Final RCV: ${estimate.get('rcv_total', 0):,.2f}")
    print("="*60 + "\n")
    
    return estimate


if __name__ == "__main__":
    # Standalone test: load an existing estimate.json + run QA
    if len(sys.argv) < 2:
        print("Usage: python qa_agent.py <PROJECT_PREFIX>")
        print("       Loads <prefix>_estimate.json and pipeline data, runs QA")
        sys.exit(1)
    
    prefix = sys.argv[1]
    estimate_path = Path(__file__).parent / f"{prefix}_estimate.json"
    if not estimate_path.exists():
        for f in Path(__file__).parent.glob("*_estimate.json"):
            if f.name.upper().startswith(prefix.upper()):
                estimate_path = f
                break
    
    if not estimate_path.exists():
        print(f"No estimate.json found for '{prefix}'")
        sys.exit(1)
    
    with open(estimate_path) as f:
        estimate = json.load(f)
    
    # Try to load pipeline data
    pipeline_path = Path(__file__).parent / f"{prefix}_pipeline.json"
    if pipeline_path.exists():
        with open(pipeline_path) as f:
            pipeline_data = json.load(f)
    else:
        print(f"⚠️  No pipeline data found at {pipeline_path}")
        print("Running QA with limited context (no EV/INS/pricelist validation)")
        pipeline_data = {"ev_data": {}, "ins_data": {}, "bids": [], "pricelist": {}}
    
    corrected = qa_review(estimate, pipeline_data)
    
    # Save corrected
    with open(estimate_path, "w") as f:
        json.dump(corrected, f, indent=2)
    print(f"Saved corrected estimate to {estimate_path}")
