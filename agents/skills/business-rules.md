# IFC Business Rules — Supplement Knowledge Base

## Business Model
- IFC = general contractor for insurance-funded construction (storm damage restoration)
- Homeowner pays deductible, insurance pays the claim
- IFC coordinates all trades: roofing, gutters, paint, fence, siding, windows, chimney, interior, etc.
- Wholesale pricing from subcontractors, retail pricing to insurance + O&P (overhead & profit)

## Pricing Architecture
- **Xactimate** = industry-standard pricing software used by insurance. All line items reference Xactimate codes.
- **Pricelist** = regional Xactimate price table (e.g., `TXFW8X_MAR26`). Updated monthly. Both IFC and carrier use the same pricelist.
- **O&P** = 20% overhead and profit, applied per line item. Warranted when 3+ trades are coordinated by a general contractor.
- **Tax** = 8.25% on materials only. Labor items: tax = 0.
- **Bid items** = subcontractor work priced via market bid instead of Xactimate. Used when Xactimate can't capture complexity (specialty gutters, chimney caps, custom metal, discontinued products).
  - Bids are wholesale from sub → marked up 30% → that's the retail price requested from insurance.
  - Bid items: remove=0, tax=0, replace=bid retail total, qty=1 EA.

## What a Supplement IS
A supplement is a formal request to the insurance company to add or adjust line items on their estimate. It includes:
1. The items we're requesting (with Xactimate codes, quantities, pricing)
2. F9 justification notes explaining WHY each item is needed
3. Supporting evidence (EagleView measurements, photos, sub-bids)

## Supplement Phases

### Phase 1 — First Send to Insurance
- Parse carrier's initial estimate (INS)
- Compare against actual scope (EagleView + bids + field inspection)
- Build supplement with missing items, quantity corrections, and bid replacements
- Write F9 notes for every added/adjusted item
- Package and send to carrier after Vanessa's QA review

### Phase 2 — Post-Insurance Response
- Carrier responds with updated estimate (new INS version)
- Compare previous INS vs new INS → what changed?
- Compare new INS vs our supplement → what's still missing?
- Extract denial reasons from carrier's response
- Rewrite F9 notes to address specific denials
- Determine action per item: defend, rewrite, need more evidence, etc.

## Quantity Rules
- **Tear-off** = MEASURED SQ from EagleView (no waste — removing what's there)
- **Shingles** = SUGGESTED SQ from EV (includes waste for cuts)
- **Roofing felt** = MEASURED SQ (covers the deck, minimal waste)
- **Starter strip** = drip edge LF (eaves + rakes — starter runs full drip edge)
- **All other materials** = EV measurements as given
- **Round** all EV linear measurements DOWN to nearest whole number for insurance presentation (e.g., 297.25 LF → 297 LF). Do NOT round SQ values.

## Bid vs Xactimate Rules
- **When a SUB BID exists for a trade** → drop ALL INS items from that trade section. The bid REPLACES the entire INS scope.
  - Exception: items clearly outside bid scope (supervision, cleanup, painting) may stay.
  - Example: @gutter bid → drop all gutter R&R, gutter guard, downspout INS items. Use only the bid.
- **Chimney bids** cover chase cover/cap ONLY — chimney flashing is separate and must be added as a Xactimate line item.
- **Roofing exception**: Roofing bids are NOT required. Naming any approved roofing contractor (H&R, G5, Walter, Rigo, etc.) is acceptable as production reality / labor rate evidence.
- **Multiple bids with same @trade tag** = different scopes. Include ALL of them as separate bid items.

## Bid Item F9 Format
"The Insurance report left out the [scope].\nWe are requesting for our sub bid.\n1. Our sub bid cost is $[retail_total].\n   a. Please see attached Photo Report showing damage.\n   b. Please see attached [sub_name] bid for the confirmation of price."

## Pricing Evidence Rule
If insurance is already paying for a line item but pricing is wrong or too low:
- You do NOT need a photo to justify asking for more
- You DO need: a subcontractor bid, OR a written cost justification (labor, material, code, production condition)

## EagleView Structure Mapping
- Structure #1 = Main Dwelling (house)
- Structure #2 = Detached Garage / Other Structure
- NEVER mix structure measurements. Dwelling Roof uses Structure #1, Garage Roof uses Structure #2.
- Waste percentage is per-structure from EV's bbox detection.

## Section Order (in estimate)
Dwelling Roof → Detached Garage Roof → Elevations → Gutters → Windows → Fence/Siding → Specialty → Interior → Debris Removal → General → Labor Minimums Applied → O&P

## Carrier Risk Shield
- Remove or flag weak, fraudulent, or unclear items BEFORE they reach the carrier
- "Approval" = get everything DEFENSIBLE paid, not "get everything paid"
- Protect IFC's credibility at all times

## SLAs
- Submit to insurance: 3 business days from handoff
- Re-respond to insurance: 3 business days
- Vanessa review: <24h (goal <3h)
- Airah/Geraldine send: 2 days after Vanessa approval
