"""
comment_reader.py — Reads Google Drive comments on a supplement PDF,
translates them into edit actions, and applies them.

Flow:
  1. Find the latest supplement PDF for a project on Drive
  2. Read all unresolved comments
  3. Use AI to translate comment + selected text → edit actions
  4. Apply edits via edit_estimate.py
  5. Re-render PDF and upload
  6. Resolve the comments

Usage:
  python comment_reader.py "Rose Brock"
  python comment_reader.py "Rose Brock" --dry-run     # preview edits without applying
  python comment_reader.py --file-id <drive_file_id>   # target specific file
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

WORKSPACE = Path(__file__).resolve().parent


def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_path = ROOT / "google-drive-key.json"
    creds = service_account.Credentials.from_service_account_file(
        str(creds_path),
        scopes=['https://www.googleapis.com/auth/drive']
    ).with_subject('sup@ifcroofing.com')
    return build('drive', 'v3', credentials=creds)


def find_latest_supplement_pdf(project_name: str) -> Optional[dict]:
    """Find the most recent supplement PDF for a project on Drive."""
    service = get_drive_service()
    
    # Extract last name for search
    parts = project_name.strip().split()
    lastname = parts[-1].upper() if parts else project_name.upper()
    
    # Search in Drive
    query = f"name contains '{lastname}_IFC Supp' and mimeType='application/pdf' and trashed=false"
    results = service.files().list(
        q=query,
        spaces='drive',
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields='files(id, name, modifiedTime, parents)',
        orderBy='modifiedTime desc'
    ).execute()
    
    files = results.get('files', [])
    if not files:
        return None
    
    # Return most recent
    return files[0]


def get_unresolved_comments(file_id: str) -> list:
    """Get all unresolved comments on a Drive file."""
    service = get_drive_service()
    
    comments = service.comments().list(
        fileId=file_id,
        fields='comments(id,content,quotedFileContent,author,resolved,createdTime,replies)',
        includeDeleted=False
    ).execute()
    
    # Filter to unresolved only
    unresolved = [
        c for c in comments.get('comments', [])
        if not c.get('resolved', False)
    ]
    
    return unresolved


def _load_f9_matrix() -> str:
    """Load F9 matrix templates for context."""
    matrix_path = WORKSPACE / "f9_matrix.json"
    if not matrix_path.exists():
        return ""
    with open(matrix_path) as f:
        matrix = json.load(f)
    # Summarize categories and scenarios
    summaries = []
    for entry in matrix[:30]:  # Keep it reasonable
        summaries.append(f"- {entry.get('category', '?')} / {entry.get('line_item', '?')} / {entry.get('scenario', '?')}")
    return "\n".join(summaries)


def _find_item_in_estimate(estimate: dict, section_name: str, description_contains: str) -> Optional[dict]:
    """Find a specific line item in the estimate."""
    for section in estimate.get('sections', []):
        if section_name.lower() in section.get('name', '').lower() or section.get('name', '').lower() in section_name.lower():
            for item in section.get('line_items', []):
                if description_contains.lower() in item.get('description', '').lower():
                    return {**item, '_section': section.get('name', '')}
    # Fallback: search all sections
    for section in estimate.get('sections', []):
        for item in section.get('line_items', []):
            if description_contains.lower() in item.get('description', '').lower():
                return {**item, '_section': section.get('name', '')}
    return None


def _generate_f9_for_item(client, item: dict, estimate: dict, comment_hint: str = "") -> str:
    """Use Opus to generate a proper F9 note for a line item."""
    # Load F9 matrix for reference
    matrix_path = WORKSPACE / "f9_matrix.json"
    matrix_context = ""
    if matrix_path.exists():
        with open(matrix_path) as f:
            matrix = json.load(f)
        # Find relevant templates
        desc_lower = item.get('description', '').lower()
        relevant = [e for e in matrix if any(
            kw in desc_lower for kw in e.get('xact_description', '').lower().split()[:3]
            if len(kw) > 3
        )][:5]
        if relevant:
            matrix_context = "RELEVANT F9 TEMPLATES:\n" + json.dumps(relevant, indent=2)

    # Build item context
    item_context = json.dumps({
        k: v for k, v in item.items() if k != '_section'
    }, indent=2)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"""You are an insurance supplement F9 note writer for IFC Contracting Solutions.

