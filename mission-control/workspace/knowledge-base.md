# Knowledge Base — Supplement Lessons Learned

Distilled from real job reviews. Use these patterns when answering questions, running skills, or advising the team.

---

## QA Rules (Critical — Apply to Every Job)

### Quantity Matching
- **If INS quantity > IFC quantity on ANY line item → UPDATE our estimate to match or exceed.** Leaving ours lower risks INS noticing and reducing theirs. (Source: Steffek L1)
- **Cross-reference INS line items against our estimate.** Flag anything INS has that we don't — even small items like pipe jack flashing add up. (Source: Steffek L8)

### Bid Math Verification
- Verify bid markup math traces cleanly: `retail ÷ 1.3` should equal original bid. If not, flag it. Ghost communication creates untraceable decisions. (Source: Steffek L3)

### Depreciation
- **Check NRD column, not just depreciation.** Recoverable depreciation = we get it back after job completion. Only NRD is a real loss. (Source: Sanchez L12)
- State Farm depreciation is usually recoverable — don't let large holdbacks scare you. (Source: Schmidt L35)

### Pricelist
- **Don't waste F9 notes on pricelist price differences.** Focus on quantity/scope disputes. Pricelist variance is noise. (Source: Schmidt L32)
- If INS uses a newer (higher) pricelist, that's generally favorable for IFC. (Source: Engle L50)

---

## Trade Strategies

### Xactimate vs Bid Items
- **Use whichever pays more.** If Xactimate codes exist for the trade AND pay more than 30% marked-up bid → use Xactimate. (Source: Steffek L4)
- Gutters: Xactimate almost always wins over bid.
- Fence/Pergola: No good Xactimate codes for power wash + stain → bid item is the only option.
- Garage doors: Bid often higher, but INS may deny. Push bid, accept Xactimate if forced.
- D&R costs absorbed by Xactimate margin — not separately line-itemed. (Source: Steffek L5)

### Steep Charges on Waste SQ
- ~50/50 fight. Always include steep on waste SQ in initial supplement.
- Argument: labor for waste material is still performed on steep roof.
- INS counterargument: "steep on actual SQ only, not waste."
- **Don't hold up a job over this.** Move on if INS won't budge. (Source: Steffek L2)
- **Allstate has explicit "no steep on waste" policy** — include anyway but expect denial. (Source: Engle L48)

### Fence Strategy
- Pre-loss condition argument: partial treatment creates visual mismatch.
- Fight for full fence scope, not just damaged sections. (Source: Sanchez L15)
- **Check fence NRD early.** Old fences with high NRD may not be worth supplementing. If fence NRD > 40% of RCV, warn that economics may not work. (Source: Engle L46)
- Sales rep decides whether to keep fighting or drop.

### Chimney
- Chimney bid = cap/chase only. Chimney flashing is a SEPARATE Xactimate line item. (Source: Dawson L27)
- When multiple chimney bids exist → human in the loop decides. (Source: Sanchez L13)

### Solar Panels
- INS can pay MORE than IFC's Xactimate on specialty bids. (Source: Engle L41)
- Submit actual bid alongside Xactimate. Allstate uses "Bid Item" line to reconcile difference.
- When INS pays more than our bid, DON'T TOUCH IT. Accept the gift. (Source: Engle L53)

### O&P
- When denied and significant → fight through supplementing → escalate to appraisal if needed.
- Appraisal usually gets O&P approved. After appraisal, neither side can dispute. (Source: Steffek L7)
- **O&P and individual trade denials are connected.** Losing trades weakens the O&P case. Fight trades first, then use approved scope to justify O&P. (Source: Schmidt L31)
- O&P gets abandoned on small/non-complex claims. Flag complexity score at @start. (Source: Schmidt L38)

### 3-Tab Shingles
- Allstate says hip/ridge cap is "included in waste" for 3-tab. Different from laminated/architectural. (Source: Engle L42)
- IFC still fights it regardless — worth the attempt.

### Starter Strip
- Needs PRE-EXISTING evidence. Photos of starter on rakes BEFORE tear-off. Once roof is torn off, evidence is gone. (Source: Engle L43)

---

## Domino Effect Strategy
- Getting one trade approved creates justification for adjacent/connected work. (Source: Dawson L22)
- **Roof tear-off is the #1 domino trigger** → justifies flashing, starter, IWS, anything touched during removal.
- Chimney flashing → chimney siding. Gutter work → fascia access.
- Flashing is ALWAYS a domino from roof work — tear-off damages existing flashing.

