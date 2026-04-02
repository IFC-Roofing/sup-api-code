#!/usr/bin/env python3
"""
AI-powered insurance estimate PDF parser.

Converts PDF pages to images and uses vision AI to extract structured data
from any carrier format — Xactimate, scanned documents, proprietary layouts.

Strategy: small page batches (3 pages max) for high accuracy, then a
reconciliation pass to validate and flag discrepancies. Quality over speed.

Usage:
    python3 parse_insurance.py <pdf_path> [--output file.json] [--summary] [--verbose]
    python3 parse_insurance.py <pdf_path> --provider anthropic
    python3 parse_insurance.py <pdf_path> --provider openai --model gpt-4o

Environment variables:
    ANTHROPIC_API_KEY - Anthropic Claude (recommended)
    OPENAI_API_KEY    - OpenAI
    GOOGLE_API_KEY    - Google Gemini
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF required. Install: pip3 install PyMuPDF", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow required. Install: pip3 install Pillow", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PDF → Images
# ---------------------------------------------------------------------------

def pdf_to_images(pdf_path, dpi=200, max_pages=40):
    """Convert PDF pages to PIL Images."""
    doc = fitz.open(pdf_path)
    images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    page_count = len(doc)
    doc.close()
    return images, page_count


def image_to_base64(img, fmt="JPEG", max_size=1800):
    """Resize and encode image as base64."""
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Extraction prompt — per page batch
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are an expert insurance estimate parser. Analyze these PDF page images and extract ALL structured data with maximum accuracy.

Return ONLY valid JSON matching this exact schema (no markdown, no commentary):

{
  "carrier": "string or null — insurance company name (e.g. 'UNITED SERVICES AUTOMOBILE ASSOCIATION', 'Allstate', 'State Farm')",
  "claim_number": "string or null — claim number, member number, or loss/claim ID. For USAA: combine Member Number + L/R Number (e.g. '002056103-802')",
  "policy_number": "string or null",
  "date_of_loss": "string or null",
  "estimate_date": "string or null",
  "insured_name": "string or null",
  "insured_email": "string or null — insured's email if shown",
  "property_address": "string or null",
  "type_of_loss": "string or null — e.g. 'Hail', 'Wind', 'Wind/Hail', 'Fire', etc.",
  "date_inspected": "string or null",
  "date_received": "string or null",
  "adjuster": "string or null — claim rep or estimator name",
  "sections": [
    {
      "name": "string — section/category name exactly as it appears",
      "items": [
        {
          "line_number": "integer or null — the ORIGINAL line number as printed in the estimate (e.g. 1, 2, 3... 36). Extract the exact number shown on each line. This is critical for cross-referencing.",
          "description": "string — full line item description",
          "quantity": null or float,
          "unit": "string or null (SQ, LF, SF, EA, HR, etc.)",
          "unit_price": null or float,
          "rcv": null or float,
          "depreciation": null or float,
          "non_recoverable_depreciation": null or float,
          "acv": null or float,
          "o_and_p": null or float,
          "action": "string or null (remove, replace, repair, R&R, D&R, etc.)",
          "category_code": "string or null (Xactimate code if visible e.g. RFG, HVC)",
          "is_overhead_and_profit_line": false,
          "confidence": "high or medium or low",
          "notes": "string or null — CRITICAL: capture ALL triple-asterisk (***) annotations, carrier footnotes, Material Metrix notes, and any text explaining what is BUNDLED or INCLUDED in this line item (e.g. 'includes starter course', 'includes cap shingles'). Also capture waste calculation details, auto-calculated waste %, and Options lines. These notes are essential for understanding scope bundling."
        }
      ],
      "section_totals": {
        "rcv": null or float,
        "depreciation": null or float,
        "non_recoverable_depreciation": null or float,
        "acv": null or float,
        "o_and_p": null or float
      }
    }
  ],
  "overhead_and_profit": {
    "rate": null or float,
    "applied_to": "string or null (e.g. 'all trades', 'labor only')",
    "total": null or float,
    "is_line_item": true or false,
    "is_percentage": true or false
  },
  "totals": {
    "subtotal": null or float,
    "tax": null or float,
    "overhead_and_profit": null or float,
    "depreciation": null or float,
    "non_recoverable_depreciation": null or float,
    "recoverable_depreciation": null or float,
    "acv": null or float,
    "rcv": null or float,
    "deductible": null or float,
    "net_claim": null or float
  },
  "document_type": "xactimate_estimate or carrier_estimate or appraisal or policy or unknown",
  "format_detected": "Brief description of what format/layout you see",
  "warnings": ["any issues, unclear areas, or things to verify"]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL: DEPRECIATION & NRD EXTRACTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Insurance estimates have complex depreciation columns. Extract EXACTLY:

1. COLUMN IDENTIFICATION — First, identify the column headers:
   - Common Xactimate columns: Description | Qty | Unit | Unit Cost | Tax | O&P | RCV | Age/Life | Dep% | Depreciation | ACV
   - Some carriers add: "Non-Recoverable" or "NRD" as a separate column
   - Column order can vary — read the header row carefully

2. TOTAL DEPRECIATION per line item → set "depreciation" field
   - This is the total amount being withheld (recoverable + non-recoverable)
   - Often shown in parentheses like (125.00) or as a negative
   - In Xactimate: the "Depreciation" column
   - If no depreciation on a line → null or 0

3. NON-RECOVERABLE DEPRECIATION (NRD) per line item → set "non_recoverable_depreciation"
   - This portion of depreciation will NEVER be paid — even after repairs are completed
   - Usually applied to: items at/near end of useful life, cosmetic items, pre-existing damage
   - How carriers show NRD:
     a) Separate column labeled "Non-Recoverable", "NRD", or "Non-Rec"
     b) Values in angle brackets: <125.00> means $125 is non-recoverable
     c) Asterisk (*) next to the depreciation amount with footnote explanation
     d) Line item notes like "NR" or "Non-Recoverable"
     e) ACV-only designation on the line (means full depreciation is non-recoverable)
   - If NRD cannot be determined per line, set to null and add a warning
   - NOTE: NRD ≤ total depreciation always. If NRD = total dep, the item is ACV-only.

4. ACV per line item → set "acv" field
   - ACV = RCV - total depreciation
   - Verify: rcv - depreciation ≈ acv (flag if it doesn't)

5. O&P per line item → set "o_and_p" field (if carrier shows it per line)
   - Some Xactimate formats show O&P as a column per line
   - Others show a single O&P total at the bottom — mark those lines null, use "overhead_and_profit" block

6. SECTION TOTALS — many estimates print subtotals at the end of each section
   - Capture these in "section_totals" — they help validate line item extraction
   - If a section total is visible but line items don't add up, add a warning

7. DOCUMENT-LEVEL TOTALS — capture from the summary page
   - "non_recoverable_depreciation" at document level = sum of all NRD
   - "recoverable_depreciation" = total dep - NRD (what gets released when work is done)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL: SKIP SUMMARY / RECAP PAGES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Many insurance estimates include SUMMARY or RECAP pages that repeat totals already captured in the detailed sections. These appear as:
- "PRICING SUMMARY" or "ESTIMATE SUMMARY" pages with one row per trade/category (e.g. "ROOFING $11,197.40")
- "Area:" prefixed sections that just restate area subtotals (e.g. "Area: Tarp $1,308.12")
- "Source - EagleView Roof: Main Roof" recap lines that duplicate "Source - EagleView Roof / Main Roof" detail
- Category-level one-liners like "GENERAL DEMOLITION $2,285.47" with no individual line items underneath
- Recap tables with columns like "Category | RCV | Depreciation | ACV" showing only totals

**DO NOT extract these summary/recap sections as line items.** They cause double-counting.

Only extract sections that contain INDIVIDUAL line items with descriptions, quantities, units, and unit prices.
If a section has only ONE item and that item's description matches the section name (e.g. section "ROOFING" with item "ROOFING $11,197"), it is a summary line — SKIP IT.

If you see a summary page, you MAY use it to populate the document-level "totals" block for cross-validation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GENERAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Extract EVERY individual line item — do not skip any row
- Dollar amounts: numbers only, no $ signs (e.g. 1234.56 not "$1,234.56")
- Negative depreciation: use positive numbers (125.00 not -125.00)
- If this is NOT an estimate, set document_type accordingly and explain in warnings
- If sections aren't labeled, group items by apparent category and name the section
- Parse ALL pages in the batch — data spans multiple pages
- O&P line items at the bottom of sections: set is_overhead_and_profit_line=true
- If values are partially visible or hard to read, set confidence to "medium" or "low" and note it
- Return raw JSON only, no wrapping"""


