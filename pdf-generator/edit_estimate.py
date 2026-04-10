"""
edit_estimate.py — Edit an existing estimate.json with full math recalculation.

Every edit that touches qty, rate, or description triggers:
  1. Pricelist lookup (if description changed)
  2. calc_line_item() recalculation
  3. Section + grand total refresh
  4. F9 rewrite if needed

Usage:
  python edit_estimate.py <PROJECT_PREFIX> <edit_json>
  python edit_estimate.py <PROJECT_PREFIX> --smart "change line 11 to R&R"

Edit JSON format (array of edits):
  [
    {"action": "remove_section", "section": "Fence"},
    {"action": "remove_item", "section": "Dwelling Roof", "description_contains": "steep"},
    {"action": "update_qty", "section": "Gutters", "description_contains": "gutter", "new_qty": 150.0},
    {"action": "update_item", "section": "Dwelling Roof", "description_contains": "power attic", "new_description": "R&R Power attic vent cover only", "new_qty": 5.0},
    {"action": "clear_f9", "section": "Dwelling Roof", "description_contains": "ridge"},
    {"action": "clear_all_f9s"},
    {"action": "update_f9", "section": "Dwelling Roof", "description_contains": "starter", "new_f9": "Updated justification..."},
    {"action": "revert_to_ins", "section": "Dwelling Roof", "description_contains": "ridge cap"},
    {"action": "add_item", "section": "Dwelling Roof", "description": "R&R Drip edge", "qty": 150.0},
    {"action": "update_meta", "fields": {"claim_number": "002056103-802"}}
  ]
"""

import sys
import os
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_pipeline import lookup_price, _guess_is_material
from estimate_builder import calc_line_item, f9_left_out, TX_TAX_RATE, OP_RATE
from estimate_utils import refresh_totals

ROOT = Path(__file__).resolve().parent


# ─── Totals Refresh ───────────────────────────────────────────────────────────

def _refresh_totals(estimate: dict):
    """Recalculate ALL totals from line items up. Call after any edit."""
    refresh_totals(estimate)


