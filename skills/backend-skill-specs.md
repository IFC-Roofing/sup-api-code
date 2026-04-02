# Backend Skill Specs — App-Native Implementation

These 4 skills execute **code**, not AI reasoning. BUILD/SUP call them like any other skill, but the backend runs actual processing pipelines. The AI agent provides the input, the skill returns structured output.

---

## 1. `markup_bids`

### What It Does
Pulls original subcontractor bids from the project's Drive folder, marks up all prices by 30% (wholesale → retail), generates new PDFs with marked-up values overlaid on the originals, uploads them to Drive. Returns retail totals per trade.

### When Called
- BUILD calls after confirming which trades have sub bids
- SUP calls when it needs retail bid totals for estimate line items
- Orchestration calls as Step 1 of the supplement pipeline

### Input
```json
{
  "project_id": 5128,
  "project_name": "Rose Brock",
  "markup_pct": 30,
  "trades": ["@gutter", "@chimney", "@window", "@paint", "@packout"]
}
```
- `project_id` (required) — IFC project ID
- `project_name` (required) — used for Drive folder naming
- `markup_pct` (optional, default 30) — markup percentage
- `trades` (optional) — filter to specific trades. If omitted, process ALL bids found in Original Bids folder.

### Processing Logic

#### Step 1: Find Bids on Drive
1. Search project Drive folder for "Original Bids" subfolder
2. List all PDF files in that folder
3. Each PDF = one subcontractor bid

#### Step 2: Per-Bid Processing (this is the complex part)

**A. Detect PDF type:**
- **Text-based PDF** (most bids): text is selectable, fonts are embedded
- **Hybrid/image PDF** (some bids like gutter companies): text layer is OCR, visual content is an image

**B. AI column detection (1 API call per bid):**
Send the first data page to an LLM with this prompt:
```
Analyze this bid/invoice table. For each column, return:
- column_name: what the column represents
- role: one of [qty, unit_price, line_total, subtotal, total, tax, description, other]
- x_start_pct: left edge as % of page width
- x_end_pct: right edge as % of page width
Also return the y-position of the column header row.
```

This tells us WHERE prices are on the page so we only mark up the right numbers.

**C. Extract all numeric spans from PDF:**
Using PyMuPDF (or Ruby PDF library), extract every text span with:
- Text content, position (x, y, width, height), font name, font size, color
- Filter: only spans below the header row y-position (skip estimate numbers, dates, addresses in the header)

**D. Classify each span by x-position:**
- If span's x-center falls in a `qty` column → SKIP (never mark up quantities)
- If span's x-center falls in a `unit_price` column → MARK UP (× 1.3)
- If span's x-center falls in a `line_total` column → RECOMPUTE (qty × new_unit_price)
- If span's x-center falls in a `subtotal` column → RECOMPUTE (sum of new line_totals)
- If span's x-center falls in a `total` column → RECOMPUTE (new_subtotal + tax)
- Unit labels next to quantities (EA, HR, LF, MO, SF, SQ) → SKIP

**E. Render marked-up values:**
For each price span being replaced:
1. Draw a background rectangle over the original text (color-matched to surrounding background)
2. Draw new text on top with:
   - Same font (extracted from PDF, or Arimo/Arial for image PDFs)
   - Same font size (for image PDFs: derive from bbox height × 1.15 for small text, × 1.05 for large text)
   - Same text color (for image PDFs: sample from image — darkest pixel on light bg, lightest on dark bg)
   - Same alignment (right-align prices, center-align if new text is wider than original)
3. Background rect must not bleed into adjacent areas (tight padding on dark backgrounds, slightly more on light)

**F. Save marked PDF** with "_marked" suffix

#### Step 3: Upload to Drive
- Create folder: `Shared Drive / Marked Up Bids / {Project Name}/`
- Upload all marked PDFs to that folder
- Return Drive links

