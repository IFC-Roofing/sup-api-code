# IFC Platform Integration — Session Log
**Date:** March 9, 2026 (00:20 - 01:26 CST)
**Agent:** Sup (dashboard, Opus)
**Human:** Alvaro

---

## What We Built

### 1. Sup API Service (`tools/sup-api/`)
Standalone FastAPI service wrapping the existing Python pipeline. Deployable anywhere.

**Files:**
- `tools/sup-api/main.py` — FastAPI app with 6 endpoints
- `tools/sup-api/requirements.txt` — fastapi, uvicorn, pydantic
- `tools/sup-api/start.sh` — startup script (creates venv, runs uvicorn)
- `tools/sup-api/Dockerfile` — container deployment
- `tools/sup-api/README.md` — full documentation

**Endpoints:**
| Endpoint | Skill | Status | Notes |
|---|---|---|---|
| `POST /v1/estimate` | @estimate | ✅ Tested in app | Full pipeline, PDF + Drive upload |
| `POST /v1/markup` | @markup | ✅ Tested via curl | Returns markup %, QA pass/fail |
| `POST /v1/precall` | @precall | ✅ Works | Needs existing supplement w/ F9s |
| `POST /v1/calling` | @calling | ✅ Works | Needs existing supplement w/ F9s |
| `POST /v1/review` | @review | ✅ Added | QA review of supplement |
| `GET /v1/health` | — | ✅ Works | No auth required |

