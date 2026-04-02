"""
Parse Xactimate pricelist PDF (text-extracted) into structured data.
Handles multi-line descriptions and note lines.
"""
import re
import json
import csv
import sys

def parse_pricelist(text_path: str) -> list[dict]:
    with open(text_path, 'r') as f:
        lines = f.readlines()

    items = []
    # Pattern: line number. Description    QTY UNIT   REMOVE   REPLACE   TAX   TOTAL
    # e.g.: "     1. Tarp - all-purpose poly - per sq ft          1.00 SF                  0.00                   1.22                   0.03                     1.25"
    item_pattern = re.compile(
        r'^\s+(\d[\d,]*)\.\s+'           # line number (may have commas like 1,777)
        r'(.+?)\s+'                       # description
        r'(\d+\.\d+)\s+'                  # qty
        r'([A-Z]{2})\s+'                  # unit
        r'([\d,]+\.\d+)\s+'              # remove
        r'([\d,]+\.\d+)\s+'              # replace
        r'([\d,]+\.\d+)\s+'              # tax
        r'([\d,]+\.\d+)\s*$'             # total
    )

    # Continuation of description (no numbers, just text on next line)
    continuation_pattern = re.compile(r'^\s{5,}([A-Za-z].+?)\s*$')

    # Note lines (lowercase, longer explanatory text) — skip these
    note_pattern = re.compile(r'^\s{5,}[A-Za-z].{40,}$')

    # Section headers
    section_pattern = re.compile(r'^\s*(CONTINUED\s*-\s*|Coverage\s*-\s*)(.*)')

    current_section = "Main Level"
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for section headers
        sec = section_pattern.match(line)
        if sec:
            current_section = sec.group(2).strip()
            i += 1
            continue

        # Skip page headers, footers, empty lines
        if 'DESCRIPTION' in line and 'QTY' in line:
            i += 1
            continue
        if 'TEST_LLM' in line or 'Price List:' in line or 'Estimate:' in line:
            i += 1
            continue
        if line.strip() == '' or re.match(r'^\s*\d+\s*$', line.strip()):
            i += 1
            continue

        m = item_pattern.match(line)
        if m:
            line_num = m.group(1).replace(',', '')
            desc = m.group(2).strip()
            qty = float(m.group(3))
            unit = m.group(4)
            remove = float(m.group(5).replace(',', ''))
            replace_val = float(m.group(6).replace(',', ''))
            tax = float(m.group(7).replace(',', ''))
            total = float(m.group(8).replace(',', ''))

            # Check next line for description continuation
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # If next line is continuation (text only, indented, not a number line, not a note)
                cont = continuation_pattern.match(next_line)
                if cont and not item_pattern.match(next_line):
                    cont_text = cont.group(1).strip()
                    # Skip if it looks like a note (very long explanatory text)
                    if len(cont_text) < 60 and not any(kw in cont_text.lower() for kw in ['due to', 'changed to', 'labor', 'because', 'this is']):
                        desc = desc + ' ' + cont_text
                        i += 1

            items.append({
                'line_num': int(line_num),
                'description': desc,
                'unit': unit,
                'remove': remove,
                'replace': replace_val,
                'tax': tax,
                'total': total,
                'section': current_section,
            })

        i += 1

    return items


if __name__ == '__main__':
    items = parse_pricelist('/tmp/pricelist_raw.txt')
    print(f"Parsed {len(items)} items")
    print()

    # Show first 10 and last 5
    for item in items[:10]:
        print(f"  {item['line_num']:>4}. {item['description']:<55} {item['unit']:>3}  Remove:{item['remove']:>8.2f}  Replace:{item['replace']:>8.2f}  Total:{item['total']:>8.2f}")
    print("  ...")
    for item in items[-5:]:
        print(f"  {item['line_num']:>4}. {item['description']:<55} {item['unit']:>3}  Remove:{item['remove']:>8.2f}  Replace:{item['replace']:>8.2f}  Total:{item['total']:>8.2f}")

    # Key items check
    print("\n=== KEY ITEMS ===")
    key_items = ['shingle', 'felt', 'step flash', 'drip edge', 'chimney', 'starter', 'hip / ridge', 'gutter']
    for kw in key_items:
        matches = [i for i in items if kw.lower() in i['description'].lower()]
        for m in matches[:2]:
            print(f"  {m['description']:<55} {m['unit']:>3}  Replace: ${m['replace']:.2f}")

    # Save as JSON
    with open('/tmp/pricelist_parsed.json', 'w') as f:
        json.dump(items, f, indent=2)
    print(f"\nSaved to /tmp/pricelist_parsed.json")
