# Sup API — External Supplement Service

The bridge between the IFC platform and the Sup AI supplement pipeline.

## Architecture

```
┌──────────────────┐     HTTP/JSON      ┌──────────────────┐
│   IFC Rails App  │ ─────────────────→ │    Sup API       │
│   (plat-api)     │                    │    (FastAPI)     │
│                  │ ←───────────────── │                  │
│  SupExternal::   │   {pdf_url, rcv,   │  Runs existing   │
│  GenerateTool    │    trades, f9s}    │  Python pipeline │
└──────────────────┘                    └──────────────────┘
                                              │
                                              ├── generate.py (estimate)
                                              ├── calling.py (call scripts)
                                              ├── precall.py (pre-call prep)
                                              ├── review.py (QA review)
                                              └── markup_bids.py (bid markup)
```

## Quick Start (Local Dev)

```bash
# 1. Set required env vars (or they'll be loaded from workspace .env)
export SUP_API_KEY="your-secret-key-here"

# 2. Start the Sup API
cd tools/sup-api
bash start.sh

# 3. Test health
curl http://localhost:8090/v1/health

# 4. Test estimate generation (takes 2-5 min)
curl -X POST http://localhost:8090/v1/estimate \
  -H "Authorization: Bearer $SUP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "Rose Brock"}'
```

## Environment Variables

