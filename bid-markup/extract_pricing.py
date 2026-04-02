#!/usr/bin/env python3
"""
Extract line-item pricing from subcontractor bid PDFs and log to Google Sheet.
Uses spatial text analysis to match descriptions with amounts.

Usage:
    python3 extract_pricing.py --drive "<project_name>"
"""

import fitz
import re
import os
import sys
import json
from datetime import datetime

try:
    from ocr_support import is_image_pdf, ocr_page
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_ID = '13gzTw5JnF6aRntU91OThC9mvkLr6KZ2rTq63qki4jhc'


def extract_pricing_from_pdf(pdf_path):
    """
    Extract structured pricing data from a bid PDF.
    Uses Y-coordinate grouping to associate descriptions with amounts.
    """
    doc = fitz.open(pdf_path)
    
    # Check if image PDF — use OCR for text extraction
    use_ocr = HAS_OCR and is_image_pdf(pdf_path)
    if use_ocr:
        print(f"    📷 Image PDF — using OCR for extraction")
    
    full_text = ""
    for page in doc:
        if use_ocr:
            blocks = ocr_page(page)
            full_text += '\n'.join(b['text'] for b in blocks) + '\n'
        else:
            full_text += page.get_text() + "\n"
    
    result = {
        'subcontractor': '',
        'sub_phone': '',
        'sub_email': '',
        'bid_total': 0.0,
        'line_items': [],
    }
    
    # Extract contact info
    phones = re.findall(r'[\(]?\d{3}[\)]?[-.\s]?\d{3}[-.\s]?\d{4}', full_text)
    if phones:
        result['sub_phone'] = phones[0]
    emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', full_text)
    if emails:
        result['sub_email'] = emails[0]
    
    # Extract subcontractor name (first prominent text, not IFC)
    result['subcontractor'] = _extract_sub_name(full_text, pdf_path)
    
    # Process each page
    for page_num, page in enumerate(doc):
        if use_ocr:
            _extract_page_items_ocr(page, result)
        else:
            _extract_page_items(page, result)
    
    # If no line items but we have a total, add a single entry
    if not result['line_items'] and result['bid_total'] > 0:
        result['line_items'].append({
            'description': 'Full bid (no line items parsed)',
            'quantity': None,
            'unit': None,
            'unit_price': None,
            'line_total': result['bid_total'],
        })
    
    doc.close()
    return result


