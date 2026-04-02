# Supplement 2.0 Pipeline — Spec Draft

## Overview
Generate an updated IFC supplement (Supp 2.0+) after insurance responds to a previous supplement.
Takes the previous IFC estimate as the base, applies changes from @response analysis + human decisions, and produces a new PDF.

## Trigger
`@update "Project Name"` or integrated into orchestrator as a Phase 2 mode.

## Inputs

### Required
1. **Previous IFC Supplement** (parsed) — the estimate we already sent (Supp 1.0 or N.0)
2. **Latest INS Estimate** (parsed) — the carrier's response
3. **@response output** — action table with per-item status + rewritten F9s
4. **Human decisions** — provided via convo tags or direct input:
   - Items to drop (stop fighting)
   - Items to add (new scope)
   - Bid swaps (bid → Xactimate or vice versa)
   - Quantity overrides

### Optional
- New bids (if subs provided updated/itemized/comparative bids)
- New photo reports (referenced in F9s)
- Convo context (@supplement, @ifc tags for strategy changes)

## Pipeline Steps

### Step 1 — Parse Previous IFC Supplement
- Use existing IFC supplement parser (`parse_supplement.py`)
- Extract: line items, quantities, unit prices, F9 notes, section totals, O&P
- This becomes the BASE for the new estimate

### Step 2 — Parse Latest INS Estimate
- Use existing INS parser (`parse_insurance.py`)
- Extract: line items, quantities, unit prices, RCV, depreciation, NRD

### Step 3 — Run @response Analysis
- Compare previous INS vs new INS
- Compare IFC supp vs new INS
- Produce action table:
  | Line Item | Status | Action Tag | New F9 |
  |-----------|--------|------------|--------|
  - Status: APPROVED, DENIED, PARTIAL, NEW_FROM_INS, UNCHANGED
  - Action Tag: KEEP_AS_IS, UPDATE_QTY, REWRITE_F9, DROP, ADD_NEW, SWITCH_TO_XACT, PUSH_BID

### Step 4 — Apply Automated Rules (no human needed)

These happen automatically based on lessons learned:

| Rule | Trigger | Action |
|------|---------|--------|
| **L1: INS exceeds IFC** | INS qty > IFC qty for any line item | Update IFC qty to match INS (at minimum) |
| **L8: Cross-reference** | INS has line item IFC doesn't | Flag for human decision (add or ignore) |
| **Approved items** | INS approved at our number | Keep as-is, remove F9 note (no longer disputed) |
| **Approved at different qty** | INS approved but different qty | Update to higher of (IFC, INS) |
| **F9 rewrites** | @response tagged REWRITE_F9 | Replace old F9 with new F9 from @response |

### Step 5 — Human Decision Gate ⛔
Present a summary to the human (via Slack/chat) and WAIT for approval:

```
📋 Supp 2.0 Changes for [Client Name]

✅ APPROVED (no changes needed): 
  - Shingle rfg: 94.33 SQ (INS matched)
  - Garage door bid: $2,535 approved

📈 AUTO-UPDATED (INS gave more):
  - Shingles: 92.33 → 94.33 SQ (+2 SQ, +$XXX)

✏️ F9 REWRITTEN:
  - Step flashing: new F9 addresses "not pre-existing" denial
  - Gutter screen: new F9 with photo evidence for Smart Flow

❓ NEEDS YOUR DECISION:
  - [item]: INS has pipe jack flashing ($193) we don't. Add? [Y/N]
  - [item]: Steep charges denied again. Keep fighting? [Y/N]
  - [item]: O&P denied. Keep or escalate to appraisal? [KEEP/APPRAISAL/DROP]

🆕 NEW SCOPE (from human/convo):
  - (any new items added via @supplement tags or direct input)
```

Human responds → decisions are applied.

### Step 6 — Generate Updated Estimate
- Start from previous IFC supplement line items
- Apply all changes from Steps 4 + 5
- For each line item:
  - KEEP_AS_IS → copy from previous supp (including F9 if still disputed)
  - UPDATE_QTY → update quantity, recalculate totals using same unit prices
  - REWRITE_F9 → replace F9 text, keep line item unchanged
  - DROP → remove from estimate
  - ADD_NEW → add new line item (from INS cross-reference, new bids, or new scope)
  - SWITCH_TO_XACT → replace bid item with Xactimate line items (or vice versa)