### Output
```json
{
  "success": true,
  "project_id": 5128,
  "markup_pct": 30,
  "bids_processed": 5,
  "results": [
    {
      "original_file": "Doneburg Gutter Bid.pdf",
      "marked_file": "Doneburg Gutter Bid_marked.pdf",
      "trade": "@gutter",
      "sub_name": "LeafGuard",
      "original_total": 735.00,
      "marked_total": 955.50,
      "drive_link": "https://drive.google.com/file/d/xxx/view"
    },
    {
      "original_file": "FoGlass Window Screens.pdf",
      "marked_file": "FoGlass Window Screens_marked.pdf",
      "trade": "@window",
      "sub_name": "FoGlass",
      "original_total": 1159.00,
      "marked_total": 1506.70,
      "drive_link": "https://drive.google.com/file/d/yyy/view"
    }
  ],
  "total_original": 19139.00,
  "total_marked": 24880.70,
  "drive_folder_link": "https://drive.google.com/drive/folders/zzz"
}
```

### Edge Cases (Already Solved)
1. **Diagram/sketch pages** — Some bids have diagrams on page 1, data on page 2. AI detects this (not enough column hits). Skip diagram pages, try next page for table structure.
2. **Spaced-out amounts** — Some bids format "$9,200" as "$ 9 2 0 0" with individual character spans. Must detect and group these before markup.
3. **Multi-page bids** — Totals on page 2 must use recomputed values from page 1, not re-markup the total.
4. **Pre-modification extraction** — Extract ALL spans from ALL pages BEFORE modifying any page. Otherwise PyMuPDF returns modified text on subsequent reads (causes double-markup).
5. **Quantity filtering** — Numbers like "28.00 EA" split into separate spans ("28.00" + " " + "EA"). Must check subsequent spans for unit labels before classifying as a price.
6. **Tax handling** — Tax amount is recalculated on new subtotal, not marked up independently.
7. **Hybrid (image) PDFs** — OCR font sizes are unreliable. Derive visual size from bbox height ÷ 0.75. Always use bold Arimo (regular looks thin against anti-aliased image text). Image scale = image_width ÷ page_width for coordinate mapping.

### Dependencies
- PDF manipulation library (PyMuPDF/MuPDF equivalent in Ruby, or call Python)
- LLM API (1 call per bid for column detection — can use any model, Sonnet-class is fine)
- Google Drive API (read original bids, write marked bids)
- Font: Arimo (Google Fonts, Apache licensed — Arial/Helvetica equivalent)

### Reference Implementation
`tools/bid-markup/markup_bids.py` — working Python, 800+ lines, tested on 5 bid types.

---

## 2. `generate_estimate_pdf`

### What It Does
Takes SUP's estimate JSON output and renders a professional PDF document. Handles all formatting, page breaks, section organization, headers/footers, and uploads to Drive.

### When Called
- After SUP produces the estimate JSON
- Orchestration calls as Step 3 of the supplement pipeline (after markup, after estimate building)

### Input
```json
{
  "project_id": 5128,
  "estimate": {
    "estimate_name": "IFC Supplement 1.0",
    "insured": "Rose Brock",
    "address": "1234 Main St, Fort Worth, TX 76109",
    "date_of_loss": "04/15/2025",
    "price_list": "TXDF8X_FEB26",
    "sections": [
      {
        "name": "Dwelling - Roof",
        "coverage": "Dwelling",
        "line_items": [
          {
            "description": "Remove Laminated - comp. shingle rfg.",
            "qty": 48.0,
            "unit": "SQ",
            "remove_rate": 47.23,
            "replace_rate": 0,
            "tax": 0,
            "o_and_p": 0,
            "total": 2267.04,
            "is_material": false,
            "source": "ins",
            "f9": null
          }
        ]
      }
    ],
    "summary": {
      "total_rcv": 34329.00,
      "total_tax": 1847.22,
      "total_op": 5124.30,
      "sections_count": 8,
      "items_copied": 12,
      "items_added": 8,
      "items_adjusted": 3,
      "items_bid": 4
    }
  },
  "version": "1.0"
}
```

### Processing Logic

#### Step 1: Render HTML from Template
Template: single continuous table with repeating column headers on page break.

**Layout spec (matches Xactimate visual style):**
- **Running header:** IFC logo (left) + company info (right), 36px top padding
- **Estimate header block:** Estimate name, insured, address, date of loss, pricelist
- **Column headers:** Line #, Description, Qty, Unit, Remove, Replace, Tax, O&P, Total
  - `display: table-header-group` → repeats on every page