def _extract_page_items(page, result):
    """Extract line items from a single page using Y-coordinate grouping."""
    
    # Collect all text spans with positions
    spans = []
    for block in page.get_text("dict")["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    spans.append({
                        'text': span["text"].strip(),
                        'x': span["bbox"][0],
                        'y': round(span["bbox"][1], 0),  # Round Y to group nearby lines
                        'x2': span["bbox"][2],
                        'font': span["font"],
                        'size': span["size"],
                    })
    
    # Group spans by Y-coordinate (same row)
    rows = {}
    for span in spans:
        y = span['y']
        # Allow 3px tolerance for same row
        matched_y = None
        for existing_y in rows:
            if abs(existing_y - y) <= 3:
                matched_y = existing_y
                break
        if matched_y is not None:
            rows[matched_y].append(span)
        else:
            rows[y] = [span]
    
    # Sort rows by Y position
    sorted_ys = sorted(rows.keys())
    
    # Find the bid total
    for y in sorted_ys:
        row_text = ' '.join(s['text'] for s in rows[y])
        if re.search(r'(?i)\b(total|grand total)\b', row_text):
            amounts = re.findall(r'\$?([\d,]+\.\d{2})', row_text)
            for a in amounts:
                val = float(a.replace(',', ''))
                if val > result['bid_total']:
                    result['bid_total'] = val
    
    # Now find line items: rows that have dollar amounts but aren't total/header rows
    # Build context: for each amount row, look for description text
    
    skip_labels = re.compile(r'(?i)^(total|subtotal|sub\s*total|grand total|tax|discount|balance|deposit|payment|services? subtotal|estimate|quote|date|expires|page|terms|recipient|sent|prepared|customer|project|contact|IFC|service address|bill to|ship to|notes?|thank you|signature|approval|please|sincerely|warranty|terms and)')
    header_labels = re.compile(r'(?i)^(product|service|description|qty|quantity|unit price|amount|price|item|total|services|#)$')
    address_pattern = re.compile(r'(?i)(\d+\s+\w+\s+(blvd|drive|street|st|rd|ave|court|ct|lane|ln|parkway|pkwy|trail|road)|TX\s+\d{5}|texas\s+\d{5}|\d{5,})')
    noise_pattern = re.compile(r'(?i)(^PO\s*#|^estimate\s*/|^quote\s*#|^invoice\s*#|^phone:|^email:|^web:|\.com$|^fax:|services\s+qty|unit\s+price\s+amount|product.*service.*description)')
    
    
    prev_desc_lines = []  # Buffer for description lines above an amount row
    
    for i, y in enumerate(sorted_ys):
        row_spans = sorted(rows[y], key=lambda s: s['x'])
        row_text = ' '.join(s['text'] for s in row_spans)
        
        # Find amounts in this row
        amounts = []
        for s in row_spans:
            for m in re.finditer(r'\$?([\d,]+\.\d{2})', s['text']):
                val = float(m.group(1).replace(',', ''))
                if val > 0:
                    amounts.append(val)
        
        # Skip header rows
        if header_labels.match(row_text.strip()):
            prev_desc_lines = []
            continue
        
        # Skip total rows
        if skip_labels.match(row_text.strip()):
            prev_desc_lines = []
            continue
        
        if not amounts:
            # No amounts - this might be a description line
            text = row_text.strip()
            if text and len(text) > 1 and not re.match(r'^\d+$', text):
                if (not skip_labels.match(text) and 
                    not address_pattern.search(text) and 
                    not header_labels.match(text) and
                    not noise_pattern.search(text)):
                    prev_desc_lines.append(text)
            else:
                prev_desc_lines = []  # Reset on non-description lines
            continue
        
        # This row has amounts - build a line item
        
        # Get non-amount text from this row as description
        row_desc_parts = []
        for s in row_spans:
            text = s['text'].strip()
            # Skip if it's purely a dollar amount or number
            cleaned = re.sub(r'\$?[\d,]+\.\d{2}', '', text).strip()
            cleaned = re.sub(r'^\d+\.?\d*$', '', cleaned).strip()
            if cleaned and not header_labels.match(cleaned):
                row_desc_parts.append(cleaned)
        
        row_desc = ' '.join(row_desc_parts).strip()
        
        # Combine with buffered description lines from above
        if prev_desc_lines and not row_desc:
            description = ' '.join(prev_desc_lines)
        elif prev_desc_lines and row_desc:
            description = ' '.join(prev_desc_lines) + ' - ' + row_desc
        else:
            description = row_desc
        
        # Clean up description
        description = re.sub(r'\s+', ' ', description).strip()
        description = description.strip('|-: ')
        # Remove address fragments that snuck in
        description = re.sub(r'(?i)\d+\s+\w+\s+(blvd|drive|street|st|rd|ave|court|ct|lane|ln|pkwy|trail|road)\b[^,]*,?\s*(TX|texas)?\s*\d*', '', description).strip()
        # Remove phone/email fragments
        description = re.sub(r'(?i)phone:?\s*[\(\d][\d\s\-\(\)]+', '', description).strip()
        description = re.sub(r'[\w.+-]+@[\w.-]+\.\w+', '', description).strip()
        # Remove PO/estimate number fragments
        description = re.sub(r'(?i)(PO\s*#|estimate\s*[/#])\s*\S+', '', description).strip()
        description = description.strip('|-:* ')
        
        # Skip if this is the bid total line
        if len(amounts) == 1 and amounts[0] == result['bid_total'] and not description:
            prev_desc_lines = []
            continue
        
        # Parse quantity from row
        quantity = None
        unit = None
        
        # Check for explicit quantity spans (standalone numbers)
        for s in row_spans:
            text = s['text'].strip()
            # Quantity with unit: "74LF", "39LF", "1.0"
            qty_match = re.match(r'^(\d+\.?\d*)\s*(LF|SF|EA|SQ|pcs?|each|units?|hours?|hrs?)?$', text, re.IGNORECASE)
            if qty_match and '$' not in text and '.' not in text.replace(qty_match.group(1), ''):
                q = float(qty_match.group(1))
                if q < 10000 and q != amounts[0] if amounts else True:  # Likely a qty, not an amount
                    quantity = q
                    if qty_match.group(2):
                        unit = qty_match.group(2).upper()
        
        # Also check description for embedded qty
        if not quantity and description:
            qty_match = re.search(r'(\d+)\s*(LF|SF|EA|SQ)\b', description, re.IGNORECASE)
            if qty_match:
                quantity = float(qty_match.group(1))
                unit = qty_match.group(2).upper()
                # Remove qty from description
                description = description[:qty_match.start()] + description[qty_match.end():]
                description = description.strip(' -|')
        
        # Determine unit price vs line total
        unit_price = None
        line_total = None
        
        if len(amounts) >= 2:
            # Multiple amounts: smaller is unit price, larger is line total
            sorted_amts = sorted(amounts)
            unit_price = sorted_amts[0]
            line_total = sorted_amts[-1]
            # Verify: if qty * unit_price ≈ line_total, good
            if quantity and abs(quantity * unit_price - line_total) < 0.02:
                pass  # confirmed
        elif len(amounts) == 1:
            line_total = amounts[0]
            # If we have quantity, calculate unit price
            if quantity and quantity > 0:
                unit_price = round(line_total / quantity, 2)
        
        # Skip if line_total equals bid_total and there are other items
        if line_total == result['bid_total'] and len(result['line_items']) > 0:
            prev_desc_lines = []
            continue
        
        if description or line_total:
            result['line_items'].append({
                'description': description,
                'quantity': quantity,
                'unit': unit,
                'unit_price': unit_price,
                'line_total': line_total,
            })
        
        prev_desc_lines = []


