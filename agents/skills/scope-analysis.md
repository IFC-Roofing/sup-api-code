# Scope Analysis — How BUILD Compares INS vs Actual Scope

## Purpose
BUILD's core job is to determine what's missing, what's underscoped, and what's correctly covered in the insurance estimate. This skill defines the methodology.

## Step 1: Parse Insurance Estimate
Extract every line item from INS:
- Item number, description, trade, qty, unit, unit price, total
- Group by section/trade
- Note total RCV

## Step 2: Parse EagleView
Extract all measurements per structure:
- Total SQ (measured), Suggested SQ (with waste), Waste %
- Eaves LF, Rakes LF, Ridges LF, Hips LF, Valleys LF
- Step Flashing LF, Drip Edge LF
- Pitch, Stories, Facets

## Step 3: Pull Sub Bids
From Flow action_trackers:
- Trade tag, sub name, scope description
- retail_exactimate_bid = price to use in supplement
- Each bid has line items with amounts

## Step 4: Pull Convo Context
From post_notes:
- @ifc = game plan (what trades are we doing, strategy)
- @supplement = supplementing strategy (internal only)
- @momentum = status updates

## Step 5: Standard Roof Checklist
Every roof supplement should check for these items. If INS is missing them AND evidence supports adding them, flag as ADDED:

### Always Check (Roof)
| Item | Source for Qty | Evidence Needed |
|------|---------------|-----------------|
| Shingle tear-off | EV measured SQ | Always needed for replacement |
| Shingles (install) | EV suggested SQ (with waste) | Always needed |
| Roofing felt / underlayment | EV measured SQ | Always needed |
| Starter strip | EV drip edge LF (eaves + rakes) | Always needed — separate from waste |
| Drip edge R&R | EV eaves + rakes LF | Photo showing felt under drip edge |
| Hip/Ridge cap | EV ridges + hips LF | Always needed for replacement |
| Valley metal | EV valleys LF | If valleys exist on structure |
| Step flashing | EV step flashing LF | If wall-to-roof transitions exist |
| Counter/apron flashing | Field measurement or photos | Where roof meets vertical surfaces |
| Pipe jacks R&R | Photo count | Count visible in photo report |
| Pipe jack prime & paint | Same as above | If previously painted (photo evidence) |
| Exhaust vent R&R | Photo count | Count visible |
| Steep roof charges | EV pitch per facet | If any facet ≥ 7/12 pitch |
| High roof charges (2-story) | Photos / EV | If structure is 2+ stories |
| Ice & water shield | EV eaves + valleys LF | Required by code in most jurisdictions |
| Ridge vent | EV ridge LF | If currently installed |
| Satellite D&R | Photos | If satellite on roof |

### Trade-Specific Checklists

#### Gutters
- Gutter/downspout R&R (hand measurements or gutter diagram)
- Gutter guards/screens (if present)
- Splash guards (if present — HOA or homeowner decision)
- Prime & paint gutter/downspout (if previously painted)
- Gutter D&R (if gutters must be removed for drip edge work)

#### Chimney
- Chimney flashing R&R (always separate from cap bid)
- Chimney cap / chase cover (usually bid item)

#### Fence
- Powerwash + paint/stain (wood or iron)
- Picket replacement (if needed pre-powerwash)

#### Windows
- Screen repair/replacement (usually bid item — FoGlass)

#### General
- Dumpster / debris haul
- Building permits
- Labor minimums (when scope is small but still requires crew mobilization)

## Step 6: Comparison Logic

### For each INS item:
1. Is it in our scope (@ifc says we're doing this trade)? → Keep
2. Does the qty match EV? → If INS qty < EV → flag UNDER_SCOPED, recommend adjustment
3. Does the qty exceed EV? → If INS qty > EV → flag CARRIER_HIGHER_THAN_EV, **keep carrier's qty** (more money)
4. Is there a sub bid for this trade? → If yes, this item gets REPLACED by the bid

### For each expected item NOT in INS:
1. Is it on the standard checklist above?
2. Does evidence support it (photo, EV, code, production)?
3. If yes → flag as ADDED_VS_INSURANCE with scenario type

### For each sub bid:
1. Map to trade
2. Drop ALL INS items from that trade section
3. Add bid as replacement item
4. Note: chimney bid ≠ chimney flashing (flashing stays as Xactimate item)

## Step 7: Measurement Comparison Table
For every measurable item:

| Measurement | EV Qty | INS Qty | IFC Qty | Flag |
|------------|--------|---------|---------|------|
| If INS > EV | — | — | — | CARRIER_HIGHER_THAN_EV — keep carrier's |
| If IFC < both EV and INS | — | — | — | UNDER_SCOPED — raise to min(EV, INS) |
| If IFC > both EV and INS | — | — | — | OVER_SCOPED — lower to EV |

## Step 8: Scope Maximization
After the standard comparison, look across ALL trades for defensible items that could be added:
- Only suggest if: clear photo support, required by code/manufacturer for approved work, production condition item unavoidably damaged during approved scope, or legitimate labor minimum
- Do NOT suggest: "nice to have" / purely aesthetic / obviously non-storm items
- Priority levels: HIGH (strong evidence + high dollar), MEDIUM (solid evidence), LOW (possible but needs more evidence)

## Output
BUILD produces the handoff JSON (see handoff-schema.json) with all analysis populated. SUP consumes this to write the actual supplement.
