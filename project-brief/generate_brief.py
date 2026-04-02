#!/usr/bin/env python3
"""IFC Project Brief Generator — pulls project data from Omni API and generates a markdown brief."""

import argparse
import json
import re
import sys
import html
import requests

BASE_URL = "https://omni.ifc.shibui.ar"
TOKEN = "ea6d402f02e42090a8ab9b34d06d0864f00e9b252719ca244f9963b1334bb226"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
TIMEOUT = 30


# ── API helpers ──────────────────────────────────────────────────────────────

def api_get(path, params=None):
    r = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_project_by_id(pid):
    # Try direct endpoint first
    try:
        data = api_get(f"/projects/{pid}")
        if isinstance(data, dict):
            # Might be wrapped in {"project": {...}} or just {...}
            proj = data.get("project", data) if "project" in data else data
            if proj.get("id") == pid:
                return proj
    except Exception:
        pass
    # Fallback: search with the ID as string
    data = api_get("/projects", {"search": str(pid)})
    for p in data.get("projects", []):
        if p["id"] == pid:
            return p
    return None


def search_projects(name):
    data = api_get("/projects", {"search": name})
    return data.get("projects", [])


def fetch_action_trackers(project_id):
    return api_get("/action_trackers", {"project_id": project_id})


def fetch_posts(project_id):
    data = api_get("/posts", {"project_id": project_id})
    return data.get("posts", [])


# ── HTML cleaning ────────────────────────────────────────────────────────────

def clean_html(text):
    """Convert HTML post note body to readable text with @tags extracted."""
    if not text:
        return ""
    # Extract @tags from mention-tag spans
    tags = re.findall(r'class="mention-tag">@(\w+)</span>', text)
    # Extract user mentions
    user_mentions = re.findall(r"class='user-mention-message'>(.*?)</span>", text)
    # Replace <br>, <div>, </div>, </p> with newlines
    t = re.sub(r'<br\s*/?>', '\n', text)
    t = re.sub(r'</(div|p)>', '\n', t)
    t = re.sub(r'<(div|p)[^>]*>', '', t)
    # Strip all remaining HTML tags
    t = re.sub(r'<[^>]+>', '', t)
    # Decode HTML entities
    t = html.unescape(t)
    # Collapse multiple blank lines
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip(), tags, user_mentions


def extract_tags_from_body(body):
    """Return set of @tags found in a post note body."""
    if not body:
        return set()
    tags = re.findall(r'class="mention-tag">@(\w+)</span>', body)
    # Also catch plain text @tags
    tags += re.findall(r'(?<!\w)@(\w+)(?!\w)', re.sub(r'<[^>]+>', '', body))
    return set(t.lower() for t in tags)


# ── Brief generation ─────────────────────────────────────────────────────────

TAG_CATEGORIES = {
    "ifc": "ifc",
    "supplement": "supplement",
    "momentum": "momentum",
    "ins_responded": "status",
    "supp_sent": "status",
    "appraisal": "status",
    "pa_law_appraisal_expert": "status",
    "client": "client",
    "bill": "billing",
    "billhome": "billing",
    "accounting": "billing",
    "install": "install",
}


def categorize_notes(posts):
    """Categorize all post notes by tag."""
    categorized = {
        "ifc": [], "supplement": [], "momentum": [], "status": [],
        "client": [], "billing": [], "install": [], "other": []
    }
    for post in posts:
        for note in post.get("post_notes", []):
            body = note.get("body", "")
            tags = extract_tags_from_body(body)
            cleaned, _, _ = clean_html(body)
            entry = {
                "id": note.get("id"),
                "date": note.get("created_at", ""),
                "author": note.get("user", {}).get("name", "Unknown"),
                "body": cleaned,
                "tags": tags,
            }
            placed = False
            for tag in tags:
                cat = TAG_CATEGORIES.get(tag)
                if cat and cat in categorized:
                    categorized[cat].append(entry)
                    placed = True
            if not placed:
                categorized["other"].append(entry)
    # Sort each category by date
    for cat in categorized:
        categorized[cat].sort(key=lambda x: x["date"])
    return categorized


def format_date(iso):
    if not iso:
        return "N/A"
    return iso[:10]


