#!/usr/bin/env python3
"""
generate.py — Main entry point for IFC Supplement PDF Generator.

Usage:
    python3 generate.py "Rose Brock"
    python3 generate.py "Chris Isbell" --skip-upload
    python3 generate.py "Rose Brock" --json-only      # stop after estimate.json
    python3 generate.py "Rose Brock" --html-only      # stop after estimate.html
    python3 generate.py "Rose Brock" --from-json estimate.json  # skip pipeline

⚠️  HARD RULE: This script NEVER sends anything to insurance.
    It generates a PDF and saves it to Drive for human review.
    A human must always review and approve before sending to insurance.
"""

import sys
import os
import json
import argparse
import tempfile
from pathlib import Path
from datetime import datetime

# Add parent for module resolution
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# Activate venv if present
VENV_SITE = Path(__file__).parent / ".venv" / "lib"
if VENV_SITE.exists():
    import site
    for p in VENV_SITE.glob("python*/site-packages"):
        site.addsitedir(str(p))


def parse_args():
    parser = argparse.ArgumentParser(description="IFC Supplement PDF Generator")
    parser.add_argument("project_name", nargs="*", help="Project name (e.g. 'Rose Brock')")
    parser.add_argument("--skip-upload", action="store_true", help="Skip Drive upload")
    parser.add_argument("--json-only", action="store_true", help="Stop after building estimate.json")
    parser.add_argument("--html-only", action="store_true", help="Stop after building estimate.html")
    parser.add_argument("--from-json", metavar="PATH", help="Load estimate.json from file, skip pipeline")
    parser.add_argument("--output-dir", metavar="DIR", help="Output directory (default: current dir)")
    parser.add_argument("--version", metavar="VER", help="Supplement version override (e.g. 1.0)")
    return parser.parse_args()