Write a professional F9 justification note for this line item. The F9 explains to the insurance adjuster why this item is needed.

LINE ITEM:
Section: {item.get('_section', 'Unknown')}
{item_context}

{matrix_context}

{f'REVIEWER HINT: {comment_hint}' if comment_hint else ''}

RULES:
- Write from IFC's perspective as the general contractor
- Reference EagleView measurements, photos, or pre-loss condition as appropriate
- Be professional but firm — we are requesting fair compensation
- Use the F9 matrix templates as style/structure reference but customize to THIS specific item
- Keep it concise but thorough (2-4 paragraphs)
- Do NOT include any JSON or code — just the F9 note text
- Do NOT reference internal IFC jargon — this goes to insurance"""
        }]
    )
    return response.content[0].text.strip()


def translate_comments_to_edits(comments: list, project_prefix: str) -> list:
    """Use AI to translate Drive comments into edit actions."""
    import anthropic
    
    # Load current estimate for context
    estimate_path = WORKSPACE / f"{project_prefix}_estimate.json"
    estimate = {}
    sections_summary = ""
    if estimate_path.exists():
        with open(estimate_path) as f:
            estimate = json.load(f)
        sections_summary = "\n".join([
            f"Section: {s['name']} — Items: {', '.join(item.get('description', '?') for item in s.get('line_items', []))}"
            for s in estimate.get('sections', [])
        ])
    
    # Format comments for AI
    comment_descriptions = []
    for i, c in enumerate(comments):
        quoted = c.get('quotedFileContent', {}).get('value', '')
        content = c.get('content', '')
        author = c.get('author', {}).get('displayName', 'Unknown')
        comment_descriptions.append(
            f"Comment {i+1} by {author}:\n"
            f"  Selected text: \"{quoted}\"\n"
            f"  Comment: \"{content}\""
        )
    
    comments_text = "\n\n".join(comment_descriptions)
    
    client = anthropic.Anthropic()
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""You are an insurance supplement editor. Translate these PDF review comments into edit actions.

CURRENT ESTIMATE SECTIONS:
{sections_summary}

COMMENTS FROM REVIEWER:
{comments_text}

Translate each comment into one or more edit actions. Available actions:
- {{"action": "clear_f9", "section": "<name>", "description_contains": "<keyword>"}}
- {{"action": "clear_all_f9s"}}
- {{"action": "update_f9", "section": "<name>", "description_contains": "<keyword>", "new_f9": "<text>"}}
- {{"action": "remove_section", "section": "<name>"}}
- {{"action": "remove_item", "section": "<name>", "description_contains": "<keyword>"}}
- {{"action": "update_qty", "section": "<name>", "description_contains": "<keyword>", "new_qty": <number>}}
- {{"action": "update_rate", "section": "<name>", "description_contains": "<keyword>", "new_replace_rate": <number>}}
- {{"action": "revert_to_ins", "section": "<name>", "description_contains": "<keyword>"}}
- {{"action": "add_item", "section": "<name>", "description": "<Xactimate line item name>", "qty": <number>}}

IMPORTANT RULES:
- Each comment applies ONLY to the specific item whose text was selected/highlighted. Never generalize a single comment to all items.
- "remove F9" or "clear F9" on a specific selected text → use clear_f9 with that item's section + description. Do NOT use clear_all_f9s unless the comment explicitly says "all F9s" or "clear all notes".
- Use the selected text to identify which section and line item the comment targets. Match against the estimate sections above.
- clear_all_f9s should ONLY be used when the reviewer explicitly asks to clear ALL F9 notes across the entire estimate.
- For "add F9" or "write F9" comments: if the comment includes specific F9 text after the instruction, use that text as new_f9. If the comment is JUST "add F9" with no specific text, set new_f9 to "AUTO_GENERATE" — it will be generated separately.
- MERGE MULTIPLE COMMENTS ON THE SAME ITEM: If two or more comments target the same line item (same section + description), combine them into ONE update_f9 action with the merged text. Do NOT emit two separate update_f9 actions for the same item — the second would overwrite the first. Combine all reviewer feedback into one cohesive F9 note.
- ADD LINE ITEMS: If a comment says "add [item name] [qty] [unit]" or "we need [item name] here" — use add_item. The description should be the Xactimate line item name (e.g. "R&R Drip edge", "Step flashing", "Ice & water barrier"). Rates and F9 are auto-generated from the pricelist. If the comment mentions a bid item instead of Xactimate, use {{"action": "flag", "section": "<name>", "note": "<what bid needs to be added>"}} for human handling.
- Other instruction patterns: "move this to...", "split this into...", "this needs to be separate" → use "flag" action with a descriptive note.

Match section names and descriptions to the actual estimate sections above.
Return ONLY a JSON array of edit actions. No explanation."""
        }]
    )
    
    # Parse response
    response_text = response.content[0].text.strip()
    # Handle markdown code blocks
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    
    try:
        edits = json.loads(response_text)
    except json.JSONDecodeError:
        print(f"⚠️ AI response was not valid JSON: {response_text[:200]}")
        return []
    
    # Phase 2: Auto-generate F9s where needed
    for edit in edits:
        if edit.get('action') == 'update_f9' and edit.get('new_f9', '').strip().upper() in ('AUTO_GENERATE', 'F9', ''):
            desc_kw = edit.get('description_contains', '')
            section = edit.get('section', '')
            print(f"  🧠 Auto-generating F9 for: {desc_kw} in {section}...")
            item = _find_item_in_estimate(estimate, section, desc_kw)
            if item:
                # Find original comment hint
                comment_hint = ""
                for c in comments:
                    quoted = c.get('quotedFileContent', {}).get('value', '')
                    if desc_kw.lower() in quoted.lower():
                        comment_hint = c.get('content', '')
                        break
                generated_f9 = _generate_f9_for_item(client, item, estimate, comment_hint)
                edit['new_f9'] = generated_f9
                print(f"  ✅ Generated F9 ({len(generated_f9)} chars)")
            else:
                print(f"  ⚠️ Could not find item '{desc_kw}' in estimate — skipping F9 generation")
    
    return edits
    
    # Parse response
    response_text = response.content[0].text.strip()
    # Handle markdown code blocks
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    
    try:
        edits = json.loads(response_text)
        return edits
    except json.JSONDecodeError:
        print(f"⚠️ AI response was not valid JSON: {response_text[:200]}")
        return []


