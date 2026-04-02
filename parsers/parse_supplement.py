#!/usr/bin/env python3
"""Parse IFC supplement estimate PDFs (Xactimate format) and extract structured data."""

import argparse
import json
import re
import sys
import fitz  # PyMuPDF


def parse_number(s):
    """Parse a number string with commas."""
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


def extract_text_lines(pdf_path):
    """Extract all text from PDF, stripping page headers and CONTINUED lines."""
    doc = fitz.open(pdf_path)
    all_lines = []
    for page in doc:
        text = page.get_text()
        lines = text.split("\n")
        all_lines.extend(lines)
    doc.close()
    return all_lines


def strip_page_headers(lines):
    """Remove page headers and column headers."""
    cleaned = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Skip page numbers at start of line (standalone digits like "3", "5", "8")
        if re.match(r'^\d{1,2}$', line) and i + 1 < len(lines) and lines[i+1].strip() == "IFC Contracting Solutions":
            i += 1
            continue
        # Skip page header block
        if line == "IFC Contracting Solutions" and i + 1 < len(lines):
            # Check if next lines are estimate name, date, page
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j].strip()
                if next_line.startswith("Page:") or re.match(r'\d{1,2}/\d{1,2}/\d{4}', next_line) or next_line in ("ISBELL_CHRIS",) or re.match(r'^[A-Z_]+$', next_line):
                    j += 1
                else:
                    break
            # If we skipped at least 2 lines, it's a header
            if j > i + 1:
                i = j
                continue
        # Skip CONTINUED lines
        if line.startswith("CONTINUED -"):
            i += 1
            continue
        # Skip column headers
        if line == "DESCRIPTION" or line == "QTY" or line == "REMOVE" or line == "REPLACE" or line == "TAX" or line == "O&P" or line == "TOTAL":
            i += 1
            continue
        cleaned.append(lines[i])
        i += 1
    return cleaned


