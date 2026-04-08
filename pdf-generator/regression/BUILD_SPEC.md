# Regression Test Harness — Build Spec

## Goal
Catch pipeline logic bugs before they hit live jobs. No AI calls needed — test only the deterministic code.

## Location
`tools/pdf-generator/regression/`

## What to build

### 1. `regression/baselines/` folder
Copy these as known-good baselines:
- `RADDAD_pipeline.json` + `RADDAD_estimate.json`
- `GUIRGUIS_pipeline.json` + `GUIRGUIS_estimate.json`
- `BROCK_estimate.json`
- `DOYLE_estimate.json`
- `SHULTZ_estimate.json`

Source: `tools/pdf-generator/` (current files are known-good)

### 2. `regression/run_tests.py` script

The script should:

#### Step 1 — Load each baseline `estimate.json`
Read from `regression/baselines/`

#### Step 2 — Re-run deterministic post-processing
Import and run these functions from the pipeline against the baseline data:
- `estimate_utils._refresh_totals()` — recalculates all math
- `qa_agent._handle_missing_item()` — should NOT add duplicates (test the dedup guard)
- `data_pipeline._enforce_rr_on_tearoff()` — R&R upgrade logic
- `data_pipeline._inject_chimney_flashing()` — chimney flashing auto-add
- `data_pipeline._inject_paint_companions()` — paint companion auto-add

Each function should be applied to a COPY of the baseline, not the original.

#### Step 3 — Diff against baseline
For each project, compare the post-processed output vs the original baseline on these fields:
- Total line item count
- Section count
- Section names
- Per-item: `num`, `description`, `qty`, `unit`, `total`
- Grand total (sum of all item totals)
- O&P total

#### Step 4 — Report
- If NO differences: `✅ {PROJECT}: PASS`
- If differences found: `❌ {PROJECT}: FAIL` + list each diff
- Exit code 0 if all pass, 1 if any fail

### 3. Important constraints
- Do NOT make any AI/API calls
- Do NOT modify baseline files
- Work on deep copies only
- Import paths: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` to reach `tools/pdf-generator/`
- Use `json.loads(json.dumps(data))` for deep copy (no import copy needed)
- The script should be runnable as: `python3 tools/pdf-generator/regression/run_tests.py`

### 4. Bonus: `regression/snapshot.py`
A helper to save new baselines:
- Usage: `python3 regression/snapshot.py PROJECTNAME`
- Copies `{PROJECT}_pipeline.json` and `{PROJECT}_estimate.json` from `tools/pdf-generator/` into `regression/baselines/`
- Overwrites existing baseline if present
- Prints confirmation

## File structure when done
```
tools/pdf-generator/regression/
├── baselines/
│   ├── RADDAD_pipeline.json
│   ├── RADDAD_estimate.json
│   ├── GUIRGUIS_pipeline.json
│   ├── GUIRGUIS_estimate.json
│   ├── BROCK_estimate.json
│   ├── DOYLE_estimate.json
│   └── SHULTZ_estimate.json
├── run_tests.py
└── snapshot.py
```

## Test it works
After building, run `python3 tools/pdf-generator/regression/run_tests.py` — all projects should PASS since baselines = current code output.
