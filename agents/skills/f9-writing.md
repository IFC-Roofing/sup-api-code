# F9 Writing Rules — Carrier-Facing Justification Notes

## What is an F9?
An F9 note is a justification attached to a supplement line item. It explains to the insurance adjuster WHY this item is needed. Named after the F9 key shortcut in Xactimate for adding notes.

## F9 Structure
Every F9 follows this pattern:
1. **Opening sentence** — What the item is and what happened (forgotten, wrong qty, quality mismatch)
2. **Request line** — "We are requesting X [unit] of [item]."
3. **Numbered justification** — Evidence-backed bullets:
   a. Measurement reference (EagleView attachment)
   b. Photo reference (Photo Report)
   c. Code/production/manufacturer reference (when applicable)
   d. Dollar difference (for adjusted items)

## F9 Scenarios
Each item falls into one of these scenarios:

### "Did INS FORGET the line item?"
- Item is in our scope but NOT in insurance estimate
- F9 starts: "The insurance report left out the [item]."
- Must reference evidence: EV measurements, photos, or production necessity

### "Did INS get the QUANTITY wrong?"
- Item exists in both but INS has less quantity
- F9 starts: "Our line item X covers insurance line X."
- Must show: our qty vs their qty, dollar difference, EV measurements

### "Did INS get the QUALITY wrong?"
- INS has a lower grade than what's actually installed
- F9 references: ITEL report, manufacturer specs, like-kind-and-quality policy requirement
- Example: 35-year shingle discontinued → must use 40-year (high grade)

### "Did INS get the PRICE wrong?"
- Same item, same qty, but unit price differs from pricelist
- Usually handled via pricelist negotiation, NOT via F9
- Only write F9 if carrier is using wrong pricelist entirely

### "Bid replacement"
- Xactimate can't capture complexity → market bid from subcontractor
- F9 references: attached sub bid, photo report
- Must explain WHY Xactimate is insufficient for this specific work

## FORBIDDEN LANGUAGE — NEVER use in F9 text
These terms trigger claim denials. NEVER appears in any carrier-facing F9:

| ❌ FORBIDDEN | ✅ USE INSTEAD |
|-------------|---------------|
| "water damage" | "Substrate is structurally compromised and cannot support new installation" |
| "wood rot" / "rot" / "rotted" | "Substrate is structurally compromised" |
| "decay" / "deterioration" | "Existing [component] will be damaged during tear-off and must be replaced" |
| "wear and tear" / "aging" / "weathering" | "Existing [component] cannot be reused after removal" |
| "maintenance issue" | (never mention — reframe as production necessity) |
| "pre-existing condition" | (never mention — focus on production/code requirement) |
| "matching" (aesthetic) | "Replacement must integrate with existing structure to maintain uniform appearance and property value" |
| "cosmetic matching" | (never use — reframe as like-kind-and-quality) |
| "policy states" / "your policy requires" / "per policy section [X]" | Use IRC/building code references or production-based language instead |

## Key Principle: Production-Based Language
Frame everything around WHAT IS REQUIRED TO DO THE WORK, not what the policy says.

**Good:** "During tear-off, the existing chimney flashing will be compromised and cannot be reused. Replacement is required to maintain a weather-tight seal."

**Bad:** "Per your policy, like-kind-and-quality requires replacing the chimney flashing because it has deteriorated."

## Evidence Hierarchy
1. **EagleView measurements** — strongest for quantity disputes
2. **Photo evidence** — strongest for forgotten items and damage claims
3. **Sub-contractor bid** — strongest for pricing/complexity arguments
4. **Building code (IRC)** — strongest for code upgrade items
5. **Manufacturer specs** — strongest for quality disputes
6. **Production necessity** — "required to perform approved scope"

## F9 Quality Rules
- Minimum 2 sentences or bullets per F9
- Always include at least one evidence reference (EV, photo, bid, code)
- Fill ALL placeholder values (XX, $XX.xx, line numbers) with real data
- F9s are EXTERNAL documents — zero internal IFC language (@ifc, @supplement, "game plan", "strategy")
- If low confidence on an item → still draft best F9 but flag LOW_CONFIDENCE

## Carrier-Specific Notes
- **USAA** — Outlier that bundles starter into waste. Most other carriers pay starter separately.
- When rebutting denials in Phase 2: explicitly address the carrier's stated denial reason, use their language as the problem statement, then rebut with evidence.
