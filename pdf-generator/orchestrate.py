#!/usr/bin/env python3
"""
orchestrate.py — Full end-to-end supplement automation for a single project.

Flow:
  1. Run data pipeline (fetch project, @ifc notes, INS, EV, bids, action trackers)
  2. Check @ifc exists    → Slack alert + stop if missing
  3. Check INS exists     → Slack alert + stop if missing
  4. Run bid markup       → mark up original bids 30%, upload to staging
  5. Build estimate (AI)  → estimate.json
  6. Render HTML → PDF
  7. Build flow package   → clarity JSON
  8. Create client folder under Shared Drive: projects/{ClientName}/
  9. Upload estimate PDF + flow JSON to that folder
 10. Slack Alvaro with links + summary

Usage:
    python3 orchestrate.py "Karen Shultz"
    python3 orchestrate.py "Chris Isbell" --skip-markup
    python3 orchestrate.py "Rose Brock" --dry-run        # skip uploads + Slack
"""

import sys
import os
import json
import argparse
import subprocess
import tempfile
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Staging folder: Shared Drive > projects/
PROJECTS_STAGING_FOLDER_ID = "12o_6kiRT86TV4sF1T38UxDiiNSWfDQyw"
ALVARO_SLACK_DM = "D0AFTHSM7DF"
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def slack_dm(message: str, dry_run: bool = False):
    """Send a DM to Alvaro on Slack."""
    if dry_run:
        print(f"[slack DRY RUN] {message}")
        return
    if not SLACK_BOT_TOKEN:
        print(f"[slack] ⚠️  No SLACK_BOT_TOKEN — skipping: {message}")
        return
    import requests
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": ALVARO_SLACK_DM, "text": message},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            print(f"[slack] ⚠️  Send failed: {data.get('error')}")
        else:
            print(f"[slack] ✅ Sent to Alvaro")
    except Exception as e:
        print(f"[slack] ⚠️  Exception: {e}")


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def get_service_account():
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_file(
        str(ROOT / "google-drive-key.json").with_subject('sup@ifcroofing.com'),
        scopes=["https://www.googleapis.com/auth/drive"]
    )


