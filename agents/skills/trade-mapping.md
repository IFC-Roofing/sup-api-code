# Trade Mapping — Item Attribution Rules

## Flow Tags (Trade Cards)
Each project has trade cards tracked in Flow. These map to @tags:

### Roof Trades
- `@shingle_roof` — Main dwelling shingle roof (tear-off, shingles, felt, steep charges, high roof charges)
- `@flat_roof` — Flat/roll roofing sections
- `@garage` — Detached garage roof (separate structure, separate EV measurements)
- `@metal` — Standing seam, metal panels, custom metal work

### Roof Components (attributed to @shingle_roof unless standalone)
- Drip edge, starter strip, hip/ridge cap, valley metal
- Step flashing, counter flashing, apron flashing
- Pipe jacks (R&R + prime & paint)
- Exhaust vents, turbines, power vents, ridge vents
- Ice & water shield, synthetic underlayment
- Satellite D&R, solar panel D&R

### Exterior Trades
- `@gutter` — Gutters, downspouts, gutter guards/screens, splash guards, gutter D&R
- `@chimney` — Chimney cap, chase cover, chimney flashing (flashing = Xactimate, cap/cover = usually bid)
- `@fence` — Wood fence, iron fence, staining, painting, pressure washing
- `@paint` — Exterior painting, staining (siding, trim, beams, fascia, soffit, garage doors)
- `@siding` — Siding repair/replacement, Hardie board, vinyl, stucco
- `@window` — Window screens, window R&R, FoGlass bids
- `@garage_door` — Garage door panel/full replacement (usually bid item — Southwest Garage Door)
- `@stucco` — Stucco patching and refinishing (usually bid item — Southern Royal)

### Interior
- `@interior` — Ceiling/wall repairs, drywall, texture, paint (only storm-related)

### Support Items
- `@pergola` / `@gazebo` / `@patio` — Pergolas, gazebos, patio covers, beams
- `@pool` — Pool tarp/protection during roof install

### General / Labor
- Labor minimums — go in their own section
- Debris removal / dumpster — attributed to primary trade (usually roof)
- Building permits — General section
- O&P — own section/line at end

## Attribution Edge Cases
These items are commonly misattributed. Follow these rules:

| Item | Attribute To | Reason |
|------|-------------|--------|
| Dumpster / debris haul | @shingle_roof | Primary debris source is roof tear-off |
| Satellite D&R | @shingle_roof | Must remove for roof install |
| Solar panel D&R | @shingle_roof | Must remove for roof install |
| Electrician (solar reconnect) | @shingle_roof | Part of solar D&R scope |
| Gutter D&R | @shingle_roof | Required to replace drip edge under gutters |
| Siding removal (for flashing) | @siding OR @shingle_roof | Context-dependent: if removing to access roof flashing → roof |
| Chimney flashing | @chimney | Always chimney, even though it's at the roof |
| Pipe jack paint | @shingle_roof | Part of roof component scope |
| Pergola/beam staining | @paint OR @pergola | If standalone scope → @pergola; if part of exterior paint → @paint |
| Tarp for pool | @pool | Separate protection scope |
| Building permits | General | Not trade-specific |

## Convo Tags (post_notes)
These are conversation tags used in project notes, NOT trade cards:

- **@ifc** — The GAME PLAN. Overall strategy for the project. Critical for supplements — BUILD bases scope decisions on this.
- **@supplement** — Special supplementing strategies. Internal-only. NOT included in anything sent to insurance. Examples: asking for one trade but money goes to another, requesting D&R of gutters because roof replacement requires it.
- **@momentum** — Status updates. Context for what happened and when. Examples: what got approved/denied, what was sent.
- **@client** — Customer communication notes.
- **@Bill** / **@BillHome** / **@Accounting** — Billing/accounting markers.
- **@install** — Production dept game plan.

## Flow Card Emojis
- 👍 = doing this trade
- 👎 = not doing
- 💰 = enough money to start installation
- 👏 = fully approved
- 🛑 = not enough money
- 📥 = no bid / unknown
- 🚩 = homeowner decision needed