def build_markdown(project, trackers, categorized):
    lines = []
    name = project.get("name", "Unknown")
    lines.append(f"# Project Brief: {name}")
    lines.append("")
    lines.append(f"**Address:** {project.get('full_address', 'N/A')}")
    lines.append(f"**Status:** {project.get('status', 'N/A')}")
    lines.append(f"**Record Status:** {project.get('record_status', 'N/A')}")
    lines.append(f"**Last Contact:** {format_date(project.get('last_contacted'))}")
    drive = project.get("google_drive_link")
    lines.append(f"**Drive:** [{drive}]({drive})" if drive else "**Drive:** N/A")
    lines.append("")

    # Game Plan (@ifc)
    lines.append("## Game Plan (@ifc)")
    lines.append("")
    gpn = project.get("supplement_gameplan_notes")
    if gpn:
        lines.append("### Supplement / Gameplan Notes (from project)")
        lines.append(gpn.strip())
        lines.append("")
    if categorized["ifc"]:
        for n in categorized["ifc"]:
            lines.append(f"**{format_date(n['date'])}** — {n['author']}")
            lines.append(n["body"])
            lines.append("")
    elif not gpn:
        lines.append("*No @ifc notes found.*")
        lines.append("")

    # Supplement Strategy
    lines.append("## Supplement Strategy (@supplement)")
    lines.append("*⚠️ INTERNAL ONLY — not sent to insurance*")
    lines.append("")
    if categorized["supplement"]:
        for n in categorized["supplement"]:
            lines.append(f"**{format_date(n['date'])}** — {n['author']}")
            lines.append(n["body"])
            lines.append("")
    else:
        lines.append("*No @supplement notes found.*")
        lines.append("")

    # Timeline (@momentum)
    lines.append("## Timeline (@momentum)")
    lines.append("")
    if categorized["momentum"]:
        for n in categorized["momentum"]:
            lines.append(f"- **{format_date(n['date'])}** ({n['author']}): {n['body'][:200]}{'...' if len(n['body']) > 200 else ''}")
            lines.append("")
    else:
        lines.append("*No @momentum notes found.*")
        lines.append("")

    # Action Trackers / Flow
    lines.append("## Action Trackers / Flow")
    lines.append("")

    bids = []
    pricelist_tracker = None
    op_tracker = None
    ifc_tracker = None

    for t in trackers:
        tag = t.get("tag") or ""
        if tag == "@ifc":
            ifc_tracker = t
        elif tag in ("@pricelist",):
            pricelist_tracker = t
        else:
            bids.append(t)

    lines.append("### Bids")
    lines.append("")
    if bids:
        for b in bids:
            tag = b.get("tag") or "untagged"
            status = b.get("status") or "—"
            emoji = b.get("supplement_status_emoji") or ""
            content = (b.get("content") or "")[:150]
            lines.append(f"- {emoji} **{tag}** — Status: {status}")
            if content:
                lines.append(f"  {content}")
    else:
        lines.append("*No bid trackers found.*")
    lines.append("")

    lines.append("### Pricelist")
    lines.append("")
    if ifc_tracker:
        ours = ifc_tracker.get("our_price_list") or "N/A"
        theirs = ifc_tracker.get("ins_price_list") or "N/A"
        lines.append(f"- **Ours:** {ours}")
        lines.append(f"- **Theirs:** {theirs}")
        if ifc_tracker.get("pricelist_notes"):
            lines.append(f"- Notes: {ifc_tracker['pricelist_notes']}")
    else:
        lines.append("*No pricelist data found.*")
    lines.append("")

    lines.append("### O&P")
    lines.append("")
    if ifc_tracker:
        our_op = ifc_tracker.get("our_op") or "N/A"
        their_op = ifc_tracker.get("their_op") or "N/A"
        op_notes = ifc_tracker.get("op_card_notes") or ""
        lines.append(f"- **Our O&P:** {our_op}")
        lines.append(f"- **Their O&P:** {their_op}")
        if op_notes:
            lines.append(f"- Notes: {op_notes}")
    else:
        lines.append("*No O&P data found.*")
    lines.append("")

    # Client Communications
    lines.append("## Client Communications (@client)")
    lines.append("")
    if categorized["client"]:
        for n in categorized["client"]:
            lines.append(f"**{format_date(n['date'])}** — {n['author']}")
            lines.append(n["body"])
            lines.append("")
    else:
        lines.append("*No @client notes found.*")
        lines.append("")

    # Install
    if categorized["install"]:
        lines.append("## Production Game Plan (@install)")
        lines.append("")
        for n in categorized["install"]:
            lines.append(f"**{format_date(n['date'])}** — {n['author']}")
            lines.append(n["body"])
            lines.append("")

    # Notepad
    lines.append("## Notepad")
    lines.append("")
    notepad = project.get("notepad")
    if notepad:
        cleaned, _, _ = clean_html(notepad)
        lines.append(cleaned)
    else:
        lines.append("*Empty.*")
    lines.append("")

    return "\n".join(lines)


def build_json_output(project, trackers, categorized):
    return {
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "address": project.get("full_address"),
            "status": project.get("status"),
            "record_status": project.get("record_status"),
            "last_contacted": project.get("last_contacted"),
            "google_drive_link": project.get("google_drive_link"),
            "supplement_gameplan_notes": project.get("supplement_gameplan_notes"),
            "notepad": project.get("notepad"),
        },
        "notes": categorized,
        "action_trackers": trackers,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IFC Project Brief Generator")
    parser.add_argument("project_name", nargs="?", help="Project name to search for")
    parser.add_argument("--id", type=int, help="Project ID (skip search)")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    args = parser.parse_args()

    if not args.project_name and not args.id:
        parser.error("Provide a project name or --id <project_id>")

    # Resolve project
    if args.id:
        project = fetch_project_by_id(args.id)
        if not project:
            # Try searching by id in list
            projects = search_projects("")
            project = next((p for p in projects if p["id"] == args.id), None)
        if not project:
            print(f"Error: Project ID {args.id} not found.", file=sys.stderr)
            sys.exit(1)
    else:
        projects = search_projects(args.project_name)
        if not projects:
            print(f"No projects found for '{args.project_name}'", file=sys.stderr)
            sys.exit(1)
        if len(projects) > 1:
            print(f"Multiple projects found for '{args.project_name}':", file=sys.stderr)
            for p in projects:
                print(f"  ID {p['id']}: {p['name']} — {p.get('full_address', 'N/A')}", file=sys.stderr)
            print("\nUse --id <project_id> to select one.", file=sys.stderr)
            sys.exit(1)
        project = projects[0]

    pid = project["id"]
    print(f"Generating brief for: {project['name']} (ID: {pid})", file=sys.stderr)

    # Fetch data
    trackers = fetch_action_trackers(pid)
    posts = fetch_posts(pid)
    categorized = categorize_notes(posts)

    # Generate output
    if args.as_json:
        output = json.dumps(build_json_output(project, trackers, categorized), indent=2, default=str)
    else:
        output = build_markdown(project, trackers, categorized)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Brief saved to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