def create_or_get_client_folder(client_name: str) -> str:
    """
    Create (or find) a subfolder under projects/ for this client.
    Returns the folder ID.
    """
    from googleapiclient.discovery import build
    service = build("drive", "v3", credentials=get_service_account())

    # Check if folder already exists
    safe_name = client_name.strip()
    resp = service.files().list(
        q=(f"name='{safe_name}' and '{PROJECTS_STAGING_FOLDER_ID}' in parents "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
        fields="files(id, name)"
    ).execute()
    files = resp.get("files", [])
    if files:
        folder_id = files[0]["id"]
        print(f"[orchestrate] Client folder exists: {safe_name} [{folder_id}]")
        return folder_id

    # Create it
    folder = service.files().create(
        body={
            "name": safe_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [PROJECTS_STAGING_FOLDER_ID],
        },
        supportsAllDrives=True, fields="id, name"
    ).execute()
    folder_id = folder["id"]
    print(f"[orchestrate] Created client folder: {safe_name} [{folder_id}]")
    return folder_id


def upload_file_to_folder(file_path: str, folder_id: str, mime_type: str = None) -> str:
    """Upload a file to a Drive folder. Returns the file ID."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    service = build("drive", "v3", credentials=get_service_account())

    file_name = Path(file_path).name
    if mime_type is None:
        if file_path.endswith(".pdf"):
            mime_type = "application/pdf"
        elif file_path.endswith(".json"):
            mime_type = "application/json"
        else:
            mime_type = "application/octet-stream"

    # Delete existing file with same name in folder (avoid duplicates)
    existing = service.files().list(
        q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false",
        supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
        fields="files(id)"
    ).execute().get("files", [])
    for f in existing:
        service.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
        print(f"[orchestrate] Replaced existing: {file_name}")

    media = MediaFileUpload(file_path, mimetype=mime_type)
    uploaded = service.files().create(
        body={"name": file_name, "parents": [folder_id]},
        media_body=media,
        supportsAllDrives=True,
        fields="id, name, webViewLink"
    ).execute()
    print(f"[orchestrate] ✅ Uploaded: {file_name} [{uploaded['id']}]")
    return uploaded["id"], uploaded.get("webViewLink", "")


# ---------------------------------------------------------------------------
# Bid markup runner
# ---------------------------------------------------------------------------

def run_bid_markup(project_name: str, staging_folder_id: str, dry_run: bool = False) -> bool:
    """
    Run bid markup for this project, uploading into the staging folder.
    Returns True if successful (or no bids to mark up), False on error.
    """
    if dry_run:
        print(f"[orchestrate] [DRY RUN] Would run bid markup for: {project_name}")
        return True

    sys.path.insert(0, str(ROOT / "tools" / "bid-markup"))
    try:
        from markup_bids import run_drive_markup
    except ImportError:
        print(f"[orchestrate] ⚠️  markup_bids not importable — skipping markup")
        return True

    print(f"\n[orchestrate] Running bid markup for: {project_name}")
    try:
        result = run_drive_markup(
            project_name,
            markup=0.30,
            run_qa=True,
            output_folder_id=staging_folder_id,
        )
        if result.get("error"):
            print(f"[orchestrate] ⚠️  Markup: {result['error']} — continuing")
            return False
        n = len(result.get("results", []))
        print(f"[orchestrate] ✅ Markup done — {n} bid(s) processed, uploaded to staging folder")
        return True
    except Exception as e:
        print(f"[orchestrate] ⚠️  Markup error: {e} — continuing")
        return False


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def orchestrate(project_name: str, skip_markup: bool = False, dry_run: bool = False,
                version: str = "1.0"):

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n{'='*65}")
    print(f"  SUP ORCHESTRATOR — {run_id}")
    print(f"  Project: {project_name}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*65}\n")

    td = tempfile.mkdtemp(prefix="sup_orch_")

    # ── Step 1: Data Pipeline ────────────────────────────────────────────────
    print("[orchestrate] Step 1: Running data pipeline...")
    from data_pipeline import run as pipeline_run
    pipeline_data = pipeline_run(project_name, temp_dir=td)

    client_name = pipeline_data["project"].get("name", project_name)
    project_id  = pipeline_data["project_id"]
    lastname    = pipeline_data["lastname"]

    # ── Step 2: Check @ifc ───────────────────────────────────────────────────
    print("\n[orchestrate] Step 2: Checking @ifc notes...")
    ifc_notes      = pipeline_data["notes"].get("ifc", [])
    momentum_notes = pipeline_data["notes"].get("momentum", [])
    if not ifc_notes and not momentum_notes:
        msg = (f"⚠️ *{client_name}* (ID {project_id}) — No *@ifc* game plan found.\n"
               f"I can't build a supplement without it. Please add @ifc notes in the project convo and re-run.")
        print(f"[orchestrate] ❌ No @ifc notes — alerting Alvaro")
        slack_dm(msg, dry_run=dry_run)
        return {"status": "blocked", "reason": "no_ifc", "project": client_name}

    if ifc_notes:
        print(f"[orchestrate] ✅ @ifc notes found ({len(ifc_notes)} entry/entries)")
    else:
        print(f"[orchestrate] ⚠️  No @ifc notes — proceeding with @momentum context ({len(momentum_notes)} note(s))")

    # ── Step 3: Check INS estimate ───────────────────────────────────────────
    print("\n[orchestrate] Step 3: Checking INS estimate...")
    ins_data  = pipeline_data.get("ins_data", {})
    ins_items = ins_data.get("items", [])
    if not ins_items:
        msg = (f"⚠️ *{client_name}* (ID {project_id}) — No insurance estimate found in Drive.\n"
               f"Please upload the INS estimate PDF to the project Drive folder (named `{lastname}_INS`) and re-run.")
        print(f"[orchestrate] ❌ No INS estimate — alerting Alvaro")
        slack_dm(msg, dry_run=dry_run)
        return {"status": "blocked", "reason": "no_ins", "project": client_name}

    print(f"[orchestrate] ✅ INS estimate found ({len(ins_items)} items)")

    # ── Step 4: Create staging folder (needed before markup) ─────────────────
    print(f"\n[orchestrate] Step 4: Creating staging folder for '{client_name}'...")
    if dry_run:
        print(f"[orchestrate] [DRY RUN] Would create projects/{client_name}/")
        client_folder_id = "DRY_RUN"
    else:
        client_folder_id = create_or_get_client_folder(client_name)

    # ── Step 5: Bid markup → into staging folder ─────────────────────────────
    if not skip_markup:
        print("\n[orchestrate] Step 5: Running bid markup...")
        markup_ok = run_bid_markup(project_name, staging_folder_id=client_folder_id, dry_run=dry_run)
        if not markup_ok:
            print("[orchestrate] ⚠️  Markup had issues — continuing with estimate anyway")
    else:
        print("\n[orchestrate] Step 5: Bid markup skipped (--skip-markup)")

    # ── Step 6: Build estimate ───────────────────────────────────────────────
    print("\n[orchestrate] Step 6: Building estimate (AI)...")
    from estimate_builder import build_estimate
    try:
        estimate = build_estimate(pipeline_data)
    except json.JSONDecodeError as e:
        msg = f"❌ *{client_name}* — Estimate builder returned invalid JSON: {e}"
        print(f"[orchestrate] {msg}")
        slack_dm(msg, dry_run=dry_run)
        return {"status": "error", "reason": "estimate_json_error", "project": client_name, "detail": str(e)}
    except Exception as e:
        msg = f"❌ *{client_name}* — Estimate builder failed: {type(e).__name__}: {e}"
        print(f"[orchestrate] {msg}")
        slack_dm(msg, dry_run=dry_run)
        return {"status": "error", "reason": "estimate_build_error", "project": client_name, "detail": str(e)}

    # Save estimate JSON locally
    json_path = Path(td) / f"{lastname}_estimate.json"
    with open(json_path, "w") as f:
        json.dump(estimate, f, indent=2)
    print(f"[orchestrate] estimate.json saved ({estimate.get('rcv_total', 0):,.2f} RCV)")

    # ── Step 7: Render HTML + PDF ────────────────────────────────────────────
    print("\n[orchestrate] Step 7: Rendering PDF...")
    from html_renderer import render as render_html
    from pdf_renderer import render as render_pdf

    html_path = str(Path(td) / f"{lastname}_estimate.html")
    try:
        render_html(estimate, html_path)
        pdf_filename = f"{lastname}_IFC Supp {version}.pdf"
        pdf_path     = str(Path(td) / pdf_filename)
        render_pdf(html_path, pdf_path)
    except Exception as e:
        msg = f"❌ *{client_name}* — PDF rendering failed: {type(e).__name__}: {e}\nEstimate JSON was saved — you can re-render manually."
        print(f"[orchestrate] {msg}")
        slack_dm(msg, dry_run=dry_run)
        return {"status": "error", "reason": "pdf_render_error", "project": client_name, "detail": str(e)}
    print(f"[orchestrate] PDF rendered: {pdf_filename}")

    # ── Step 8: Flow package ─────────────────────────────────────────────────
    print("\n[orchestrate] Step 8: Building flow package...")
    from flow_package import generate_flow_package, save_flow_package, print_flow_summary
    try:
        flow_pkg  = generate_flow_package(estimate, pipeline_data)
        flow_path, clarity_path = save_flow_package(flow_pkg, Path(td), lastname)
    except Exception as e:
        msg = f"⚠️ *{client_name}* — Flow package failed: {e}\nEstimate PDF was built successfully — uploading without flow package."
        print(f"[orchestrate] {msg}")
        slack_dm(msg, dry_run=dry_run)
        flow_pkg = {"cards": [], "warnings": [f"Flow package failed: {e}"], "project_name": client_name, "project_id": project_id, "rcv_total": estimate.get("rcv_total", 0)}
        flow_path = None
        clarity_path = None
    else:
        print(f"[orchestrate] Flow package saved ({len(flow_pkg['cards'])} cards)")

    # ── Step 9: Upload estimate PDF + flow JSON + estimate JSON ──────────────
    if dry_run:
        pdf_link     = "DRY_RUN"
        clarity_link = "DRY_RUN"
    else:
        print(f"\n[orchestrate] Step 9: Uploading to Shared Drive → projects/{client_name}/...")
        try:
            pdf_file_id, pdf_link       = upload_file_to_folder(pdf_path,           client_folder_id)
            if clarity_path:
                _, clarity_link         = upload_file_to_folder(str(clarity_path),  client_folder_id)
            else:
                clarity_link = "(flow package failed — not uploaded)"
            if flow_path:
                upload_file_to_folder(str(flow_path), client_folder_id)  # debug copy
            upload_file_to_folder(str(json_path), client_folder_id)
            pipeline_data["uploaded_pdf_link"] = pdf_link
        except Exception as e:
            msg = f"⚠️ *{client_name}* — Upload failed: {e}\nFiles saved locally in: {td}"
            print(f"[orchestrate] {msg}")
            slack_dm(msg, dry_run=dry_run)
            pdf_link     = f"(upload failed — local: {td})"
            clarity_link = pdf_link

    # ── Step 10: Slack summary ────────────────────────────────────────────────
    print(f"\n[orchestrate] Step 10: Notifying Alvaro on Slack...")

    # Build summary
    sections   = estimate.get("sections", [])
    n_items    = sum(len(s["line_items"]) for s in sections)
    n_added    = sum(1 for s in sections for i in s["line_items"] if i.get("source") == "added")
    n_bids     = len([c for c in flow_pkg["cards"] if c["action_type"] == "bid"])
    nrd_warns  = [w for w in flow_pkg.get("warnings", []) if "NRD" in w]
    n_create   = sum(1 for c in flow_pkg["cards"] if c["action"] == "create")
    n_update   = sum(1 for c in flow_pkg["cards"] if c["action"] == "update")

    msg_lines = [
        f"✅ *{client_name}* supplement is ready for review.",
        f"",
        f"*Estimate:* ${estimate.get('rcv_total', 0):,.2f} RCV | {n_items} items | {n_added} items added",
        f"*Flow cards:* {n_update} update, {n_create} create",
    ]
    if nrd_warns:
        msg_lines.append(f"⚠️ *NRD flagged:* {len(nrd_warns)} trade(s) — check for rebuttal opportunities")
    if flow_pkg.get("warnings"):
        other_warns = [w for w in flow_pkg["warnings"] if "NRD" not in w]
        if other_warns:
            msg_lines.append(f"⚠️ *Warnings:* {len(other_warns)} — review flow package")
    msg_lines += [
        f"",
        f"📄 *Estimate PDF:* {pdf_link}",
        f"📋 *Clarity JSON:* {clarity_link}",
        f"",
        f"_Download the Clarity JSON and upload it directly to Clarity in the project._",
    ]

    print_flow_summary(flow_pkg)
    slack_dm("\n".join(msg_lines), dry_run=dry_run)

    print(f"\n{'='*65}")
    print(f"  ✅ DONE — {client_name}")
    print(f"  RCV: ${estimate.get('rcv_total', 0):,.2f}")
    print(f"  Staging: projects/{client_name}/")
    print(f"{'='*65}\n")

    return {
        "status": "ok",
        "project": client_name,
        "project_id": project_id,
        "rcv_total": estimate.get("rcv_total", 0),
        "pdf_link": pdf_link,
        "clarity_link": clarity_link,
        "flow_cards": len(flow_pkg["cards"]),
        "warnings": flow_pkg.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="IFC Supplement Orchestrator")
    parser.add_argument("project_name", nargs="+", help="Project name (e.g. 'Karen Shultz')")
    parser.add_argument("--skip-markup", action="store_true", help="Skip bid markup step")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip uploads and Slack — test mode")
    parser.add_argument("--version", default="1.0",
                        help="Supplement version number (default: 1.0)")
    args = parser.parse_args()

    name = " ".join(args.project_name)
    result = orchestrate(
        project_name=name,
        skip_markup=args.skip_markup,
        dry_run=args.dry_run,
        version=args.version,
    )

    if result["status"] == "blocked":
        sys.exit(1)


if __name__ == "__main__":
    main()