---

## F9 Note Strategy

### Pattern
```
Our line item X covers insurance line item Y.
We are requesting [additional/approval of] [QTY] [UNIT] [description].
1. The difference is $X. [Xactimate/Our cost] is $Y. While in insurance report cost is $Z.
   a. See Attachment [N] ([description]) which [evidence].
   b. [Technical justification for why the item is needed].
```

### Evolution
- Best effort from day 1. (Source: Sanchez L16)
- If denied AND denial makes sense → update F9 with better evidence (photos, IRC codes, measurements).
- If denied AND doesn't make sense → Cathy handles via phone, not rewritten F9.
- Phase 2 supplements can be the same estimate re-sent with a targeted photo report addressing the denial. (Source: Steffek L10)

### Hard Rule
- **Never re-send without new supporting documentation.** Each submission must contain something NEW — photos, measurements, codes, bids. Re-sending identical docs burns a round. (Source: Schmidt L28)

---

## Carrier Patterns

### Allstate
- Item-by-item email responses (not always updated Xactimate).
- Firm on steep/O&P denial. Requires photo evidence.
- NRD on Other Structures (50%). Accepts sub bids for non-Xactimate trades.
- **RPS Factor** (Roof Surface Payment Schedule) — additional % reduction on top of depreciation. Brutal for older roofs. (Source: Dawson L24)
- Wants itemized + comparative bids when denying bid items. (Source: Dawson L25)
- Uses "Bid Item" line to reconcile bid vs Xactimate pricing. (Source: Engle L45)
- Hip/ridge cap "included in waste" for 3-tab shingles. (Source: Engle L42)
- Explicit "no steep on waste" policy. (Source: Engle L48)

### State Farm
- Very documentation-heavy. Won't approve without photos. (Source: Sanchez L20)
- Uses depreciation aggressively but mostly RECOVERABLE. (Source: Schmidt L35)
- May use own pricelist (not Xactimate).
- Responds with updated estimates.
- Can change adjusters mid-claim.
- Reinspection process can take months.
- **State Farm responds to photos, not arguments.** Every denied item that eventually gets approved gets there through NEW photographic evidence. (Source: Schmidt L29)

---

## Decision Authority
- **Sales reps have FINAL authority** on job decisions: fight or drop a trade, go to appraisal or not, accept a compromise. (Source: Engle L51)
- **Sup never independently decides to accept a lower number.** Human decides when to stop fighting. (Source: Sanchez L14)
- When multiple bids exist → human in the loop decides. Sup presents options. (Source: Sanchez L13)

---

## Workflow Intelligence

### Adjuster Calls Are Gold
- A single call can produce an itemized list of exactly what's needed for each denied item. (Source: Engle L47)
- Read INS denial as a checklist of what to submit next. If they tell you what they need, give it to them. (Source: Schmidt L30)

### Sending Without Adjuster
- Valid strategy. Sending supplement can trigger adjuster assignment. Don't wait. (Source: Engle L44)

### Claims Can Be Reopened
- Formally denied/closed claims can be fought back open through persistent communication + photo evidence. (Source: Sanchez L18)

### Production Evidence Gap
- **Systemic issue:** production teams don't always capture photos when doing work on disputed items. (Source: Schmidt L34, Engle L52)
- Two confirmed cases: chimney tear-off photos requested → fell through. Starter strip photos during install → fell through.
- When production is doing work on disputed items, send reminders/alerts.

### Scope Shrinkage
- Not every gameplan item makes it to supplement. Evidence quality gates what we can fight for. (Source: Schmidt L39, L33)
- Photo gaps = revenue gaps.

### Triage by Claim Size
- Big claims reward supplementing. Prioritize effort by claim size and expected supplement potential. (Source: Engle L49)
- Schmidt: $831 net gain over 2+ months (3% increase). Engle: $19,914 gain (70% increase).

### Coverage Splits
- Fence/shed under "Other Structures" / "Dwelling Extension" may have different (often lower) deductible. (Source: Schmidt L36)

### One Bid, Multiple Scopes
- A single contractor bid can cover different scopes. Each scope = separate line item with its own markup + O&P. Not double-counting. (Source: Dawson L21)