RECONCILIATION_PROMPT = """You are a quality-control auditor for insurance estimate data extraction.

I extracted line items from an insurance estimate PDF. Now verify the extraction is complete and accurate.

EXTRACTED DATA:
{extracted_json}

Review the images and check:

1. LINE ITEM COUNT — Does the count of extracted items per section match what's visible in the PDF? Flag any sections where items appear to be missing.
2. DEPRECIATION MATH — For each item with depreciation: does rcv - depreciation ≈ acv? Flag any that don't.
3. NRD IDENTIFICATION — Look specifically for non-recoverable depreciation indicators (<values>, asterisks, NRD columns, ACV-only flags). Did we capture them all?
4. SECTION TOTALS — If the PDF shows section subtotals, do our extracted line items sum to those totals? Flag discrepancies > $5.
5. DOCUMENT TOTALS — Do our section totals sum to the document totals? Flag discrepancies.
6. MISSING ITEMS — Are there any line items visible in the PDF that were not extracted?

Return ONLY valid JSON:
{
  "issues": [
    {
      "type": "missing_items | math_error | nrd_missed | total_mismatch | other",
      "section": "section name or null",
      "description": "what's wrong",
      "suggested_fix": "what to do"
    }
  ],
  "corrections": [
    {
      "section": "section name",
      "item_description": "item to correct or add",
      "field": "field name to correct",
      "current_value": null or current value,
      "correct_value": corrected value,
      "confidence": "high or medium or low"
    }
  ],
  "overall_quality": "high | medium | low",
  "summary": "1-2 sentence summary of extraction quality and main issues"
}"""


