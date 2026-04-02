# PDF Generator — Build Brief
_Written 2026-02-25 before context window reset. Everything a fresh session needs to start building._

---

## What We're Building
An HTML → PDF supplement generator that replicates the Xactimate format IFC currently sends to insurance.
Replaces Xactimate computer use entirely. IFC sends plain PDFs — no Xactimate branding required.

---

## Architecture

### Input Sources
1. **IFC API** — `GET /projects?search=<name>` → project ID, claim #, policy #, address
2. **IFC API posts** — `GET /posts?project_id=<id>` → `@ifc` (game plan) + `@supplement` (internal strategy) notes
3. **INS estimate PDF** — in Drive, named `{LASTNAME}_INS X.0.pdf` → parse with `tools/parsers/parse_insurance.py`
4. **Pricelist Sheet** — `1wpp-nwHlUCJSECx9iOSlpyCCczX1_iDYy-p08UFiyTQ` → unit price lookups
5. **EagleView PDF** — in Drive, named `{LASTNAME}_EagleView.pdf` → parse for measurements

### Build Logic
1. Parse INS estimate → extract all line items (copy them into IFC estimate)
2. Pull @ifc + @supplement notes → understand what's missing / what to add
3. Apply standard checklist of commonly-missed items (drip edge, O&P, steep charges, labor minimums)
4. Look up unit prices from pricelist sheet (TXDF8X_FEB26)
5. Generate F9 notes for every item we're adding (3 formulas — see PROCESS.md)
6. Render HTML → PDF via WeasyPrint

### Output
- PDF file matching Xactimate skeleton exactly
- Upload to project's Drive folder
- **NEVER send to insurance — always human review gate**

---

## Key Files (already built)
| File | Purpose |
|---|---|
| `tools/pdf-generator/SKELETON.md` | Full page-by-page PDF structure |
| `tools/pdf-generator/PROCESS.md` | EV→line item mapping, F9 formulas, business rules |
| `tools/pdf-generator/assets/ifc_logo.png` | Logo extracted from real PDFs (752×254px) |
| `tools/parsers/parse_insurance.py` | AI-powered INS estimate parser (Gemini vision) |
| `tools/parsers/parse_supplement.py` | IFC supplement parser |
| `tools/bid-markup/markup_bids.py` | Bid markup pipeline |
| `IFC_API.md` | Full API docs |
| `.env` | GOOGLE_API_KEY, IFC_API_TOKEN |
| `google-drive-key.json` | Drive/Sheets service account |

---

## PDF Skeleton (summary — full details in SKELETON.md)

### Page order
1. Cover page (project header info)
2. Line item pages (grouped by section/room, with F9 notes inline)
3. Line Item Totals row
4. Coverage Summary table
5. Summary per Coverage type (Dwelling / Other Structures / Contents)
6. Recap of Taxes, Overhead and Profit
7. Recap by Room
8. Recap by Category

### Columns
`DESCRIPTION | QTY | REMOVE | REPLACE | TAX | O&P | TOTAL`
(Add RESET column only when D&R items are present)

### Math
- O&P = 20% (10% overhead + 10% profit) on REMOVE + REPLACE combined
- Tax = 8.25% (Texas) on REPLACE for material items, 0 for labor
- Bid items: REMOVE=0, TAX=0, REPLACE=bid amount, O&P=bid×20%
- Line total = REMOVE + REPLACE + TAX + O&P

### Header (every page)
- Top-left: IFC logo (`assets/ifc_logo.png`, rendered ~188×63px)
- Top-right: page number
- Below logo: "IFC Contracting Solutions"
- Line items pages also show: estimate name + section name

### Cover page fields
Pull from IFC API + INS estimate:
- Insured: LAST, FIRST
- Property address
- Contractor: IFC Contracting Solutions | (817) 470-2600 | 5115 Colleyville TX 76034
- Claim #, Policy #, Type of Loss
- Date of Loss, Date Inspected, Date Entered
- Price List: TXDF8X_FEB26
- Estimate name: {LASTNAME_FIRSTNAME} (all caps)

---

