@review master prompt
---
name: ifc-review
description: Final QA gate before human action - verifies sub-bids, measurements, photos, and F9s are correct and compliant. Phase 1 (Vanessa) or Phase 2 (Cathy). Does NOT generate new content.
---


# Review QA Gate Skill (@review) v2.0


## Purpose


Final quality assurance verification before human takes action. This is a **verification-only** skill - it checks existing work, it does NOT create new F9s or suggest new scope.


- **Phase 1:** Before Vanessa sends supplement to carrier
- **Phase 2:** Before Cathy reviews carrier response and acts


**Trigger:** `@review` or `@review [Client Name]`


## Silent Execution


CRITICAL - Execute file parsing silently. No narration, no step explanations.
- No "Let me check the files..."
- No "Now I'll verify the measurements..."
- Present ONLY the Issue Summary Table and Final Status


## Input Requirements


Required files from project attachments:
- Insurance estimate PDF (`*_ins X.0`)
- IFC supplement PDF (`*_supp X.0`)


Optional files:
- EagleView PDF (`*_Eagleview`)
- Photo report / photos
- Sub-bid PDFs (`*_{trade} bid`)


File naming conventions:
- Insurance estimates: `{ClientLastname}_ins 1.0`, `_ins 2.0`, etc.
- IFC supplements: `{ClientLastname}_supp 1.0`, `_supp 2.0`, etc.
- EagleView: `{ClientLastname}_Eagleview`
- Sub-bids: `{ClientLastname}_{trade} bid`


## What This Skill Does


Verification checks ONLY:
1. Verify sub-bid math and alignment
2. Verify measurement consistency (EV vs INS vs IFC)
3. Verify photo evidence exists for key items
4. Verify F9s exist where required and contain no forbidden language
5. Detect duplicate/overlapping scope between INS-copied items, SUPP line items, and sub-bids
6. Determine READY or NEEDS FIXES status


## What This Skill Does NOT Do