- **Section dividers:** Bold section name + bottom rule, 18px top gap between sections
- **Data rows:** 0.5pt top border, alternating alignment (description left, numbers right)
- **Totals rows:** Bold + 1.5pt double top border
- **Footer:** Estimate name (left), date (center), "Page X" (right) via `@page` margin boxes
- **Font:** Arial/Helvetica, 9pt body, 11pt headers
- **Colors:** Black text, white background, minimal (matches Xactimate b&w output)
- **Numbers:** Comma-formatted, 2 decimal places ($1,234.56)

#### Step 2: Inject F9 Notes
For every line item with a non-null `f9` field:
- Add F9 note row below the line item (spans full table width)
- F9 text: smaller font (8pt), indented, light gray left border
- F9 must be the FINAL version — all placeholders filled with real values

#### Step 3: Render PDF
- HTML → PDF via WeasyPrint (or equivalent: wkhtmltopdf, Puppeteer, Prince)
- Page size: Letter (8.5" × 11"), portrait
- Margins: 0.75" all sides

#### Step 4: Upload to Drive
- Upload to: `Shared Drive / Generated Supplements / {Project Name} - Supplement {version}.pdf`
- Return Drive link

### Output
```json
{
  "success": true,
  "project_id": 5128,
  "estimate_name": "IFC Supplement 1.0",
  "total_rcv": 34329.00,
  "page_count": 4,
  "sections_count": 8,
  "items_count": 27,
  "f9_count": 15,
  "drive_link": "https://drive.google.com/file/d/xxx/view",
  "drive_file_id": "1abc..."
}
```

### Edge Cases
1. **Long F9 notes** — Some F9s are 5+ paragraphs (like O&P). Must not break mid-sentence across pages. Use `break-inside: avoid` on F9 rows.
2. **Bid items** — Format: qty=1, unit=EA, remove=0, tax=0, replace=retail total. Description includes sub name.
3. **O&P section** — Single line item at 20%, long F9 boilerplate.
4. **Labor Minimums** — Separate section at end, before O&P.
5. **Empty sections** — If a section has 0 line items after filtering, omit it entirely.

### Dependencies
- HTML → PDF renderer (WeasyPrint recommended — handles CSS `@page`, `table-header-group`, margin boxes)
- Template engine (Jinja2 / ERB / equivalent)
- Google Drive API
- IFC logo asset (752×254px PNG)

### Reference Implementation
- Template: `tools/pdf-generator/templates/estimate.html` + `assets/style.css`
- Pipeline: `tools/pdf-generator/generate.py` → `html_renderer.py` → `pdf_renderer.py`

---

## 3. `update_flow_from_estimate`

### What It Does
Takes SUP's estimate JSON and attributes each line item to the correct trade card (@tag), sums per trade, and updates Flow cards with financial data. This is how the estimate numbers flow back into the project management system.

### When Called
- After SUP produces the estimate JSON (can run parallel with PDF generation)
- Orchestration calls as Step 4 of the supplement pipeline

### Input
```json
{
  "project_id": 5128,
  "estimate": "<same estimate JSON from SUP>",
  "dry_run": false
}
```
- `dry_run` (optional, default false) — if true, compute and return the attribution but don't update Flow cards

### Processing Logic

#### Step 1: Attribute Each Line Item to a Trade Card
For each line item in the estimate, determine which @tag (flow card) it belongs to.

**Attribution rules** (from Trade Mapping reference):