def resolve_comments(file_id: str, comment_ids: list):
    """Mark comments as resolved on Drive."""
    service = get_drive_service()
    
    for cid in comment_ids:
        try:
            # Add a reply that resolves the comment
            service.replies().create(
                fileId=file_id,
                commentId=cid,
                fields='id',
                body={
                    'content': '✅ Applied by Sup AI',
                    'action': 'resolve'
                }
            ).execute()
            print(f"  ✅ Resolved comment {cid}")
        except Exception as e:
            print(f"  ⚠️ Could not resolve comment {cid}: {e}")


def process_comments(project_name: str, file_id: str = None, dry_run: bool = False) -> dict:
    """Main entry point: read comments → translate → edit → upload → resolve."""
    
    # Step 1: Find the PDF
    if file_id:
        pdf_info = {"id": file_id, "name": "specified file"}
    else:
        print(f"[comment_reader] Finding latest supplement PDF for '{project_name}'...")
        pdf_info = find_latest_supplement_pdf(project_name)
        if not pdf_info:
            print(f"❌ No supplement PDF found for '{project_name}' on Drive")
            return {"success": False, "error": "No PDF found on Drive"}
    
    file_id = pdf_info['id']
    print(f"[comment_reader] Found: {pdf_info.get('name', file_id)}")
    
    # Step 2: Get comments
    print(f"[comment_reader] Reading comments...")
    comments = get_unresolved_comments(file_id)
    
    if not comments:
        print(f"[comment_reader] No unresolved comments found.")
        return {"success": True, "message": "No comments to process", "edits_applied": 0}
    
    print(f"[comment_reader] Found {len(comments)} unresolved comment(s):")
    for c in comments:
        quoted = c.get('quotedFileContent', {}).get('value', '(no selection)')
        author = c.get('author', {}).get('displayName', 'Unknown')
        print(f"  • {author}: \"{c['content']}\" [on: \"{quoted[:60]}\"]")
    
    # Step 3: Get project prefix
    parts = project_name.strip().split()
    prefix = parts[-1].upper() if parts else project_name.upper()
    
    # Step 4: Translate to edits
    print(f"\n[comment_reader] Translating comments to edits...")
    edits = translate_comments_to_edits(comments, prefix)
    
    if not edits:
        print(f"[comment_reader] No edits could be extracted from comments.")
        return {"success": True, "message": "Comments didn't map to edits", "edits_applied": 0}
    
    print(f"[comment_reader] Translated to {len(edits)} edit(s):")
    for e in edits:
        print(f"  → {e}")
    
    if dry_run:
        print(f"\n[comment_reader] DRY RUN — not applying edits.")
        return {"success": True, "edits": edits, "edits_applied": 0, "dry_run": True}
    
    # Step 5: Apply edits
    print(f"\n[comment_reader] Applying edits...")
    from edit_estimate import apply_edits, rerender
    
    edit_result = apply_edits(prefix, edits)
    
    # Step 6: Re-render and upload to project Supplement folder
    print(f"\n[comment_reader] Re-rendering PDF...")
    # Resolve project folder for upload routing
    project_folder_id = None
    try:
        from data_pipeline import fetch_project, find_project_folder
        project_data = fetch_project(project_name)
        if project_data:
            project_folder_id = find_project_folder(project_data)
    except Exception as e:
        print(f"  ⚠️ Could not resolve project folder: {e}")
    
    render_result = rerender(prefix, skip_upload=False, project_folder_id=project_folder_id)
    
    pdf_url = None
    if isinstance(render_result, dict):
        pdf_url = render_result.get("drive_link")
    
    # Step 7: Keep comments visible (do NOT resolve)
    # Previously resolved comments automatically, but Vanessa wants to see them after edits
    print(f"\n[comment_reader] Keeping {len(comments)} comment(s) visible on Drive (not resolving).")
    
    result = {
        "success": True,
        "comments_processed": len(comments),
        "edits_applied": len(edits),
        "edit_results": edit_result.get("results", []),
        "pdf_url": pdf_url,
    }
    
    print(f"\n✅ Done! Processed {len(comments)} comment(s) → {len(edits)} edit(s)")
    if pdf_url:
        print(f"📄 Updated PDF: {pdf_url}")
    
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process Drive comments on supplement PDFs")
    parser.add_argument("project_name", nargs="?", help="Project name (e.g. 'Rose Brock')")
    parser.add_argument("--file-id", help="Specific Drive file ID to check")
    parser.add_argument("--dry-run", action="store_true", help="Preview edits without applying")
    
    args = parser.parse_args()
    
    if not args.project_name and not args.file_id:
        print("Usage: python comment_reader.py 'Rose Brock' [--dry-run]")
        sys.exit(1)
    
    result = process_comments(
        project_name=args.project_name or "Unknown",
        file_id=args.file_id,
        dry_run=args.dry_run
    )
    
    if not result.get("success"):
        sys.exit(1)