**Key features:**
- Bearer token auth (SUP_API_KEY env var)
- Project name normalization (strips "Test Project - " prefixes from IFC app)
- Async subprocess execution (doesn't block the event loop)
- Proper timeout handling (600s for estimates, 180s for skills)
- Output parser extracts RCV total, trade count, flow package from stdout
- Falls back to flow_package data when stdout parser misses values

### 2. Rails Tool Classes (`plat-api/app/services/ai_tools/sup_external/`)
Clean HTTP-based tools that plug into the IFC ToolRegistry system. Zero Python dependency.

**Files created/modified in plat-api:**
- `app/services/ai_tools/sup_external/generate_supplement_tool.rb` — estimate (includes flow card updates)
- `app/services/ai_tools/sup_external/precall_tool.rb`
- `app/services/ai_tools/sup_external/calling_tool.rb`
- `app/services/ai_tools/sup_external/markup_tool.rb`
- `app/services/ai_tools/sup_external/review_tool.rb`
- `app/services/ai_tools/tool_registry.rb` — added friendly messages for all 5 tools
- `lib/tasks/sup_external.rake` — setup/cleanup/status/ping tasks

**Env vars added to plat-api/.env:**
```
SUP_API_URL=http://localhost:8090
SUP_API_KEY=test-key-123
```

**Tools registered in DB:**
All 5 tools registered as active AiTool records, linked to "Supplement AI Assistant" prompt (ID: 1).

### 3. Bugs Fixed During Testing
- `import re` was scoped inside an `if` block — moved to function scope
- Project name mismatch: IFC app sends "Test Project - Rose Brock", pipeline expects "Rose Brock" → added `normalize_project_name()` 
- Output parser wasn't matching `generate.py`'s exact format (`RCV Total:     $   32,735.59` with spaces) → rewrote parser
- Error messages from skills going to stderr were lost → combined stdout+stderr in error responses
- STOP messages (prerequisites) were returning empty errors → now parsed and returned clearly

---

## IFC Platform Architecture (from code inspection)

### Agent System
- AI is called "Syna" internally
- Each agent = a `Prompt` record in DB with `functionality` field
- `ChatContextFactory` maps `chat_type` → context class (20+ contexts)
- `AiService` → `ClaudeService` (default) with Gemini fallback
- Tools linked via `prompt_ai_tools` join table
- All tools dispatched through `ToolRegistry.execute()`

### System Prompt Layering (4 layers)
1. **Layer 0 (cached):** Global output rules, formatting, citations, actions, resource links, memory instructions (~5-6K tokens)
2. **Layer 1 (cached):** Master prompt (functionality='master') — **currently empty/missing**
3. **Layer 2 (dynamic):** Agent prompt + SharedKnowledge blocks (conditional on trigger_keywords)
4. **Layer 3 (dynamic):** User preferences (Comments on User+Prompt) + AgentMemory (top 10 by relevance)

### Current Supplement Agent State
- **Prompt:** "You are SUP, an AI assistant specialized in creating insurance construction supplements for IFC Roofing. You help sales reps generate supplements through conversation." (one sentence)
- **Master prompt:** None
- **SharedKnowledge:** None
- **Tools:** 5 Sup external tools (all active)

### Memory System
- `AgentMemory` model — per-user, cross-agent
- Categories: strength, weakness, practice, win, loss, goal, preference, insight
- Relevance scoring: recency (40%) + reference_count (30%) + confidence (30%)
- Limits: 100 active/user, 20/category, 3 new per 10-min window
- Memory tools injected into every agent automatically
- Top 10 memories pre-loaded into system prompt

### Caching (what exists)
- Anthropic prompt caching on static system prompt blocks (90% token discount)
- SharedKnowledge trigger_keywords (conditional loading)
- Tool result compaction (4-pass: light→extreme)
- Conversation history limits (20 messages max)
- Insurance PDF parse cache in `.pipeline_cache/` (by project_id + pdf_hash)

### Caching (what's missing)
- No per-project data cache — every message re-fetches project/flow/posts from API
- No pipeline data cache — back-to-back skills re-fetch everything from scratch
- No cross-skill data sharing — estimate→review→calling all fetch independently

---

## Key Files & Paths

### IFC Repos
- `/Users/IFCSUP/ifc-repos/plat-api/` — Rails API (running on localhost:3000, Puma PID was 56760)
- `/Users/IFCSUP/ifc-repos/plat-frontend/` — React frontend
- `/Users/IFCSUP/ifc-repos/plat-docs/` — Documentation

### Our Workspace
- `/Users/IFCSUP/.openclaw/workspace/tools/sup-api/` — Sup API service
- `/Users/IFCSUP/.openclaw/workspace/tools/pdf-generator/` — Estimate pipeline
- `/Users/IFCSUP/.openclaw/workspace/tools/skills/` — Skill scripts
- `/Users/IFCSUP/.openclaw/workspace/tools/bid-markup/` — Markup analysis
- `/Users/IFCSUP/.openclaw/workspace/tools/pdf-generator/.pipeline_cache/` — Existing cache

### Rails Ruby
- rbenv at `/opt/homebrew/bin/rbenv`, Ruby 3.1.1
- Run rake: `cd /Users/IFCSUP/ifc-repos/plat-api && eval "$(/opt/homebrew/bin/rbenv init -)" && bundle exec rake ...`
- Restart Puma: `kill -USR2 <puma_pid>`

---

## Next Steps (Priority Order)

### 🔴 P1 — Extend pipeline data cache (we own this)
- Cache full `pipeline_data` output per project (10 min TTL)
- Back-to-back skills (estimate→review→calling) share fetched data
- Saves 1-2 min per subsequent skill run on same project

### 🔴 P2 — Project context cache in Rails (needs IFC team)
- `Rails.cache.fetch("project_context/#{project_id}", expires_in: 5.minutes)`
- Follow-up messages in a session don't re-fetch project/flow/posts
- Significant token savings on multi-message conversations

### 🟡 P3 — Auto-learning from decisions (weekly distill job)
- Pull decisions from Google Sheet (1QLeEHPr1mmhJfKqC7rgTlirmBXN3618d_77yK4jrW_8)
- Pull supplement outcomes (won/lost per trade per carrier)
- Claude distills patterns → updates SharedKnowledge records
- Every agent gets smarter without manual knowledge curation

### 🟡 P4 — Rep preference auto-detection
- Enhance existing memory `insight` category
- Detect patterns from chat: "John always asks about steep first" → store as preference
- Already supported by AgentMemory, just needs smarter observation logic

### 🟢 P5 — Knowledge base as SharedKnowledge
- Format our `knowledge-base.md` (53 lessons) for SharedKnowledge records
- Add trigger_keywords so lessons load conditionally (carrier names, trade names)
- Immediate improvement to supplement agent quality

### 🟢 P6 — Production deployment
- Deploy Sup API to VPS or container service
- Update SUP_API_URL in production Rails env
- Get approval from IFC team for plat-api changes (5 tool files + rake task + registry update)

---

## User Note
Alvaro does NOT have permission to push to the plat-api repo. All Rails changes are local only. Need IFC team approval to merge. The local test proved everything works end-to-end through the app.
