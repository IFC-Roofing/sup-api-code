@appraisal master prompt
---
name: appraisal
description: Appraisal package prep - compares IFC estimate to EagleView and sub-bids, checks photo presence, outputs two tables plus bullets for appraiser
---


---
name: appraisal
description: "Appraisal package prep - compares IFC estimate to EagleView and sub-bids, checks photo presence, outputs two tables plus bullets for appraiser"
---


# Appraisal Prep Skill (v1.0)


## Purpose


Prepare a clean, appraiser-friendly summary for claims going to appraisal.


**Trigger:** `@appraisal` or `@appraisal [Client Name]`


**Audience:** The insured's appraiser on IFC's side (not the carrier).


## Silent Execution


CRITICAL - Execute file parsing silently. No narration, no step explanations.
- No "Let me search for the files..."
- No "Now I'll parse the EagleView..."
- Present ONLY the final formatted tables and bullets


## Input Requirements


Required files from project attachments:
- IFC appraisal estimate (same scope as SUPP, but no F9s)
- EagleView report


Optional files:
- Sub-bid PDFs (stucco, paint, gutter, specialty trades, etc.)
- Photo report(s)


If missing required files, briefly explain what is missing and stop.


## What This Skill Does NOT Do


- Write F9s
- Draft carrier-facing letters or scripts
- Run full photo fraud mode
- Produce long narratives
- Simulate adjuster or appraiser dialogue


## Internal Processing Logic


### Step 1 - Parse IFC Appraisal Estimate


Extract line-by-line:
- Line number
- Description
- Group or area name
- Trade (roof, stucco, chimney, gutter, fence, etc.)
- Quantity and unit
- Unit price
- Line total RCV


### Step 2 - Tag Key Trades


Roof and roof-adjacent items:
- Shingles, ridge, hip, valleys
- Drip edge, flashing, step flashing
- Vents, pipe jacks, ridge vent
- Underlayment, felt, ice and water
- Decking, starter course


Sub-bid-based trades:
- Stucco, paint, specialty finishes
- Metal work, counterflashing
- Fence, garage, windows


### Step 3 - Extract EagleView Measurements


Key metrics:
- Total Squares (SQ)
- Eaves (LF)
- Rakes (LF)
- Hips (LF)
- Ridges (LF)
- Valleys (LF)
- Step Flashing (LF)
- Drip Edge total (LF)


### Step 4 - Compare IFC vs EagleView for Roof Items


For each roof line, mark one of:
- Aligned with EV
- Above EV (IFC greater than EV)
- Below EV (IFC less than EV)
- No EV metric


IMPORTANT - Being Above EV is not automatically wrong. Flag, do not judge.


### Step 5 - Check Sub-Bids vs Estimate Lines


For each sub-bid, compare bid total vs estimate line total. Mark one of:
- Matches Bid
- Over Bid
- Under Bid
- N/A


### Step 6 - Check Photo Presence (Light Mode)


Per major trade, mark one of:
- Yes
- Sparse
- No


Do NOT run heavy per-photo analysis. Presence-only.


### Step 7 - Determine Appraisal Strength


Based on EV alignment, sub-bid alignment, photo presence, and internal consistency. Mark one of:
- STRONG
- OK
- WEAK


## OUTPUT FORMAT


### Table 1 - Appraisal Item Prep


| Trade / Area | Item / Line Ref | IFC QTY and Total | EV Measurement Check | Sub-Bid Check | Photo Presence | Appraisal Strength | Notes for Appraiser |


Column values:
- Trade / Area - Roof, Stucco, Chimney, Gutter, Fence, etc.
- Item / Line Ref - Description plus line number if available
- IFC QTY and Total - Example "287 LF / $1,234"
- EV Measurement Check - Aligned with EV / Above EV / Below EV / No EV metric
- Sub-Bid Check - Matches Bid / Over Bid / Under Bid / N/A
- Photo Presence - Yes / Sparse / No
- Appraisal Strength - STRONG / OK / WEAK
- Notes for Appraiser - Max one sentence, tactical


Include all roof items, high-dollar items, and bid-based items.


### Table 2 - Trade-Level Summary


| Trade | Total IFC in Appraisal | EV Alignment | Sub-Bid Integrity | Photo Coverage | Appraisal Position |


Column values:
- Total IFC in Appraisal - Dollar amount for that trade
- EV Alignment - Mostly aligned / Mixed / Many Above EV / N/A
- Sub-Bid Integrity - Good / Mixed / Weak / N/A
- Photo Coverage - Good / Sparse / No
- Appraisal Position - Strong / Medium / Weak


### Short Action Bullets


End with 3-6 bullets for internal IFC use telling leadership and appraiser:
- What is strong
- What is weak
- Where obvious attack points are


No carrier-facing phrasing. No long paragraphs.


## Style Rules


1. Tables first, bullets second
2. No long narrative explanations
3. Do not simulate adjuster or appraiser dialogue
4. Do not invent data not visible in provided documents
5. Being Above EV or Over Bid is not automatically wrong - flag and describe only


## Trigger Detection


This skill activates when user says:
- @appraisal
- @appraisal [Client Name]
- appraisal prep for [name]
- prepare appraisal package [name]


## Edge Cases


- Missing appraisal estimate - Stop and request it
- Missing EagleView - Stop and request it
- No sub-bids - Mark Sub-Bid Check as N/A
- No photo report - Mark Photo Presence as No
- Multiple file versions - Use latest unless user specifies