## F9 Note Formulas (from PROCESS.md)

### Left out entirely
```
The Insurance report left out the {item}.
We are requesting {qty} {unit}.
1. Xactimate total cost is ${total} OR Our sub bid cost is ${amount}.
   a. {EV/measurement evidence}
   b. {Technical justification}
   c. Please see attached Photo Report showing {damage} to the {area}.
```

### Under-scoped (wrong qty)
```
Our line item {#} covers insurance line item {#}.
We are requesting an additional {qty} {unit}.
1. The difference is ${diff}. Xactimate cost ${ifc_total}. Insurance cost ${ins_total}.
   a. Per EagleView: {measurement} = {qty} {unit}
```

### Bid item
```
The Insurance report left out the {item}.
We are requesting for our sub bid.
1. Our sub bid cost is ${amount}.
   a. Please see attached Photo Report showing {damage} to the {area}.
   b. Please see attached {Sub} bid for confirmation of price.
```

---

## Standard Checklist of Commonly Missed Items
Always check if these are in INS. If not, add them:
- Drip edge (LF = EV eaves + rakes)
- Starter strip (LF = EV eaves)
- Hip/ridge cap (LF = EV hips + ridges)
- Valley metal (LF = EV valleys)
- Step flashing (LF = EV step flashing)
- Counterflashing/apron (LF = EV flashing)
- Steep charge remove + replace (if pitch >8/12)
- High roof charge (if 2+ stories)
- Gutter guard
- Splash guards
- O&P line item + F9 (if 3+ trades)
- Labor minimums (one per trade touched)

---

## Photos
- Phase 1 (this build): NO photos. F9s say "Please see attached Photo Report"
- Phase 2: After @precall, humans drop photos in Drive folder. I embed them.
- Photo anchors: leave `<!-- PHOTO: {anchor_id} -->` comments in HTML for easy injection later

---

## EagleView → Line Item Mapping (critical)
| EV Field | Line Item | Notes |
|---|---|---|
| Area (SQ) × (1 + waste%) | Shingles | Round UP to nearest 1/3 SQ |
| Area (SQ) base | Felt/underlayment | No waste |
| Eaves (LF) | Starter strip | |
| Eaves + Rakes (LF) | Drip edge | |
| Ridges + Hips (LF) | Hip/ridge cap | |
| Valleys (LF) | Valley metal | |
| Step Flashing (LF) | Step flashing | Exact |
| Flashing (LF) | Counterflashing/apron | Exact |

---

## Sections / Grouping Logic
- Dwelling Roof (always first)
- Detached Garage Roof (if applicable)
- Trade sections (Gutters, Fence, Windows, Siding...)
- Specialty sections (Pergola, Copper, Shutters...)
- Interior (if applicable)
- Debris Removal
- General
- Labor Minimums Applied
- O&P (if standalone $0 line item)

---