- Recalculate section totals, O&P, tax, coverage splits
- Update attachment references in F9s (new photo report numbers, etc.)

### Step 7 — Render PDF
- Same html_renderer → pdf_renderer pipeline as Supp 1.0
- Update date, version number (Supp 2.0), page headers
- Include updated F9 notes inline

### Step 8 — Upload + Notify
- Upload to Shared Drive staging folder
- Move previous supplement to Archive subfolder
- Slack notification to Alvaro with:
  - RCV comparison (Supp 1.0 vs 2.0)
  - Items changed summary
  - Drive link
  - Remaining gap vs INS

## What Changes Between Supp Versions (from @learning)

| Change Type | Frequency | Automated? |
|-------------|-----------|------------|
| Updated F9 notes | Every time | Yes (from @response) |
| Quantity updates (match INS) | Common | Yes (auto-rule L1) |
| New attachments referenced | Common | Semi (human picks photos, Sup updates F9 refs) |
| New line items added | Sometimes | No (human decision) |
| Bid → Xactimate swap | Rare | No (human decision) |
| Line items dropped | Rare | No (human decision) |
| O&P text unchanged | Almost always | Yes (same boilerplate) |

## Key Design Decisions

### 1. Previous Supp as Base (not rebuild from scratch)
Supp 2.0 should modify the existing estimate, NOT regenerate from scratch.
- Reason: Supp 1.0 was human-reviewed and approved by Vanessa. Regenerating might change things that were intentional.
- Exception: if Supp 1.0 was AI-generated by Sup, then regeneration is fine.

### 2. F9 Removal on Approved Items
When INS approves a line item at our number → remove the F9 note entirely.
- Reason: F9 notes are justification for disputed items. Approved items don't need justification.
- Keep the line item itself unchanged.

### 3. Attachment Numbering
Each supplement version may have different attachments (new photo reports, new bids).
F9 references like "See Attachment 3 (Photo Report)" need to be updated if attachment order changes.
- Approach: maintain an attachment manifest that maps attachment # to document name
- When F9s reference attachments, use the manifest to ensure correct numbering

### 4. Version Tracking
- Filename: `{CLIENT}_Supp {version}.pdf`
- Internal header date updates to generation date
- Previous version moved to Archive/ in Drive

## Dependencies
- `parse_supplement.py` — needs to handle IFC supplements (already built)
- `parse_insurance.py` — needs to handle any carrier format (already built)
- `@response` prompt — already generates action table + rewritten F9s
- `estimate_builder.py` — needs a new mode: "update" vs "create"
- `html_renderer.py` — no changes needed (same template)
- `pdf_renderer.py` — no changes needed
- `uploader.py` — needs archive-previous-version logic

## Open Questions
1. Should Supp 2.0 track what changed from 1.0? (e.g., a changelog section or just the updated F9s?)
2. ~~How to handle the Xactimate file?~~ **ANSWERED:** New jobs = Sup handles full pipeline (1.0 + 2.0+). Old/in-progress jobs = human pipeline stays. No hybrid — either Sup owns the job or humans do.
3. Should the human decision gate be synchronous (wait for response) or async (generate draft, human edits)?
4. ~~When Supp 1.0 was human-made vs AI-made~~ **ANSWERED:** Supp 2.0 pipeline only applies to jobs where Sup generated Supp 1.0. Old jobs stay human. This simplifies parsing — we always have our own structured JSON from Supp 1.0 as the base (no need to parse human-made Xactimate PDFs).

## Implementation Priority
1. **Automated quantity matching** (L1) — biggest quick win, catches human errors
2. **F9 merge from @response** — already have the rewritten F9s, just need to plug them in
3. **Human decision gate** — Slack-based approval flow
4. **Full PDF generation** — the rendering pipeline already exists
5. **Attachment manifest** — needed for F9 reference accuracy

## Relationship to Existing Tools
```
Current Pipeline (Phase 1 — Supp 1.0):
  data_pipeline.py → estimate_builder.py → html_renderer.py → pdf_renderer.py → uploader.py

New Pipeline (Phase 2 — Supp 2.0+):
  parse_supplement.py (previous IFC supp)
  + parse_insurance.py (new INS)
  + @response analysis
  + human decisions
  → update_builder.py (NEW — applies changes to base estimate)
  → html_renderer.py → pdf_renderer.py → uploader.py
```