### Sup API Config
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUP_API_KEY` | **Yes** | — | Bearer token for API authentication |
| `SUP_PORT` | No | `8090` | Server port |
| `SUP_WORKSPACE` | No | `../../` | Path to OpenClaw workspace root |
| `SUP_ENV` | No | `development` | `development` or `production` |
| `SUP_CORS_ORIGINS` | No | `localhost:8080,3000` | Comma-separated allowed CORS origins |

### Pipeline Dependencies (must be available to the service)
| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | **Yes** | For AI estimate generation (Claude Opus) |
| `IFC_TOKEN` | **Yes** | For IFC API data access |
| `GOOGLE_API_KEY` | **Yes** | For insurance PDF parsing (Gemini vision) |
| `google-drive-key.json` | **Yes** | Service account key in workspace root (for Drive/Sheets) |

> **Note:** `start.sh` auto-loads variables from `$SUP_WORKSPACE/.env` if it exists.

## API Endpoints

### `POST /v1/estimate`
Generate a full supplement PDF **with learning integration**. **Rate limit: 3/min.**

Queries learned patterns before generating, tracks the event after.

**Request:**
```json
{
  "project_name": "Rose Brock",
  "project_id": 5128,
  "carrier": "Allstate",
  "adjuster_name": "John Smith",
  "skip_upload": false,
  "version": "1.0",
  "pricelist_override": null,
  "notes": "Focus on roof scope"
}
```

**Response:**
```json
{
  "success": true,
  "pdf_url": "https://drive.google.com/file/d/.../view",
  "total_rcv": "$34,567.89",
  "trade_count": 5,
  "f9_count": 12,
  "flow_package": { ... },
  "intelligence_provided": ["Allstate_steep_waste", "Allstate_O&P"],
  "pricelist_used": "TXDF8X_MAR26",
  "pricelist_reason": "latest_available",
  "event_id": 42,
  "request_id": "a1b2c3d4e5f6"
}
```

### `POST /v1/precall`
Generate pre-supplement call script data. **Rate limit: 10/min.**

### `POST /v1/calling`
Generate carrier phone call script. **Rate limit: 10/min.**

### `POST /v1/markup`
Run bid markup analysis. **Rate limit: 10/min.**

### `POST /v1/review`
Run QA review on supplement. **Rate limit: 10/min.**

### `POST /v1/track_response`
Track insurance response for learning. **Rate limit: 5/min.**
```json
{
  "event_id": 42,
  "approved_items": [{"strategy": "O&P", "amount": 5200}],
  "denied_items": [{"strategy": "steep_on_waste", "reason": "Not per our guidelines"}]
}
```

### `GET /v1/insights?days=30&carrier=Allstate`
Dashboard insights summary — success rates, top strategies, trends. **Rate limit: 10/min.**

### `GET /v1/intelligence?carrier=Allstate&strategy=O&P&strategy=steep_on_waste`
Strategy-level intelligence + recommendations. **Rate limit: 10/min.**

### `GET /v1/seasonal?carrier=Allstate`
Seasonal success patterns by month/quarter. **Rate limit: 10/min.**

### `GET /v1/adjusters/{adjuster_name}`
Adjuster-specific patterns and success rates. **Rate limit: 10/min.**

### `GET /v1/pricelists?region=TX` / `POST /v1/pricelists`
List or register available pricelists. **Rate limit: 10/min.**

### `GET /v1/projects/{project_id}/pricelists`
Pricelist usage history for a project. **Rate limit: 10/min.**

### `GET /v1/health`
Health check (no auth required). Returns minimal info in production.

## Features

- **Learning Loop** — Every estimate tracks strategies, carrier, adjuster; every response feeds back outcomes
- **Intelligence Engine** — Recommendations based on success rates, denial patterns, seasonal trends
- **F9 Effectiveness** — Tracks which F9 wording wins/loses per carrier and adjuster
- **Adjuster Profiling** — Per-adjuster success rates and preferences
- **Seasonal Patterns** — Success rate analysis by month and quarter
- **Pricelist Management** — Version consistency across supplement iterations
- **Dynamic Approaches** — Learns new strategies from successful outcomes over time
- **Rate Limiting** — Per-endpoint limits to prevent API credit burn
- **Request Dedup** — Simultaneous identical requests won't double-generate
- **Request IDs** — Every response includes a traceable `request_id`
- **Structured Logging** — Timestamped logs with request IDs for audit trail
- **CORS Support** — Configurable allowed origins for direct frontend access
- **Production Mode** — Hides docs, strips health details, sanitizes errors

## Learning Dimensions

| What It Tracks | How | When |
|----------------|-----|------|
| **Strategy success rates** | Per carrier, per strategy | Every insurance response |
| **Carrier behavior** | Approval/denial patterns | 90-day rolling window |
| **Adjuster preferences** | Per-adjuster success rates | Every estimate + response |
| **F9 effectiveness** | Which wording wins/loses | Every line item outcome |
| **Seasonal patterns** | Success by month/quarter | Ongoing analysis |
| **User preferences** | Team member styles | On preference set |
| **Photo evidence** | Which photos led to approvals | Every strategy outcome |
| **Response times** | How long carriers take | Every response tracked |
| **Pricelist versions** | Which list used per supplement | Every generation |
| **Dynamic approaches** | New strategies from wins | Auto-discovered |

**Philosophy:** The system provides INTELLIGENCE and RECOMMENDATIONS, never automatic decisions. It never says "skip this" — always "try this approach instead."

## IFC App Setup

### Environment Variables
Add to the Rails app's `.env`:
```
SUP_API_URL=http://localhost:8090   # or production URL
SUP_API_KEY=your-secret-key-here
```

### Register Tools
```bash
rails sup_external:setup    # Register tools + link to supplement prompt
rails sup_external:status   # Check integration status
rails sup_external:ping     # Test API connection
rails sup_external:cleanup  # Remove tools
```

### What Gets Registered
| Tool | Rails Class | API Endpoint | Rate Limit |
|------|-------------|-------------|------------|
| `sup_external_generate_supplement` | `GenerateSupplementTool` | `POST /v1/estimate` | 3/min |
| `sup_external_precall` | `PrecallTool` | `POST /v1/precall` | 10/min |
| `sup_external_calling` | `CallingTool` | `POST /v1/calling` | 10/min |
| `sup_external_markup` | `MarkupTool` | `POST /v1/markup` | 10/min |
| `sup_external_review` | `ReviewTool` | `POST /v1/review` | 10/min |

## Deployment

### Option A: Same Server as OpenClaw (local dev)
```bash
export SUP_API_KEY="generate-a-secure-key"
bash tools/sup-api/start.sh
```

### Option B: Production (same server)
```bash
export SUP_API_KEY="generate-a-secure-key"
bash tools/sup-api/start.sh --prod
```

### Option C: Docker
```bash
docker build -t sup-api -f tools/sup-api/Dockerfile .
docker run -p 8090:8090 \
  -e SUP_API_KEY=your-key \
  -e SUP_ENV=production \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e IFC_TOKEN=your-ifc-token \
  -e GOOGLE_API_KEY=your-google-key \
  -v /path/to/google-drive-key.json:/workspace/google-drive-key.json \
  sup-api
```

### Option D: VPS / Cloud
Deploy to any cloud provider that runs Python:
- Railway, Fly.io, Render (container)
- DigitalOcean, Linode (VPS with Docker or direct)
- The Sup API + pipeline deps are ~100MB

## Security Notes

- **Never commit `SUP_API_KEY` or other secrets to git**
- **Production mode** (`SUP_ENV=production`) hides Swagger docs and infrastructure details
- **Rate limiting** protects against accidental API credit burn
- **Request dedup** prevents double-generation from retries
- **All endpoints require Bearer auth** except `/v1/health`

## Files Changed in plat-api

```
app/services/ai_tools/sup_external/
  ├── generate_supplement_tool.rb  ← Main estimate tool
  ├── precall_tool.rb              ← Pre-call + shared API helper
  ├── calling_tool.rb              ← Carrier call script tool
  ├── markup_tool.rb               ← Bid markup tool
  └── review_tool.rb               ← QA review tool
app/services/ai_tools/tool_registry.rb  ← Friendly messages
lib/tasks/sup_external.rake             ← Setup/cleanup/status/ping
```

No Python, no subprocess, no local file paths in the Rails app.
Just HTTP calls to wherever the Sup API is running.