def _recalc_item(item: dict):
    """Recalculate a single item's math from qty + rates."""
    math = calc_line_item(
        item.get("qty", 0),
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


def _update_item_from_pricelist(item: dict, description: str = None, skip_pricelist: bool = False):
    """Look up pricelist for a description and update item rates/unit/is_material.
    
    Skips lookup for bid items, O&P, agreed-price items, and when explicitly told to skip.
    """
    # Skip pricelist lookup for items that don't belong in Xactimate
    if skip_pricelist:
        return False
    if item.get("is_bid"):
        return False
    if item.get("source") == "bid":
        return False
    desc = description or item.get("description", "")
    desc_lower = desc.lower()
    if any(tag in desc_lower for tag in ["(bid item)", "(agreed price)", "(paid bill)"]):
        return False
    if desc_lower.strip() == "overhead and profit":
        return False
    
    pricing = lookup_price(desc)
    if pricing:
        item["remove_rate"] = pricing["remove"]
        item["replace_rate"] = pricing["replace"]
        item["unit"] = pricing["unit"]
        item["is_material"] = pricing.get("is_material", _guess_is_material(desc))
        if description:
            item["description"] = pricing["description"]  # canonical name
        return True
    return False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_estimate(project_prefix: str) -> tuple:
    """Load estimate.json for a project."""
    path = ROOT / f"{project_prefix}_estimate.json"
    if not path.exists():
        for f in ROOT.glob("*_estimate.json"):
            if f.name.upper().startswith(project_prefix.upper()):
                path = f
                break
    if not path.exists():
        raise FileNotFoundError(f"No estimate.json found for '{project_prefix}'")
    with open(path) as f:
        data = json.load(f)
    return data, path


def find_items(sections: list, section_name: str, desc_contains: str) -> list:
    """Find matching items across sections."""
    matches = []
    section_lower = section_name.lower() if section_name else None
    desc_lower = desc_contains.lower() if desc_contains else None
    
    for section in sections:
        if section_lower and section_lower not in section["name"].lower():
            continue
        for item in section.get("line_items", []):
            if desc_lower and desc_lower not in item.get("description", "").lower():
                continue
            matches.append((section, item))
    return matches


# ─── Edit Actions ─────────────────────────────────────────────────────────────

def apply_edit(estimate: dict, edit: dict) -> str:
    """Apply a single edit with full recalculation. Returns description of what was done."""
    action = edit["action"]
    sections = estimate.get("sections", [])
    
    if action == "remove_section":
        target = edit["section"].lower()
        before = len(sections)
        estimate["sections"] = [s for s in sections if target not in s["name"].lower()]
        removed = before - len(estimate["sections"])
        return f"Removed {removed} section(s) matching '{edit['section']}'" if removed else f"No section matching '{edit['section']}'"
    
    elif action == "remove_item":
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        for section, item in matches:
            section["line_items"].remove(item)
        return f"Removed {len(matches)} item(s) matching '{edit.get('description_contains', '?')}'"
    
    elif action == "update_qty":
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        count = 0
        for section, item in matches:
            old_qty = item.get("qty")
            item["qty"] = edit["new_qty"]
            _recalc_item(item)
            if item.get("source") == "ins":
                item["source"] = "adjusted"
            count += 1
            print(f"  [edit] qty {old_qty} → {edit['new_qty']}, total ${item['total']:,.2f}")
        return f"Updated qty to {edit['new_qty']} on {count} item(s) (recalculated)" if count else "No matching items"
    
    elif action == "update_item":
        """Full item update — can change description, qty, rates, everything with proper recalc."""
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        count = 0
        for section, item in matches:
            changes = []
            
            # Description change triggers pricelist lookup
            if edit.get("new_description"):
                old_desc = item["description"]
                found = _update_item_from_pricelist(item, edit["new_description"], skip_pricelist=edit.get("skip_pricelist", False))
                if found:
                    changes.append(f"desc '{old_desc}' → '{item['description']}' (rates from pricelist)")
                else:
                    item["description"] = edit["new_description"]
                    changes.append(f"desc '{old_desc}' → '{edit['new_description']}' (⚠️ no pricelist match)")
            
            # Explicit rate overrides
            if edit.get("new_remove_rate") is not None:
                item["remove_rate"] = edit["new_remove_rate"]
                changes.append(f"remove_rate → {edit['new_remove_rate']}")
            if edit.get("new_replace_rate") is not None:
                item["replace_rate"] = edit["new_replace_rate"]
                changes.append(f"replace_rate → {edit['new_replace_rate']}")
            if edit.get("new_is_material") is not None:
                item["is_material"] = edit["new_is_material"]
                changes.append(f"is_material → {edit['new_is_material']}")
            
            # Qty change
            if edit.get("new_qty") is not None:
                old_qty = item["qty"]
                item["qty"] = edit["new_qty"]
                changes.append(f"qty {old_qty} → {edit['new_qty']}")
            
            # Source update
            if edit.get("new_source"):
                item["source"] = edit["new_source"]
            elif item.get("source") == "ins" and changes:
                item["source"] = "adjusted"
            
            # F9 update
            if edit.get("new_f9") is not None:
                item["f9"] = edit["new_f9"]
                changes.append("F9 updated")
            
            # Recalculate
            _recalc_item(item)
            changes.append(f"total=${item['total']:,.2f}")
            
            print(f"  [edit] Line {item.get('num', '?')}: {', '.join(changes)}")
            count += 1
        
        return f"Updated {count} item(s)" if count else "No matching items"
    
    elif action == "clear_f9":
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        for _, item in matches:
            item["f9"] = ""
        return f"Cleared F9 on {len(matches)} item(s)"
    
    elif action == "clear_all_f9s":
        count = sum(1 for s in sections for item in s.get("line_items", []) if item.get("f9"))
        for section in sections:
            for item in section.get("line_items", []):
                item["f9"] = ""
        return f"Cleared F9 on all {count} item(s)"
    
    elif action == "update_f9":
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        for _, item in matches:
            item["f9"] = edit["new_f9"]
        return f"Updated F9 on {len(matches)} item(s)"
    
    elif action == "revert_to_ins":
        matches = find_items(sections, edit.get("section"), edit.get("description_contains"))
        count = 0
        for _, item in matches:
            if item.get("source") in ("added", "adjusted"):
                item["source"] = "ins"
                item["f9"] = ""
                count += 1
        return f"Reverted {count} item(s) to INS baseline"
    
    elif action == "add_item":
        description = edit.get("description", "")
        qty = edit.get("qty", 1.0)
        section_name = edit.get("section", "")
        custom_f9 = edit.get("f9")
        
        if not description or not section_name:
            return "add_item: missing 'description' or 'section'"
        
        pricing = lookup_price(description)
        if not pricing:
            # Placeholder for manual entry
            target = None
            for s in sections:
                if section_name.lower() in s["name"].lower():
                    target = s
                    break
            if not target:
                target = {"name": section_name, "line_items": []}
                sections.append(target)
            
            all_nums = [item.get("num", 0) for s in sections for item in s.get("line_items", [])]
            next_num = max(all_nums) + 1 if all_nums else 1
            
            target["line_items"].append({
                "num": next_num,
                "description": f"⚠️ {description} [NOT IN PRICELIST]",
                "qty": qty, "unit": "EA",
                "remove_rate": 0, "replace_rate": 0,
                "remove": 0, "replace": 0, "tax": 0, "op": 0, "total": 0,
                "is_material": False, "is_bid": False, "source": "added",
                "ins_item_num": None, "ins_total": 0,
                "f9": f"PLACEHOLDER — '{description}' not in pricelist.",
                "photo_anchor": "", "sub_name": "",
            })
            return f"⚠️ PRICELIST MISS: '{description}' — added placeholder"
        
        # Found in pricelist — build full item
        remove_rate = pricing["remove"]
        replace_rate = pricing["replace"]
        unit = pricing["unit"]
        is_material = pricing.get("is_material", _guess_is_material(description))
        
        math = calc_line_item(qty, remove_rate, replace_rate, is_material, False)
        
        # Find or create section
        target = None
        for s in sections:
            if section_name.lower() in s["name"].lower():
                target = s
                break
        if not target:
            target = {"name": section_name, "line_items": []}
            op_idx = next((i for i, s in enumerate(sections) if s["name"].lower() in ("o&p", "overhead")), None)
            if op_idx is not None:
                sections.insert(op_idx, target)
            else:
                sections.append(target)
        
        all_nums = [item.get("num", 0) for s in sections for item in s.get("line_items", [])]
        next_num = max(all_nums) + 1 if all_nums else 1
        
        f9 = custom_f9 or f9_left_out(pricing["description"], qty, unit, math["total"])
        
        target["line_items"].append({
            "num": next_num,
            "description": pricing["description"],
            "qty": qty, "unit": unit,
            "remove_rate": remove_rate, "replace_rate": replace_rate,
            "remove": math["remove"], "replace": math["replace"],
            "tax": math["tax"], "op": math["op"], "total": math["total"],
            "is_material": is_material, "is_bid": False,
            "source": "added", "ins_item_num": None, "ins_total": 0,
            "f9": f9, "photo_anchor": "", "sub_name": "",
        })
        return f"Added '{pricing['description']}' {qty} {unit} = ${math['total']:,.2f}"
    
    elif action == "update_meta":
        fields = edit.get("fields", {})
        if not fields:
            return "update_meta: missing 'fields'"
        allowed = {
            "claim_number", "policy_number", "type_of_loss", "date_of_loss",
            "date_inspected", "date_received", "date_entered", "policy_holder",
            "address", "city", "state", "zip", "client_email", "insurance_company",
            "adjuster", "deductible", "estimate_name",
        }
        updated = []
        for key, value in fields.items():
            if key not in allowed:
                updated.append(f"  skipped '{key}'")
                continue
            old = estimate.get(key, "")
            estimate[key] = str(value)
            updated.append(f"  {key}: '{old}' → '{value}'")
        return "Updated meta:\n" + "\n".join(updated)
    
    else:
        return f"Unknown action: {action}"


# ─── Smart Edit (AI-powered) ─────────────────────────────────────────────────

def smart_edit(estimate: dict, instruction: str) -> dict:
    """
    Takes a natural language instruction and figures out what edits to make.
    E.g., "change line 11 to R&R" or "drop the fence section" or "update starter to 402 LF"
    
    Returns dict with {edits: [...], results: [...]}
    """
    import anthropic
    
    # Build estimate summary for AI
    summary_lines = []
    for section in estimate.get("sections", []):
        summary_lines.append(f"\n=== {section['name']} ===")
        for item in section.get("line_items", []):
            summary_lines.append(
                f"  Line {item['num']}: {item['description']} | {item['qty']} {item.get('unit', 'EA')} | "
                f"source={item.get('source', '?')} | total=${item.get('total', 0):,.2f}"
            )
            if item.get("f9"):
                summary_lines.append(f"    F9: {item['f9'][:150]}...")
    
    prompt = f"""You are an estimate editor. Given a human instruction, generate the edit commands needed.

## CURRENT ESTIMATE
{chr(10).join(summary_lines)}

## INSTRUCTION
{instruction}

## AVAILABLE EDIT ACTIONS
- {{"action": "update_qty", "section": "...", "description_contains": "...", "new_qty": X}}
- {{"action": "update_item", "section": "...", "description_contains": "...", "new_description": "...", "new_qty": X, "new_f9": "...", "skip_pricelist": true}}
  (update_item can change any combination: description, qty, rates, F9. Pricelist is auto-looked up for new descriptions UNLESS skip_pricelist is true.)
- {{"action": "remove_item", "section": "...", "description_contains": "..."}}
- {{"action": "remove_section", "section": "..."}}
- {{"action": "add_item", "section": "...", "description": "...", "qty": X}}
- {{"action": "clear_f9", "section": "...", "description_contains": "..."}}
- {{"action": "update_f9", "section": "...", "description_contains": "...", "new_f9": "..."}}
- {{"action": "revert_to_ins", "section": "...", "description_contains": "..."}}
- {{"action": "update_meta", "fields": {{"key": "value"}}}}

## RULES
- When changing D&R → R&R: use update_item with new_description (prepend "R&R " to the base description). The system will auto-lookup pricelist rates.
- When changing qty: the system will auto-recalculate all prices. Just set new_qty.
- description_contains should be a unique substring that matches ONE item. Be specific.
- If the instruction implies F9 should change too, include new_f9 in update_item.
- For bid items, O&P, agreed-price items, or any non-Xactimate description: set "skip_pricelist": true in update_item to prevent rate corruption. Only Xactimate line items should trigger pricelist lookup.

Return a JSON array of edit commands. No markdown, no explanation."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    
    edits = json.loads(raw)
    print(f"[edit_estimate] smart_edit generated {len(edits)} edit(s):")
    for e in edits:
        print(f"  → {e.get('action', '?')}: {e.get('description_contains', e.get('description', e.get('section', '?')))}")
    
    results = []
    for edit in edits:
        result = apply_edit(estimate, edit)
        results.append(result)
        print(f"  → {result}")
    
    # Refresh totals after all edits
    _refresh_totals(estimate)
    
    return {"edits": edits, "results": results}


# ─── Batch Apply ──────────────────────────────────────────────────────────────

def apply_edits(project_prefix: str, edits: list) -> dict:
    """Apply a list of edits and save. Every edit recalculates, final refresh at end."""
    estimate, path = load_estimate(project_prefix)
    
    results = []
    for edit in edits:
        result = apply_edit(estimate, edit)
        results.append(result)
        print(f"  → {result}")
    
    # Remove empty sections
    estimate["sections"] = [s for s in estimate["sections"] if s.get("line_items")]
    
    # Final totals refresh
    _refresh_totals(estimate)
    
    # Save
    with open(path, "w") as f:
        json.dump(estimate, f, indent=2)
    
    print(f"\n✅ Saved {path.name} — RCV: ${estimate.get('rcv_total', 0):,.2f}")
    return {"path": str(path), "results": results, "rcv_total": estimate.get("rcv_total", 0)}


def rerender(project_prefix: str, skip_upload: bool = False, project_folder_id: str = None):
    """Re-render HTML → PDF → upload from existing estimate.json."""
    from html_renderer import render
    from pdf_renderer import render as render_pdf
    
    estimate_path = ROOT / f"{project_prefix}_estimate.json"
    if not estimate_path.exists():
        for f in ROOT.glob("*_estimate.json"):
            if f.name.upper().startswith(project_prefix.upper()):
                estimate_path = f
                break
    
    if not estimate_path.exists():
        raise FileNotFoundError(f"No estimate.json found for '{project_prefix}'")
    
    with open(estimate_path) as f:
        estimate = json.load(f)
    
    prefix = estimate_path.name.replace("_estimate.json", "")
    
    html_path = ROOT / f"{prefix}_estimate.html"
    render(estimate, str(html_path))
    print(f"✅ HTML: {html_path.name}")
    
    pdf_path = ROOT / f"{prefix}_IFC Supp.pdf"
    render_pdf(str(html_path), str(pdf_path))
    print(f"✅ PDF: {pdf_path.name}")
    
    if not skip_upload and project_folder_id:
        try:
            from uploader import upload
            project_name = estimate.get("project_name", prefix)
            file_id = upload(str(pdf_path), project_name=project_name, lastname=prefix, project_folder_id=project_folder_id)
            drive_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
            print(f"✅ Uploaded: {drive_link}")
            return {"pdf_path": str(pdf_path), "drive_link": drive_link, "file_id": file_id}
        except Exception as e:
            print(f"⚠️ Upload failed: {e}")
    elif not skip_upload:
        print("⚠️ No project_folder_id — skipping upload")
    
    return {"pdf_path": str(pdf_path), "drive_link": None, "file_id": None}


def run_full_edit(project_name: str, project_prefix: str, edits: list, skip_upload: bool = False) -> dict:
    """Full edit flow for API: apply edits → resolve project folder → rerender → upload → return JSON."""
    # Apply edits
    edit_result = apply_edits(project_prefix, edits)
    edit_results = edit_result.get("results", [])

    # Resolve project Drive folder for upload routing
    project_folder_id = None
    if not skip_upload:
        try:
            from data_pipeline import fetch_project, find_project_folder
            project_data = fetch_project(project_name)
            if project_data:
                project_folder_id = find_project_folder(project_data)
        except Exception as e:
            print(f"[edit_estimate] Could not resolve project folder: {e}", file=sys.stderr)

    # Re-render and upload
    render_result = rerender(project_prefix, skip_upload=skip_upload, project_folder_id=project_folder_id)

    # Calculate new RCV from edited estimate
    estimate_path = ROOT / f"{project_prefix}_estimate.json"
    total_rcv = None
    if estimate_path.exists():
        with open(estimate_path) as f:
            est = json.load(f)
        total = sum(
            item.get("qty", 0) * item.get("replace_rate", 0)
            for section in est.get("sections", [])
            for item in section.get("line_items", [])
        )
        total_rcv = f"${total:,.2f}"

    pdf_url = None
    if isinstance(render_result, dict):
        pdf_url = render_result.get("drive_link")

    return {
        "success": True,
        "pdf_url": pdf_url,
        "total_rcv": total_rcv,
        "edit_results": edit_results,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Edit an existing supplement estimate")
    parser.add_argument("prefix_or_name", help="Project prefix (e.g. MERRIFIELD) or project name")
    parser.add_argument("edits_or_flag", nargs="?", default=None, help="JSON edits array or --smart")
    parser.add_argument("--smart", action="store_true", help="Smart edit mode (natural language)")
    parser.add_argument("--api", action="store_true", help="API mode: full flow with JSON output")
    parser.add_argument("--project-name", default=None, help="Full project name (for Drive folder resolution)")
    parser.add_argument("--skip-upload", action="store_true", help="Skip Drive upload")
    parser.add_argument("instruction", nargs="*", help="Smart edit instruction (with --smart)")

    args, remaining = parser.parse_known_args()

    if args.smart:
        instruction = " ".join(args.instruction) if args.instruction else (" ".join(remaining) if remaining else "")
        if not instruction:
            print("Usage: python edit_estimate.py PREFIX --smart 'change line 11 to R&R'")
            sys.exit(1)
        prefix = args.prefix_or_name
        print(f"[edit_estimate] Smart edit: {instruction}")
        estimate, path = load_estimate(prefix)
        smart_edit(estimate, instruction)

        estimate["sections"] = [s for s in estimate["sections"] if s.get("line_items")]
        with open(path, "w") as f:
            json.dump(estimate, f, indent=2)
        print(f"\n✅ Saved {path.name}")

        print(f"\n[edit_estimate] Re-rendering...")
        rerender(prefix, skip_upload=True)
        print("\nDone.")

    elif args.api:
        # API mode: read edits from stdin, output JSON
        edits_json = sys.stdin.read().strip() if not args.edits_or_flag else args.edits_or_flag
        edits = json.loads(edits_json)
        prefix = args.prefix_or_name
        project_name = args.project_name or prefix

        result = run_full_edit(project_name, prefix, edits, skip_upload=args.skip_upload)
        print(json.dumps(result))

    else:
        # Legacy CLI mode
        if not args.edits_or_flag:
            print("Usage: python edit_estimate.py <PREFIX> '<edits_json>'")
            print("       python edit_estimate.py <PREFIX> --smart 'instruction'")
            print("       python edit_estimate.py <PREFIX> --api --project-name 'Name' < edits.json")
            sys.exit(1)
        edits = json.loads(args.edits_or_flag)
        prefix = args.prefix_or_name
        print(f"[edit_estimate] Applying {len(edits)} edit(s) to {prefix}...")
        apply_edits(prefix, edits)

        print(f"\n[edit_estimate] Re-rendering...")
        rerender(prefix, skip_upload=True)
        print("\nDone.")
