# IFC Supplement PDF Skeleton

Reverse-engineered from ISBELL_CHRIS (Supp 1.0) and BROCK_ROSE (Supp 1.0).
These are the real Xactimate-generated PDFs IFC sends to insurance.
Our PDF generator must match this structure exactly.

---

## Page Order

1. **Cover Page** — header info
2. **Line Item Pages** — grouped by section/room, with F9 notes
3. **Line Item Totals Row** — sum of everything
4. **Coverage Summary Table** — Dwelling / Other Structures / Contents split
5. **Summary per Coverage** — one page each (Dwelling, Other Structures, Contents if applicable)
6. **Recap of Taxes, Overhead and Profit** — single table
7. **Recap by Room** — each section with % of total
8. **Recap by Category** — Xactimate categories with % of total

---

## PAGE 1 — Cover Page

```
[page number]
IFC Contracting Solutions

Insured: {LAST, FIRST}             E-mail: {email}
Property: {address line 1}
          {city}, TX {zip}
Contractor:                        Business: (817) 470-2600
Company: IFC Contracting Solutions
Business: 5115
          Colleyville, TX 76034

Claim Number: {claim#}    Policy Number: {policy#}    Type of Loss: {loss_type}
Date of Loss: {date}      Date Received:
Date Inspected: {date}    Date Entered: {date}
Price List: {pricelist_code}
Restoration/Service/Remodel
Estimate: {ESTIMATE_NAME}
```

**Notes:**
- Estimate name = `{LASTNAME_FIRSTNAME}` (all caps, e.g. `ISBELL_CHRIS`, `BROCK_ROSE`)
- Price list = e.g. `TXDF8X_FEB26`, `TXDF8X_NOV25`
- "Date Received" is always blank

---

## PAGE 2+ — Line Item Sections

### Section Header
```
{ESTIMATE_NAME}
{Section Name}
DESCRIPTION    QTY    REMOVE    REPLACE    TAX    O&P    TOTAL
```

**Notes on columns:**
- Some estimates include a `RESET` column between QTY and REMOVE (for D&R items)
- When RESET column is present: `DESCRIPTION | QTY | RESET | REMOVE | REPLACE | TAX | O&P | TOTAL`
- When not present: `DESCRIPTION | QTY | REMOVE | REPLACE | TAX | O&P | TOTAL`
- BROCK uses RESET column; ISBELL does not → standardize TO INCLUDE RESET (more complete)
- Continued sections repeat: `CONTINUED - {Section Name}` as header

### Line Item Format
```
{#}. {Description}    {QTY} {UNIT}    {REMOVE}    {REPLACE}    {TAX}    {O&P}    {TOTAL}
```

**Math:**
- TOTAL = (RESET + REMOVE + REPLACE) × QTY + TAX + O&P
- O&P = (line item base × 20%) = 10% overhead + 10% profit
- TAX = REPLACE × 8.25% (Texas sales tax) on material-only items
- Labor-only items: TAX = 0
- Bid Items: REPLACE = sub bid amount, TAX = 0, O&P = bid × 20%

### F9 Notes (inline, below the line item)

**Standard format for items insurance LEFT OUT:**
```
The Insurance report left out the {item description}.
We are requesting {qty} {unit}
1. {Cost justification sentence} Xactimate total cost is ${total} OR Our sub bid cost is ${amount}.
   a. {Evidence point — EagleView / measurements / photo}
   b. {Technical justification — production, code, manufacturer}
   c. {Additional point if needed}
```

**Standard format for items insurance UNDER-SCOPED:**
```
Our line item {#} covers insurance line item {#}.
We are requesting for an additional of {qty} {unit}.
1. The difference is ${diff}. Xactimate cost ${ifc_total}. While in insurance report cost is ${ins_total}.
   a. {EagleView / measurement justification}
   b. {Additional point}
```

**Bid Item F9 format:**
```
The Insurance report left out the {item}.
We are requesting for our sub bid.
1. Our sub bid cost is ${amount}.
   a. Please see attached Photo report showing {damage type} to the {item}.
   b. Please see attached {Subcontractor} bid for the confirmation of price.
   [optional: additional scope/measurement details]
```

### Section Totals Row
```
Totals: {Section Name}    {REMOVE_TOTAL}    {REPLACE_TOTAL}    {GRAND_TOTAL}
```
(TAX and O&P columns are blank in totals row — only REMOVE, REPLACE, TOTAL shown)

---

## Bid Items

Description format: `{SubcontractorName}_{ScopeDescription} (Bid Item)`
Examples:
- `Copper Masters Inc._Chimney Chase and Cap (Bid Item)`
- `Grizzly Fence & Patio_Iron Fence (Bid Item)`
- `3 Nails Gutter_Painting (Bid Item)`

Always: QTY = 1.00 EA, REMOVE = 0.00, TAX = 0.00, REPLACE = bid amount, O&P = bid × 0.20

---

## O&P Line Item (optional — ISBELL includes it, BROCK does not)

