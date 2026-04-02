# Supplement Creation Process
_Reverse-engineered from Chris Isbell (Supp 1.0–3.0) and Rose Brock (Supp 1.0)_

---

## High-Level Flow

```
Sales Rep hands off job
        ↓
@ifc note written (Will or rep, voice/text) → defines scope game plan
        ↓
EagleView ordered → measurements
        ↓
Sub bids collected (per trade: gutter, fence, window, specialty)
        ↓
Vanessa audits (compares INS vs what we can get, decides strategy)
        ↓
@precall (Cathy calls insurance before sending — find blockers)
        ↓
Supp 1.0 built and sent
        ↓
INS responds → @ins_responded
        ↓
Cathy negotiates / follows up
        ↓
Supp 2.0, 3.0... as needed
        ↓
If stalled → Appraisal (Taylor Asfar) or @pa_law_appraisal_expert
```

---

## INPUT DOCUMENTS

For every supplement, these are the source documents:

| Document | Source | Used For |
|---|---|---|
| **@ifc note** | IFC API `post_notes` | Game plan — what to go after |
| **@supplement note** | IFC API `post_notes` | Internal strategy (NOT sent to INS) |
| **EagleView** | Drive PDF | All roof measurements |
| **INS estimate** | Drive PDF | What insurance already paid / missed |
| **Sub bids** | Drive PDFs (per trade) | Bid item pricing |
| **Gutter diagram** | Drive PDF | Gutter LF breakdown |
| **Photos** | Drive folder | Evidence in F9s + photo report |

---

## THE @ifc NOTE — The Game Plan

Written by the sales rep (usually Will or Zane) right after the initial inspection.
Contains scope intelligence that isn't in any document:

**Isbell @ifc example:**
> "He has an atlas roof, Lifetime shingle. He has copper upfront metal in the back. Told him I can upgrade his Chimney cap. He just got his gutters painted, told him we could repaint them. He has high profile ridge and closed valleys. He has splash guards on some valleys that he wants to take off on the left side... Go after fence being stained and the arbor top being redone because we're gonna have to take the arbor off the roof... chimney flashing gonna need to be redone and the chimney has cracks in it..."

**What it tells us:**
- What the existing system is (Atlas Lifetime = specific shingle type)
- What the homeowner wants (splash guard removal from certain valleys)
- What scope to go after (pergola, fence, chimney, copper)
- Special conditions (chimney cracks → masonry bid)
- What CAN'T be reused (pergola top pieces)

**Brock @ifc note:** Just `@momentum @client @ifc` with no body — this means the scope game plan was either verbal or not logged yet. When this happens, we work from EV + INS + photos only.

---

## EAGLEVIEW → LINE ITEM MAPPING

This is how EV measurements become specific line items in the estimate:

| EV Field | Line Item | Notes |
|---|---|---|
| **Area (SQ) + suggested waste %** | Shingles (SQ) | EV area × (1 + waste%) → round UP to nearest 1/3 SQ |
| **Area (SQ) base** | Felt/underlayment (SQ) | Base area only, no waste |
| **Eaves (LF)** | Starter strip (LF) | Eaves length = starter course |
| **Eaves + Rakes (LF)** | Drip edge (LF) | Full perimeter edge |
| **Ridges + Hips (LF)** | Hip/ridge cap (LF) | Both combined |
| **Valleys (LF)** | Valley metal (LF) | Open valley flashing |
| **Step Flashing (LF)** | Step flashing (LF) | Exact EV value |
| **Flashing (LF)** | Counterflashing / apron (LF) | Exact EV value |
| **Predominant Pitch** | Steep charge | >8/12 = 10-12/12 rate; >12/12 = separate charge |
| **Number of Stories** | High roof charge | 2+ stories = additional charge |
| **Roof Penetrations (count)** | Pipe jacks, exhaust caps | 1 EA per penetration |

### Steep/High Roof Charges — ALWAYS TWO LINE ITEMS
- Remove steep charge (lower rate)
- Replace steep charge (higher rate)
- Both use EV area (SQ)
- If >12/12 AND 2 stories → both steep AND high apply

### Waste Factor — IFC Convention
- Use EV's "Suggested" waste % (highlighted column)
- Round up to nearest 1/3 SQ
- Apply same waste % to: shingles, hip/ridge cap (sometimes), felt
- Drip edge, starter, valley, flashing = no waste (linear, measured)

---

## INS ESTIMATE ANALYSIS — What to Go After

### INS estimate structure (State Farm)
Columns: `QUANTITY | UNIT | PRICE | TAX | RCV | AGE/LIFE | DEPREC | ACV | CONDITION | DEP%`
Note: INS shows depreciation. IFC estimate doesn't (we claim RCV only).
Note: INS shows 0% O&P (State Farm routinely denies it). IFC adds 20%.