def parse_metadata(lines):
    """Parse metadata from the first page."""
    meta = {}
    text = "\n".join(lines[:50])  # First ~50 lines should have metadata

    patterns = {
        "insured": r"Insured:\s*\n\s*(.+)",
        "claim_number": r"Claim Number:\s*(\S+)",
        "policy_number": r"Policy Number:\s*(\S+)",
        "type_of_loss": r"Type of Loss:\s*(\S+)",
        "date_of_loss": r"Date of Loss:\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})",
        "date_inspected": r"Date Inspected:\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})",
        "date_entered": r"Date Entered:\s*\n?\s*(\d{1,2}/\d{1,2}/\d{4})",
        "price_list": r"Price List:\s*\n?\s*(\S+)",
        "estimate_name": r"Estimate:\s*\n?\s*(\S+)",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            meta[key] = m.group(1).strip()

    # Property address - multi-line
    m = re.search(r"Property:\s*\n\s*(.+?)\n\s*(.+?)(?:\n|$)", text)
    if m:
        addr = m.group(1).strip() + ", " + m.group(2).strip()
        addr = re.sub(r',{2,}', ',', addr)  # Fix double commas
        meta["property_address"] = addr

    meta["contractor"] = "IFC Contracting Solutions"
    return meta


def parse_body(lines):
    """Parse sections, line items, and F9 notes from the body."""
    sections = []
    all_line_items = []
    current_section = None
    current_item = None
    current_f9_lines = []
    grand_totals = {}

    # Line item pattern: starts with number followed by period and TWO+ spaces
    # e.g., "1.  Tear off, haul and dispose of comp."
    # F9 sub-items use single space: "1. Xactimate total cost..."
    line_item_re = re.compile(r'^(\d+)\.\s{2,}(.+)')
    # Quantity pattern: e.g., "75.34 SQ" or "1.00 EA"
    qty_re = re.compile(r'^([\d,]+\.?\d*)\s+(SQ|LF|EA|SF|HR)$')
    # Numbers line: sequences of numbers (prices)
    numbers_re = re.compile(r'^[\d,]+\.\d{2}$')
    # Section header: a line that is a section name (capitalized, no numbers)
    section_header_re = re.compile(r'^[A-Z][A-Za-z &/]+$')
    # Totals line
    totals_re = re.compile(r'^Totals:\s+(.+)')
    # Line Item Totals
    line_totals_re = re.compile(r'^Line Item Totals:\s+(.+)')

    i = 0
    # Skip to after metadata (find first section or line item)
    while i < len(lines):
        line = lines[i].strip()
        if line == "Dwelling Roof" or line_item_re.match(line):
            break
        i += 1

    def flush_item():
        nonlocal current_item, current_f9_lines
        if current_item:
            if current_f9_lines:
                current_item["f9_notes"] = "\n".join(current_f9_lines).strip()
            else:
                current_item["f9_notes"] = None
            all_line_items.append(current_item)
            if current_section and "line_items" in current_section:
                current_section["line_items"].append(current_item)
            current_item = None
            current_f9_lines = []

    def flush_section():
        nonlocal current_section
        flush_item()
        if current_section:
            sections.append(current_section)
            current_section = None

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Check for Line Item Totals (grand totals)
        m = line_totals_re.match(line)
        if m:
            flush_section()
            # Next lines should have the totals numbers
            nums = []
            j = i + 1
            while j < len(lines) and len(nums) < 3:
                nl = lines[j].strip()
                if numbers_re.match(nl):
                    nums.append(parse_number(nl))
                j += 1
            if len(nums) >= 3:
                grand_totals = {"tax": nums[0], "op": nums[1], "total": nums[2]}
            # Skip past summary pages
            break

        # Check for Totals line
        m = totals_re.match(line)
        if m:
            flush_item()
            # Collect the totals numbers
            nums = []
            j = i + 1
            while j < len(lines) and len(nums) < 3:
                nl = lines[j].strip()
                if numbers_re.match(nl):
                    nums.append(parse_number(nl))
                    j += 1
                else:
                    break
            if current_section and len(nums) >= 3:
                current_section["totals"] = {"tax": nums[0], "op": nums[1], "total": nums[2]}
            i = j
            flush_section()
            continue

        # Check for section header
        # A section header is a line like "Dwelling Roof", "Detached Garage Roof", etc.
        # Not starting with a digit, not a continuation of description
        if (not line[0].isdigit() and not current_item and
            line not in ('"For', 'Coverage', 'Item Total', 'Summary', 'Recap') and
            not line.startswith("Coverage") and
            not line.startswith("Summary") and
            not line.startswith("Recap") and
            not line.startswith("Line Item") and
            not line.startswith("Total") and
            re.match(r'^[A-Z]', line) and
            not numbers_re.match(line) and
            not qty_re.match(line)):
            # Could be a section header
            # Check if next lines have DESCRIPTION/QTY headers or line items
            j = i + 1
            looks_like_section = False
            while j < len(lines) and j < i + 5:
                nl = lines[j].strip()
                if nl == "DESCRIPTION" or line_item_re.match(nl) or nl.startswith("CONTINUED"):
                    looks_like_section = True
                    break
                if nl and not nl in ("QTY", "REMOVE", "REPLACE", "TAX", "O&P", "TOTAL"):
                    break
                j += 1
            if looks_like_section:
                flush_section()
                current_section = {"name": line, "line_items": [], "totals": {}}
                i += 1
                continue

        # Check for line item start
        m = line_item_re.match(line)
        if m:
            flush_item()
            line_num = int(m.group(1))
            desc_part = m.group(2).strip()
            current_item = {
                "line_number": line_num,
                "description": desc_part,
                "quantity": None,
                "unit": None,
                "remove_price": None,
                "replace_price": None,
                "tax": None,
                "op": None,
                "total": None,
                "is_bid_item": "(Bid Item)" in desc_part,
                "section": current_section["name"] if current_section else None,
            }
            current_f9_lines = []
            # Now collect: qty line, price numbers, possible desc continuation
            i += 1
            # Collect remaining parts of this line item
            # Look for qty, numbers, and desc continuation
            nums_collected = []
            while i < len(lines):
                nl = lines[i].strip()
                if not nl:
                    i += 1
                    continue

                # Check if this is a qty line
                qm = qty_re.match(nl)
                if qm and current_item["quantity"] is None:
                    current_item["quantity"] = parse_number(qm.group(1))
                    current_item["unit"] = qm.group(2)
                    i += 1
                    continue

                # Check if this is a number (price)
                if numbers_re.match(nl):
                    nums_collected.append(parse_number(nl))
                    i += 1
                    continue

                # If we haven't got qty yet, this might be desc continuation
                if current_item["quantity"] is None and not line_item_re.match(nl) and not totals_re.match(nl):
                    # Description continuation
                    current_item["description"] += " " + nl
                    if "(Bid Item)" in nl:
                        current_item["is_bid_item"] = True
                    i += 1
                    continue

                # We have qty and collected numbers - done with this item's data
                break

            # Assign numbers: remove, replace, tax, op, total
            # Standard order: remove, replace, tax, op, total (5 numbers)
            if len(nums_collected) >= 5:
                current_item["remove_price"] = nums_collected[0]
                current_item["replace_price"] = nums_collected[1]
                current_item["tax"] = nums_collected[2]
                current_item["op"] = nums_collected[3]
                current_item["total"] = nums_collected[4]
            elif len(nums_collected) == 4:
                current_item["remove_price"] = nums_collected[0]
                current_item["replace_price"] = nums_collected[1]
                current_item["tax"] = nums_collected[2]
                current_item["op"] = nums_collected[3]

            # After numbers, check for description continuation
            # Continuations are short (< ~60 chars), don't start with known F9 patterns
            f9_start_re = re.compile(r'^(Our line item|The Insurance|We are requesting|"For decades)', re.IGNORECASE)
            while i < len(lines):
                nl = lines[i].strip()
                if not nl:
                    i += 1
                    continue
                # If it's a new line item, totals, section, or F9 note - stop
                if (line_item_re.match(nl) or totals_re.match(nl) or
                    line_totals_re.match(nl) or f9_start_re.match(nl) or
                    numbers_re.match(nl) or qty_re.match(nl)):
                    break
                # Short non-sentence text = description continuation
                if len(nl) < 80 and not nl.endswith('.') and not nl[0].isdigit():
                    current_item["description"] += " " + nl
                    if "(Bid Item)" in nl:
                        current_item["is_bid_item"] = True
                    i += 1
                else:
                    break

            continue  # Don't increment i, already at next line

        # If we have a current item and this isn't a new item or section marker,
        # it's an F9 note
        if current_item and current_item["quantity"] is not None:
            # Check it's not a section-related line
            if not totals_re.match(line) and not line_totals_re.match(line):
                current_f9_lines.append(line)
                i += 1
                continue

        i += 1

    flush_section()

    return sections, all_line_items, grand_totals


def parse_summary(lines):
    """Parse summary/grand totals from end of document."""
    totals = {"line_item_total": None, "tax": None, "op": None, "total": None}
    text = "\n".join(lines)

    # Look for "Line Item Totals" section
    m = re.search(r'Line Item Totals:\s+\S+\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', text)
    if m:
        totals["tax"] = parse_number(m.group(1))
        totals["op"] = parse_number(m.group(2))
        totals["total"] = parse_number(m.group(3))

    # Line item total from summary
    m = re.search(r'Line Item Total\s+([\d,]+\.\d{2})', text)
    if m:
        totals["line_item_total"] = parse_number(m.group(1))

    return totals


def parse_supplement(pdf_path):
    """Main parsing function."""
    raw_lines = extract_text_lines(pdf_path)
    metadata = parse_metadata(raw_lines)
    cleaned = strip_page_headers(raw_lines)
    sections, line_items, grand_totals = parse_body(cleaned)

    # Try to get grand totals from raw text too
    summary_totals = parse_summary(raw_lines)
    if grand_totals:
        summary_totals.update({k: v for k, v in grand_totals.items() if v is not None})

    return {
        "metadata": metadata,
        "sections": [
            {
                "name": s["name"],
                "line_items": [li["line_number"] for li in s["line_items"]],
                "totals": s.get("totals", {})
            }
            for s in sections
        ],
        "line_items": line_items,
        "totals": summary_totals,
    }


def print_summary(result):
    """Print a human-readable summary."""
    meta = result["metadata"]
    print(f"Contractor: {meta.get('contractor', 'N/A')}")
    print(f"Insured: {meta.get('insured', 'N/A')}")
    print(f"Claim #: {meta.get('claim_number', 'N/A')}")
    print(f"Policy #: {meta.get('policy_number', 'N/A')}")
    print(f"Property: {meta.get('property_address', 'N/A')}")
    print(f"Date of Loss: {meta.get('date_of_loss', 'N/A')}")
    print(f"Price List: {meta.get('price_list', 'N/A')}")
    print()
    print(f"{'Section':<30} {'Tax':>12} {'O&P':>12} {'Total':>12}")
    print("-" * 70)
    for sec in result["sections"]:
        t = sec.get("totals", {})
        print(f"{sec['name']:<30} {t.get('tax', 0):>12,.2f} {t.get('op', 0):>12,.2f} {t.get('total', 0):>12,.2f}")
    print("-" * 70)
    gt = result["totals"]
    print(f"{'GRAND TOTAL':<30} {gt.get('tax', 0) or 0:>12,.2f} {gt.get('op', 0) or 0:>12,.2f} {gt.get('total', 0) or 0:>12,.2f}")
    print()
    print(f"Total line items: {len(result['line_items'])}")
    f9_count = sum(1 for li in result["line_items"] if li.get("f9_notes"))
    print(f"Items with F9 notes: {f9_count}")


def main():
    parser = argparse.ArgumentParser(description="Parse IFC supplement estimate PDFs")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--summary", "-s", action="store_true", help="Print summary")
    args = parser.parse_args()

    result = parse_supplement(args.pdf)

    if args.summary:
        print_summary(result)
    elif args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Written to {args.output}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
