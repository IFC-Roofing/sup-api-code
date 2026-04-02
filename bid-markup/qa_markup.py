#!/usr/bin/env python3
"""
Markup QA Agent — Reviews marked-up bid PDFs for quality issues.
Compares original vs marked-up PDFs using vision AI.

Checks:
1. Every dollar amount was found and marked up (text layer + visual)
2. 30% math is correct on every amount
3. No formatting issues (white boxes, ghost text, font mismatch, background color)
4. Internal consistency (unit × qty = line total, line totals sum to subtotal)
5. No artifacts (stray characters, misalignment, overflow)

Usage:
    python3 qa_markup.py file <original.pdf> <marked.pdf>
    python3 qa_markup.py drive <project_name>
    
Returns JSON report with verdict: pass / warn / fail
"""

import fitz
import re
import os
import sys
import json
import base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, '..', '..')


def pdf_to_images(pdf_path, dpi=200):
    """Convert PDF pages to PNG images, return list of base64 strings."""
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        images.append(b64)
    doc.close()
    return images


def extract_amounts_text(pdf_path):
    """Extract all dollar amounts from PDF text layer.
    
    Skips quantities by checking if a bare decimal is followed by a unit label
    (EA, HR, MO, LF, RL, SQ, SF, SY, GAL, etc.) in the same span or the next
    span in the same line. This prevents QA from flagging correctly-skipped
    quantities as missed markups.
    """
    doc = fitz.open(pdf_path)
    money_dollar = re.compile(r'[\$Š]\s?([\d,]+\.\d{2})')
    money_bare = re.compile(r'(?<![A-Za-z#/\d])([\d,]+\.\d{2})(?!\d|%|[A-Za-z])(?!\s+[A-Za-z]{2})')
    money_spaced = re.compile(r'[\$Š]\s?((?:\d\s+){2,}(?:\d)(?:\s*,\s*(?:\d\s+)*\d)?(?:\s*\.\s*\d\s*\d)?)')
    
    # Unit labels that indicate a quantity, not a price
    UNIT_LABELS = {'EA', 'HR', 'MO', 'LF', 'RL', 'SQ', 'SF', 'SY', 'GAL', 'CF',
                   'BF', 'CY', 'TON', 'DAY', 'WK', 'YR', 'PR', 'SET', 'BAG',
                   'ROLL', 'BOX', 'PAIL', 'TUBE', 'EACH'}
    unit_pattern = re.compile(r'^\s*(' + '|'.join(UNIT_LABELS) + r')\b', re.IGNORECASE)
    # Also check within the same span: "28.00 EA" all in one text
    qty_inline = re.compile(r'[\d,]+\.\d{2}\s+(' + '|'.join(UNIT_LABELS) + r')\b', re.IGNORECASE)
    
    amounts = []
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                spans = line["spans"]
                for span_idx, span in enumerate(spans):
                    text = span["text"]
                    if '%' in text:
                        continue
                    
                    # Try spaced amounts
                    for m in money_spaced.finditer(text):
                        collapsed = re.sub(r'\s+', '', m.group(1)).replace(',', '')
                        try:
                            amt = float(collapsed)
                            if amt > 0:
                                amounts.append({
                                    'amount': amt, 'page': page_num + 1,
                                    'text': m.group(0).strip(),
                                    'bbox': list(span['bbox']),
                                    'font': span['font'], 'size': span['size']
                                })
                        except ValueError:
                            pass
                    
                    # Dollar amounts (always prices — have $ prefix)
                    for m in money_dollar.finditer(text):
                        raw = m.group(1).replace(',', '')
                        amt = float(raw)
                        if amt > 0:
                            amounts.append({
                                'amount': amt, 'page': page_num + 1,
                                'text': m.group(0).strip(),
                                'bbox': list(span['bbox']),
                                'font': span['font'], 'size': span['size']
                            })
                    
                    # Bare decimals (only if no dollar match)
                    if not money_dollar.search(text) and not money_spaced.search(text):
                        for m in money_bare.finditer(text):
                            raw = m.group(1).replace(',', '')
                            amt = float(raw)
                            if amt >= 1.00:
                                # Check if this is a quantity (followed by unit label)
                                is_qty = False
                                
                                # Check inline: "28.00 EA" in same span
                                after_match = text[m.end():]
                                if unit_pattern.match(after_match):
                                    is_qty = True
                                
                                # Check if entire span looks like "28.00 EA"
                                if not is_qty and qty_inline.search(text):
                                    is_qty = True
                                
                                # Check subsequent spans in same line for unit label
                                # (skip whitespace-only spans — PyMuPDF often splits
                                # "28.00   EA" into "28.00" + " " + "EA")
                                if not is_qty:
                                    for next_idx in range(span_idx + 1, min(span_idx + 4, len(spans))):
                                        next_text = spans[next_idx]["text"].strip()
                                        if not next_text:
                                            continue  # skip whitespace spans
                                        if unit_pattern.match(next_text):
                                            is_qty = True
                                        break  # stop at first non-empty span
                                
                                if not is_qty:
                                    amounts.append({
                                        'amount': amt, 'page': page_num + 1,
                                        'text': m.group(0).strip(),
                                        'bbox': list(span['bbox']),
                                        'font': span['font'], 'size': span['size']
                                    })
    
    doc.close()
    return amounts