def main():
    args = parse_args()
    project_name = " ".join(args.project_name) if args.project_name else None

    if not project_name and not args.from_json:
        print("Usage: python3 generate.py \"Rose Brock\"")
        print("       python3 generate.py \"Rose Brock\" --skip-upload")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n{'='*60}")
    print(f"IFC Supplement PDF Generator — {run_id}")
    if project_name:
        print(f"Project: {project_name}")
    print(f"{'='*60}\n")

    # ── Step 1: Data Pipeline ─────────────────────────────────
    if args.from_json:
        print(f"[generate] Loading estimate from: {args.from_json}")
        with open(args.from_json) as f:
            estimate = json.load(f)
        pipeline_data = {
            "lastname": estimate.get("estimate_name", "UNKNOWN").split("_")[0],
            "action_trackers": [],
            "ins_by_tag": {},
            "bids": [],
            "notes": {"supplement": [], "momentum": [], "ifc": []},
        }
        project_folder_id = None
    else:
        print("[generate] Step 1/6: Running data pipeline...")
        from data_pipeline import run as pipeline_run
        pipeline_data = pipeline_run(project_name)
        project_folder_id = pipeline_data.get("project_folder_id")

        # ── Step 2: Estimate Builder (AI) ─────────────────────
        print("\n[generate] Step 2/6: Building estimate (AI)...")
        from estimate_builder import build_estimate
        estimate = build_estimate(pipeline_data)

        # ── Step 2.5: QA Agent (AI review + corrections) ─────
        print("\n[generate] Step 2.5/6: Running QA review...")
        from qa_agent import qa_review
        estimate = qa_review(estimate, pipeline_data)

        # Save pipeline data for standalone QA reruns
        pipeline_json_path = output_dir / f"{pipeline_data['lastname']}_pipeline.json"
        try:
            # Save serializable subset of pipeline data
            _save_pipeline = {
                "ev_data": pipeline_data.get("ev_data", {}),
                "ins_data": pipeline_data.get("ins_data", {}),
                "bids": pipeline_data.get("bids", []),
                "pricelist": {k: v for k, v in pipeline_data.get("pricelist", {}).items()},
                "notes": pipeline_data.get("notes", {}),
                "lastname": pipeline_data.get("lastname", ""),
            }
            with open(pipeline_json_path, "w") as f:
                json.dump(_save_pipeline, f, indent=2)
            print(f"[generate] Pipeline data saved for QA reruns: {pipeline_json_path}")
        except Exception as e:
            print(f"[generate] ⚠️  Could not save pipeline data: {e}")

    # Save estimate.json
    json_path = output_dir / f"{pipeline_data['lastname']}_estimate.json"
    with open(json_path, "w") as f:
        json.dump(estimate, f, indent=2)
    print(f"\n[generate] estimate.json saved: {json_path}")

    if args.json_only:
        print("\n✅ Done (--json-only). Review estimate.json before proceeding.")
        _print_summary(estimate)
        return

    # ── Step 3: HTML Renderer ─────────────────────────────────
    print("\n[generate] Step 3/6: Rendering HTML...")
    from html_renderer import render as render_html
    html_path = str(output_dir / f"{pipeline_data['lastname']}_estimate.html")
    render_html(estimate, html_path)

    if args.html_only:
        print(f"\n✅ Done (--html-only). Review HTML: {html_path}")
        _print_summary(estimate)
        return

    # ── Step 4: PDF Renderer ──────────────────────────────────
    print("\n[generate] Step 4/6: Generating PDF...")
    from pdf_renderer import render as render_pdf
    lastname = pipeline_data.get("lastname", estimate.get("estimate_name", "ESTIMATE").split("_")[0])
    pdf_filename = f"{lastname}_IFC Supp {args.version or '1.0'}.pdf"
    pdf_path = str(output_dir / pdf_filename)
    render_pdf(html_path, pdf_path)

    print(f"\n[generate] PDF saved: {pdf_path}")

    # ── Step 5: Upload to Drive (Supplement folder) ─────────
    if args.skip_upload:
        print("\n[generate] Skipping Drive upload (--skip-upload)")
    elif not project_folder_id:
        print("\n[generate] ⚠️  No project_folder_id — skipping Drive upload")
    else:
        print("\n[generate] Step 5/6: Uploading to project Supplement folder...")
        from uploader import upload
        file_id = upload(
            pdf_path,
            project_name=project_name or pipeline_data.get("lastname", "UNKNOWN"),
            lastname=lastname,
            version=args.version,
            project_folder_id=project_folder_id,
        )
        if file_id:
            drive_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
            pipeline_data["uploaded_pdf_link"] = drive_link
            print(f"[generate] ✅ Uploaded to Supplement/: {drive_link}")

    # ── Step 6: Flow Package ──────────────────────────────────
    print("\n[generate] Step 6/6: Generating Flow card package...")
    from flow_package import generate_flow_package, print_flow_summary, save_flow_package
    flow_pkg = generate_flow_package(estimate, pipeline_data)
    flow_path = save_flow_package(flow_pkg, output_dir, pipeline_data.get("lastname", "ESTIMATE"))
    print(f"[generate] Flow package saved: {flow_path}")

    # ── Final Summary ─────────────────────────────────────────
    print()
    _print_summary(estimate)
    print_flow_summary(flow_pkg)

    print("⚠️  REVIEW REQUIRED BEFORE SENDING TO INSURANCE")
    print("Human review gate — never send directly from this script.")
    print("="*60)


def _print_summary(estimate: dict):
    sections = estimate.get("sections", [])
    total_items = sum(len(s["line_items"]) for s in sections)
    added = sum(1 for s in sections for i in s["line_items"] if i.get("source") == "added")
    adjusted = sum(1 for s in sections for i in s["line_items"] if i.get("source") == "adjusted")
    ins_items = sum(1 for s in sections for i in s["line_items"] if i.get("source") == "ins")

    print(f"\n📋 Estimate Summary: {estimate.get('estimate_name', '')}")
    print(f"   Insured:     {estimate.get('policy_holder', '')}")
    print(f"   Address:     {estimate.get('address', '')}")
    print(f"   Sections:    {len(sections)}")
    print(f"   Total items: {total_items} ({ins_items} copied, {added} added, {adjusted} adjusted)")
    print(f"   Price List:  {estimate.get('price_list', '')}")
    print()
    print(f"   Remove Total:  ${estimate.get('remove_total', 0):>12,.2f}")
    print(f"   Replace Total: ${estimate.get('replace_total', 0):>12,.2f}")
    print(f"   Tax:           ${estimate.get('tax_total', 0):>12,.2f}")
    print(f"   O&P:           ${estimate.get('op_total', 0):>12,.2f}")
    print(f"   ─────────────────────────────")
    print(f"   RCV Total:     ${estimate.get('rcv_total', 0):>12,.2f}")
    print()
    for cov, amount in estimate.get("coverage_split", {}).items():
        if amount > 0:
            print(f"   {cov}: ${amount:,.2f}")


if __name__ == "__main__":
    main()