# ---------------------------------------------------------------------------
# AI Provider calls
# ---------------------------------------------------------------------------

def _call_anthropic(images_b64, prompt=None, model="claude-sonnet-4-6", verbose=False):
    from anthropic import Anthropic
    client = Anthropic()
    content = []
    for b64 in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
        })
    content.append({"type": "text", "text": prompt or EXTRACTION_PROMPT})
    if verbose:
        print(f"  → Anthropic {model}: {len(images_b64)} images", file=sys.stderr)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
    )
    return response.content[0].text


def _call_openai(images_b64, prompt=None, model="gpt-4o", verbose=False):
    from openai import OpenAI
    client = OpenAI()
    content = [{"type": "text", "text": prompt or EXTRACTION_PROMPT}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}
        })
    if verbose:
        print(f"  → OpenAI {model}: {len(images_b64)} images", file=sys.stderr)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=16000,
        temperature=0.1,
    )
    return response.choices[0].message.content


def _call_gemini(images_b64, prompt=None, model="gemini-2.0-flash", verbose=False):
    import google.generativeai as genai
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    genai.configure(api_key=api_key)
    model_obj = genai.GenerativeModel(model)
    parts = [prompt or EXTRACTION_PROMPT]
    for b64 in images_b64:
        parts.append({"mime_type": "image/jpeg", "data": base64.b64decode(b64)})
    if verbose:
        print(f"  → Gemini {model}: {len(images_b64)} images", file=sys.stderr)
    response = model_obj.generate_content(parts, generation_config={"temperature": 0.1})
    return response.text


PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", _call_anthropic),
    "openai": ("OPENAI_API_KEY", _call_openai),
    "gemini": ("GOOGLE_API_KEY", _call_gemini),
}


def detect_provider():
    for name, (env_key, _) in PROVIDERS.items():
        if os.environ.get(env_key):
            return name
    return None


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------

def _parse_json_response(text):
    """Extract JSON from AI response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end])
    return json.loads(text)


# ---------------------------------------------------------------------------
# Per-batch extraction
# ---------------------------------------------------------------------------

def _extract_batch(images_b64, provider_fn, model=None, verbose=False):
    """Extract data from a batch of page images. Returns parsed dict."""
    kwargs = {"verbose": verbose}
    if model:
        kwargs["model"] = model
    raw = provider_fn(images_b64, **kwargs)
    try:
        return _parse_json_response(raw)
    except json.JSONDecodeError as e:
        return {
            "sections": [],
            "totals": {},
            "warnings": [f"JSON parse error in batch: {e}", f"Raw (first 300): {raw[:300]}"]
        }


# ---------------------------------------------------------------------------
# Merge multiple batch results
# ---------------------------------------------------------------------------

def _merge_batches(results):
    """Merge extracted data from multiple page batches."""
    if not results:
        return {}
    if len(results) == 1:
        return results[0]

    merged = {
        "carrier": None, "claim_number": None, "policy_number": None,
        "date_of_loss": None, "estimate_date": None,
        "insured_name": None, "insured_email": None, "property_address": None,
        "type_of_loss": None, "date_inspected": None, "date_received": None,
        "adjuster": None,
        "sections": [],
        "overhead_and_profit": None,
        "totals": {},
        "document_type": None,
        "format_detected": None,
        "warnings": [],
    }

    # Track sections seen — use name as key, accumulate items
    section_map = {}

    for r in results:
        # Fill metadata from first non-null value
        for k in ("carrier", "claim_number", "policy_number", "date_of_loss",
                   "estimate_date", "insured_name", "insured_email", "property_address",
                   "type_of_loss", "date_inspected", "date_received", "adjuster",
                   "document_type", "format_detected"):
            if not merged.get(k) and r.get(k):
                merged[k] = r[k]

        # O&P block — first non-null wins
        if not merged.get("overhead_and_profit") and r.get("overhead_and_profit"):
            merged["overhead_and_profit"] = r["overhead_and_profit"]

        # Totals — last non-null wins (summary page comes last)
        for k, v in r.get("totals", {}).items():
            if v is not None:
                merged["totals"][k] = v

        # Sections — merge by name, accumulate items
        for sec in r.get("sections", []):
            name = sec.get("name", "Unknown")
            if name not in section_map:
                section_map[name] = {
                    "name": name,
                    "items": [],
                    "section_totals": sec.get("section_totals") or {}
                }
            section_map[name]["items"].extend(sec.get("items", []))
            # Section totals — last batch to provide them wins
            if sec.get("section_totals"):
                section_map[name]["section_totals"] = sec["section_totals"]

        merged["warnings"].extend(r.get("warnings", []))

    merged["sections"] = list(section_map.values())
    return merged


# ---------------------------------------------------------------------------
# Reconciliation pass
# ---------------------------------------------------------------------------

def _reconcile(extracted, images_b64, provider_fn, model=None, verbose=False):
    """
    Second AI pass: validate extraction quality, flag issues, apply corrections.
    Returns updated extracted dict with corrections applied and issues logged.
    """
    if verbose:
        print("\n[reconcile] Running reconciliation pass...", file=sys.stderr)

    # Build compact summary for the prompt (don't send all items, just counts + totals)
    compact = {
        "sections": [
            {
                "name": s["name"],
                "item_count": len(s.get("items", [])),
                "item_rcv_sum": round(sum(i.get("rcv") or i.get("total") or 0 for i in s.get("items", [])), 2),
                "item_dep_sum": round(sum(i.get("depreciation") or 0 for i in s.get("items", [])), 2),
                "item_nrd_sum": round(sum(i.get("non_recoverable_depreciation") or 0 for i in s.get("items", [])), 2),
                "section_totals": s.get("section_totals", {}),
                "sample_items": [
                    {"desc": i.get("description", ""), "rcv": i.get("rcv"), "dep": i.get("depreciation"), "nrd": i.get("non_recoverable_depreciation")}
                    for i in s.get("items", [])[:5]
                ]
            }
            for s in extracted.get("sections", [])
        ],
        "totals": extracted.get("totals", {}),
        "overhead_and_profit": extracted.get("overhead_and_profit"),
        "warnings": extracted.get("warnings", []),
    }

    prompt = RECONCILIATION_PROMPT.replace("{extracted_json}", json.dumps(compact, indent=2))

    kwargs = {"prompt": prompt, "verbose": verbose}
    if model:
        kwargs["model"] = model

    try:
        raw = provider_fn(images_b64, **kwargs)
        recon = _parse_json_response(raw)
    except Exception as e:
        extracted.setdefault("warnings", []).append(f"Reconciliation pass failed: {e}")
        return extracted

    # Log issues into warnings
    issues = recon.get("issues", [])
    for issue in issues:
        msg = f"[QC/{issue.get('type', 'issue')}] {issue.get('description', '')} — {issue.get('suggested_fix', '')}"
        if issue.get("section"):
            msg = f"[{issue['section']}] " + msg
        extracted.setdefault("warnings", []).append(msg)

    # Apply high-confidence corrections
    corrections = recon.get("corrections", [])
    applied = 0
    for corr in corrections:
        if corr.get("confidence") != "high":
            continue
        sec_name = corr.get("section")
        item_desc = corr.get("item_description", "")
        field = corr.get("field")
        correct_val = corr.get("correct_value")
        if not (sec_name and field and correct_val is not None):
            continue
        # Find matching section
        for sec in extracted.get("sections", []):
            if sec["name"] != sec_name:
                continue
            # Find matching item
            for item in sec.get("items", []):
                if item_desc.lower() in item.get("description", "").lower():
                    old = item.get(field)
                    item[field] = correct_val
                    extracted["warnings"].append(
                        f"[QC/AUTO-CORRECTED] {sec_name} | {item_desc} | {field}: {old} → {correct_val}"
                    )
                    applied += 1
                    break

    # Log reconciliation summary
    quality = recon.get("overall_quality", "unknown")
    summary = recon.get("summary", "")
    extracted["warnings"].append(f"[QC/SUMMARY] quality={quality} | {summary} | {len(issues)} issues, {applied} auto-corrected")

    if verbose:
        print(f"[reconcile] Quality: {quality} | {len(issues)} issues | {applied} auto-corrected", file=sys.stderr)

    return extracted


# ---------------------------------------------------------------------------
# Post-process: flatten items + backfill computed fields
# ---------------------------------------------------------------------------

def _postprocess(result):
    """
    Flatten items to top-level list (for backward compat), backfill rcv/acv,
    deduplicate O&P line items from sections, remove summary/recap sections.
    """
    # --- Remove summary/recap sections (safety net) ---
    filtered_sections = []
    removed_sections = []
    for sec in result.get("sections", []):
        items = sec.get("items", [])
        sec_name = sec.get("name", "")

        # Skip sections with only 1 item where the item description ≈ section name
        # These are summary recap lines (e.g. section "ROOFING" with item "ROOFING $11,197")
        if len(items) == 1:
            item_desc = items[0].get("description", "").upper().strip()
            sec_upper = sec_name.upper().strip()
            # Check if item desc is just the section name (possibly with a dollar amount)
            desc_clean = re.sub(r'[\$\d,.\s]+$', '', item_desc).strip()
            if desc_clean and (desc_clean == sec_upper or sec_upper.startswith(desc_clean) or desc_clean.startswith(sec_upper)):
                removed_sections.append(sec_name)
                continue

        # Skip "Area:" prefixed sections that restate subtotals
        if sec_name.lower().startswith("area:"):
            removed_sections.append(sec_name)
            continue

        # Skip "Recap by Room", "Recap by Category", or similar recap sections
        if re.match(r'(?i)recap\b', sec_name.strip()):
            removed_sections.append(sec_name)
            continue

        # Skip sketch/diagram sections with $0 totals (floor plan pages)
        if re.search(r'(?i)(sketch|diagram|floor\s*plan)', sec_name):
            sec_rcv = sum(i.get("rcv") or i.get("total") or 0 for i in items)
            if sec_rcv == 0:
                removed_sections.append(sec_name)
                continue

        # Skip sections that are near-duplicates of already-kept sections
        # (e.g. "Source - EagleView Roof: Main Roof" vs "Source - EagleView Roof / Main Roof")
        sec_normalized = re.sub(r'[:/\-–—]', ' ', sec_name).lower().split()
        is_dup = False
        for kept in filtered_sections:
            kept_normalized = re.sub(r'[:/\-–—]', ' ', kept.get("name", "")).lower().split()
            # If >80% word overlap and similar RCV, it's a duplicate
            if kept_normalized and sec_normalized:
                overlap = len(set(sec_normalized) & set(kept_normalized))
                max_words = max(len(sec_normalized), len(kept_normalized))
                if overlap / max_words > 0.7:
                    kept_rcv = sum(i.get("rcv") or i.get("total") or 0 for i in kept.get("items", []))
                    sec_rcv = sum(i.get("rcv") or i.get("total") or 0 for i in items)
                    if abs(kept_rcv - sec_rcv) < 1.0:  # same total = duplicate
                        removed_sections.append(sec_name)
                        is_dup = True
                        break
        if is_dup:
            continue

        filtered_sections.append(sec)

    if removed_sections:
        result.setdefault("warnings", []).append(
            f"[DEDUP] Removed {len(removed_sections)} summary/recap section(s): {', '.join(removed_sections)}"
        )
    result["sections"] = filtered_sections

    # --- Flatten items ---
    all_items = []
    for sec in result.get("sections", []):
        for item in sec.get("items", []):
            # Backward compat: keep "total" as alias for "rcv"
            if item.get("rcv") is not None and item.get("total") is None:
                item["total"] = item["rcv"]
            elif item.get("total") is not None and item.get("rcv") is None:
                item["rcv"] = item["total"]

            # Backfill ACV if missing but rcv + dep are present
            if item.get("acv") is None and item.get("rcv") and item.get("depreciation"):
                item["acv"] = round(item["rcv"] - item["depreciation"], 2)

            # Ensure NRD ≤ depreciation
            dep = item.get("depreciation") or 0
            nrd = item.get("non_recoverable_depreciation") or 0
            if nrd > dep and dep > 0:
                result.setdefault("warnings", []).append(
                    f"NRD ({nrd}) > depreciation ({dep}) on '{item.get('description', '')}' — capped"
                )
                item["non_recoverable_depreciation"] = dep

            item["section"] = sec["name"]
            all_items.append(item)

    result["items"] = all_items

    # Compute per-section NRD/dep sums if section_totals missing
    for sec in result.get("sections", []):
        st = sec.setdefault("section_totals", {})
        items = sec.get("items", [])
        if st.get("rcv") is None:
            st["rcv"] = round(sum(i.get("rcv") or i.get("total") or 0 for i in items if not i.get("is_overhead_and_profit_line")), 2)
        if st.get("depreciation") is None:
            st["depreciation"] = round(sum(i.get("depreciation") or 0 for i in items), 2)
        if st.get("non_recoverable_depreciation") is None:
            st["non_recoverable_depreciation"] = round(sum(i.get("non_recoverable_depreciation") or 0 for i in items), 2)

    return result


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_insurance_estimate(pdf_path, provider=None, model=None, verbose=False,
                              batch_size=3, skip_reconciliation=False):
    """
    Parse an insurance estimate PDF using AI vision.

    Strategy:
    - Convert PDF to images
    - Extract in small batches (batch_size pages) for high accuracy
    - Merge batch results
    - Run a reconciliation pass to validate and auto-correct
    - Return normalized dict

    Args:
        pdf_path: Path to PDF
        provider: "anthropic" | "openai" | "gemini" (auto-detected if None)
        model: Model override
        verbose: Print progress to stderr
        batch_size: Pages per extraction call (default 3 — quality over speed)
        skip_reconciliation: Skip the QC pass (faster but less reliable)
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if provider is None:
        provider = detect_provider()
    if provider is None:
        raise RuntimeError("No API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY")

    env_key, provider_fn = PROVIDERS[provider]
    if not os.environ.get(env_key):
        raise RuntimeError(f"{env_key} not set for provider '{provider}'")

    if verbose:
        print(f"\n[parse_insurance] Provider: {provider} | PDF: {pdf_path}", file=sys.stderr)

    # Step 1 — PDF → images
    if verbose:
        print("[parse_insurance] Converting PDF to images...", file=sys.stderr)
    images, page_count = pdf_to_images(pdf_path)
    if verbose:
        print(f"  {page_count} pages total, processing {len(images)}", file=sys.stderr)

    images_b64 = [image_to_base64(img) for img in images]

    # Step 2 — Extract in batches
    n_batches = (len(images_b64) + batch_size - 1) // batch_size
    if verbose:
        print(f"[parse_insurance] Extracting in {n_batches} batch(es) of ≤{batch_size} pages...", file=sys.stderr)

    batch_results = []
    t0 = time.time()
    for i in range(0, len(images_b64), batch_size):
        batch = images_b64[i:i + batch_size]
        batch_num = i // batch_size + 1
        if verbose:
            print(f"  Batch {batch_num}/{n_batches}: pages {i+1}–{min(i+batch_size, len(images_b64))}", file=sys.stderr)
        result = _extract_batch(batch, provider_fn, model=model, verbose=verbose)
        batch_results.append(result)
        if i + batch_size < len(images_b64):
            time.sleep(0.5)  # brief pause between calls

    elapsed = time.time() - t0
    if verbose:
        print(f"[parse_insurance] Extraction done in {elapsed:.1f}s", file=sys.stderr)

    # Step 3 — Merge batches
    extracted = _merge_batches(batch_results)

    # Step 4 — Reconciliation pass (uses all page images)
    if not skip_reconciliation:
        # For reconciliation: send first 6 pages (enough to see structure + headers)
        recon_pages = images_b64[:6]
        extracted = _reconcile(extracted, recon_pages, provider_fn, model=model, verbose=verbose)

    # Step 5 — Post-process
    extracted = _postprocess(extracted)

    # Finalize metadata
    extracted["page_count"] = page_count
    extracted["_pdf_size"] = os.path.getsize(pdf_path)
    for field in ("carrier", "claim_number", "policy_number", "date_of_loss",
                  "estimate_date", "insured_name", "insured_email", "property_address",
                  "type_of_loss", "date_inspected", "date_received", "adjuster",
                  "document_type", "format_detected"):
        extracted.setdefault(field, None)
    extracted.setdefault("sections", [])
    extracted.setdefault("totals", {})
    extracted.setdefault("warnings", [])
    extracted.setdefault("overhead_and_profit", None)

    return extracted


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(result):
    print("=" * 70)
    print("INSURANCE ESTIMATE SUMMARY")
    print("=" * 70)
    print(f"Document Type:    {result.get('document_type', 'unknown')}")
    print(f"Format Detected:  {result.get('format_detected', 'N/A')}")
    print(f"Pages:            {result.get('page_count', '?')}")
    print()

    for label, key in [("Carrier", "carrier"), ("Claim #", "claim_number"),
                        ("Policy #", "policy_number"), ("Insured", "insured_name"),
                        ("Property", "property_address"), ("Date of Loss", "date_of_loss"),
                        ("Estimate Date", "estimate_date")]:
        if result.get(key):
            print(f"{label:<18}{result[key]}")
    print()

    sections = result.get("sections", [])
    items = result.get("items", [])
    total_nrd = sum(i.get("non_recoverable_depreciation") or 0 for i in items)
    total_dep = sum(i.get("depreciation") or 0 for i in items)
    print(f"Sections: {len(sections)}  |  Line Items: {len(items)}")
    print("-" * 70)
    for sec in sections:
        st = sec.get("section_totals", {})
        sec_rcv = st.get("rcv") or 0
        sec_dep = st.get("depreciation") or 0
        sec_nrd = st.get("non_recoverable_depreciation") or 0
        nrd_flag = f"  ⚠️ NRD: ${sec_nrd:,.2f}" if sec_nrd else ""
        print(f"  {sec.get('name', 'Unknown'):<35} ${sec_rcv:>12,.2f}{nrd_flag}")
    print("-" * 70)

    totals = result.get("totals", {})
    for key, label in [
        ("rcv", "RCV"),
        ("depreciation", "Total Depreciation"),
        ("non_recoverable_depreciation", "Non-Recoverable Dep."),
        ("recoverable_depreciation", "Recoverable Dep."),
        ("acv", "ACV"),
        ("overhead_and_profit", "O&P"),
        ("tax", "Tax"),
        ("subtotal", "Subtotal"),
        ("deductible", "Deductible"),
        ("net_claim", "Net Claim"),
    ]:
        val = totals.get(key)
        if val:
            flag = "  ⚠️" if key == "non_recoverable_depreciation" and val > 0 else ""
            print(f"  {label:<30} ${val:>12,.2f}{flag}")

    if total_nrd and not totals.get("non_recoverable_depreciation"):
        print(f"  {'NRD (summed from items)':<30} ${total_nrd:>12,.2f}  ⚠️")

    warnings = result.get("warnings", [])
    if warnings:
        print()
        print(f"⚠️  {len(warnings)} NOTE(S):")
        for w in warnings:
            print(f"  - {w}")

    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AI-powered insurance estimate PDF parser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 parse_insurance.py estimate.pdf --summary
  python3 parse_insurance.py estimate.pdf -o parsed.json
  python3 parse_insurance.py estimate.pdf --provider anthropic --verbose
  python3 parse_insurance.py estimate.pdf --batch-size 5 --skip-reconciliation
        """,
    )
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--summary", "-s", action="store_true", help="Print human-readable summary")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose progress output")
    parser.add_argument("--provider", choices=["anthropic", "openai", "gemini"],
                        help="AI provider (auto-detected from env if not specified)")
    parser.add_argument("--model", help="Model override")
    parser.add_argument("--batch-size", type=int, default=3,
                        help="Pages per extraction call (default: 3)")
    parser.add_argument("--skip-reconciliation", action="store_true",
                        help="Skip QC reconciliation pass (faster, less reliable)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    try:
        result = parse_insurance_estimate(
            args.pdf,
            provider=args.provider,
            model=args.model,
            verbose=args.verbose,
            batch_size=args.batch_size,
            skip_reconciliation=args.skip_reconciliation,
        )
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.summary:
        print_summary(result)
    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"JSON written to {args.output}")
    elif not args.summary:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