def _extract_page_items_ocr(page, result):
    """Extract line items from an OCR'd page. Uses same logic as text version but with OCR blocks."""
    blocks = ocr_page(page)
    
    money_pat = re.compile(r'\$?([\d,]+\.\d{2})')
    skip_labels = re.compile(r'(?i)^(total|subtotal|sub\s*total|grand total|tax|discount|balance|deposit|payment|services? subtotal|estimate|quote|date|expires|page|terms|recipient|sent|prepared|customer|project|contact|IFC|service address)')
    
    prev_desc = []
    
    for block in blocks:
        text = block['text']
        amounts = []
        for m in money_pat.finditer(text):
            val = float(m.group(1).replace(',', ''))
            if val > 0:
                amounts.append(val)
        
        # Track bid total
        if re.search(r'(?i)\btotal\b', text) and amounts:
            for a in amounts:
                result['bid_total'] = max(result['bid_total'], a)
        
        if skip_labels.match(text.strip()):
            prev_desc = []
            continue
        
        if not amounts:
            if text.strip() and len(text.strip()) > 2:
                prev_desc.append(text.strip())
            continue
        
        # Build description
        desc_parts = re.sub(r'\$?[\d,]+\.\d{2}', '', text).strip()
        desc_parts = re.sub(r'^\d+\.?\d*\s*', '', desc_parts).strip()
        
        if prev_desc and not desc_parts:
            description = ' '.join(prev_desc)
        elif prev_desc:
            description = ' '.join(prev_desc) + ' - ' + desc_parts
        else:
            description = desc_parts
        
        description = re.sub(r'\s+', ' ', description).strip().strip('|-:* ')
        
        # Parse quantity
        quantity = None
        unit = None
        qty_match = re.search(r'(\d+)\s*(LF|SF|EA|SQ)\b', text, re.IGNORECASE)
        if qty_match:
            quantity = float(qty_match.group(1))
            unit = qty_match.group(2).upper()
        
        # Unit price vs total
        unit_price = None
        line_total = None
        if len(amounts) >= 2:
            sorted_amts = sorted(amounts)
            unit_price = sorted_amts[0]
            line_total = sorted_amts[-1]
        elif amounts:
            line_total = amounts[0]
            if quantity and quantity > 0:
                unit_price = round(line_total / quantity, 2)
        
        if line_total and line_total != result['bid_total']:
            result['line_items'].append({
                'description': description,
                'quantity': quantity,
                'unit': unit,
                'unit_price': unit_price,
                'line_total': line_total,
            })
        
        prev_desc = []