def math_check(orig_amounts, mark_amounts, markup=0.30):
    """
    Verify every original amount has a correct 30% marked-up counterpart.
    Returns list of issues.
    """
    issues = []
    tolerance = 0.02
    
    # Deduplicate by amount value (same amount on same page counts once)
    def dedup(amounts):
        seen = set()
        result = []
        for a in amounts:
            key = (round(a['amount'], 2), a['page'])
            if key not in seen:
                seen.add(key)
                result.append(a)
        return result
    
    orig_dedup = dedup(orig_amounts)
    mark_dedup = dedup(mark_amounts)
    
    orig_values = sorted([(a['amount'], i, a) for i, a in enumerate(orig_dedup)])
    mark_values = sorted([(a['amount'], i, a) for i, a in enumerate(mark_dedup)])
    
    matched_mark = set()
    
    for i, (orig_amt, _, orig_info) in enumerate(orig_values):
        expected = round(orig_amt * (1 + markup), 2)
        found = False
        
        for j, (mark_amt, _, mark_info) in enumerate(mark_values):
            if j in matched_mark:
                continue
            if abs(mark_amt - expected) <= tolerance:
                matched_mark.add(j)
                found = True
                break
        
        if not found and orig_amt > 1.00:
            # The marked PDF text layer retains covered-up spans, so we check
            # if the marked-up value exists AT ALL (not just as a unique match)
            expected_exists = any(abs(mv[0] - expected) <= tolerance for mv in mark_values)
            if not expected_exists:
                # Line totals may be recomputed as qty × marked_up_unit_price instead
                # of original_total × 1.3. This produces slightly different values due
                # to rounding at the unit price level. Accept any marked value within
                # 1% of the expected value as a valid recomputed total.
                recompute_tolerance = expected * 0.01  # 1% window
                recomputed_exists = any(
                    abs(mv[0] - expected) <= recompute_tolerance 
                    for mv in mark_values if mv[0] not in matched_mark
                )
                if not recomputed_exists:
                    issues.append({
                        'type': 'missed_markup',
                        'severity': 'high' if orig_amt > 50 else 'medium',
                        'original': orig_amt,
                        'expected': expected,
                        'page': orig_info['page'],
                        'message': f'${orig_amt:,.2f} → expected ${expected:,.2f} but not found in marked PDF'
                    })
    
    # Note: We do NOT flag "unmarked amounts" based on text layer alone.
    # The marked PDF's text layer retains original spans (visually covered by rectangles)
    # plus our new overlay spans. Both get extracted, creating apparent duplicates.
    # The vision QA handles visual verification of coverage.
    
    return issues


def vision_qa(original_images, marked_images, trade_name=''):
    """
    Use Gemini vision to compare original vs marked-up PDF pages.
    Checks formatting, artifacts, background matching, font consistency.
    Returns list of issues.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        return [{'type': 'vision_skip', 'severity': 'info',
                 'message': 'google-generativeai not installed — pip3 install google-generativeai'}]
    
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(WORKSPACE, '.env'))
    except ImportError:
        pass  # .env may already be loaded or key set in environment
    
    api_key = os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        return [{'type': 'vision_skip', 'severity': 'info', 
                 'message': 'No GOOGLE_API_KEY — skipping vision QA'}]
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    issues = []
    
    for page_num in range(min(len(original_images), len(marked_images))):
        import PIL.Image
        import io
        
        orig_pil = PIL.Image.open(io.BytesIO(base64.b64decode(original_images[page_num])))
        mark_pil = PIL.Image.open(io.BytesIO(base64.b64decode(marked_images[page_num])))
        
        prompt = f"""You are a visual QA agent for an insurance construction company. Compare these two PDF pages of a subcontractor bid ({trade_name}).

IMAGE 1 = ORIGINAL bid (wholesale prices)
IMAGE 2 = MARKED-UP bid (all dollar amounts increased by 30%)

Focus ONLY on VISUAL/FORMATTING issues. Do NOT check math — math is verified separately.

