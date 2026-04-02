#!/usr/bin/env python3
"""
IFC Photo Report Parser — AI-powered extraction from labeled photo report PDFs.

Two modes:
  --inventory  (default) Light pass: photo label, trade, what's visible
  --evidence   Heavy pass: damage type, severity, evidence quality, fraud flags

Usage:
    python3 parse_photos.py report.pdf --inventory
    python3 parse_photos.py report.pdf --evidence
    python3 parse_photos.py report.pdf --evidence -o parsed.json
"""

import argparse
import base64
import io
import json
import os
import sys
import tempfile

# PDF to image
try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF required. Install: pip3 install PyMuPDF", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# Load env
env_path = os.path.join(WORKSPACE, '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')


def pdf_pages_to_images(pdf_path, dpi=150, max_pages=40):
    """Convert PDF pages to PNG images, return list of (page_num, image_bytes)."""
    doc = fitz.open(pdf_path)
    images = []
    total = min(len(doc), max_pages)
    for i in range(total):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append((i + 1, img_bytes))
    doc.close()
    return images


def batch_pages(images, batch_size=8):
    """Split images into batches for API calls."""
    batches = []
    for i in range(0, len(images), batch_size):
        batches.append(images[i:i + batch_size])
    return batches


def call_gemini(prompt, image_list, model="gemini-2.0-flash", max_retries=3):
    """Call Gemini with images and text prompt, return parsed JSON."""
    import time
    try:
        import google.generativeai as genai
    except ImportError:
        print("ERROR: google-generativeai required. Install: pip3 install google-generativeai", file=sys.stderr)
        sys.exit(1)

    genai.configure(api_key=GOOGLE_API_KEY)

    # Build content parts
    parts = [prompt]
    for page_num, img_bytes in image_list:
        parts.append({
            "mime_type": "image/png",
            "data": img_bytes
        })

    model_obj = genai.GenerativeModel(model)

    for attempt in range(max_retries):
        try:
            response = model_obj.generate_content(parts, generation_config={"temperature": 0.1})
            break
        except Exception as e:
            if '429' in str(e) and attempt < max_retries - 1:
                wait = (attempt + 1) * 15
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise

    # Extract JSON from response
    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
        return {"raw_text": text, "parse_error": True}


INVENTORY_PROMPT_TEMPLATE = (
    "You are analyzing pages from a labeled construction photo report PDF.\n\n"
    "For each photo visible on these pages, extract:\n"
    '- "page": page number in the PDF (provided in order starting from PAGE_START)\n'
    '- "label": the photo\'s label/caption as written in the report\n'
    '- "trade": which trade this photo relates to. Use one of: roof, gutter, siding, fence, chimney, window, door, paint, stucco, hvac, interior, exterior, foundation, garage, deck, landscape, general, unknown\n'
    '- "description": brief plain-language description of what the photo shows (1 sentence)\n'
    '- "area": location on property if identifiable (front, rear, left, right, unknown)\n\n'
    "Return a JSON array of objects. One object per photo. If a page has multiple photos, return one object per photo.\n"
    "If a page has no photos (e.g. cover page, text-only), skip it.\n\n"
    "Return ONLY the JSON array, no other text."
)

EVIDENCE_PROMPT_TEMPLATE = (
    "You are an expert construction insurance photo analyst reviewing pages from a labeled photo report PDF.\n\n"
    "For each photo visible on these pages, extract:\n"
    '- "page": page number (pages start from PAGE_START)\n'
    '- "label": the photo\'s label/caption as written\n'
    '- "trade": one of: roof, gutter, siding, fence, chimney, window, door, paint, stucco, hvac, interior, exterior, foundation, garage, deck, landscape, general, unknown\n'
    '- "description": what the photo shows (1-2 sentences)\n'
    '- "area": location on property (front, rear, left, right, unknown)\n'
    '- "damage_type": what type of damage if visible (hail, wind, impact, water_intrusion, structural, wear, storm_debris, none_visible, unclear)\n'
    '- "damage_severity": LOW, MEDIUM, HIGH, or NONE if no damage visible\n'
    '- "evidence_quality": STRONG (clear damage, good angle, identifiable location), WEAK (blurry, far away, unclear what\'s shown), or NONE (no useful evidence)\n'
    '- "scope_items": list of construction scope items this photo could support (e.g. ["shingle replacement", "ridge cap replacement"])\n'
    '- "flags": list of any issues. Possible flags:\n'
    '  - "REUSE_RISK" — photo looks very similar to another (note which)\n'
    '  - "LOW_RESOLUTION" — too blurry/far to be useful\n'
    '  - "NO_DAMAGE_VISIBLE" — photo shows area but no clear damage\n'
    '  - "WRONG_PROPERTY_RISK" — doesn\'t match expected property style\n'
    '  - "STOCK_IMAGE_RISK" — looks like a stock/generic photo\n'
    '  - Leave empty array [] if no flags\n\n'
    "Return a JSON array of objects. One per photo. Skip pages with no photos.\n\n"
    "Return ONLY the JSON array, no other text."
)