### How to read the INS estimate
1. **What they paid:** Items listed with amounts = acknowledged damage
2. **What they lowballed:** Same line item but wrong QTY (e.g., 66 SQ instead of 75 SQ)
3. **What they missed:** Items we have that don't appear at all
4. **"No Accidental Direct Physical Loss Observed"** = they explicitly denied that area

### ISBELL Case Study — What insurance missed vs IFC got
Insurance paid:
- Roof: 90.67 SQ shingles, felt, starter, ridge, ice&water, vents, pipe jacks, steep/high charges, step/apron flashing
- Windows: 2 bid items (Foglass screens, Copper Masters copper work)
- Gutters: 753 LF gutter, 120 LF DS, guard, splash guards, half-round copper
- Fence: Grizzly bid (wrought iron painting, wood fence)
- Shutters/Pergola/Pillars: Grizzly bid

IFC added (Supp 1.0 items not in INS):
- Drip edge (insurance missed it entirely)
- More shingle SQ (75.34 vs INS's line item base)
- Detached garage: IFC used 11.67 SQ vs INS implied ~9 SQ  
- Additional bid items (Chimney chase cover via Copper Masters)
- O&P (20% — main fight through 3 supplements → went to appraisal)

### BROCK Case Study — Full supplement vs near-$0 insurance
Insurance paid: $4,113 RCV (deductible $4,444 → net = $0)
- 5 shingles (front slope only), 2 vents, 2 rain caps, 4 hrs roofer
- 120 LF downspouts only
- Interior: ceiling popcorn, paint, stair ceiling

IFC Supp 1.0: full roof replacement ($35,642 total)
- Full 31 SQ laminated shingles (EV: 26.66 SQ base, 20% waste = 32 SQ)
- All flashings (hip/ridge, drip edge, starter, valley, step, apron, flue cap)
- Full gutter system (167 LF + 143 LF DS + guard)
- Shed roof (1.67 SQ)
- Interior (kept what insurance had + added items)
- General section: ladders, tarps, supervision
- Labor minimums for all trades touched

---

## SUB BIDS — Bid Items

### When to use a bid item vs pricelist price
- **Pricelist:** Standard materials/labor (shingles, felt, gutters, etc.)
- **Bid item:** When a specialty subcontractor has a specific scope that Xactimate can't price well (copper work, specialty fence, wrought iron, chimney masonry, custom gutters)

### Bid item line item format
```
{SubName}_{ScopeDescription} (Bid Item)
QTY: 1.00 EA | REMOVE: 0.00 | TAX: 0.00 | REPLACE: [bid amount]
O&P: bid × 20% | TOTAL: bid × 1.20
```

### How to mark up bids
- Pull original sub bid from Drive
- Mark up 30% (wholesale → retail) via `@markup` script  
- The marked-up number becomes the REPLACE value in the bid item
- O&P is still applied on top of the marked-up bid

---

## F9 NOTE FORMULAS

### Formula 1 — Insurance left it out entirely
```
The Insurance report left out the {item}.
We are requesting {qty} {unit}.
1. {Cost ref: Xactimate = $X} OR {Our sub bid cost is $X}.
   a. {EagleView / measurement evidence}
   b. {Technical justification: production code, manufacturer spec, necessity}
   c. {Photo reference: "Please see attached Photo Report showing {damage} to the {area}"}
```

### Formula 2 — Insurance under-scoped (wrong quantity)
```
Our line item {#} covers insurance line item {#}.
We are requesting an additional {qty} {unit}.
1. The difference is ${diff}. Xactimate cost ${ifc_total}. While in insurance report cost is ${ins_total}.
   a. Per EagleView report ID {id}: {measurement} = {qty} {unit}
   b. {Additional evidence}
```

### Formula 3 — Bid item (sub contracted scope)
```
The Insurance report left out the {item}.
We are requesting for our sub bid.
1. Our sub bid cost is ${amount}.
   a. Please see attached Photo Report showing {damage type} to the {item}.
   b. Please see attached {Sub name} bid for the confirmation of price.
   c. {Optional: scope details, measurements}
```

### Formula 4 — O&P justification boilerplate
```
For decades we have vetted, managed, trained and warrantied subcontractors for roofing, gutters,
painting, fencing, siding etc. due to storm restoration in the DFW area.

We charge a minimum 20% overhead and profit above the subcontractors cost as we act as the single
point of contact for all subcontractors' trade complexities, plus cover all their liability and
warranty for our clients.

Project Requires General Contracting
This project involves coordination of multiple trades including [list trades]. Per industry standards
and Xactimate guidelines, O&P is warranted whenever three or more trades are involved and coordinated
by a general contractor.
[Continue with full justification...]
```

---

## SUPPLEMENT MATH

### Unit Price Lookup
1. Match description to pricelist (Google Sheet `1wpp-nwHlUCJSECx9iOSlpyCCczX1_iDYy-p08UFiyTQ`)
2. Price list must match the current period (e.g., TXDF8X_FEB26)
3. INS uses older price lists (TXDF28_MAY25, TXDF28_AUG25) — IFC uses current

### Line Item Calculation
```
REMOVE_TOTAL = QTY × remove_rate (from pricelist)
REPLACE_TOTAL = QTY × replace_rate (from pricelist)
TAX = REPLACE_TOTAL × 0.0825  (materials only; labor-only = $0)
O&P = (REMOVE_TOTAL + REPLACE_TOTAL) × 0.20
TOTAL = REMOVE_TOTAL + REPLACE_TOTAL + TAX + O&P
```

### For Bid Items
```
REMOVE = 0.00
REPLACE = marked_up_bid_amount
TAX = 0.00
O&P = REPLACE × 0.20
TOTAL = REPLACE + O&P
```

### Grand Total Calculation
```
Line Item Total = sum of all TOTAL column values
Material Sales Tax = sum of all TAX column values
Subtotal = Line Item Total + Material Sales Tax
Overhead = Subtotal × 0.10  (wait — O&P already in line items)
Profit = Subtotal × 0.10
RCV = Subtotal + Overhead + Profit
```
⚠️ Note: In the IFC estimate format, O&P is baked INTO each line item (not added at summary level).
The summary pages show totals but O&P is already captured in each line's TOTAL.
The "Recap of Taxes, Overhead and Profit" page shows O&P = 0% because it's already in line items.

---

## SECTION GROUPING LOGIC

Sections in the supplement = physical areas or trade groups:

| Section Type | When to Use | Examples |
|---|---|---|
| **Physical area** | Multi-trade scope on same structure | Dwelling Roof, Detached Garage Roof |
| **Trade group** | Single trade across structure | Gutters, Fence, Windows |
| **Custom item** | Specialty work | Pergola, Shutters, Corbels, Copper Bay Window |
| **Admin** | Always present if applicable | General, Labor Minimums Applied, O&P |
| **Interior** | If interior damage included | Upstairs Living Area, Stairs |

### Section Order Convention (observed from real PDFs)
1. Dwelling Roof (always first)
2. Detached Garage Roof (if applicable)
3. Exterior elevations that had damage (Front, Back, Left, Right)
4. Trade sections (Gutters, Windows, Fence, Siding...)
5. Specialty sections (Pergola, Copper, Shutters...)
6. Interior (if applicable)
7. Debris Removal
8. General / Labor Minimums Applied
9. O&P (if standalone $0 line item with F9 boilerplate)

---

## KEY BUSINESS RULES

1. **O&P = 20%** (10% + 10%) — always fight for it, often goes to appraisal
2. **State Farm often denies O&P** — this is a known fight, not a mistake
3. **INS price lists are OLDER** — IFC uses current (higher) price list → always a gap
4. **REMOVE lines = labor to tear off** — always include when replacing
5. **Labor Minimums** — each trade touched has a minimum charge, always goes in own section
6. **Drip edge** — commonly missed by insurance, always include, EV = Eaves + Rakes
7. **Gutter guard, splash guards** — almost always missed by insurance
8. **Steep/High charges** — always two lines each (remove + replace)
9. **Waste factor** — use EV suggested %, round UP to 1/3 SQ
10. **Interior damage** — if INS includes it, IFC should match or exceed
11. **Sub bids must be marked up 30%** before going into bid item REPLACE value

---

## WHAT VANESSA AUDITS BEFORE SENDING

Per @start skill:
- Every EV measurement used correctly
- All flashings included (drip edge, step, apron, valley, counterflashing)
- All steep/high charges applied
- Bid items have correct marked-up amounts
- F9 notes are complete and justified
- Photos exist for every line item being claimed
- Labor minimums for all trades touched
- O&P line item with justification (if 3+ trades)
- Gutter diagram matches LF in estimate

---

## FILES BY SUPPLEMENT VERSION

| File | What Changed |
|---|---|
| `Supp 1.0` | Initial build — full scope |
| `Supp 2.0` | After INS responds — add/remove/adjust items |
| `Supp 3.0` | After second INS response — continued fight |
| `INS X.0` | Insurance's latest estimate (their counter-response) |
| `SOL` | Summary of Loss (insurance's initial payout letter) |
| `EagleView` | Measurement report (may be ordered multiple times) |
| `Reinspection Report` | If reinspection was done (photos + measurements) |
| `GutterDiagram` | Gutter layout diagram used to justify LF |
