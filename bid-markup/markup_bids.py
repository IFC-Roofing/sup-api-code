#!/usr/bin/env python3
"""
IFC Roofing — Bid Markup Tool
Marks up subcontractor bid PDFs by a given percentage (default 30%).
Replaces all dollar amounts (unit prices, line items, totals) while preserving fonts.

Usage:
    python3 markup_bids.py <input_pdf> <output_pdf> [--markup 0.30]
    python3 markup_bids.py --batch <input_dir> <output_dir> [--markup 0.30]
    python3 markup_bids.py --drive <project_name> [--markup 0.30]
"""

import fitz
import re
import os
import sys
import io
import json
import base64
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(SCRIPT_DIR, "fonts")

# Map PDF font names to full font files
from font_resolver import resolve_font

try:
    from ocr_support import is_image_pdf, markup_image_pdf
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


# ─── AI Structure Detection ─────────────────────────────────────────────────
# One AI call per bid: identifies which page has the table, column roles,
# and where data values appear (as % of page width). This tells us which
# numbers are prices (mark up) vs quantities (never touch).

COLUMN_DETECT_PROMPT = """Analyze this bid/invoice PDF page. I need to know the table structure so I can mark up prices by 30%.

Return JSON with:
1. "has_table": true/false — does this page have a pricing table?
2. "is_diagram": true/false — is this primarily a diagram/sketch/drawing page?
3. "columns": array of column objects, each with:
   - "header": the column header text as shown
   - "role": one of: "description", "qty", "unit_price", "line_total", "remove_price", "replace_price", "tax_col", "skip"
   - "data_x_pct_start": where DATA values start as % of page width (0-100)
   - "data_x_pct_end": where DATA values end as % of page width (0-100)
4. "lump_sum_total": if no itemized table, just a single total amount (number or null)
5. "summary_labels": list of label texts that precede totals/subtotals (e.g. ["Subtotal", "Tax", "Total"])

IMPORTANT column role rules:
- "qty" = quantities (EA, SQ, LF, units) — NEVER mark these up
- "unit_price" = price per unit — MARK UP
- "line_total" = extended amount (qty × unit price) — RECOMPUTE after markup
- "remove_price" / "replace_price" = separate price columns — MARK UP  
- "tax_col" = tax amount — MARK UP
- "description" = text descriptions — skip
- "skip" = any other non-price column (item #, notes, etc.)

For data_x_pct_start/end: look at where the actual NUMBER VALUES are positioned, not the header text. Headers may be centered/left-aligned while numbers are right-aligned.

Return ONLY valid JSON, no markdown."""


def _page_to_base64(page):
    """Render a PDF page to base64 PNG for AI vision."""
    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    return base64.b64encode(img_bytes).decode()


def _call_ai_structure(page_b64):
    """Call Claude to detect table structure from a page image."""
    import anthropic
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        # Try .env file
        env_path = os.path.join(SCRIPT_DIR, '..', '..', '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith('ANTHROPIC_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
    
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": page_b64}},
                {"type": "text", "text": COLUMN_DETECT_PROMPT}
            ]
        }]
    )
    
    text = msg.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    return json.loads(text)


def find_font(font_name):
    """Find the best matching full font file for a PDF font name."""
    return resolve_font(font_name)