When project involves 3+ trades, add a $0 line item at the end:
```
{#}. O&P    1.00 EA    0.00    0.00    0.00    0.00    0.00
```
With F9 justification text (boilerplate):
```
"For decades we have vetted, managed, trained and warrantied subcontractors for roofing, gutters,
painting, fencing, siding etc. due to storm restoration in the DFW area.

We charge a minimum 20% overhead and profit above the subcontractors cost as we act as the single
point of contact for all subcontractors' trade complexities, plus cover all their liability and
warranty for our clients.

Project Requires General Contracting
This project involves coordination of multiple trades—including roofing, gutter replacement, exterior
painting, window screen repair, and possible stucco or interior restoration. Per industry standards
and Xactimate guidelines, O&P is warranted whenever three or more trades are involved and coordinated
by a general contractor.

[... full boilerplate ...]"
```

---

## Line Item Totals Row (after all sections)
```
Line Item Totals: {ESTIMATE_NAME}    {TAX_TOTAL}    {REPLACE_TOTAL}    {GRAND_TOTAL}
```

---

## Coverage Summary Table
```
Coverage          Item Total    %         ACV Total    %
Dwelling          {amount}      {pct}%    {amount}     {pct}%
Other Structures  {amount}      {pct}%    {amount}     {pct}%
Contents          {amount}      {pct}%    {amount}     {pct}%
Total             {amount}      100.00%   {amount}     100.00%
```

---

## Summary for {Coverage} (one page per coverage type used)
```
Summary for {Coverage Type}

Line Item Total            {amount}
Material Sales Tax         {amount}
Subtotal                   {amount}
Overhead                   {amount}
Profit                     {amount}
Replacement Cost Value     ${amount}
Net Claim                  ${amount}
```

---

## Recap of Taxes, Overhead and Profit
```
               Overhead (10%)  Profit (10%)  Material Sales Tax (8.25%)  Manuf. Home Tax (5%)
Line Items     {amount}        {amount}      {amount}                    0.00
Total          {amount}        {amount}      {amount}                    0.00
```

---

## Recap by Room
```
Estimate: {ESTIMATE_NAME}

{Section Name}    {line_item_subtotal}    {pct}%
Coverage: {Type} {coverage_pct}% = {coverage_amount}
...
Subtotal of Areas   {total}   100.00%
Coverage: Dwelling     {pct}% = {amount}
Coverage: Other Structures  {pct}% = {amount}
Total   {total}   100.00%
```

---

## Recap by Category
Xactimate's internal category grouping (different from our trade grouping):
```
O&P Items Total    %
GENERAL DEMOLITION          {amount}   {pct}%
ELECTRICAL                  {amount}   {pct}%
FENCING                     {amount}   {pct}%
PAINTING                    {amount}   {pct}%
ROOFING                     {amount}   {pct}%
SOFFIT, FASCIA, & GUTTER    {amount}   {pct}%
...
O&P Items Subtotal          {amount}   {pct}%
Material Sales Tax          {amount}   {pct}%
Overhead                    {amount}   {pct}%
Profit                      {amount}   {pct}%
Total                       {amount}   100.00%
```

---

## Sections Observed (real project data)

From ISBELL (complex job):
- Dwelling Roof
- Detached Garage Roof
- Gutters
- Windows
- Fence
- Pergola
- Shutters
- Corbels
- Pilars
- Copper Bay Window
- Dormer
- Porch
- O&P

From BROCK (simpler job):
- Dwelling Roof
- Gutters
- Shed
- Upstairs Living Area
- Stairs
- Debris Removal
- General
- Labor Minimums Applied

**Pattern:** Sections = physical areas of the property OR trade groupings OR special categories (General, Labor Minimums Applied, O&P)

---

## Key Observations for PDF Generator

1. **Photos are NOT embedded inline** in current format — F9s say "Please see attached Photo Report"
   - Our improvement: keep F9 references as-is, but add a linked Photo Report section at end
   - Or: embed thumbnails inline with each line item (TBD with Alvaro)

2. **F9 notes are plain text**, no special formatting — just indented paragraphs below the line

3. **Page numbers** are shown at top-left of each page (just the number, no "Page X of Y")

4. **Header repeats** on every page: company name + estimate name on continued pages

5. **Tax is Texas 8.25%** on materials only. Labor = $0 tax.

6. **O&P = 20%** (10% overhead + 10% profit). Applied to all line items including bid items.

7. **Bid items always**: QTY=1 EA, REMOVE=0, TAX=0, REPLACE=bid amount

8. **"Labor Minimums Applied"** is a standard section — trade labor minimums go here as their own section

9. **Section name on line item pages** uses the estimate name as a sub-header (not the company name for continued pages)

---

## What We Need to Build

- [ ] HTML template matching this layout exactly
- [ ] Line item data model (description, qty, unit, remove, replace, tax, o&p, total, f9_text, is_bid_item)
- [ ] Section/room grouping logic
- [ ] O&P calculation engine (20% on base, tax on materials @ 8.25%)
- [ ] Recap pages generator (by room, by category, by coverage)
- [ ] Photo report section (our addition — linked from F9s)
- [ ] Pricelist lookup (from Google Sheet `1wpp-nwHlUCJSECx9iOSlpyCCczX1_iDYy-p08UFiyTQ`)
