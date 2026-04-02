# @estimate — PDF Supplement Generator

Triggered by: `@estimate <project name>`
Example: `@estimate Rose Brock`

## What it does
Runs the full PDF supplement generator pipeline for a project and reports results.

## Script
```
tools/pdf-generator/generate.py
venv: tools/pdf-generator/.venv/bin/python
```

## Steps
1. Extract project name from the message (everything after `@estimate`)
2. Run: `cd tools/pdf-generator && .venv/bin/python generate.py "<project name>" 2>&1`
3. Report summary back: sections, items added, RCV total, Drive link
4. If `--skip-upload` is in the message, add that flag
5. If `--json-only` is in the message, stop after estimate.json

## Flags (optional, pass through if mentioned)
- `--skip-upload` — don't upload to Drive
- `--json-only` — stop after building estimate.json, show line items for review
- `--html-only` — stop after rendering HTML

## Output to report
- ✅ or ❌ status
- Sections count, total items (copied / added / adjusted)
- RCV Total
- Drive link (from uploader output)
- Any warnings

## Hard rule
NEVER send to insurance. Always remind: human review required before sending.
