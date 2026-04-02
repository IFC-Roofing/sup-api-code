# Skill Specs — New/Reassigned Skills for BUILD & SUP

## 🔴 CRITICAL — Assign Existing Skills

### 1. `list_posts` / `get_post` → Assign to BUILD + SUP

**Current status:** Assigned to CALLING, FLOW Pulse, CLARITY. NOT on BUILD or SUP.

**Why critical:** BUILD cannot read @ifc (game plan) or @supplement (strategy) without this. The @ifc tag is the single most important input for scope decisions — it tells BUILD which trades to include and what the strategy is. Without it, BUILD is guessing.

**Action:** Add BUILD and SUP to the agent list for both `list_posts` and `get_post`. No backend changes needed.

---

### 2. `convo_post` → Assign to BUILD + SUP

**Current status:** Assigned to ORDER, CLARITY. NOT on BUILD or SUP.

**Why critical:** Both agents need to post @momentum updates after analysis. BUILD posts scope findings, SUP posts estimate completion status. Without it, project status tracking breaks — humans have to manually post what the AI already knows.

**Action:** Add BUILD and SUP to agent list for `convo_post`. No backend changes needed.

---

### 3. `validate_bids` → Assign to BUILD

**Current status:** Assigned to ORDER, CLARITY. NOT on BUILD.

**Why important:** BUILD audits bid integrity (math check, scope match, base amount alignment). This skill validates bids against the Original Bids folder in Drive — exactly what BUILD needs for sub-bid verification.

**Action:** Add BUILD to agent list. No backend changes needed.

---

### 4. `list_tasks` / `get_task` → Assign to BUILD + SUP

**Current status:** Assigned to ORDER, FLOW Pulse, CLARITY. NOT on BUILD or SUP.

**Why important:** Both agents create tasks (route to Vanessa, Cathy, etc.). Without `list_tasks`, they can't check for duplicates before creating. Leads to double-tasking office staff.

**Action:** Add BUILD and SUP to agent list. No backend changes needed.

---

### 5. `create_supplement` → Assign to SUP

**Current status:** Exists but has **0 agents** assigned.

**Why critical:** SUP's entire output is the supplement. This skill creates the supplement record in the app. Without it, SUP can only output text — can't actually save the supplement to the project.

**Action:** Assign to SUP. Verify the skill's input schema matches SUP's estimate JSON output (see section below).

---

### 6. All `read_*` skills → Assign to SUP

**Current status:** Most read skills are on BUILD but NOT on SUP (SUP is a new agent).

**Skills SUP needs assigned:**
- `read_insurance_markdown`
- `read_sub_pricing`
- `read_price_list`
- `read_flow_trade_status`
- `read_red_flags`
- `material_calculator`
- `get_flow_card`
- `get_project` / `project_data`
- `get_drive_file_content` / `list_project_drive_files` / `list_drive_folder_files`
- `read_conversation_history` / `get_conversation_context`
- `get_user`
- `retrieve_memories` / `store_memory` / `update_memory`
- `user_preferences`
- `create_red_flag` / `resolve_red_flag`
- `create_task`
- `update_flow_card`
- `find_project_contract`

**Action:** Assign all of the above to SUP. No backend changes needed.

---

## 🟢 NEW SKILLS — Need Backend Work

### 7. `photo_inventory` — NEW SKILL

**Skill Description:**
Lists all project photos from Drive and/or CompanyCam, categorized by trade. Returns a structured inventory that BUILD and SUP use to verify photo evidence exists for each line item. This is the "do we have the evidence?" check that prevents sending supplements with weak or missing photo support.

BUILD uses this to flag `WEAK_PHOTO_EVIDENCE` or `NO_PHOTO_EVIDENCE` per line item. SUP uses this to reference specific photos in F9 notes ("Please see attached Photo Report showing damage to [trade]").

**Status:** Active

**Dev Description:**
Ruby backend class needed: `AiTools::Documents::PhotoInventoryTool`

