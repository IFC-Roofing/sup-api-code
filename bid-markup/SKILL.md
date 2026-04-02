# Bid Markup Agent

Process subcontractor bids: mark up PDFs by 30%, QA automatically, then extract pricing data.

## Full Pipeline (recommended)

One command does markup + QA + pricing extraction:

```bash
cd /Users/IFCSUP/.openclaw/workspace
python3 tools/bid-markup/markup_bids.py drive "<project_name>"
python3 tools/bid-markup/extract_pricing.py --drive "<project_name>" 2>/dev/null
```

**Markup now includes automatic QA.** After marking up each bid, it runs math checks to verify every amount was correctly increased by 30%. Results show per-bid QA verdicts.

## What Happens on `@markup "<project_name>"`

1. Search Drive for the project folder
2. Find all PDFs in `Original Bids` trade subfolders (@roof, @gutter, @window, etc.)
3. Mark up all dollar amounts by 30% (unit prices, line items, totals)
4. **QA each bid** — verify every original amount has a correct 30% counterpart
5. Upload marked-up PDFs to Shared Drive
6. Report results with QA verdicts

**If QA fails:** Report the issues. Bids still upload (team can review), but flag the problems clearly.

### QA Agent (`qa_markup.py`)

Two modes:
- **Math QA** (default, fast): Extracts amounts from both PDFs, verifies 30% math
- **Vision QA** (optional, slow): Sends page images to Gemini to check formatting — white boxes, ghost text, font mismatches, stray characters

```bash
# Math-only QA (runs automatically with markup)
python3 tools/bid-markup/qa_markup.py drive "<project_name>"

# With vision QA
python3 tools/bid-markup/qa_markup.py drive "<project_name>"  # (vision runs if google-generativeai installed)

# Skip vision
python3 tools/bid-markup/qa_markup.py --no-vision drive "<project_name>"
```

### extract_pricing.py
- Extracts line items from bid PDFs: description, quantity, unit, unit price, line total
- Extracts subcontractor name, phone, email
- Logs everything to the IFC Pricing Database Google Sheet
- Sheet ID: `13gzTw5JnF6aRntU91OThC9mvkLr6KZ2rTq63qki4jhc`

## Output Format

Report back as a summary table:
- Project name
- Per-bid: trade, original total → marked-up total, QA verdict (✅/⚠️/❌)
- Overall QA status
- Number of pricing rows logged (if extract_pricing ran)

## Flags

```bash
# Skip QA
python3 tools/bid-markup/markup_bids.py drive "<project_name>" --no-qa

# Include vision QA (slower but checks formatting)
python3 tools/bid-markup/markup_bids.py drive "<project_name>" --vision-qa

# Custom markup percentage
python3 tools/bid-markup/markup_bids.py drive "<project_name>" --markup 0.25
```

## Single File Mode

```bash
python3 tools/bid-markup/markup_bids.py file input.pdf output.pdf
```

## Smart Features

- **QTY detection**: Skips quantity values like "3.00 EA", "18.00 HR" — only marks up dollar amounts
- **Hybrid PDF handling**: Detects PDFs with background images, uses correct font (sans-serif instead of Courier)
- **Background color sampling**: Matches cover rectangles to actual page background (no white boxes on dark headers)
- **Spaced text**: Handles "$ 9 2 0 0" style amounts
- **Corrupted `$`**: Handles `Š` and other garbled dollar signs
- **Sub-dollar amounts**: Marks up amounts like $0.40, $0.74 correctly

## Troubleshooting

- **Font not found**: Auto-downloads from Google Fonts. If still missing, add .ttf to `tools/bid-markup/fonts/`
- **Project not found**: Try a shorter/different name — it does partial matching
- **No PDFs found**: Project needs an `Original Bids` folder with trade subfolders
- **Vision QA skipped**: Install `pip3 install google-generativeai python-dotenv` and set GOOGLE_API_KEY in .env