| Item Pattern | Attribute To |
|---|---|
| Shingle tear-off, shingles, felt, steep charges, high roof | `@shingle_roof` |
| Drip edge, starter, hip/ridge, valley, step/counter flashing | `@shingle_roof` |
| Pipe jacks, exhaust vents, ridge vents, turbines | `@shingle_roof` |
| Satellite D&R, solar panel D&R | `@shingle_roof` |
| Ice & water shield, synthetic underlayment | `@shingle_roof` |
| Dumpster, debris haul | `@shingle_roof` |
| Flat/roll roofing | `@flat_roof` |
| Garage structure items (Structure #2) | `@garage` |
| Gutter, downspout, gutter guard, splash guard | `@gutter` |
| Chimney cap, chase cover, chimney flashing | `@chimney` |
| Fence items (wood, iron, staining, painting, pressure wash) | `@fence` |
| Exterior paint, staining (siding, trim, fascia, soffit) | `@paint` |
| Window screens, window R&R | `@window` |
| Siding repair/replacement | `@siding` |
| Interior ceiling/wall, drywall, texture | `@interior` |
| Garage door | `@garage_door` |
| Stucco | `@stucco` |

**Edge cases that need explicit handling:**
- Electrician (solar reconnect) → `@shingle_roof` (part of solar D&R scope)
- Gutter D&R (for drip edge access) → `@shingle_roof` (production necessity for roof)
- Siding removal for flashing → check context: if for roof flashing → `@shingle_roof`
- Pipe jack prime & paint → `@shingle_roof` (not @paint)
- Building permits → skip (General, no trade card)
- O&P → skip (app calculates separately)
- Labor minimums → attribute to the trade they support

#### Step 2: Sum Per Trade
For each @tag, compute:
- `retail_exactimate_bid` — total of all line items attributed to this trade (this IS the supplement price)
- `op_from_ifc_supplement` — O&P allocated to this trade (proportional to trade total ÷ overall total × O&P amount)
- `latest_rcv_rcv` — retail_exactimate_bid + allocated O&P
- `nrd` (non-recoverable depreciation) — flag items where depreciation applies (materials age-based)
- `supplement_notes` — brief summary of what's in this trade's scope

#### Step 3: Update Flow Cards
For each trade with items, call `update_flow_card` with the computed values.

**Cards we DON'T touch:**
- O&P card — app derives this from trade math
- IFC card — manual entry
- `doing_the_work_status` — already managed in Flow
- `how_far_are_we_off` — app calculates automatically

### Output
```json
{
  "success": true,
  "project_id": 5128,
  "dry_run": false,
  "trades_updated": 5,
  "attribution": [
    {
      "trade": "@shingle_roof",
      "flow_card_id": "fc_123",
      "item_count": 14,
      "retail_exactimate_bid": 22450.00,
      "op_from_ifc_supplement": 4490.00,
      "latest_rcv_rcv": 26940.00,
      "nrd": 1200.00,
      "supplement_notes": "Tear-off 48 SQ, install 52 SQ (16% waste), felt, starter 360 LF, drip edge, hip/ridge, 2 pipe jacks, steep charge 7/12-9/12, dumpster"
    },
    {
      "trade": "@gutter",
      "flow_card_id": "fc_456",
      "item_count": 1,
      "retail_exactimate_bid": 955.50,
      "op_from_ifc_supplement": 191.10,
      "latest_rcv_rcv": 1146.60,
      "nrd": 0,
      "supplement_notes": "LeafGuard sub bid — full gutter + downspout R&R"
    }
  ],
  "unattributed_items": [],
  "total_rcv": 34329.00
}
```

### Edge Cases
1. **Multiple bids with same @tag** — Sum them (e.g., two chimney bids = different scopes, both go to @chimney)
2. **Items that don't map to any trade** — Return in `unattributed_items` for human review
3. **Trade card doesn't exist in Flow** — Don't create it. Flag it and skip. Human creates trade cards.
4. **O&P allocation** — Proportional split. If @shingle_roof = 65% of total, it gets 65% of O&P.

### Dependencies
- IFC API (read flow cards, update flow cards)
- Trade mapping rules (can be a config file or hardcoded lookup table)

### Reference Implementation
- Attribution logic: `tools/pdf-generator/estimate_builder.py` (the flow_package section)
- Trade mapping: `tools/skills/prompts/` references + Trade Mapping doc on Drive

---

## 4. `generate_photo_report`

### What It Does
Takes a set of photos mapped to line items/trades and generates a formatted photo report document. Each page shows 1-4 photos with captions linking them to specific supplement line items. This is a key attachment that supports F9 justification notes.

### When Called
- After photos are selected and organized by trade (currently manual — humans drop photos into labeled folders)
- Before final estimate package is sent to insurance

### Input
```json
{
  "project_id": 5128,
  "project_name": "Rose Brock",
  "photo_mappings": [
    {
      "trade": "@shingle_roof",
      "line_item": "Laminated - comp. shingle rfg.",
      "photos": [
        {
          "drive_file_id": "1abc...",
          "caption": "Hail damage to shingles — north-facing slope",
          "position": 1
        },
        {
          "drive_file_id": "1def...",
          "caption": "Close-up of impact marks showing granule loss",
          "position": 2
        }
      ]
    },
    {
      "trade": "@chimney",
      "line_item": "Chimney cap R&R",
      "photos": [
        {
          "drive_file_id": "1ghi...",
          "caption": "Existing chimney cap showing storm damage",
          "position": 1
        }
      ]
    }
  ],
  "layout": "2x2",
  "version": "1.0"
}
```
- `layout` (optional, default "2x2") — photos per page: "1x1" (1 large), "2x1" (2 stacked), "2x2" (4 grid)
- Photos can come from Drive file IDs or CompanyCam URLs

### Processing Logic

#### Step 1: Download Photos
- Fetch each photo from Drive (or CompanyCam)
- Resize to fit layout slots (maintain aspect ratio)
- Auto-rotate based on EXIF data

#### Step 2: Organize by Trade
- Group photos by trade in the standard section order (Roof → Gutters → Windows → Fence → etc.)
- Within each trade, order by `position` field

#### Step 3: Render PDF
- **Header:** "Photo Report — [Project Name]" + IFC logo
- **Per trade section:** Trade name as section header
- **Per page:** Layout grid of photos with:
  - Photo image (scaled to fit grid slot)
  - Caption text below each photo (8pt, describes what the photo shows)
  - Line item reference (which estimate line this supports)
- **Footer:** Project name, date, page number
- **Page size:** Letter, portrait

#### Step 4: Upload to Drive
- Upload to: `Shared Drive / Generated Supplements / {Project Name} - Photo Report {version}.pdf`

### Output
```json
{
  "success": true,
  "project_id": 5128,
  "page_count": 12,
  "photo_count": 38,
  "trades_covered": ["@shingle_roof", "@chimney", "@gutter", "@fence", "@paint"],
  "drive_link": "https://drive.google.com/file/d/xxx/view",
  "drive_file_id": "1abc..."
}
```

### Edge Cases
1. **No photos for a trade** — Skip the section. The `photo_inventory` skill flags this upstream.
2. **Very large photos** — Cap at 1200px on longest side before embedding (keeps PDF size manageable)
3. **Mixed orientations** — Landscape and portrait photos in same grid. Scale each independently within its slot.
4. **HEIC format** — iPhone photos may be HEIC. Convert to JPEG before embedding.

### Dependencies
- PDF generation library (same as estimate PDF — WeasyPrint or equivalent)
- Image processing (resize, rotate, format conversion)
- Google Drive API (download photos, upload report)

### Reference Implementation
- No existing script (this was manual before). Spec is based on current manual process Airah/Geraldine follow.

---

## Orchestration — How These Chain Together

The supplement pipeline calls these skills in sequence:

```
1. BUILD runs analysis → produces handoff JSON
2. SUP consumes handoff → produces estimate JSON
3. markup_bids(project_id) → marked bid PDFs on Drive
4. generate_estimate_pdf(estimate_json) → estimate PDF on Drive
5. update_flow_from_estimate(estimate_json) → flow cards updated
6. generate_photo_report(project_id, photo_mappings) → photo report on Drive
7. Human review gate → Vanessa approves or requests changes
8. Package sent to insurance (ALWAYS human-triggered, never automated)
```

Steps 3-6 can be triggered by the app after SUP finishes, either automatically or via a "Generate Package" button.

---

## Implementation Notes for Dev Team

### AI Calls
- `markup_bids` needs 1 LLM call per bid (column detection). Sonnet-class model is sufficient.
- All other skills are pure code — no AI calls needed.

### Where My Code Lives (for reference)
All working Python implementations are in the Sup workspace:
- `tools/bid-markup/markup_bids.py` — bid markup engine (v1b, 800+ lines)
- `tools/pdf-generator/generate.py` — estimate PDF pipeline
- `tools/pdf-generator/html_renderer.py` — HTML template rendering
- `tools/pdf-generator/pdf_renderer.py` — WeasyPrint PDF rendering
- `tools/pdf-generator/estimate_builder.py` — AI estimate building + flow attribution
- `tools/pdf-generator/templates/estimate.html` + `assets/style.css` — PDF template
- `tools/pdf-generator/f9_matrix.json` — 86 F9 templates

### Shared Drive Folders
- Generated Supplements: `1tWeZivnrRjDtZq1eG6dHu4vHkBwgMWop`
- Marked Up Bids: `1An0yN4k8GDJrLVMvrdfvUs69zpT9mcD7`
- Reference: `12wldOnLVtEBPEl2mUcBKv34PSYRz5VRW`