Input parameters:
- `project_id` (required) — IFC project ID
- `source` (optional, enum: `drive`, `companycam`, `both`, default: `both`) — where to look for photos
- `trade_filter` (optional, string) — filter to specific trade tag (e.g., `@gutter`, `@shingle_roof`)

Data sources the class must read:
- Google Drive: project folder → look for photo report PDFs, image files, CompanyCam exports. Parse filenames and folder structure for trade hints.
- CompanyCam (if integrated): project photos with tags/labels
- Flow cards: `list_action_trackers` → trade tags to map photos against

Processing logic:
1. List all image files and photo report PDFs in project Drive folder (recursive)
2. Categorize each by trade based on:
   - Filename (e.g., "gutter_damage_01.jpg" → @gutter)
   - Parent folder name (e.g., "Roof Photos/" → @shingle_roof)
   - Photo report PDF → extract page-level trade tags if structured
3. For each active trade (from flow cards with 👍), report photo count
4. Flag trades with 0 photos as `NO_PHOTO_EVIDENCE`

Output structure (JSON):
```json
{
  "project_id": 5128,
  "photo_count": 47,
  "sources": ["drive", "companycam"],
  "by_trade": {
    "@shingle_roof": {
      "count": 22,
      "files": ["roof_overview.jpg", "hail_damage_01.jpg", "pipe_jack_painted.jpg"],
      "has_photo_report": true,
      "evidence_quality": "strong"
    },
    "@gutter": {
      "count": 8,
      "files": ["gutter_damage_left.jpg", "gutter_diagram.pdf"],
      "has_photo_report": false,
      "evidence_quality": "moderate"
    },
    "@fence": {
      "count": 0,
      "files": [],
      "has_photo_report": false,
      "evidence_quality": "none"
    }
  },
  "unmatched": {
    "count": 5,
    "files": ["IMG_2847.jpg", "IMG_2848.jpg", "photo_03.png", "overview.jpg", "front_elevation.jpg"]
  },
  "flags": [
    {"trade": "@fence", "flag": "NO_PHOTO_EVIDENCE", "severity": "high", "message": "Fence is active (👍) but has 0 photos"},
    {"trade": "@chimney", "flag": "WEAK_PHOTO_EVIDENCE", "severity": "medium", "message": "Only 1 photo for chimney — may need more"}
  ]
}
```

Edge cases:
- No photos at all → return `photo_count: 0`, flag ALL active trades as `NO_PHOTO_EVIDENCE`
- Photos exist but can't determine trade → put in `unmatched` bucket
- Photo report PDF exists but individual photos don't → still count as having evidence
- CompanyCam not integrated → `sources: ["drive"]`, skip CompanyCam

**AI Description:**
List and categorize all project photos by trade. Input: project_id. Returns photo count per trade, file names, evidence quality rating, and flags for trades missing photo evidence. Used by BUILD to verify evidence exists before recommending line items, and by SUP to reference specific photos in F9 notes.

**Assign to:** BUILD, SUP

---

### 8. `f9_matrix_lookup` — NEW SKILL

**Skill Description:**
Searches the F9 justification template matrix by category and scenario. Returns the matching F9 template text with placeholders. Replaces loading the entire 55KB F9 matrix JSON into context — instead, SUP queries for exactly the templates it needs per line item.

The F9 matrix contains 86 proven templates organized by category (Dry-in & Shingles, Roof Complexities, Roof Components, Gutters, Fence, Windows, Chimney, etc.) and scenario (INS forgot item, INS got quantity wrong, INS got quality wrong, bid replacement). Each template has been used successfully on real supplements.

**Status:** Active

**Dev Description:**
Ruby backend class needed: `AiTools::Supplements::F9MatrixLookupTool`

Input parameters:
- `category` (optional, string) — F9 matrix category (e.g., "Dry-in & Shingles", "Gutters", "Roof Components", "Chimney Cap", "Fence (Wood)", "Windows & Screens")
- `line_item` (optional, string) — specific item name (e.g., "Starter", "Drip Edge", "Gutters", "Chimney Flashing")
- `scenario` (optional, string) — scenario type (e.g., "Did INS FORGET the line item?", "Did INS get the QUANTITY wrong?", "Did INS get the QUALITY wrong?")
- `search` (optional, string) — freetext search across all fields (for fuzzy matching)