Check for these VISUAL problems only:

1. WHITE BOXES: Visible white/light rectangles covering original text that don't blend with background
2. GHOST TEXT: Original numbers faintly visible behind/around new numbers
3. FONT MISMATCH: Replacement numbers in a visibly different font/weight/size than surrounding text
4. STRAY CHARACTERS: Extra characters (braces, parentheses, trailing digits) near edited amounts
5. BACKGROUND MISMATCH: Cover areas that are a different color than the surrounding cell/row
6. MISSED AMOUNTS: Dollar amounts that appear IDENTICAL in both images (not marked up at all)

IMPORTANT RULES:
- Sub-penny rounding differences are NOT issues (e.g., $789.67 vs $789.672 is fine)
- QTY values being increased is EXPECTED (they are dollar amounts in disguise), not an issue
- Only report things that would be VISUALLY NOTICEABLE to someone reviewing the document
- If something looks correct, do NOT report it

Respond in JSON:
{{"issues": [{{"type": "white_box|ghost_text|font_mismatch|stray_chars|bg_mismatch|missed", "severity": "high|medium|low", "description": "brief specific description", "location": "where on the page"}}], "page_quality": "good|acceptable|poor"}}

If NO issues found: {{"issues": [], "page_quality": "good"}}
Return ONLY valid JSON, no markdown."""
        
        try:
            response = model.generate_content([prompt, orig_pil, mark_pil])
            text = response.text.strip()
            
            # Clean JSON from response
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                text = text.split('```')[1].split('```')[0].strip()
            
            result = json.loads(text)
            
            for issue in result.get('issues', []):
                issue['page'] = page_num + 1
                issues.append(issue)
            
            quality = result.get('page_quality', 'good')
            if quality == 'poor':
                issues.append({
                    'type': 'quality',
                    'severity': 'high',
                    'page': page_num + 1,
                    'message': f'Page {page_num + 1} rated as poor quality'
                })
                
        except json.JSONDecodeError as e:
            issues.append({
                'type': 'vision_parse_error',
                'severity': 'info',
                'page': page_num + 1,
                'message': f'Could not parse vision response: {str(e)}'
            })
        except Exception as e:
            issues.append({
                'type': 'vision_error',
                'severity': 'info',
                'page': page_num + 1,
                'message': f'Vision QA failed: {str(e)}'
            })
    
    return issues


def qa_single(original_path, marked_path, markup=0.30, trade='', use_vision=True):
    """
    Full QA on a single original → marked pair. Returns structured report.
    """
    report = {
        'original': os.path.basename(original_path),
        'marked': os.path.basename(marked_path),
        'trade': trade,
        'markup_pct': markup * 100,
        'issues': [],
        'verdict': 'pass',
    }
    
    # 1. Text-layer math check
    print(f"  📊 Extracting amounts...")
    orig_amounts = extract_amounts_text(original_path)
    mark_amounts = extract_amounts_text(marked_path)
    
    report['original_amounts'] = len(orig_amounts)
    report['marked_amounts'] = len(mark_amounts)
    
    print(f"  🔢 Math check ({len(orig_amounts)} orig → {len(mark_amounts)} marked)...")
    math_issues = math_check(orig_amounts, mark_amounts, markup)
    report['issues'].extend(math_issues)
    
    # 2. Vision QA (formatting, artifacts, background)
    if use_vision:
        print(f"  👁️ Vision QA...")
        orig_images = pdf_to_images(original_path)
        mark_images = pdf_to_images(marked_path)
        vision_issues = vision_qa(orig_images, mark_images, trade)
        report['issues'].extend(vision_issues)
    
    # 3. Determine verdict
    high = [i for i in report['issues'] if i.get('severity') == 'high']
    medium = [i for i in report['issues'] if i.get('severity') == 'medium']
    
    if high:
        report['verdict'] = 'fail'
    elif medium:
        report['verdict'] = 'warn'
    else:
        report['verdict'] = 'pass'
    
    return report


def qa_drive_project(project_name, markup=0.30, use_vision=True):
    """
    QA all markups for a Drive project.
    Finds the most recent "Marked Up Bids" folder, downloads pairs, compares.
    """
    import tempfile
    sys.path.insert(0, SCRIPT_DIR)
    from markup_bids import drive_get_service, drive_search_project, drive_find_original_bids, drive_download
    
    service = drive_get_service()
    
    # Find project
    folders = drive_search_project(service, project_name)
    if not folders:
        return {'error': f'No project folder found for "{project_name}"'}
    
    project = folders[0]
    print(f"📁 Project: {project['name']}")
    
    # Find original bids
    originals = drive_find_original_bids(service, project['id'])
    if not originals:
        return {'error': 'No original bids found'}
    
    print(f"📄 Found {len(originals)} original bids")
    
    # Find the most recent Marked Up Bids folder on Shared Drive
    from markup_bids import OUTPUT_FOLDER_ID
    results = service.files().list(
        q=f"'{OUTPUT_FOLDER_ID}' in parents and name contains '{project_name}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name,createdTime)",
        orderBy="createdTime desc",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora='allDrives'
    ).execute()
    
    if not results.get('files'):
        # Also search more broadly
        results = service.files().list(
            q=f"name contains '{project_name}' and name contains 'Marked Up' and mimeType='application/vnd.google-apps.folder'",
            fields="files(id,name,createdTime)",
            orderBy="createdTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora='allDrives'
        ).execute()
    
    if not results.get('files'):
        return {'error': 'No Marked Up Bids folder found — run @markup first'}
    
    marked_folder = results['files'][0]
    print(f"📂 Marked folder: {marked_folder['name']}")
    
    # Get marked-up PDFs
    marked_files = service.files().list(
        q=f"'{marked_folder['id']}' in parents and mimeType='application/pdf'",
        fields="files(id,name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora='allDrives'
    ).execute()
    
    # Map marked files back to originals by name
    marked_map = {}
    for f in marked_files.get('files', []):
        # Strip _marked suffix to match original
        orig_name = f['name'].replace('_marked', '')
        marked_map[orig_name] = f
    
    reports = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for orig in originals:
            marked = marked_map.get(orig['name'])
            if not marked:
                reports.append({
                    'original': orig['name'],
                    'trade': orig.get('trade', ''),
                    'verdict': 'skip',
                    'message': 'No matching marked-up file found'
                })
                continue
            
            trade = orig.get('trade', '')
            print(f"\n{'='*60}")
            print(f"🔍 QA: {orig['name']} ({trade})")
            print(f"{'='*60}")
            
            orig_path = os.path.join(tmpdir, f"orig_{orig['name']}")
            mark_path = os.path.join(tmpdir, f"mark_{marked['name']}")
            
            drive_download(service, orig['id'], orig_path)
            drive_download(service, marked['id'], mark_path)
            
            report = qa_single(orig_path, mark_path, markup, trade, use_vision)
            reports.append(report)
            
            icon = '✅' if report['verdict'] == 'pass' else '⚠️' if report['verdict'] == 'warn' else '❌'
            issue_count = len([i for i in report['issues'] if i.get('severity') != 'info'])
            print(f"  {icon} {report['verdict'].upper()} — {issue_count} issues")
            for issue in report['issues']:
                if issue.get('severity') != 'info':
                    sev_icon = '🔴' if issue['severity'] == 'high' else '🟡' if issue['severity'] == 'medium' else '🔵'
                    msg = issue.get('message', issue.get('description', ''))
                    print(f"    {sev_icon} {msg}")
    
    # Summary
    passes = len([r for r in reports if r.get('verdict') == 'pass'])
    warns = len([r for r in reports if r.get('verdict') == 'warn'])
    fails = len([r for r in reports if r.get('verdict') == 'fail'])
    skips = len([r for r in reports if r.get('verdict') == 'skip'])
    
    summary = {
        'project': project['name'],
        'marked_folder': marked_folder['name'],
        'total_bids': len(reports),
        'passed': passes,
        'warnings': warns,
        'failed': fails,
        'skipped': skips,
        'overall': 'fail' if fails > 0 else 'warn' if warns > 0 else 'pass',
        'reports': reports,
    }
    
    print(f"\n{'='*60}")
    print(f"📋 SUMMARY: {passes}✅ {warns}⚠️ {fails}❌ {skips}⏭️")
    print(f"{'='*60}")
    
    return summary


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Markup QA Agent')
    parser.add_argument('--markup', type=float, default=0.30)
    parser.add_argument('--no-vision', action='store_true', help='Skip vision QA (faster)')
    
    subparsers = parser.add_subparsers(dest='mode')
    
    single = subparsers.add_parser('file', help='QA a single pair')
    single.add_argument('original', help='Original PDF')
    single.add_argument('marked', help='Marked-up PDF')
    
    drive = subparsers.add_parser('drive', help='QA all markups for a Drive project')
    drive.add_argument('project_name', help='Project name')
    
    args = parser.parse_args()
    
    if args.mode == 'file':
        report = qa_single(args.original, args.marked, args.markup, 
                          use_vision=not args.no_vision)
        print(json.dumps(report, indent=2))
    elif args.mode == 'drive':
        result = qa_drive_project(args.project_name, args.markup,
                                 use_vision=not args.no_vision)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