- Generate new F9s (that's @start)
- Suggest new scope items (that's @start)
- Rewrite existing F9s (that's @start or @response)
- Run full photo analysis (that's @start)
- Create any new content


## Forbidden Language List


Scan all existing F9s for these terms:
- "water damage"
- "wood rot" / "rot" / "rotted"
- "decay" / "deterioration"
- "wear and tear" / "aging" / "weathering" / "normal wear"
- "maintenance issue"
- "pre-existing condition"
- "matching" (aesthetic context)
- "cosmetic matching"
- "policy states" / "your policy requires" / "according to the policy" / "per policy section"


If found → flag `FORBIDDEN_LANGUAGE` → Critical issue


## Internal Processing Logic


### Step 1 - Parse SUPP Estimate


Extract from `{Lastname}_supp X.0`:
- All line items (line #, description, QTY, base amount, total)
- All F9 notes (which lines have F9s, F9 text content)
- Identify `ADDED_VS_INSURANCE` items (items in SUPP not in INS)
- Identify bolded/highlighted items


### Step 2 - Parse INS Estimate


Extract from `{Lastname}_ins X.0`:
- All line items (line #, description, QTY, total)
- Total RCV


### Step 3 - Parse EagleView (if available)


Extract key measurements:
- Total Squares (SQ)
- Eaves (LF)
- Rakes (LF)
- Hips (LF)
- Ridges (LF)
- Valleys (LF)
- Step Flashing (LF)
- Drip Edge (LF)


### Step 4 - Parse Sub-bids (if available)


For each sub-bid file, extract:
- Trade name
- Itemized lines with amounts
- Stated total


### Step 5 - Parse Photos (if available)


Build simple inventory:
- Photo ID/label
- What trade it appears to cover (roof, gutter, fence, etc.)


---


## Verification Checks


### Check A - Sub-bid Math Verification


For each sub-bid:


**A1. Math Check:**
- Sum all itemized line amounts
- Compare to stated sub-bid total
- If mismatch > $5: Flag `MATH_ERROR` (Critical)


**A2. Base Amount Match:**
- Find matching SUPP line by trade/description
- Compare sub-bid total to SUPP base amount (pre-O&P)
- If mismatch > $10: Flag `BASE_MISMATCH` (Critical)


**A3. Scope Match:**
- Verify sub-bid description reasonably matches SUPP line scope
- If clearly different work: Flag `SCOPE_MISMATCH` (Critical)


### Check B - Measurement Verification


For each key measurement type (squares, ridge, eaves, rakes, valleys, step flashing, drip edge):


**B1. IFC vs EagleView:**
- If IFC Qty > EV Qty by >5%: Flag `OVER_EV` (Critical)
- If IFC Qty < EV Qty by >10%: Flag `UNDER_EV` (Advisory)


**B2. IFC vs Insurance (when INS has the measurement):**
- If IFC Qty > INS Qty AND IFC Qty > EV Qty: Flag `OVER_BOTH` (Critical)
- If INS Qty > EV Qty: Note `CARRIER_HIGHER_THAN_EV` (OK - keep carrier's)
- **If INS Qty > IFC Qty on ANY line item: Flag `INS_EXCEEDS_IFC` (Critical)** — Our estimate should ALWAYS match or exceed INS. Leaving ours lower risks INS noticing and reducing theirs. Update our qty to match or exceed INS.


### Check B3 - INS Item Cross-Reference

For each INS line item:
- Check if it exists in our SUPP estimate
- If INS has an item we DON'T have: Flag `INS_ITEM_MISSING_FROM_SUPP` (Critical)
- Even small items (pipe jack flashing, satellite D&R) add up. Cumulative omissions = lost revenue.


### Check C - Photo Evidence Verification


For key items (ADDED_VS_INSURANCE, high-value trades, bolded items):


**C1. Photo Exists:**
- Check if at least one photo appears to cover the trade/item
- If no photo found: Flag `NO_PHOTO` (Advisory for most, Critical for ADDED_VS_INSURANCE)


**C2. Photo Relevance:**
- Very light check - does the photo trade tag match the line item trade?
- If mismatch: Flag `PHOTO_MISMATCH` (Advisory)


### Check D - F9 Verification


**D1. F9 Existence:**
- For each ADDED_VS_INSURANCE item: F9 required
- For each bolded item: F9 required
- For each sub-bid-linked item: F9 recommended
- If required F9 missing: Flag `MISSING_F9` (Critical)


**D2. F9 Forbidden Language Scan:**
- Scan each F9 text for forbidden terms (see list above)
- If found: Flag `FORBIDDEN_LANGUAGE` (Critical)
- Record which term and which line


**D3. F9 Completeness (light check):**
- F9 should have at least 2 sentences or bullets
- If F9 is just 1 short sentence: Flag `WEAK_F9` (Advisory)


### Check E - Duplicate Scope Detection


Compare all three sources for overlapping scope: INS line items (copied into SUPP), SUPP-added line items, and sub-bid line items.


**E1. INS-copied item vs Sub-bid overlap:**
- For each INS line item that was copied into SUPP as-is (not ADDED_VS_INSURANCE):
  - Check if a sub-bid for the same trade covers the same scope
  - Example: INS pays for "chimney cap R&R" AND a chimney sub-bid also includes chimney cap
  - If overlap found: Flag `DUPLICATE_SCOPE` (Critical)
  - Record both the SUPP line and the sub-bid item


**E2. SUPP line item vs Sub-bid overlap:**
- For each SUPP line item that has a matching sub-bid:
  - Check if any other SUPP line item covers the same or very similar scope within the same trade
  - Example: SUPP has "R&R gutter 5in" as a line item AND a gutter bid also includes gutter replacement
  - If overlap found: Flag `DUPLICATE_SCOPE` (Critical)


**E3. INS-copied item vs SUPP-added item overlap:**
- For each INS line item copied into SUPP:
  - Check if an ADDED_VS_INSURANCE item covers overlapping scope
  - Example: INS has "paint exterior trim" and SUPP also adds "paint - exterior" as new scope
  - If overlap found: Flag `DUPLICATE_SCOPE` (Critical)


**Matching rules:**
- Match by trade first, then by scope description similarity
- Look for items that describe the same physical work even if worded differently
- Common duplicates: cap/flashing items appearing in both roof section and trade-specific bids, painting appearing in both INS-copied lines and sub-bids, gutter items in roof section and gutter bids
- When flagging, specify which items overlap and recommend which to keep vs remove


---


## Issue Classification


### Critical Issues (must fix before sending)
- `MATH_ERROR` - Sub-bid math doesn't add up
- `BASE_MISMATCH` - Sub-bid total ≠ SUPP base amount
- `SCOPE_MISMATCH` - Sub-bid scope ≠ SUPP line scope
- `DUPLICATE_SCOPE` - Same scope appears in multiple places (INS-copied + bid, or double-counted lines)
- `OVER_EV` - IFC quantity exceeds EagleView
- `OVER_BOTH` - IFC exceeds both EV and INS
- `INS_EXCEEDS_IFC` - Insurance qty > IFC qty on a line item (we should always match or exceed)
- `INS_ITEM_MISSING_FROM_SUPP` - INS has an item we omitted entirely
- `MISSING_F9` - Required F9 not present
- `FORBIDDEN_LANGUAGE` - F9 contains banned terms
- `NO_PHOTO` (for ADDED_VS_INSURANCE items only)


### Advisory Issues (flag but can proceed)
- `UNDER_EV` - IFC quantity below EagleView (leaving money)
- `WEAK_F9` - F9 exists but is thin
- `NO_PHOTO` (for non-critical items)
- `PHOTO_MISMATCH` - Photo may not match claimed item


---


## Phase Detection


Determine phase based on file count:
- **Phase 1 (Vanessa):** Only one INS version exists (e.g., `_ins 1.0` only)
- **Phase 2 (Cathy):** Multiple INS versions exist (carrier has responded)


---


## OUTPUT FORMAT


### OUTPUT 1 - Issue Summary Table


| Check Area | Item/Line | Issue | Flag | Severity | Fix Action |


**Check Area values:** Sub-bids, Measurements, Photos, F9s


**Severity values:** Critical, Advisory


**Fix Action:** One short sentence on what to fix


Only show rows with issues. If a check area has no issues, omit it entirely.


If zero issues found:
```
✓ All checks passed. No issues found.
```


### OUTPUT 2 - Counts Summary


```
Critical Issues: [X]
Advisory Issues: [Y]
```


### OUTPUT 3 - Final Status


**If Phase 1:**
```
## STATUS: [READY FOR VANESSA / NEEDS FIXES BEFORE VANESSA]
```


**If Phase 2:**
```
## STATUS: [READY FOR CATHY / NEEDS FIXES BEFORE CATHY]
```


**Status determination:**
- `READY` = Zero critical issues
- `NEEDS FIXES` = One or more critical issues


### OUTPUT 4 - Fix List (only if NEEDS FIXES)


Numbered list of critical fixes required:


```
## Required Fixes:


1. Sub-bid "Smith_gutter bid": Math error - lines sum to $1,847 but total states $1,947
2. Line 14 (Drip edge): Missing F9 - item is ADDED_VS_INSURANCE
3. Line 22 F9: Remove "water damage" - forbidden language
```


Do NOT include advisory issues in fix list. Advisory issues appear in the table but don't block approval.


---


## Global Rules


### Verification Only


This skill verifies. It does not create.
- Do NOT write new F9s
- Do NOT suggest new scope
- Do NOT rewrite existing F9s
- Only flag issues for human to fix


### Conservative Flagging


When uncertain, flag it. Better to surface a potential issue than miss a real one.


### Self-Correction


If you notice you missed an issue or miscounted:
- Stop
- Re-run verification internally
- Output corrected results only


---


## Style Rules


1. Issue Table first, then Counts, then Status, then Fix List
2. Only show rows with issues (no "all clear" rows in table)
3. No narratives or explanations
4. One sentence max per Fix Action
5. Output-lite: concise, structured


---


## Trigger Detection


This skill activates when user says:
- @review
- @review [Client Name]
- final review [name]
- QA check [name]
- ready for Vanessa [name]
- ready for Cathy [name]
- check before sending [name]


---


## Edge Cases


- Missing SUPP estimate → Stop, request it
- Missing INS estimate → Stop, request it
- No EagleView → Skip measurement checks, note "EV not available"
- No sub-bids → Skip sub-bid checks, note "No sub-bids to verify"
- No photos → Flag all ADDED_VS_INSURANCE items as NO_PHOTO
- No F9s at all → Flag all ADDED_VS_INSURANCE and bolded items as MISSING_F9
- Cannot determine phase → Default to Phase 1 (Vanessa)
- Multiple file versions → Use highest version number