def markup_pdf(input_path, output_path, markup=0.30):
    """
    Mark up all dollar amounts in a PDF by the given percentage.
    Uses AI to detect table structure (1 call) so quantities are never touched.
    Preserves original fonts and visual appearance.
    
    Returns dict with original and new amounts for verification.
    """
    # Check if this is a scanned/image PDF
    if HAS_OCR and is_image_pdf(input_path):
        print(f"    📷 Image PDF detected — using OCR")
        return markup_image_pdf(input_path, output_path, markup)
    
    doc = fitz.open(input_path)
    changes = []
    
    # ─── Step 1: AI structure detection ───
    # Try each page to find the one with an actual pricing table.
    # Start with the page with the most text, but if AI says it's a diagram,
    # try the next pages.
    ai_structure = None
    table_page_idx = None
    
    # Sort pages by text length (descending) — most likely table page first
    page_order = sorted(range(len(doc)), key=lambda i: len(doc[i].get_text()), reverse=True)
    
    for candidate_idx in page_order:
        try:
            b64 = _page_to_base64(doc[candidate_idx])
            structure = _call_ai_structure(b64)
            if structure.get('has_table') and structure.get('columns'):
                ai_structure = structure
                table_page_idx = candidate_idx
                break
            elif structure.get('is_diagram'):
                continue  # skip diagrams, try next page
            elif structure.get('lump_sum_total'):
                ai_structure = structure
                table_page_idx = candidate_idx
                break
            else:
                # No table, no diagram — use it as fallback
                if ai_structure is None:
                    ai_structure = structure
                    table_page_idx = candidate_idx
        except Exception as e:
            print(f"    ⚠️ AI structure detection failed on page {candidate_idx}: {e}")
            continue
    
    if table_page_idx is None:
        table_page_idx = 0
    best_page_idx = table_page_idx
    
    # ─── Step 2: Build column x-ranges from AI response ───
    # These ranges tell us: is a number at position X a qty, price, or total?
    column_ranges = []  # list of (x_start, x_end, role)
    price_roles = {'unit_price', 'line_total', 'remove_price', 'replace_price', 'tax_col'}
    qty_roles = {'qty'}
    is_lump_sum = False
    is_diagram_only = False
    summary_labels = []
    
    if ai_structure:
        columns = ai_structure.get('columns', [])
        is_diagram_only = ai_structure.get('is_diagram', False)
        summary_labels = [s.lower() for s in ai_structure.get('summary_labels', [])]
        
        if columns:
            page_width = doc[best_page_idx].rect.width
            for col in columns:
                role = col.get('role', 'skip')
                x_start = col.get('data_x_pct_start', 0) / 100 * page_width
                x_end = col.get('data_x_pct_end', 100) / 100 * page_width
                column_ranges.append((x_start, x_end, role))
        elif ai_structure.get('lump_sum_total'):
            is_lump_sum = True
    
    # ─── Step 3: Find header row y-position to skip metadata above table ───
    header_y_threshold = 0
    if column_ranges:
        # Use FULL header text for matching (not just first word) to avoid
        # false matches like "United" matching "Unit"
        header_texts = []
        for col in ai_structure.get('columns', []):
            if col.get('role') != 'description' and col.get('header'):
                header_texts.append(col['header'].upper().strip())
        
        if header_texts:
            table_page = doc[best_page_idx]
            header_y_candidates = []
            for block in table_page.get_text("dict")["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    line_text = " ".join(s["text"] for s in line["spans"]).upper().strip()
                    line_y_max = max(s["bbox"][3] for s in line["spans"])
                    # Count how many column headers are found in this line
                    # Use word-boundary matching to avoid "United" → "Unit"
                    hits = 0
                    for h in header_texts:
                        # Check each span individually for exact or near-exact match
                        for span in line["spans"]:
                            st = span["text"].strip().upper()
                            if st == h or st == h.split()[0]:
                                hits += 1
                                break
                    if hits >= 2:
                        header_y_candidates.append(line_y_max)
            
            if header_y_candidates:
                # Use the FIRST (topmost) header row, not the last
                header_y_threshold = min(header_y_candidates) + 2
    
    # ─── Step 4: Classify a span's role by its x-position ───
    def _classify_span(bbox, page_idx):
        """Returns the role of a number based on its x-position in the column layout."""
        if not column_ranges:
            return None  # no AI data, fall back to regex
        
        # On the table page, skip spans above the header row
        if page_idx == best_page_idx and header_y_threshold > 0:
            if bbox.y0 < header_y_threshold:
                return 'skip'  # metadata area (estimate numbers, dates, etc.)
        
        # Find which column this span's center-x falls into
        cx = (bbox.x0 + bbox.x1) / 2
        for x_start, x_end, role in column_ranges:
            if x_start <= cx <= x_end:
                return role
        
        # Not in any column — check if it's near a price column (within 15pt tolerance)
        for x_start, x_end, role in column_ranges:
            if role in price_roles and abs(cx - x_end) < 15:
                return role
        
        return None  # unknown position
    
    # ─── Regex patterns (same as v1, but now gated by AI classification) ───
    money_with_dollar = re.compile(r'([\$Š]\s?)([\d,]+\.\d{2})')
    money_bare = re.compile(r'(?<![A-Za-z#/\d])([\d,]+\.\d{2})(?!\d|%|[A-Za-z])(?!\s+[A-Za-z]{2})')
    money_spaced = re.compile(r'([\$Š]\s?)((?:\d\s+){2,}(?:\d)(?:\s*,\s*(?:\d\s+)*\d)?(?:\s*\.\s*\d\s*\d)?)')

    def _collapse_spaced(s):
        return re.sub(r'\s+', '', s)

    def _is_summary_line(text):
        """Check if span text is or is near a summary label (Subtotal, Tax, Total)."""
        t = text.strip().lower().rstrip(':')
        return any(lbl in t for lbl in summary_labels) if summary_labels else False

    def _extract_amount(text):
        """Extract a single dollar amount from span text. Returns float or None."""
        # Try dollar-prefixed first
        m = re.search(r'[\$Š]\s?([\d,]+\.\d{2})', text)
        if m:
            return float(m.group(1).replace(',', ''))
        # Try spaced-out dollar amounts
        m = re.search(r'[\$Š]\s?((?:\d\s+){2,}(?:\d)(?:\s*,\s*(?:\d\s+)*\d)?(?:\s*\.\s*\d\s*\d)?)', text)
        if m:
            collapsed = re.sub(r'\s+', '', m.group(1))
            try:
                return float(collapsed)
            except ValueError:
                pass
        # Try bare decimal
        m = re.search(r'(?<![A-Za-z#/\d])([\d,]+\.\d{2})(?!\d|%|[A-Za-z])', text)
        if m:
            return float(m.group(1).replace(',', ''))
        # Try integer (for quantities)
        stripped = text.strip().replace(',', '')
        try:
            return float(stripped)
        except ValueError:
            return None

    def bump_text(text, bbox=None, page_idx=None, override_total=None):
        """Mark up monetary values in text. Uses AI column classification when available.
        
        If override_total is set (for line_total recomputation), replaces the amount
        with that exact value instead of multiplying by markup.
        """
        if '%' in text:
            return text
        
        role = None
        if bbox is not None and column_ranges:
            role = _classify_span(bbox, page_idx)
            # If AI says this is a qty or skip column, don't touch it
            if role in qty_roles or role == 'skip' or role == 'description':
                return text
        
        # ─── Line total override: use recomputed value instead of markup ───
        if override_total is not None and role == 'line_total':
            def replace_with_override(m):
                raw = m.group(2).replace(',', '') if m.lastindex >= 2 else m.group(1).replace(',', '')
                amt = float(raw)
                if amt == 0:
                    return m.group(0)
                changes.append({'original': amt, 'marked_up': override_total})
                if m.group(0).lstrip().startswith('$') or m.group(0).lstrip().startswith('Š'):
                    prefix = m.group(1)
                    return f"{prefix}{override_total:,.2f}"
                return f"{override_total:,.2f}"
            
            # Try dollar-prefixed first, then bare
            result = money_with_dollar.sub(replace_with_override, text)
            if result != text:
                return result
            result = money_spaced.sub(lambda m: f"${override_total:,.2f}", text)
            if result != text:
                changes.append({'original': _extract_amount(text) or 0, 'marked_up': override_total})
                return result
            if role == 'line_total':
                def replace_bare_override(m):
                    raw = m.group(1).replace(',', '')
                    amt = float(raw)
                    if amt == 0:
                        return m.group(0)
                    changes.append({'original': amt, 'marked_up': override_total})
                    return f"{override_total:,.2f}"
                return money_bare.sub(replace_bare_override, text)
            return text
        
        # Spaced-out amounts (e.g., "$ 9 2 0 0") — always mark up (these have $ prefix)
        def bump_spaced(m):
            collapsed = _collapse_spaced(m.group(2)).replace(',', '')
            try:
                amt = float(collapsed)
            except ValueError:
                return m.group(0)
            if amt == 0:
                return m.group(0)
            new_amt = round(amt * (1 + markup), 2)
            changes.append({'original': amt, 'marked_up': new_amt})
            return f"${new_amt:,.2f}"
        
        result = money_spaced.sub(bump_spaced, text)
        if result != text:
            return result
        
        # Dollar-prefixed amounts — always mark up
        def bump_dollar(m):
            raw = m.group(2).replace(',', '')
            amt = float(raw)
            if amt == 0:
                return m.group(0)
            new_amt = round(amt * (1 + markup), 2)
            changes.append({'original': amt, 'marked_up': new_amt})
            return f"${new_amt:,.2f}"
        
        result = money_with_dollar.sub(bump_dollar, text)
        if result != text:
            return result
        
        # Bare decimal numbers — ONLY mark up if AI says it's a price column
        # This is the key fix: without AI info, we skip bare numbers entirely
        # to avoid marking up quantities
        if role and role in price_roles:
            def bump_bare(m):
                raw = m.group(1).replace(',', '')
                amt = float(raw)
                if amt == 0:
                    return m.group(0)
                new_amt = round(amt * (1 + markup), 2)
                changes.append({'original': amt, 'marked_up': new_amt})
                return f"{new_amt:,.2f}"
            return money_bare.sub(bump_bare, text)
        elif role is None and not column_ranges:
            # No AI data at all — fall back to bare regex (original v1 behavior)
            # but only for $-prefixed values to be safe
            pass
        
        return text

    def _sample_bg_color(page, bbox):
        """
        Sample the background color immediately around a text span.
        Uses a tight margin to stay within the same visual cell/band.
        Returns (r, g, b) as floats 0-1.
        """
        try:
            from collections import Counter
            # Tight margin: just a few points beyond the text bbox
            # This keeps us in the same visual cell/band
            margin_x = max(3, bbox.width * 0.3)
            margin_y = max(2, bbox.height * 0.3)
            sample = fitz.Rect(bbox)
            sample.x0 -= margin_x
            sample.y0 -= margin_y
            sample.x1 += margin_x
            sample.y1 += margin_y
            sample = sample & page.rect
            
            clip_pix = page.get_pixmap(clip=sample, dpi=200)
            w, h = clip_pix.width, clip_pix.height
            
            if w < 3 or h < 3:
                return (1.0, 1.0, 1.0)
            
            # Sample at the horizontal edges (left of and right of the text)
            # and at the vertical center (same row as the text)
            # These points are most likely to be pure background
            samples = []
            cy = h // 2
            
            # Left edge (before the text starts)
            for x in range(0, min(4, w)):
                for dy in [-1, 0, 1]:
                    y = max(0, min(cy + dy, h - 1))
                    px = clip_pix.pixel(x, y)
                    samples.append((px[0]/255.0, px[1]/255.0, px[2]/255.0))
            
            # Right edge (after the text ends)
            for x in range(max(0, w - 4), w):
                for dy in [-1, 0, 1]:
                    y = max(0, min(cy + dy, h - 1))
                    px = clip_pix.pixel(x, y)
                    samples.append((px[0]/255.0, px[1]/255.0, px[2]/255.0))
            
            # Top and bottom edges at horizontal center
            cx = w // 2
            for y in [0, 1, h - 2, h - 1]:
                y = max(0, min(y, h - 1))
                for dx in [-2, 0, 2]:
                    x = max(0, min(cx + dx, w - 1))
                    px = clip_pix.pixel(x, y)
                    samples.append((px[0]/255.0, px[1]/255.0, px[2]/255.0))
            
            if not samples:
                return (1.0, 1.0, 1.0)
            
            # Round coarsely and pick most common
            rounded = [tuple(round(c, 1) for c in s) for s in samples]
            most_common_coarse = Counter(rounded).most_common(1)[0][0]
            
            # Average the samples near that coarse value for smoother result
            close_samples = [s for s, r in zip(samples, rounded) 
                           if all(abs(r[i] - most_common_coarse[i]) <= 0.15 for i in range(3))]
            if close_samples:
                avg = tuple(sum(c) / len(close_samples) for c in zip(*close_samples))
                return avg
            return most_common_coarse
        except Exception:
            return (1.0, 1.0, 1.0)

    # Detect hybrid PDFs (background image + text overlay)
    # In these cases, the declared font often doesn't match the visual rendering
    # because the numbers are baked into the background image
    is_hybrid = {}
    hybrid_scale = {}  # page_idx → scale factor (image pixels / page points)
    for page_idx in range(len(doc)):
        pg = doc[page_idx]
        images = pg.get_images()
        has_big_image = False
        for img in images:
            try:
                xref = img[0]
                info = doc.extract_image(xref)
                # If image covers most of the page (>50% area), it's hybrid
                if info['width'] * info['height'] > 500000:
                    has_big_image = True
                    # Calculate scale: image width / page width
                    hybrid_scale[page_idx] = info['width'] / pg.rect.width
            except:
                pass
        is_hybrid[page_idx] = has_big_image

    # Track subtotal overrides across pages (for totals that repeat on later pages)
    cross_page_overrides = {}  # original_amount → recomputed_amount

    for page_idx, page in enumerate(doc):
        # Skip diagram-only pages
        if is_diagram_only and page_idx == best_page_idx:
            continue
        
        registered = {}
        page_is_hybrid = is_hybrid.get(page_idx, False)

        blocks = page.get_text("dict")["blocks"]

        # ─── Page-wide pre-scan: group spans by visual row (y-position) ───
        # PDF tables often put qty, unit_price, and line_total in separate blocks,
        # so per-line correlation fails. Group all spans by y-center across the page.
        page_recomputed_totals = {}  # (y0, y1, x0, x1) → recomputed_total
        if column_ranges:
            # Collect all spans with their role and value
            all_spans_by_y = []  # (y_center, role, value, bbox_tuple)
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for prescan_span in line["spans"]:
                        prescan_bbox = fitz.Rect(prescan_span["bbox"])
                        prescan_role = _classify_span(prescan_bbox, page_idx)
                        prescan_text = prescan_span["text"]
                        y_center = (prescan_bbox.y0 + prescan_bbox.y1) / 2
                        val = _extract_amount(prescan_text) if prescan_role in ('qty', 'unit_price', 'line_total') else None
                        all_spans_by_y.append((y_center, prescan_role, val, tuple(prescan_bbox)))

            # Group by y-center (within 4pt tolerance = same visual row)
            Y_TOL = 4
            all_spans_by_y.sort(key=lambda s: s[0])
            visual_rows = []
            current_row = []
            current_y = None
            for item in all_spans_by_y:
                y_c = item[0]
                if current_y is None or abs(y_c - current_y) <= Y_TOL:
                    current_row.append(item)
                    current_y = y_c if current_y is None else (current_y + y_c) / 2
                else:
                    if current_row:
                        visual_rows.append(current_row)
                    current_row = [item]
                    current_y = y_c
            if current_row:
                visual_rows.append(current_row)

            # For each visual row, compute recomputed total if qty + 1 unit_price + line_total
            for row in visual_rows:
                qty_val = None
                unit_prices = []
                line_total_bboxes = []
                for y_c, role, val, bbox_t in row:
                    if role == 'qty' and val is not None and val > 0:
                        qty_val = val
                    elif role == 'unit_price' and val is not None and val > 0:
                        unit_prices.append(val)
                    elif role == 'line_total' and val is not None:
                        line_total_bboxes.append(bbox_t)
                if qty_val is not None and len(unit_prices) == 1 and line_total_bboxes:
                    marked_up_price = round(unit_prices[0] * (1 + markup), 2)
                    recomputed = round(qty_val * marked_up_price, 2)
                    for bbox_t in line_total_bboxes:
                        page_recomputed_totals[bbox_t] = recomputed
            # ─── Recompute subtotals/totals as sum of recomputed line totals ───
            # Find line_total spans that have NO qty in their visual row (= summary rows)
            # and compute their override as the sum of all recomputed line totals
            if page_recomputed_totals:
                # Collect original line totals and their recomputed values (as list — dupes possible)
                orig_recomputed_pairs = []  # [(original_value, recomputed_value), ...]
                for row in visual_rows:
                    for yc, role, val, bbox_t in row:
                        if role == 'line_total' and bbox_t in page_recomputed_totals and val is not None:
                            orig_recomputed_pairs.append((val, page_recomputed_totals[bbox_t]))

                # For summary rows (line_total with no qty), check if their value
                # equals the sum of original line totals → replace with sum of recomputed
                if orig_recomputed_pairs:
                    sum_original = sum(ov for ov, _ in orig_recomputed_pairs)
                    sum_recomputed = sum(rv for _, rv in orig_recomputed_pairs)
                    for row in visual_rows:
                        qty_in_row = any(r == 'qty' and v is not None and v > 0 for _, r, v, _ in row)
                        if qty_in_row:
                            continue  # skip item rows, already handled
                        for yc, role, val, bbox_t in row:
                            if role == 'line_total' and val is not None and bbox_t not in page_recomputed_totals:
                                # Check if this is a subtotal (equals sum of line totals)
                                if abs(val - sum_original) <= 0.05:
                                    recomputed_sub = round(sum_recomputed, 2)
                                    page_recomputed_totals[bbox_t] = recomputed_sub
                                    cross_page_overrides[val] = recomputed_sub
                                # Check if it's a grand total (subtotal + tax or same as subtotal)
                                # by seeing if subtracting tax yields the subtotal
                                elif val > sum_original:
                                    diff = val - sum_original
                                    # The difference is likely tax — mark up the non-tax portion
                                    recomputed_grand = round(sum_recomputed + round(diff * (1 + markup), 2), 2)
                                    page_recomputed_totals[bbox_t] = recomputed_grand
                                    cross_page_overrides[val] = recomputed_grand

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                prev_span = None
                for span in line["spans"]:
                    text = span["text"]
                    span_bbox = fitz.Rect(span["bbox"])
                    # Look up recomputed total from page-wide pre-scan
                    span_role = _classify_span(span_bbox, page_idx) if column_ranges else None
                    bbox_key = tuple(span_bbox)
                    override = page_recomputed_totals.get(bbox_key) if span_role == 'line_total' else None
                    # Cross-page override: if this amount matches a subtotal from a previous page
                    if override is None and cross_page_overrides:
                        amt = _extract_amount(text)
                        if amt is not None:
                            for orig_amt, recomp_amt in cross_page_overrides.items():
                                if abs(amt - orig_amt) <= 0.05:
                                    override = recomp_amt
                                    break
                    new_text = bump_text(text, bbox=span_bbox, page_idx=page_idx, override_total=override)
                    if new_text == text:
                        prev_span = span
                        continue

                    # Check if previous span is a standalone "$" — if so, cover it
                    # and prepend "$" to our replacement text (the original "$" span
                    # is separate and would otherwise be left as a ghost underneath)
                    dollar_span_to_cover = None
                    if prev_span and prev_span["text"].strip() in ("$", "Š") and not new_text.startswith("$"):
                        new_text = "$" + new_text
                        dollar_span_to_cover = prev_span

                    bbox = fitz.Rect(span["bbox"])
                    font_size = span["size"]
                    color = span["color"]
                    font_name = span["font"]
                    
                    # On hybrid pages, the text layer is an invisible OCR layer
                    # behind the background image. The OCR font size and bbox are
                    # often smaller than the visual rendering.
                    # Strategy: use font_size from span as-is when it's reasonable
                    # (>= bbox height). When font_size << bbox height, the OCR
                    # metadata is unreliable — derive from bbox height instead.
                    # Save original right edge for alignment before any bbox expansion
                    orig_right = bbox.x1
                    orig_y0 = bbox.y0
                    
                    img_scale = hybrid_scale.get(page_idx, 1.0) if page_is_hybrid else 1.0
                    if page_is_hybrid and img_scale > 1.2:
                        # On hybrid PDFs, the OCR font size is an approximation that
                        # consistently underestimates the visual size of image text.
                        # Always derive font size from bbox height, which corresponds
                        # to the actual rendered text dimensions in the image.
                        # Pixel measurement shows true font ≈ 1.0-1.1× bbox height.
                        # Smaller OCR boxes underestimate more, so scale inversely:
                        # small text (bbox < 8pt) → 1.15×, large text → 1.05×
                        scale = 1.15 if bbox.height < 8 else 1.05
                        font_size = bbox.height * scale
                        # Widen the cover area to hide image text underneath.
                        # Only expand RIGHT and vertically — never expand LEFT
                        # beyond the original text start, to avoid covering
                        # adjacent colored areas (e.g. blue header next to gray total).
                        # Use background-aware vertical expansion:
                        # - Dark bg: tight (1pt) to avoid bleeding into white areas
                        # - Light bg: generous (3pt top, 2pt bottom) to fully hide
                        #   image text anti-aliasing artifacts above the OCR bbox
                        _pre_bg = _sample_bg_color(page, fitz.Rect(span["bbox"]))
                        _pre_brightness = _pre_bg[0] + _pre_bg[1] + _pre_bg[2]
                        if _pre_brightness < 2.0:
                            vert_top, vert_bot = 1, 1
                        else:
                            vert_top, vert_bot = 3, 2
                        bbox = fitz.Rect(
                            bbox.x0,          # keep original left edge
                            bbox.y0 - vert_top,
                            bbox.x1 + bbox.width * 0.15,
                            bbox.y1 + vert_bot
                        )

                    r_c = ((color >> 16) & 0xFF) / 255.0
                    g_c = ((color >> 8) & 0xFF) / 255.0
                    b_c = (color & 0xFF) / 255.0

                    # Register font if not already done
                    if font_name not in registered:
                        # First try PyMuPDF built-in fonts (metrically identical to PDF base fonts)
                        builtin_map = {
                            'courier': 'cour', 'helvetica': 'helv', 'times': 'tiro',
                            'symbol': 'symb', 'zapfdingbats': 'zadb',
                        }
                        norm_lower = font_name.lower().replace('-', '').replace(',', '').replace(' ', '')
                        builtin_name = None
                        is_bold_font = 'bold' in norm_lower or 'black' in norm_lower
                        is_italic_font = 'italic' in norm_lower or 'oblique' in norm_lower
                        is_mono = 'courier' in norm_lower or 'mono' in norm_lower
                        
                        # On hybrid pages with background images, monospace fonts are usually
                        # wrong (OCR/text layer artifact). Use sans-serif instead.
                        # Always use bold variant — rasterized image text has anti-aliasing
                        # that renders heavier than vector text at the same size.
                        if page_is_hybrid and is_mono:
                            builtin_name = 'helvb'
                        else:
                            for base, short in builtin_map.items():
                                if base in norm_lower:
                                    suffix = ''
                                    if is_bold_font and is_italic_font:
                                        suffix = 'bi'
                                    elif is_bold_font:
                                        suffix = 'bo' if short == 'tiro' else 'b'
                                    elif is_italic_font:
                                        suffix = 'it' if short == 'tiro' else 'i'
                                    builtin_name = short + suffix if suffix else short
                                    break
                        
                        if builtin_name:
                            try:
                                font_obj = fitz.Font(builtin_name)
                                registered[font_name] = (builtin_name, font_obj)
                            except:
                                registered[font_name] = None
                        
                        if font_name not in registered:
                            font_file = find_font(font_name)
                            if font_file and os.path.exists(font_file):
                                reg_name = f"sup{len(registered)}"
                                try:
                                    page.insert_font(fontname=reg_name, fontfile=font_file)
                                    font_obj = fitz.Font(fontfile=font_file)
                                    registered[font_name] = (reg_name, font_obj)
                                except:
                                    registered[font_name] = None
                            else:
                                registered[font_name] = None

                    fi = registered.get(font_name)
                    if fi:
                        use_font, font_obj = fi
                    else:
                        use_font = "helv"
                        font_obj = fitz.Font("helv")

                    # Sample the actual background color before covering
                    bg_color = _sample_bg_color(page, bbox)
                    
                    # On hybrid pages, sample the actual text color from the image.
                    # The OCR layer says black but the image text may be different.
                    if page_is_hybrid:
                        try:
                            sample_rect = fitz.Rect(span["bbox"])
                            pix_sample = page.get_pixmap(clip=sample_rect, dpi=400)
                            sw, sh = pix_sample.width, pix_sample.height
                            if sw > 2 and sh > 2:
                                # Collect center pixels
                                center_pixels = []
                                for sy in range(sh // 4, 3 * sh // 4):
                                    for sx in range(sw // 4, 3 * sw // 4):
                                        px = pix_sample.pixel(sx, sy)
                                        center_pixels.append(px[:3])
                                
                                darkest = min(center_pixels, key=lambda p: sum(p))
                                lightest = max(center_pixels, key=lambda p: sum(p))
                                
                                # Determine if bg is dark or light
                                bg_brightness = bg_color[0] + bg_color[1] + bg_color[2]
                                if bg_brightness < 1.0:
                                    # Dark background → text is the LIGHTEST pixels
                                    text_px = lightest
                                else:
                                    # Light background → text is the DARKEST pixels
                                    text_px = darkest
                                
                                # Only use if contrast with bg is reasonable
                                text_brightness = sum(text_px) / 255.0
                                if abs(text_brightness - bg_brightness) > 0.3:
                                    r_c = text_px[0] / 255.0
                                    g_c = text_px[1] / 255.0
                                    b_c = text_px[2] / 255.0
                        except Exception:
                            pass

                    # Cover old text with background-matched rectangle
                    # Expand to fully hide original text + anti-aliasing artifacts
                    # More padding for small fonts where anti-aliasing is proportionally bigger
                    pad_x = max(2, 8.0 / max(font_size, 1))
                    pad_y = max(1, 6.0 / max(font_size, 1))
                    # On hybrid pages, constrain vertical padding based on background.
                    # Dark backgrounds (gray boxes, colored cells): tight padding to
                    # avoid bleeding into adjacent white areas.
                    # Light backgrounds (white rows): normal padding is safe.
                    if page_is_hybrid:
                        bg_brightness = bg_color[0] + bg_color[1] + bg_color[2]
                        if bg_brightness < 2.0:  # dark background
                            pad_y = min(pad_y, 1.0)
                        # else: keep normal pad_y for light backgrounds
                    cover = fitz.Rect(bbox)
                    cover.x0 -= pad_x
                    cover.y0 -= pad_y
                    # On hybrid pages, extend right more to cover background image text
                    # that may extend beyond the text layer bbox
                    right_pad = pad_x * 3 if page_is_hybrid else pad_x
                    cover.x1 += right_pad
                    cover.y1 += pad_y

                    # Extend cover left to hide the standalone "$" span if present
                    if dollar_span_to_cover:
                        ds_bbox = fitz.Rect(dollar_span_to_cover["bbox"])
                        cover.x0 = min(cover.x0, ds_bbox.x0 - pad_x)
                        cover.y0 = min(cover.y0, ds_bbox.y0 - pad_y)
                        cover.y1 = max(cover.y1, ds_bbox.y1 + pad_y)
                    
                    shape = page.new_shape()
                    shape.draw_rect(cover)
                    shape.finish(color=bg_color, fill=bg_color)
                    shape.commit()

                    # Calculate text width and handle overflow
                    tw = font_obj.text_length(new_text, fontsize=font_size)
                    
                    # Position the new text first, then cover
                    orig_left = span["bbox"][0] if page_is_hybrid else bbox.x0
                    align_right = orig_right if page_is_hybrid else bbox.x1
                    orig_width = align_right - orig_left
                    
                    # If new text is significantly wider than original on hybrid pages,
                    # shrink font to fit within ~120% of original width
                    if page_is_hybrid and tw > orig_width * 1.2 and orig_width > 0:
                        max_width = orig_width * 1.2
                        font_size = font_size * (max_width / tw)
                        tw = font_obj.text_length(new_text, fontsize=font_size)
                    
                    if page_is_hybrid and tw > orig_width:
                        # New text is wider — center it on the original center point
                        orig_center = (orig_left + align_right) / 2
                        x = orig_center - tw / 2
                    else:
                        # Right-align to original right edge
                        x = align_right - tw

                    # Now expand cover to the left if new text extends beyond original bbox
                    # Use actual text x position so the cover always protects the full text
                    if x < bbox.x0:
                        extra_cover = fitz.Rect(bbox)
                        extra_cover.x0 = x - 3  # 3pt padding left of where text starts
                        extra_cover.y0 -= 0.5
                        extra_cover.x1 = bbox.x0
                        extra_cover.y1 += 0.5
                        shape2 = page.new_shape()
                        shape2.draw_rect(extra_cover)
                        shape2.finish(color=bg_color, fill=bg_color)
                        shape2.commit()
                    
                    y = (orig_y0 if page_is_hybrid else bbox.y0) + font_size * 0.82

                    page.insert_text(
                        (x, y),
                        new_text,
                        fontname=use_font,
                        fontsize=font_size,
                        color=(r_c, g_c, b_c)
                    )

                    prev_span = span

    doc.save(output_path)
    doc.close()
    return changes


def drive_get_service():
    """Get authenticated Google Drive service."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import warnings
    warnings.filterwarnings("ignore")
    
    key_path = os.path.join(SCRIPT_DIR, '..', '..', 'google-drive-key.json')
    if not os.path.exists(key_path):
        key_path = os.path.expanduser('~/.openclaw/workspace/google-drive-key.json')
    
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=['https://www.googleapis.com/auth/drive']
    ).with_subject('sup@ifcroofing.com')
    return build('drive', 'v3', credentials=creds)


def drive_search_project(service, project_name):
    """Search for a project folder by name (case-insensitive partial match)."""
    results = service.files().list(
        q=f"name contains '{project_name}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora='allDrives'
    ).execute()
    # Filter out output folders (Marked Up Bids)
    folders = [f for f in results.get('files', []) if 'Marked Up' not in f['name']]
    return folders


def drive_find_original_bids(service, project_folder_id):
    """Find the 'Original Bids' subfolder and return all PDFs from trade subfolders."""
    # Find Original Bids folder
    results = service.files().list(
        q=f"'{project_folder_id}' in parents and name='Original Bids'",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora='allDrives'
    ).execute()
    
    if not results.get('files'):
        return []
    
    ob_folder = results['files'][0]['id']
    
    # Find trade subfolders
    results = service.files().list(
        q=f"'{ob_folder}' in parents and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora='allDrives'
    ).execute()
    
    pdfs = []
    for folder in results.get('files', []):
        if folder['name'] == 'Archive':
            continue
        # Get PDFs in this trade folder
        files = service.files().list(
            q=f"'{folder['id']}' in parents and mimeType='application/pdf'",
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora='allDrives'
        ).execute()
        for f in files.get('files', []):
            pdfs.append({
                'id': f['id'],
                'name': f['name'],
                'trade': folder['name']
            })
    
    return pdfs


def _extract_company_name_from_pdf(pdf_path: str) -> str:
    """Extract sub/company name from first page of a bid PDF.
    Rule-based first; AI fallback via Claude if rule-based returns nothing.
    """
    try:
        doc = fitz.open(pdf_path)
        text = doc[0].get_text() if len(doc) > 0 else ""
        doc.close()
        if not text.strip():
            return ""

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # Pattern 1: After ESTIMATE/QUOTE/PROPOSAL/INVOICE header
        for i, line in enumerate(lines):
            if line.upper() in ("ESTIMATE", "QUOTE", "PROPOSAL", "INVOICE"):
                if i + 1 < len(lines):
                    candidate = lines[i + 1]
                    if not any(skip in candidate.upper() for skip in
                               ["IFC", "ROOFING", "RECIPIENT", "COLLEYVILLE"]):
                        return candidate.strip()

        # Pattern 2: First meaningful mixed-case line in first 10 lines
        skip_words = {"ifc", "roofing", "recipient:", "construction", "5115", "colleyville",
                      "total", "estimate", "date", "address", "service", "phone", "email",
                      "po box", "invoice", "quote", "proposal", "bill to", "ship to"}
        for line in lines[:10]:
            if line.endswith(":") or (line.isupper() and len(line.split()) <= 2):
                continue
            if len(line) > 4 and not any(s in line.lower() for s in skip_words):
                if re.search(r'[A-Z][a-z]', line):
                    return line.strip()

        # AI fallback — ask Claude for just the company name
        try:
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                client = anthropic.Anthropic(api_key=api_key)
                snippet = "\n".join(lines[:20])
                msg = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=50,
                    messages=[{
                        "role": "user",
                        "content": (
                            "What is the contractor or company name on this bid/invoice? "
                            "Reply with ONLY the company name, nothing else.\n\n"
                            f"{snippet}"
                        )
                    }]
                )
                name = msg.content[0].text.strip()
                if name and len(name) < 80:
                    return name
        except Exception:
            pass

        return ""
    except Exception:
        return ""


def _make_output_name(project_folder_name: str, company_name: str, trade: str) -> str:
    """Build output filename: ClientLastname_CompanyName_Trade.pdf"""
    # Client last name — folder format is usually LASTNAME_FIRSTNAME or Firstname Lastname
    if "_" in project_folder_name:
        last_name = project_folder_name.split("_")[0].title()
    else:
        parts = project_folder_name.strip().split()
        last_name = parts[-1].title() if parts else project_folder_name

    # Clean company name (strip special chars, collapse spaces)
    company_clean = re.sub(r'[^A-Za-z0-9 ]', '', company_name).strip()
    company_clean = re.sub(r'\s+', '', company_clean)
    if not company_clean:
        company_clean = "Sub"

    # Clean trade tag (@gutter → Gutter, @shingle_roof → ShingleRoof)
    trade_clean = trade.lstrip("@").replace("_", " ").title().replace(" ", "")
    if not trade_clean:
        trade_clean = "Trade"

    return f"{last_name}_{company_clean}_{trade_clean}.pdf"


def drive_download(service, file_id, dest_path):
    """Download a file from Drive."""
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    data = request.execute()
    with open(dest_path, 'wb') as f:
        f.write(data)
    return len(data)


def drive_upload(service, file_path, parent_folder_id, file_name=None):
    """Upload a file to Drive."""
    from googleapiclient.http import MediaFileUpload
    
    file_meta = {
        'name': file_name or os.path.basename(file_path),
        'parents': [parent_folder_id]
    }
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    f = service.files().create(
        body=file_meta, media_body=media,
        fields='id,name', supportsAllDrives=True
    ).execute()
    return f


# Legacy staging root (kept for reference, no longer used)
# STAGING_ROOT_FOLDER_ID = '1tWeZivnrRjDtZq1eG6dHu4vHkBwgMWop'

# Production routing: markups go to {Project}/Supplement/Generated Markups/


def _ensure_subfolder(service, parent_id, folder_name):
    """Find or create a subfolder. Returns folder ID."""
    q = (f"'{parent_id}' in parents and name='{folder_name}' "
         f"and mimeType='application/vnd.google-apps.folder' and trashed=false")
    resp = service.files().list(
        q=q, spaces='drive', supportsAllDrives=True,
        includeItemsFromAllDrives=True, fields='files(id, name)'
    ).execute()
    existing = resp.get('files', [])
    if existing:
        print(f"  📂 Found existing folder: {folder_name}")
        return existing[0]['id']

    meta = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id],
    }
    created = service.files().create(
        body=meta, fields='id, name', supportsAllDrives=True
    ).execute()
    print(f"  📂 Created folder: {folder_name}")
    return created['id']


def run_drive_markup(project_name, markup=0.30, run_qa=True, vision_qa=False, output_folder_id=None):
    """
    Full pipeline: search project → download bids → markup → QA → upload results.
    
    Uploads to per-project staging folder on Shared Drive:
      Generated Supplements / {Project Name} / (marked-up bids here)
    
    QA is integrated: markups are verified BEFORE uploading. If QA fails on a bid,
    it's flagged in the results but still uploaded (team can review).
    
    Args:
        project_name: Homeowner/project name to search Drive for
        markup: Markup percentage as decimal (default 0.30 = 30%)
        run_qa: Run QA checks after markup (default True)
        vision_qa: Include vision-based QA via Gemini (slower, default False)
        output_folder_id: Override staging folder (bypasses per-project folder creation)
    
    Returns summary dict with markup results and QA verdicts.
    """
    import tempfile
    
    service = drive_get_service()
    
    # Search for project — try all matching folders until one has Original Bids
    folders = drive_search_project(service, project_name)
    if not folders:
        return {'error': f'No project folder found for "{project_name}"'}
    
    project = None
    bids = []
    for folder in folders:
        found_bids = drive_find_original_bids(service, folder['id'])
        if found_bids:
            project = folder
            bids = found_bids
            break
    
    if not project:
        project = folders[0]
    if not bids:
        return {'error': f'No PDFs found in Original Bids for "{project["name"]}"'}
    
    print(f"📁 Found project: {project['name']}")
    print(f"📄 Found {len(bids)} bid PDFs")
    
    # Route to project's Supplement/Generated Markups/ folder
    if output_folder_id:
        markups_folder_id = output_folder_id
    else:
        # Find Supplement subfolder in project folder
        supp_folder_id = None
        resp = service.files().list(
            q=f"'{project['id']}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)", supportsAllDrives=True,
            includeItemsFromAllDrives=True, corpora="allDrives"
        ).execute()
        for f in resp.get("files", []):
            if "supplement" in f["name"].lower():
                supp_folder_id = f["id"]
                break
        
        if not supp_folder_id:
            return {'error': f'No Supplement folder found in project "{project["name"]}"'}
        
        # Create or find Generated Markups subfolder
        markups_folder_id = _ensure_subfolder(service, supp_folder_id, "Generated Markups")
    
    out_folder = {'name': f"{project['name']}/Supplement/Generated Markups", 'id': markups_folder_id}
    
    # Import QA if needed
    qa_func = None
    if run_qa:
        try:
            from qa_markup import qa_single
            qa_func = qa_single
        except ImportError:
            print("  ⚠️ QA module not found — skipping QA")
    
    results = []
    qa_summary = {'passed': 0, 'warned': 0, 'failed': 0}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for bid in bids:
            trade = bid.get('trade', '')
            print(f"\n  🔧 {bid['name']} ({trade})")
            
            input_path = os.path.join(tmpdir, f"input_{bid['name']}")

            try:
                # Download original first so we can read company name from it
                drive_download(service, bid['id'], input_path)

                company_name = _extract_company_name_from_pdf(input_path) or "Sub"
                output_name = _make_output_name(project['name'], company_name, trade)
                output_path = os.path.join(tmpdir, output_name)
                print(f"    📝 Output name: {output_name}")

                # Markup
                changes = markup_pdf(input_path, output_path, markup)
                
                if changes:
                    # Use the largest changed value as the "total" for reporting
                    orig_total = max(c['original'] for c in changes)
                    new_total = max(c['marked_up'] for c in changes)
                else:
                    orig_total = 0
                    new_total = 0
                
                bid_result = {
                    'name': bid['name'],
                    'trade': trade,
                    'original_total': orig_total,
                    'marked_up_total': new_total,
                    'changes': len(changes),
                    'status': 'success',
                }
                
                # QA check before upload
                if qa_func:
                    print(f"    🔍 QA checking...")
                    qa_report = qa_func(input_path, output_path, markup, trade, 
                                       use_vision=vision_qa)
                    bid_result['qa_verdict'] = qa_report['verdict']
                    bid_result['qa_issues'] = [
                        i for i in qa_report.get('issues', []) 
                        if i.get('severity') != 'info'
                    ]
                    
                    if qa_report['verdict'] == 'pass':
                        qa_summary['passed'] += 1
                        print(f"    ✅ PASS — ${orig_total:,.2f} → ${new_total:,.2f}")
                    elif qa_report['verdict'] == 'warn':
                        qa_summary['warned'] += 1
                        print(f"    ⚠️ WARN — ${orig_total:,.2f} → ${new_total:,.2f}")
                        for issue in bid_result['qa_issues']:
                            print(f"       {issue.get('message', issue.get('description', ''))}")
                    else:
                        qa_summary['failed'] += 1
                        print(f"    ❌ FAIL — ${orig_total:,.2f} → ${new_total:,.2f}")
                        for issue in bid_result['qa_issues']:
                            print(f"       {issue.get('message', issue.get('description', ''))}")
                else:
                    print(f"    ✅ ${orig_total:,.2f} → ${new_total:,.2f}")
                
                # Upload (even if QA warns/fails — team can review)
                drive_upload(service, output_path, out_folder['id'], output_name)
                results.append(bid_result)
                
            except Exception as e:
                results.append({
                    'name': bid['name'],
                    'trade': trade,
                    'status': 'error',
                    'error': str(e)
                })
                print(f"    ❌ Error: {e}")
    
    # Overall verdict
    if qa_func:
        if qa_summary['failed'] > 0:
            overall_qa = 'fail'
        elif qa_summary['warned'] > 0:
            overall_qa = 'warn'
        else:
            overall_qa = 'pass'
        
        print(f"\n{'='*50}")
        print(f"📋 QA: {qa_summary['passed']}✅ {qa_summary['warned']}⚠️ {qa_summary['failed']}❌")
        print(f"{'='*50}")
    else:
        overall_qa = 'skipped'
    
    return {
        'project': project['name'],
        'output_folder': out_folder['name'],
        'output_folder_id': out_folder['id'],
        'markup_pct': markup * 100,
        'results': results,
        'qa_overall': overall_qa,
        'qa_summary': qa_summary if qa_func else None,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='IFC Roofing Bid Markup Tool')
    parser.add_argument('--markup', type=float, default=0.30, help='Markup percentage (default: 0.30 = 30%%)')
    
    subparsers = parser.add_subparsers(dest='mode')
    
    # Single file mode
    single = subparsers.add_parser('file', help='Mark up a single PDF')
    single.add_argument('input', help='Input PDF path')
    single.add_argument('output', help='Output PDF path')
    
    # Batch mode
    batch = subparsers.add_parser('batch', help='Mark up all PDFs in a directory')
    batch.add_argument('input_dir', help='Input directory')
    batch.add_argument('output_dir', help='Output directory')
    
    # Drive mode
    drive = subparsers.add_parser('drive', help='Mark up bids from Google Drive project')
    drive.add_argument('project_name', help='Project/homeowner name to search for')
    drive.add_argument('--no-qa', action='store_true', help='Skip QA checks')
    drive.add_argument('--vision-qa', action='store_true', help='Include vision QA (slower)')
    
    args = parser.parse_args()
    
    if args.mode == 'file':
        changes = markup_pdf(args.input, args.output, args.markup)
        print(f"✅ Marked up {len(changes)} amounts by {args.markup*100:.0f}%")
        
    elif args.mode == 'batch':
        os.makedirs(args.output_dir, exist_ok=True)
        for fname in os.listdir(args.input_dir):
            if fname.lower().endswith('.pdf'):
                inp = os.path.join(args.input_dir, fname)
                out = os.path.join(args.output_dir, fname.replace('.pdf', '_marked.pdf'))
                changes = markup_pdf(inp, out, args.markup)
                print(f"✅ {fname}: {len(changes)} amounts")
                
    elif args.mode == 'drive':
        import json
        result = run_drive_markup(
            args.project_name, args.markup,
            run_qa=not args.no_qa,
            vision_qa=args.vision_qa
        )
        print(json.dumps(result, indent=2))
        
    else:
        parser.print_help()