Data source:
- F9 matrix JSON file. Currently stored at `tools/pdf-generator/f9_matrix.json` in Sup's workspace AND on the Shared Drive under Reference. Should be loaded into a database table or cached in memory for fast lookups.
- Schema per entry: `category`, `line_item`, `xact_description`, `scenario`, `f9`

Processing logic:
1. Filter matrix entries by provided parameters (category, line_item, scenario)
2. If `search` provided, fuzzy match across all fields
3. Return matching templates (could be 1 or multiple if category has multiple scenarios)
4. If no exact match, return closest matches with similarity note

Output structure (JSON):
```json
{
  "query": {
    "category": "Dry-in & Shingles",
    "line_item": "Starter",
    "scenario": "Did INS FORGET the line item?"
  },
  "matches": [
    {
      "category": "Dry-in & Shingles",
      "line_item": "Starter",
      "xact_description": "Asphalt starter - laminated double layer starter",
      "scenario": "Did INS FORGET the line item?",
      "f9": "The insurance report left out the Starter.\n\nWe are requesting X LF of Laminate Double Layer Starter. Please see attached EagleView Report for confirmation of the measurements.\n\n1. Per Xactimate pricing, this costs an additional $XX.xx.\n\na. This house currently has Laminate Double Layer Starter installed and it cannot be reused.\n\nb. For slate-look shingles, the starter course requires a double layer..."
    }
  ],
  "match_count": 1,
  "exact_match": true
}
```

When `category` only:
```json
{
  "query": {"category": "Gutters"},
  "matches": [
    {"line_item": "Gutters", "scenario": "Did INS get the QUANTITY wrong?", "xact_description": "R&R Gutter / downspout - aluminum - up to 6\"", "f9": "..."},
    {"line_item": "Downspouts", "scenario": "Did INS get the QUANTITY wrong?", "xact_description": "Prime & paint gutter/downspout", "f9": "..."},
    {"line_item": "Splashguard", "scenario": "Did INS FORGET the line item?", "xact_description": "Gutter splash guard", "f9": "..."}
  ],
  "match_count": 3,
  "exact_match": false
}
```

Edge cases:
- No parameters provided → return all categories with entry counts (index mode)
- No matches found → return `matches: []`, `suggestions: [closest category/item names]`
- Multiple scenarios for same item → return all matching scenarios
- Typo in category → fuzzy match to closest category name

**AI Description:**
Search the F9 justification template matrix by category, line item, and/or scenario. Returns proven F9 note templates with placeholders (XX, $XX.xx) ready to be filled with real project values. 86 templates covering all trades: roof, gutters, fence, chimney, windows, siding, interior, etc. Used by SUP to write carrier-facing F9 notes from tested templates instead of from scratch.

**Assign to:** SUP, BUILD

---

## Summary — Action Items for Dev Team

### Just assign (no backend work):
| Skill | Add To | Priority |
|-------|--------|----------|
| `list_posts` / `get_post` | BUILD, SUP | 🔴 Blocker |
| `convo_post` | BUILD, SUP | 🟡 Important |
| `validate_bids` | BUILD | 🟡 Important |
| `list_tasks` / `get_task` | BUILD, SUP | 🟡 Important |
| `create_supplement` | SUP | 🔴 Verify schema, then assign |
| All read/write skills (see list above) | SUP | 🔴 New agent setup |

### Build new:
| Skill | Assign To | Priority |
|-------|----------|----------|
| `photo_inventory` | BUILD, SUP | 🟡 Important — evidence verification |
| `f9_matrix_lookup` | SUP, BUILD | 🟡 Important — token efficiency |

### Verify:
| Skill | What to Check |
|-------|--------------|
| `create_supplement` | Does the input schema accept SUP's estimate JSON? If not, need schema alignment. |