## Business Rules (non-negotiable)
1. O&P = 20% always — baked into each line item
2. TX sales tax = 8.25% on materials, $0 on labor
3. IFC price list = TXDF8X_FEB26 (current — always higher than INS's older list)
4. Bid items always: 1 EA, REMOVE=0, TAX=0
5. Sub bids must be marked up 30% before becoming REPLACE value
6. NEVER emit output to insurance — human review gate always
7. Waste % = EV suggested %, round UP to nearest 1/3 SQ
8. Labor minimums = one per trade in own section

---

## Infrastructure

### Pipeline (generate.py is the entry point)
```
generate.py "<project_name>"
  ↓
1. data_pipeline.py  (pure Python, no AI)
   - IFC API → project info, @ifc + @supplement posts
   - Drive → INS PDF + EagleView PDF
   - parse_insurance.py → INS line items JSON
   - parse_ev.py → EV measurements JSON
   - pricelist_lookup.py → unit price function

  ↓
2. estimate_builder.py  (AI step — calls Claude API)
   - Input: INS items + @ifc + @supplement + EV + pricelist
   - Output: estimate.json (full structured estimate)
   - Logic: copy INS items + add missing + calculate math + write F9s
   - This is where all intelligence lives

  ↓
3. html_renderer.py  (pure Python, Jinja2)
   - estimate.json → HTML via template
   - All pages: cover, line items, totals, coverage summary, recaps

  ↓
4. pdf_renderer.py  (WeasyPrint)
   - HTML → PDF

  ↓
5. uploader.py  (Drive API)
   - PDF → project's Drive folder
   - Named: "{LASTNAME}_IFC Supp 1.0.pdf" (or 2.0, 3.0 etc.)
```

### estimate.json data model
```json
{
  "estimate_name": "BROCK_ROSE",
  "claim_number": "...",
  "policy_number": "...",
  "policy_holder": "Brock, Rose",
  "address": "...",
  "date_of_loss": "...",
  "date_inspected": "...",
  "date_entered": "2026-02-25",
  "price_list": "TXDF8X_FEB26",
  "type_of_loss": "Wind/Hail",
  "sections": [
    {
      "name": "Dwelling Roof",
      "coverage": "Dwelling",
      "items": [
        {
          "num": 1,
          "description": "Lam. comp shng. - w/felt",
          "qty": 31.0,
          "unit": "SQ",
          "remove": 54.32,
          "replace": 198.45,
          "is_material": true,
          "tax": 16.37,
          "op": 50.55,
          "total": 319.69,
          "f9": "The Insurance report left out...",
          "source": "added",
          "photo_anchor": "shingles-dwelling-roof"
        }
      ],
      "totals": { "remove": 0.0, "replace": 0.0, "total": 0.0 }
    }
  ],
  "line_item_total": 0.0,
  "tax_total": 0.0,
  "op_total": 0.0,
  "rcv_total": 0.0,
  "coverage_split": {
    "Dwelling": 0.0,
    "Other Structures": 0.0,
    "Contents": 0.0
  }
}
```
- `source`: `"ins"` (copied from insurance) | `"added"` (we added it) | `"adjusted"` (INS had it, we changed qty)
- `photo_anchor`: slug for future photo injection (Phase 2)
- Math fields (tax, op, total) computed by estimate_builder.py, not AI

### File structure
```
tools/pdf-generator/
  generate.py          ← entry point
  data_pipeline.py     ← all data fetching/parsing
  estimate_builder.py  ← AI step (Claude API call)
  html_renderer.py     ← Jinja2 → HTML
  pdf_renderer.py      ← WeasyPrint → PDF
  uploader.py          ← Drive upload
  templates/
    estimate.html      ← main Jinja2 template
    cover.html         ← cover page partial
    line_items.html    ← line items section partial
    recaps.html        ← recap pages partial
  assets/
    ifc_logo.png       ← header logo
    style.css          ← PDF stylesheet
  BUILD.md             ← this file
  SKELETON.md          ← full PDF structure reference
  PROCESS.md           ← business logic reference
```

## WeasyPrint Setup
```bash
pip install weasyprint
# May need: apt-get install libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0
```

## Build Steps (suggested order)
1. `generate.py` — main entry point: takes project_name → outputs PDF
2. `data_pipeline.py` — pulls all inputs (IFC API, INS parse, EV parse, pricelist lookup)
3. `estimate_builder.py` — core logic: copy INS + add missing + calculate all math
4. `f9_generator.py` — generates F9 notes for each added item
5. `html_template.html` — the actual layout (Jinja2 templated)
6. `pdf_renderer.py` — WeasyPrint HTML → PDF

---

## Real Project Test Cases
- **Rose Brock** (id=5128 in IFC API) — simple job, INS paid ~$4k, IFC supp $35k
- **Chris Isbell** (id=4965 in IFC API) — complex job, multiple trades, copper work, 3 supp rounds
- Supplement PDFs in Drive: `1. BROCK_IFC Supp 1.0.pdf`, `1. ISBELL_IFC Supp 1.0.pdf`
- INS estimates: `BROCK_INS 1.0.pdf`, `ISBELL_INS 3.0.pdf`
- EagleViews: `BROCK_EagleView.pdf`, `2. ISBELL_EagleView.pdf`
