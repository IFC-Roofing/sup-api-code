# Trade Estimator

Estimate construction costs based on IFC's historical pricing database. The more bids processed through the bid-markup pipeline, the smarter this gets.

## Usage

```bash
cd /Users/IFCSUP/.openclaw/workspace
python3 tools/trade-estimator/estimate.py --trade "@gutter" --scope "box gutters" --qty 200 --unit LF 2>/dev/null
```

### Parameters
- `--trade` — Trade folder name: @roof, @gutter, @window, @fence, @hvac, @paint, @door, @full_interior, @metal
- `--scope` — Keywords describing the work (e.g., "box gutters", "wrought iron painting", "condenser grill")
- `--qty` — Quantity of work (e.g., 200)
- `--unit` — Unit of measurement: LF, SF, EA, SQ
- `--list-trades` — Show all trades with data point counts
- `--dump` — Dump all pricing data as JSON (for deeper AI analysis)

### Examples
```bash
# How much for 200 LF of gutters?
python3 tools/trade-estimator/estimate.py --trade "@gutter" --scope "box gutters" --qty 200 --unit LF

# What do fence painters charge?
python3 tools/trade-estimator/estimate.py --trade "@fence" --scope "painting"

# What trades do we have data for?
python3 tools/trade-estimator/estimate.py --list-trades

# Dump everything for analysis
python3 tools/trade-estimator/estimate.py --dump
```

## Output Format

Returns JSON with:
- `unit_price_range`: low / avg / high per unit
- `estimated_total`: low / avg / high (if qty provided)
- `confidence`: low (<4 data points) / medium (4-9) / high (10+)
- `subcontractors`: ranked list with contact info, avg pricing, and project history
- `data_points`: number of matching entries

## How to Present Results

Summarize as a natural-language estimate:
> "Based on X data points, gutters typically run $Y-Z per LF. For 200 LF, expect $A-$B. Gladiator Gutters quoted $24/LF on the Bafna job — they're your cheapest option."

Include confidence caveat when data is limited:
> "⚠️ Low confidence — only 2 data points. Run more bids through the pipeline to improve accuracy."

## Data Source

Pulls from IFC Pricing Database (Google Sheet: `13gzTw5JnF6aRntU91OThC9mvkLr6KZ2rTq63qki4jhc`).
Data is populated by `tools/bid-markup/extract_pricing.py` every time bids are processed.