def parse_photo_report(pdf_path, mode='inventory'):
    """Parse a photo report PDF and return structured data."""
    if not GOOGLE_API_KEY:
        print("ERROR: GOOGLE_API_KEY not set. Add to .env or environment.", file=sys.stderr)
        sys.exit(1)

    print(f"Converting PDF to images...", file=sys.stderr)
    images = pdf_pages_to_images(pdf_path)
    print(f"  {len(images)} pages", file=sys.stderr)

    if not images:
        return {"photos": [], "summary": {"total_photos": 0}}

    batches = batch_pages(images, batch_size=5)
    all_photos = []

    for i, batch in enumerate(batches):
        start_page = batch[0][0]
        print(f"  Processing batch {i+1}/{len(batches)} (pages {batch[0][0]}-{batch[-1][0]})...", file=sys.stderr)

        if mode == 'evidence':
            prompt = EVIDENCE_PROMPT_TEMPLATE.replace('PAGE_START', str(start_page))
        else:
            prompt = INVENTORY_PROMPT_TEMPLATE.replace('PAGE_START', str(start_page))

        result = call_gemini(prompt, batch)

        if isinstance(result, list):
            all_photos.extend(result)
        elif isinstance(result, dict) and not result.get('parse_error'):
            # Might be wrapped
            if 'photos' in result:
                all_photos.extend(result['photos'])
            else:
                all_photos.append(result)
        else:
            print(f"  WARNING: Could not parse batch {i+1} response", file=sys.stderr)

    # Build trade summary
    trade_counts = {}
    for p in all_photos:
        trade = p.get('trade', 'unknown')
        trade_counts[trade] = trade_counts.get(trade, 0) + 1

    summary = {
        "total_photos": len(all_photos),
        "total_pages": len(images),
        "mode": mode,
        "trades_covered": trade_counts,
    }

    if mode == 'evidence':
        # Add evidence quality summary
        quality_counts = {}
        flag_counts = {}
        for p in all_photos:
            q = p.get('evidence_quality', 'unknown')
            quality_counts[q] = quality_counts.get(q, 0) + 1
            for flag in p.get('flags', []):
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
        summary['evidence_quality'] = quality_counts
        summary['flags'] = flag_counts

    return {
        "photos": all_photos,
        "summary": summary
    }


def main():
    parser = argparse.ArgumentParser(description='Parse IFC photo report PDFs')
    parser.add_argument('pdf', help='Path to photo report PDF')
    parser.add_argument('--inventory', action='store_true', default=True,
                        help='Light mode: labels, trades, descriptions (default)')
    parser.add_argument('--evidence', action='store_true',
                        help='Heavy mode: damage analysis, evidence quality, flags')
    parser.add_argument('--output', '-o', help='Output JSON file path')
    parser.add_argument('--summary', '-s', action='store_true', help='Print summary')
    args = parser.parse_args()

    mode = 'evidence' if args.evidence else 'inventory'

    result = parse_photo_report(args.pdf, mode=mode)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Saved to {args.output}", file=sys.stderr)

    if args.summary:
        s = result['summary']
        print(f"\nPhoto Report Summary ({mode} mode):")
        print(f"  Total photos: {s['total_photos']}")
        print(f"  Total pages: {s['total_pages']}")
        print(f"  Trades covered:")
        for trade, count in sorted(s['trades_covered'].items(), key=lambda x: -x[1]):
            print(f"    {trade}: {count}")
        if mode == 'evidence' and 'evidence_quality' in s:
            print(f"  Evidence quality:")
            for q, count in s['evidence_quality'].items():
                print(f"    {q}: {count}")
            if s.get('flags'):
                print(f"  Flags:")
                for flag, count in s['flags'].items():
                    print(f"    {flag}: {count}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