def _extract_sub_name(text, filename):
    """Extract subcontractor company name from bid text."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    
    skip = re.compile(r'(?i)^(estimate|quote|invoice|proposal|page|date|to:|from:|bill|ship|service|recipient|customer|project|phone|email|web|fax|address|terms|IFC|roofing|colleyville|weatherford|prepared|contact|total|subtotal|qty|quantity|unit|amount|price|description|product|sent|expires|payment|#|RECIPIENT|CONTACT|PO)')
    
    # Look for company-like names: words with capitals, LLC, Inc, Co, etc
    company_pattern = re.compile(r'(?i)(LLC|Inc|Co\b|Corp|Construction|Gutters?|Roofing|Fencing|Fence|Patio|Heating|Air|HVAC|Plumbing|Electric|Paint|Window|Door|Pros?|Property|Metal|Restoration|Exteriors|Builders?|Services)')
    
    # First pass: look for lines containing company indicators
    for line in lines[:40]:
        if company_pattern.search(line) and not re.search(r'(?i)(IFC|customer|prepared for)', line):
            if len(line) > 3 and len(line) < 80 and not re.search(r'\$', line):
                return line.strip()
    
    # Second pass: look for non-skip lines with title case
    for line in lines[:30]:
        if skip.match(line):
            continue
        if len(line) < 3 or len(line) > 60:
            continue
        if re.search(r'\$', line):
            continue
        if re.match(r'^\d', line):
            continue
        if re.match(r'^[a-z]', line):  # Skip lowercase-starting lines
            continue
        # Title case or ALL CAPS, at least 2 words
        if len(line.split()) >= 2 and re.match(r'[A-Z]', line):
            return line.strip()
    
    # Fallback from filename
    name = os.path.basename(filename).replace('.pdf', '').replace('_', ' ')
    name = re.sub(r'(?i)(BAFNA|ISBELL|estimate|invoice|bid|marked|_)', ' ', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name or 'Unknown'


def log_to_sheet(rows):
    """Append rows to the Google Sheet."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import warnings
    warnings.filterwarnings("ignore")
    
    key_path = os.path.join(SCRIPT_DIR, '..', '..', 'google-drive-key.json')
    if not os.path.exists(key_path):
        key_path = os.path.expanduser('~/.openclaw/workspace/google-drive-key.json')
    
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=['https://www.googleapis.com/auth/spreadsheets']
    ).with_subject('sup@ifcroofing.com')
    sheets = build('sheets', 'v4', credentials=creds)
    
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range='Sheet1!A:O',
        valueInputOption='USER_ENTERED',
        body={'values': rows}
    ).execute()
    
    return len(rows)


def process_drive_project(project_name):
    """Extract pricing from all bids in a Drive project and log to sheet."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import warnings, tempfile
    warnings.filterwarnings("ignore")
    
    key_path = os.path.join(SCRIPT_DIR, '..', '..', 'google-drive-key.json')
    if not os.path.exists(key_path):
        key_path = os.path.expanduser('~/.openclaw/workspace/google-drive-key.json')
    
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    ).with_subject('sup@ifcroofing.com')
    drive = build('drive', 'v3', credentials=creds)
    
    sys.path.insert(0, SCRIPT_DIR)
    from markup_bids import drive_search_project, drive_find_original_bids, drive_download
    
    folders = drive_search_project(drive, project_name)
    if not folders:
        return {'error': f'No project found for "{project_name}"'}
    
    project = folders[0]
    project_name_full = project['name']
    
    parts = project_name_full.split(' - ', 1)
    address = parts[1] if len(parts) > 1 else ''
    homeowner = parts[0] if parts else project_name_full
    
    bids = drive_find_original_bids(drive, project['id'])
    if not bids:
        return {'error': 'No PDFs found in Original Bids'}
    
    today = datetime.now().strftime('%Y-%m-%d')
    all_rows = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for bid in bids:
            pdf_path = os.path.join(tmpdir, bid['name'])
            try:
                drive_download(drive, bid['id'], pdf_path)
                pricing = extract_pricing_from_pdf(pdf_path)
                
                for item in pricing['line_items']:
                    row = [
                        today,
                        homeowner,
                        address,
                        bid['trade'],
                        pricing['subcontractor'],
                        pricing['sub_phone'],
                        pricing['sub_email'],
                        item.get('description', ''),
                        '',
                        item.get('quantity') or '',
                        item.get('unit') or '',
                        item.get('unit_price') or '',
                        item.get('line_total') or '',
                        pricing['bid_total'],
                        bid['name'],
                    ]
                    all_rows.append(row)
                
                print(f"  ✅ {bid['name']}: {len(pricing['line_items'])} items, total=${pricing['bid_total']:,.2f}")
                for item in pricing['line_items']:
                    desc = item['description'][:50] if item['description'] else '(no desc)'
                    print(f"      {desc:50s} qty={item['quantity'] or '-':>5} up=${item['unit_price'] or '-':>8} total=${item['line_total'] or '-':>10}")
                
            except Exception as e:
                print(f"  ❌ {bid['name']}: {e}")
    
    if all_rows:
        count = log_to_sheet(all_rows)
        print(f"\n📊 Logged {count} rows to pricing database")
    
    return {
        'project': project_name_full,
        'bids_processed': len(bids),
        'rows_logged': len(all_rows),
    }


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--drive':
        project = ' '.join(sys.argv[2:])
        result = process_drive_project(project)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python3 extract_pricing.py --drive \"<project_name>\"")
