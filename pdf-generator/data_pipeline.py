"""
data_pipeline.py — Pure data fetching/parsing. No AI, no business logic.
Input: project_name (string)
Output: PipelineData dict with everything estimate_builder.py needs
"""

import os
import sys
import json
import re
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Union, Dict, List, Any

# --- Path setup ---
ROOT = Path(__file__).parent.parent.parent  # workspace root
sys.path.insert(0, str(ROOT / "tools" / "parsers"))

load_dotenv(ROOT / ".env")


def _log_anthropic_usage(resp, label: str = "pipeline"):
    """Log token usage and estimated cost from an Anthropic API response."""
    try:
        usage = resp.usage
        input_tk = getattr(usage, 'input_tokens', 0)
        output_tk = getattr(usage, 'output_tokens', 0)
        model = getattr(resp, 'model', '') or ''
        # Sonnet: $3/$15, Opus: $15/$75
        is_opus = 'opus' in model.lower()
        rate_in = 15 if is_opus else 3
        rate_out = 75 if is_opus else 15
        cost_in = input_tk * rate_in / 1_000_000
        cost_out = output_tk * rate_out / 1_000_000
        print(f"[{label}] Tokens: {input_tk:,} in + {output_tk:,} out = {input_tk+output_tk:,} total | Cost: ${cost_in:.4f} + ${cost_out:.4f} = ${cost_in+cost_out:.4f}")
    except Exception:
        pass  # Don't break pipeline over logging

IFC_BASE_URL = os.getenv("IFC_BASE_URL", "https://omni.ifc.shibui.ar")
IFC_API_TOKEN = os.getenv("IFC_API_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PRICELIST_SHEET_ID = "1wpp-nwHlUCJSECx9iOSlpyCCczX1_iDYy-p08UFiyTQ"
SHARED_DRIVE_UPLOAD_FOLDER = "1tWeZivnrRjDtZq1eG6dHu4vHkBwgMWop"  # Generated Supplements in Sup AI

import requests

def get_service_account():
    creds_path = ROOT / "google-drive-key.json"
    from google.oauth2 import service_account
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ]
    return service_account.Credentials.from_service_account_file(str(creds_path), scopes=scopes).with_subject('sup@ifcroofing.com')


# ─── IFC API ───────────────────────────────────────────────────────────────────

def fetch_project(project_name: str) -> dict:
    """Search IFC API for project by name. Returns first match."""
    headers = {"Authorization": f"Bearer {IFC_API_TOKEN}"}
    r = requests.get(f"{IFC_BASE_URL}/projects", params={"search": project_name}, headers=headers)
    r.raise_for_status()
    data = r.json()
    # API can return: list, {"data": []}, {"projects": []}
    if isinstance(data, list):
        projects = data
    else:
        projects = data.get("projects") or data.get("data") or []
    if not projects:
        raise ValueError(f"No project found for: {project_name}")
    # Try exact match first
    for p in projects:
        name = p.get("name", "") or p.get("title", "") or ""
        if project_name.lower() in name.lower():
            return p
    return projects[0]


def fetch_posts(project_id: int) -> list[dict]:
    """Fetch all posts for a project. Returns list of posts."""
    headers = {"Authorization": f"Bearer {IFC_API_TOKEN}"}
    r = requests.get(f"{IFC_BASE_URL}/posts", params={"project_id": project_id, "user": "sup"}, headers=headers)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data
    return data.get("posts") or data.get("data") or []


def _strip_html(text: str) -> str:
    """Strip HTML tags from text, decode entities."""
    import html
    # Extract @tag mentions from span elements
    tag_pattern = re.compile(r'<span[^>]*class="mention-tag"[^>]*>(.*?)</span>', re.DOTALL)
    mentions = tag_pattern.findall(text)
    # Remove all HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = html.unescape(clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _fetch_game_plan_doc(folder_id: str) -> Optional[str]:
    """
    Search for a Game Plan Google Doc associated with this project.
    Searches the project folder AND its parent folders.
    Uses Drive export API (no Google Docs API required).
    Returns plain text content or None if not found.
    """
    try:
        import io
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        creds = get_service_account()
        drive_svc = build("drive", "v3", credentials=creds)

        name_patterns = ["game plan", "game", "supp & install", "supp and install"]

        # Get parent folders to widen search
        folder_ids_to_search = [folder_id]
        try:
            folder_meta = drive_svc.files().get(
                fileId=folder_id, fields="parents", supportsAllDrives=True
            ).execute()
            for pid in folder_meta.get("parents", []):
                folder_ids_to_search.append(pid)
        except Exception:
            pass

        doc_file = None
        for fid in folder_ids_to_search:
            resp = drive_svc.files().list(
                q=(f"'{fid}' in parents and trashed=false "
                   f"and mimeType='application/vnd.google-apps.document'"),
                supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
                fields="files(id,name)"
            ).execute()
            for pattern in name_patterns:
                for f in resp.get("files", []):
                    if pattern.lower() in f["name"].lower():
                        doc_file = f
                        break
                if doc_file:
                    break
            if doc_file:
                break

        if not doc_file:
            return None

        print(f"[pipeline] Found game plan doc: {doc_file['name']}")

        # Export as plain text using Drive export (no Docs API needed)
        buf = io.BytesIO()
        req = drive_svc.files().export_media(
            fileId=doc_file["id"], mimeType="text/plain"
        )
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        text = buf.getvalue().decode("utf-8", errors="ignore").strip()
        return text[:4000]  # cap at 4k chars to keep prompt lean

    except Exception as e:
        print(f"[pipeline] Game plan doc fetch failed: {e}")
        return None


def extract_tagged_notes(posts: list[dict]) -> dict:
    """
    Extract @ifc, @supplement, @momentum notes from post_notes (handles HTML bodies).

    Also captures @office_hands and @supp_sent notes as momentum — these often
    contain the actual scope/strategy and sent-supplement items respectively.

    Notes with only tag text (no real content) are skipped.
    """
    notes = {"ifc": [], "supplement": [], "momentum": [], "untagged": []}
    for post in posts:
        post_notes = post.get("post_notes", [])
        if isinstance(post_notes, str):
            try:
                post_notes = json.loads(post_notes)
            except Exception:
                post_notes = []
        for note in post_notes:
            raw_body = note.get("body", "") or ""
            # Detect tags from HTML span mentions
            tag_matches = re.findall(r'@(\w+)', raw_body)
            tag_set = {t.lower() for t in tag_matches}
            # Also check explicit tags field
            tags = note.get("tags", []) or []
            if isinstance(tags, str):
                tags = [tags]
            tag_set.update(str(t).lower().strip("#@") for t in tags)

            # Strip HTML for clean body text
            clean_body = _strip_html(raw_body)

            # Skip notes that are only tag references (no real content).
            # A note is "only tags" if after removing @word tokens it has < 10 chars.
            content_only = re.sub(r'@\w+', '', clean_body).strip()
            if len(content_only) < 10:
                continue

            matched = False
            if "ifc" in tag_set:
                notes["ifc"].append(clean_body)
                matched = True
            if "supplement" in tag_set:
                notes["supplement"].append(clean_body)
                matched = True
            # Treat @momentum, @office_hands, and @supp_sent as momentum context
            if tag_set & {"momentum", "office_hands", "supp_sent"}:
                notes["momentum"].append(clean_body)
                matched = True
            # Capture notes with no recognized tags (empty spans, missing tags, etc.)
            if not matched:
                notes["untagged"].append(clean_body)
    return notes


# ─── Google Drive ──────────────────────────────────────────────────────────────

def _build_drive_service():
    from googleapiclient.discovery import build
    creds = get_service_account()
    return build("drive", "v3", credentials=creds)


def _drive_search(service, q, fields="files(id, name, parents)"):
    resp = service.files().list(
        q=q,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields=fields,
    ).execute()
    return resp.get("files", [])


def _drive_get_subfolders(service, folder_id):
    return _drive_search(
        service,
        f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)",
    )


def search_drive_file(filename_pattern: str, drive_folder_id: str = None) -> Optional[str]:
    """Search Drive for a file matching pattern. Returns file ID."""
    service = _build_drive_service()

    if drive_folder_id:
        folders_to_search = [drive_folder_id]
        current_level = [drive_folder_id]
        for _depth in range(3):
            next_level = []
            for fid in current_level:
                next_level.extend(sf["id"] for sf in _drive_get_subfolders(service, fid))
            if not next_level:
                break
            folders_to_search.extend(next_level)
            current_level = next_level

        for fid in folders_to_search:
            q = f"name contains '{filename_pattern}' and '{fid}' in parents and trashed=false and mimeType != 'application/vnd.google-apps.folder'"
            files = _drive_search(service, q)
            if files:
                return files[0]["id"]

    q = f"name contains '{filename_pattern}' and trashed=false and mimeType != 'application/vnd.google-apps.folder'"
    files = _drive_search(service, q)
    if files:
        return files[0]["id"]
    return None


def find_drive_subfolder(folder_name: str, parent_folder_id: str) -> Optional[str]:
    """Find an immediate subfolder by exact name under a parent folder."""
    service = _build_drive_service()
    q = (
        f"name = '{folder_name}' and '{parent_folder_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    folders = _drive_search(service, q, fields="files(id, name)")
    return folders[0]["id"] if folders else None


def list_drive_images(folder_id: str) -> List[dict]:
    """List ordered image files in a Drive folder."""
    service = _build_drive_service()
    q = (
        f"'{folder_id}' in parents and trashed=false and "
        f"mimeType contains 'image/'"
    )
    resp = service.files().list(
        q=q,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields="files(id, name, mimeType)",
        orderBy="name_natural",
    ).execute()
    return resp.get("files", [])


def download_drive_file(file_id: str, dest_path: str):
    """Download a Drive file by ID to dest_path."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import io
    creds = get_service_account()
    service = build("drive", "v3", credentials=creds)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(dest_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()


def find_project_folder(project: dict) -> Optional[str]:
    """Get the Drive folder ID for the project from project record."""
    for key in ["drive_folder_id", "folder_id", "google_drive_folder", "drive_id",
                "drive_link", "google_drive_link"]:
        val = project.get(key)
        if val:
            if isinstance(val, str) and "folders/" in val:
                return val.split("folders/")[-1].split("?")[0].strip()
            elif isinstance(val, str) and len(val) > 10 and "/" not in val:
                return val  # raw folder ID
    return None


EXPECTED_FOLDERS = {"supplement", "original bids", "paid labor & materials"}
BID_SKIP_PATTERNS = ["ins", "eagleview", "eagle view", "ev_", "contract", "photo", "diagram",
                     "scope of work", "policy", "declaration"]

def drive_health_check(project_folder_id: str) -> dict:
    """
    Audit project Drive folder structure.
    Expected subfolders: Supplement/, Original Bids/, Paid Labor & Materials/
    Returns {issues, warnings, folder_ids: {supplement, original_bids, paid_labor}}
    """
    issues = []
    warnings = []
    folder_ids = {"supplement": None, "original_bids": None, "paid_labor": None}

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=get_service_account())
        resp = service.files().list(
            q=f"'{project_folder_id}' in parents and trashed=false",
            fields="files(id, name, mimeType)",
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
            pageSize=50
        ).execute()
        children = resp.get("files", [])

        found_folders = {}
        root_pdfs = []

        for f in children:
            is_folder = "folder" in f["mimeType"]
            name_lower = f["name"].lower()
            if is_folder:
                found_folders[name_lower] = f["id"]
                if "supplement" in name_lower:
                    folder_ids["supplement"] = f["id"]
                elif "original bids" in name_lower or "original_bids" in name_lower:
                    folder_ids["original_bids"] = f["id"]
                elif "paid labor" in name_lower:
                    folder_ids["paid_labor"] = f["id"]
                elif name_lower not in EXPECTED_FOLDERS:
                    warnings.append(f"Unexpected folder at root: '{f['name']}' — may contain misplaced files")
            else:
                if f["name"].lower().endswith(".pdf"):
                    root_pdfs.append(f["name"])

        # Check missing folders
        if not folder_ids["supplement"]:
            issues.append("Missing 'Supplement' folder")
        if not folder_ids["original_bids"]:
            warnings.append("Missing 'Original Bids' folder — bids may be elsewhere")
        if not folder_ids["paid_labor"]:
            warnings.append("Missing 'Paid Labor & Materials' folder")

        # Flag root-level PDFs
        if root_pdfs:
            warnings.append(f"PDFs at folder root (may be misplaced): {', '.join(root_pdfs[:5])}")

    except Exception as e:
        issues.append(f"Drive health check failed: {e}")

    return {"issues": issues, "warnings": warnings, "folder_ids": folder_ids}


def fetch_bids_from_drive(project_folder_id: str, temp_dir: str) -> list[dict]:
    """
    Drive fallback for bid discovery when Flow has no bid cards.
    1. Look for Original Bids/ subfolder → scan trade subfolders
    2. If not found/empty, scan entire project folder for bid-looking PDFs
    Returns bid dicts compatible with fetch_bids_from_flow output.
    """
    import fitz as _fitz
    MARKUP_RATE = 0.30

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=get_service_account())

        def list_pdfs(folder_id):
            resp = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false and mimeType='application/pdf'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=50
            ).execute()
            return resp.get("files", [])

        def list_subfolders(folder_id):
            resp = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=30
            ).execute()
            return resp.get("files", [])

        def download_pdf(file_id, dest):
            data = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
            with open(dest, "wb") as f:
                f.write(data)

        def looks_like_bid(name: str) -> bool:
            n = name.lower()
            return not any(p in n for p in BID_SKIP_PATTERNS)

        def tag_from_name(name: str, folder_name: str = "") -> str:
            combined = (name + " " + folder_name).lower()
            tag_hints = {
                "@gutter": ["gutter", "downspout"],
                "@fence": ["fence", "fencing", "grizzly"],
                "@window": ["window", "screen", "glass"],
                "@chimney": ["chimney", "hitech", "copper"],
                "@sheetrock": ["sheetrock", "drywall", "paint"],
                "@hvac": ["hvac", "air", "heat", "cooling"],
                "@packout": ["packout", "pack out", "content"],
                "@flat_roof": ["flat", "tpo", "modified"],
                "@metal": ["metal", "copper", "flashing"],
                "@pergola": ["pergola", "gazebo", "porch"],
                "@pool": ["pool"],
                "@other": [],
            }
            for tag, hints in tag_hints.items():
                if any(h in combined for h in hints):
                    return tag
            return "@other"

        def parse_bid_pdf_simple(pdf_path: str, file_name: str, trade_tag: str) -> Optional[dict]:
            result = _parse_bid_pdf(pdf_path, trade_tag, file_name)
            return result

        bids = []
        seen_trades = set()

        # --- Try Original Bids folder first ---
        ob_folder = None
        for sf in list_subfolders(project_folder_id):
            if "original bids" in sf["name"].lower() or "original_bids" in sf["name"].lower():
                ob_folder = sf["id"]
                break

        if ob_folder:
            print(f"[pipeline][drive-bids] Found Original Bids folder — scanning trade subfolders")
            trade_folders = list_subfolders(ob_folder)
            if trade_folders:
                for tf in trade_folders:
                    if tf["name"].lower() == "archive":
                        continue
                    pdfs = list_pdfs(tf["id"])
                    for f in pdfs[:1]:  # one bid per trade folder
                        tag = tag_from_name(f["name"], tf["name"])
                        tmp = os.path.join(temp_dir, f"drive_bid_{f['id']}.pdf")
                        download_pdf(f["id"], tmp)
                        parsed = parse_bid_pdf_simple(tmp, f["name"], tag)
                        if parsed:
                            retail = round(parsed["wholesale_total"] * (1 + MARKUP_RATE), 2)
                            bid = {**parsed, "retail_total": retail, "source": "drive",
                                   "folder_link": f"https://drive.google.com/drive/folders/{tf['id']}"}
                            bids.append(bid)
                            seen_trades.add(tag)
                            print(f"[pipeline][drive-bids]   [{tag}] {parsed['sub_name']} — ${parsed['wholesale_total']:,.2f} wholesale → ${retail:,.2f} retail (Drive fallback)")
            else:
                # Original Bids folder exists but no subfolders — scan PDFs directly
                pdfs = list_pdfs(ob_folder)
                for f in pdfs:
                    if not looks_like_bid(f["name"]):
                        continue
                    tag = tag_from_name(f["name"])
                    if tag in seen_trades:
                        continue
                    tmp = os.path.join(temp_dir, f"drive_bid_{f['id']}.pdf")
                    download_pdf(f["id"], tmp)
                    parsed = parse_bid_pdf_simple(tmp, f["name"], tag)
                    if parsed:
                        retail = round(parsed["wholesale_total"] * (1 + MARKUP_RATE), 2)
                        bid = {**parsed, "retail_total": retail, "source": "drive",
                               "folder_link": f"https://drive.google.com/drive/folders/{ob_folder}"}
                        bids.append(bid)
                        seen_trades.add(tag)
                        print(f"[pipeline][drive-bids]   [{tag}] {parsed['sub_name']} — ${parsed['wholesale_total']:,.2f} → ${retail:,.2f} (Drive fallback)")

        if not bids:
            # --- Fallback: scan whole project folder ---
            print(f"[pipeline][drive-bids] No Original Bids folder — scanning full project folder")
            all_pdfs = list_pdfs(project_folder_id)
            # Also scan immediate subfolders
            for sf in list_subfolders(project_folder_id):
                all_pdfs += list_pdfs(sf["id"])

            for f in all_pdfs:
                if not looks_like_bid(f["name"]):
                    continue
                tag = tag_from_name(f["name"])
                if tag in seen_trades:
                    continue
                tmp = os.path.join(temp_dir, f"drive_bid_{f['id']}.pdf")
                download_pdf(f["id"], tmp)
                parsed = parse_bid_pdf_simple(tmp, f["name"], tag)
                if parsed:
                    retail = round(parsed["wholesale_total"] * (1 + MARKUP_RATE), 2)
                    bid = {**parsed, "retail_total": retail, "source": "drive",
                           "folder_link": ""}
                    bids.append(bid)
                    seen_trades.add(tag)
                    print(f"[pipeline][drive-bids]   [{tag}] {parsed['sub_name']} — ${parsed['wholesale_total']:,.2f} → ${retail:,.2f} (Drive wide scan)")

        return bids

    except Exception as e:
        print(f"[pipeline][drive-bids] ERROR: {e}")
        return []


def extract_claims(project: dict) -> dict:
    """Extract claim number, policy number, insurer from project claims array."""
    claims = project.get("claims", [])
    if not claims:
        return {}
    claim = claims[0]
    return {
        "claim_number": claim.get("number", ""),
        "insurance_company": claim.get("company", ""),
        "date_of_loss": claim.get("hail_date", "") or claim.get("date_of_loss", ""),
        "policy_number": claim.get("policy_number", "") or claim.get("policy", ""),
    }


def extract_address(project: dict) -> dict:
    """Extract structured address from project."""
    addr = project.get("address", {})
    if isinstance(addr, dict):
        return {
            "street": addr.get("street_address_1", "") or "",
            "city": addr.get("city", "") or "",
            "state": addr.get("state", "TX"),
            "zip": addr.get("postal_code", "") or "",
            "full": project.get("full_address", ""),
        }
    full = project.get("full_address", "")
    return {"street": full, "city": "", "state": "TX", "zip": "", "full": full}


# ─── Pricelist ─────────────────────────────────────────────────────────────────

_pricelist_cache: Optional[dict] = None

def load_pricelist() -> dict[str, dict]:
    """Load pricelist from Google Sheet. Returns {description_lower: {remove, replace, unit, category}}"""
    global _pricelist_cache
    if _pricelist_cache is not None:
        return _pricelist_cache

    from googleapiclient.discovery import build
    creds = get_service_account()
    service = build("sheets", "v4", credentials=creds)

    result = service.spreadsheets().values().get(
        spreadsheetId=PRICELIST_SHEET_ID,
        range="Pricelist!A:Z",
    ).execute()
    rows = result.get("values", [])

    if not rows:
        return {}

    headers = [h.lower().strip() for h in rows[0]]

    def _parse_float(val):
        try:
            return float(str(val or 0).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return 0.0

    # Detect format: new sheet has explicit "remove" + "replace" columns
    has_split_columns = "remove" in headers and "replace" in headers

    pricelist = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        d = dict(zip(headers, row))
        desc = d.get("description", "") or d.get("item", "")
        if not desc:
            continue

        if has_split_columns:
            # New format: Remove and Replace columns are explicit
            remove_rate = _parse_float(d.get("remove", 0))
            replace_rate = _parse_float(d.get("replace", 0))
        else:
            # Old format: single "unit price" column, R&R items need splitting
            price = _parse_float(d.get("unit price", 0) or d.get("unit_price", 0) or d.get("replace", 0))
            desc_lower_tmp = desc.lower()
            if desc_lower_tmp.startswith("r&r "):
                remove_rate = round(price * 0.25, 2)
                replace_rate = round(price * 0.75, 2)
            else:
                remove_rate = 0.0
                replace_rate = price

        desc_lower = desc.lower()
        pricelist[desc_lower] = {
            "description": desc,
            "unit": d.get("unit", "EA"),
            "remove": remove_rate,
            "replace": replace_rate,
            "trade": d.get("trade", ""),
            "is_material": _guess_is_material(desc),
        }

    _pricelist_cache = pricelist
    return pricelist


def lookup_price(description: str) -> Optional[dict]:
    """Fuzzy-match a description against the pricelist. Returns pricing dict or None."""
    pl = load_pricelist()
    desc_lower = description.lower().strip()

    # Exact match
    if desc_lower in pl:
        return pl[desc_lower]

    # Normalize: strip R&R prefix for matching
    desc_norm = desc_lower
    if desc_norm.startswith("r&r "):
        desc_norm = desc_norm[4:]

    # Try substring match — if description is contained in a pricelist key or vice versa
    for key, val in pl.items():
        key_norm = key[4:] if key.startswith("r&r ") else key
        if desc_norm in key or key_norm in desc_lower:
            return val

    # Fuzzy match — word overlap, excluding stopwords
    STOPWORDS = {"the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "or", "and", "&",
                 "-", "w/", "w/out", "up", "per", "sq", "sf", "lf", "ea", "ft", "hr"}
    desc_words = set(desc_lower.split()) - STOPWORDS
    if not desc_words:
        return None

    best = None
    best_score = 0.0
    for key, val in pl.items():
        key_words = set(key.split()) - STOPWORDS
        if not key_words:
            continue
        overlap = len(desc_words & key_words)
        # Score as percentage of the smaller set (Jaccard-like)
        min_len = min(len(desc_words), len(key_words))
        score = overlap / min_len if min_len > 0 else 0
        if score > best_score:
            best_score = score
            best = val

    # Require at least 50% word overlap (excluding stopwords)
    if best_score >= 0.5:
        return best
    return None


def _guess_is_material(description: str) -> bool:
    """Heuristic: is this a material item (taxable) vs labor-only?"""
    labor_keywords = ["labor", "supervision", "haul", "dumpster", "permit", "inspection",
                      "minimum", "charge", "mobilization", "travel", "set up", "clean up",
                      "o&p", "overhead", "profit", "general", "miscellaneous"]
    desc = description.lower()
    return not any(kw in desc for kw in labor_keywords)


# ─── Bid Parsing ───────────────────────────────────────────────────────────────

MARKUP_RATE = 0.30  # kept for reference; retail price now comes from Flow

# These trades are billed as Xactimate line items (EV measurements), NOT as single bid items.
# Their Flow cards hold the expected Xactimate total for reference only.
XACTIMATE_TRADES = {"@shingle_roof", "@roof", "@flat_roof", "@detached_garage_roof", "@gutter"}

def fetch_action_trackers(project_id: int) -> list[dict]:
    """Fetch all action tracker cards for a project from IFC API."""
    headers = {"Authorization": f"Bearer {IFC_API_TOKEN}"}
    r = requests.get(f"{IFC_BASE_URL}/action_trackers", params={"project_id": project_id}, headers=headers)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


# ─── INS → @tag Attribution ────────────────────────────────────────────────────

# Order matters — more specific patterns first, first match wins.
# Each entry: (lowercase substring to search in section name, @tag or None)
# None = skip this section (O&P summary, page headers, etc.)
INS_SECTION_TO_TAG = [
    ("dwelling roof",         "@shingle_roof"),
    ("shingle roof",          "@shingle_roof"),
    ("detached garage roof",  "@garage"),
    ("garage roof",           "@garage"),
    ("flat roof",             "@flatroof"),
    ("metal roof",            "@metalroof"),
    ("gutter",                "@gutter"),
    ("chimney cap",           "@chimney_cap"),
    ("chimney",               "@chimney"),
    ("skylight",              "@skylight"),
    ("wood fence",            "@woodfence"),
    ("wrought iron",          "@ironfence"),
    ("iron fence",            "@ironfence"),
    ("fence",                 "@fence"),
    ("window",                "@window"),
    ("screen",                "@screen"),
    ("siding",                "@siding"),
    ("paint",                 "@paint"),
    ("drywall",               "@drywall"),
    ("interior",              "@interior"),
    ("pergola",               "@pergola"),
    ("gazebo",                "@gazebo"),
    ("shed",                  "@shed"),
    ("dormer",                "@other"),
    ("back exterior",         "@other"),
    ("front exterior",        "@other"),
    ("elevation",             "@other"),   # usually multi-trade — flag in warnings
    ("shutters",              "@other"),
    ("pillar",                "@other"),
    ("general",               "@other"),
    ("labor minimum",         "@other"),
    ("debris",                None),       # roll into roof — skip for now
    ("overhead",              None),       # O&P line — skip
    ("summary",               None),       # skip
    ("roofing",               "@shingle_roof"),  # catch-all
]

# Same for estimate section names → @tag
ESTIMATE_SECTION_TO_TAG = [
    ("dwelling roof",         "@shingle_roof"),
    ("shingle roof",          "@shingle_roof"),
    ("detached garage",       "@garage"),
    ("garage roof",           "@garage"),
    ("flat roof",             "@flatroof"),
    ("metal roof",            "@metalroof"),
    ("gutter",                "@gutter"),
    ("chimney cap",           "@chimney_cap"),
    ("chimney",               "@chimney"),
    ("skylight",              "@skylight"),
    ("wood fence",            "@woodfence"),
    ("iron fence",            "@ironfence"),
    ("fence & siding",        "@fence"),   # ambiguous — best guess, will warn
    ("fence",                 "@fence"),
    ("siding",                "@siding"),
    ("window",                "@window"),
    ("screen",                "@screen"),
    ("paint",                 "@paint"),
    ("drywall",               "@drywall"),
    ("interior",              "@interior"),
    ("pergola",               "@pergola"),
    ("specialty structure",   "@other"),
    ("gazebo",                "@gazebo"),
    ("shed",                  "@shed"),
    ("elevation",             "@other"),   # multi-trade — use bid cards instead
    ("general",               "@other"),
    ("labor minimum",         "@other"),
    ("debris",                None),       # skip
    ("overhead",              None),       # skip
]

AMBIGUOUS_SECTIONS = {"elevation", "shutters", "back exterior", "front exterior", "fence & siding"}


def _section_name_to_tag(section_name: str, mapping: list) -> tuple[Optional[str], bool]:
    """
    Map a section name to an @tag using the given mapping table.
    Returns (tag, is_ambiguous).
    tag is None if the section should be skipped.
    """
    name_lower = section_name.lower().strip()
    is_ambiguous = any(amb in name_lower for amb in AMBIGUOUS_SECTIONS)

    for pattern, tag in mapping:
        if pattern in name_lower:
            return tag, is_ambiguous

    return "@other", is_ambiguous


def attribute_ins_to_tags(ins_data: dict) -> dict:
    """
    Group INS line items by @tag, summing RCV, depreciation, NRD, and O&P per trade.

    Returns:
    {
        "@shingle_roof": {
            "rcv": 64391.37,
            "depreciation": 15445.58,
            "non_recoverable_depreciation": 0.0,
            "o_and_p": 0.0,
            "sections": ["Dwelling Roof"],
            "ambiguous": False,
            "warnings": []
        },
        ...
    }
    """
    by_tag: dict[str, dict] = {}
    warnings = []

    items = ins_data.get("items", [])
    # Also check sections for section_totals (more reliable than summing items)
    section_totals_by_name = {}
    for sec in ins_data.get("sections", []):
        st = sec.get("section_totals", {})
        if any(v for v in st.values() if v):
            section_totals_by_name[sec["name"]] = st

    # Group items by section → compute sums
    section_sums: dict[str, dict] = {}
    for item in items:
        if item.get("is_overhead_and_profit_line"):
            continue
        section = item.get("section", "Unknown")
        if section not in section_sums:
            section_sums[section] = {"rcv": 0.0, "depreciation": 0.0, "nrd": 0.0, "op": 0.0}
        section_sums[section]["rcv"]          += float(item.get("rcv") or item.get("total") or 0)
        section_sums[section]["depreciation"] += float(item.get("depreciation") or 0)
        section_sums[section]["nrd"]          += float(item.get("non_recoverable_depreciation") or 0)
        section_sums[section]["op"]           += float(item.get("o_and_p") or 0)

    # Also capture O&P from the ins_data overhead_and_profit block
    op_block = ins_data.get("overhead_and_profit") or {}
    doc_op_total = float(op_block.get("total") or ins_data.get("totals", {}).get("overhead_and_profit") or 0)

    # Map each section → @tag, accumulate
    all_sections = set(list(section_sums.keys()) + list(section_totals_by_name.keys()))
    for section_name in all_sections:
        tag, is_ambiguous = _section_name_to_tag(section_name, INS_SECTION_TO_TAG)
        if tag is None:
            continue  # skip debris, overhead, summary

        sums = section_sums.get(section_name, {"rcv": 0.0, "depreciation": 0.0, "nrd": 0.0, "op": 0.0})

        # Prefer section_totals if available (more reliable than summing items)
        st = section_totals_by_name.get(section_name, {})
        rcv = float(st.get("rcv") or sums["rcv"])
        dep = float(st.get("depreciation") or sums["depreciation"])
        nrd = float(st.get("non_recoverable_depreciation") or sums["nrd"])
        op  = float(st.get("o_and_p") or sums["op"])

        if tag not in by_tag:
            by_tag[tag] = {"rcv": 0.0, "depreciation": 0.0, "non_recoverable_depreciation": 0.0,
                            "o_and_p": 0.0, "sections": [], "ambiguous": False, "warnings": []}

        by_tag[tag]["rcv"]                          += rcv
        by_tag[tag]["depreciation"]                 += dep
        by_tag[tag]["non_recoverable_depreciation"] += nrd
        by_tag[tag]["o_and_p"]                      += op
        by_tag[tag]["sections"].append(section_name)

        if is_ambiguous:
            by_tag[tag]["ambiguous"] = True
            msg = f"Section '{section_name}' may cover multiple trades — mapped to {tag}, verify manually"
            by_tag[tag]["warnings"].append(msg)
            warnings.append(msg)

    # Round everything
    for tag_data in by_tag.values():
        for key in ("rcv", "depreciation", "non_recoverable_depreciation", "o_and_p"):
            tag_data[key] = round(tag_data[key], 2)

    # If doc-level O&P exists and no per-item O&P was captured, note it
    if doc_op_total and not any(d["o_and_p"] > 0 for d in by_tag.values()):
        warnings.append(f"INS O&P ${doc_op_total:,.2f} is a document-level total — not attributed per trade")

    if warnings:
        print(f"[pipeline][ins-attribution] {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ⚠️  {w}")

    return by_tag


def fetch_bids_from_flow(project_id: int, temp_dir: str, project_folder_id: str = None, health_folder_ids: dict = None) -> list[dict]:
    """
    Pull sub bids from Flow (IFC API action_trackers).

    - action_type='bid' + doing_the_work_status=True  →  selected bid
    - retail_exactimate_bid  →  what we request from insurance (authoritative)
    - original_sub_bid_price →  our cost (reference only, may be incomplete)
    - Multiple cards with same @tag = multiple scopes for that trade (both used)

    Relaxed filters:
    - If a card has original_sub_bid_price but NO retail_exactimate_bid, auto-calculate: retail = sub_bid * 1.3
    - If action_type is not 'bid' but the card has a sub bid price AND a trade tag (not @ifc), still include it

    Returns list of bid dicts compatible with estimate_builder.
    """
    import requests
    token = os.getenv("IFC_API_TOKEN")
    base_url = os.getenv("IFC_API_BASE", "https://omni.ifc.shibui.ar")
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(f"{base_url}/action_trackers?project_id={project_id}", headers=headers)
    r.raise_for_status()
    trackers = r.json()

    bids = []
    for card in trackers:
        trade = card.get("tag") or "@other"
        flow_retail = card.get("retail_exactimate_bid")
        wholesale_raw = card.get("original_sub_bid_price")
        is_bid_action = card.get("action_type") == "bid"
        doing_work = card.get("doing_the_work_status")

        # Original strict path: action_type='bid' + doing_the_work=True + has retail
        # Relaxed path 1: has sub bid price but no retail → auto-calculate retail
        # Relaxed path 2: not action_type='bid' but has sub bid price + trade tag (not @ifc)
        if is_bid_action and doing_work:
            if not flow_retail and not wholesale_raw:
                continue
        elif wholesale_raw and trade and trade.lower() != "@ifc":
            pass  # Relaxed: not a bid card but has sub bid + trade tag
        else:
            continue

        # ── Retail calculation ──────────────────────────────────
        # Flow's retail_exactimate_bid INCLUDES O&P (retail + 20% O&P baked in).
        # calc_line_item adds O&P separately, so we must use pure retail (wholesale × 1.3).
        #
        # Priority:
        #   1. wholesale × 1.3 (most reliable — we control the math)
        #   2. flow_retail ÷ 1.2 (back out the O&P that Flow baked in)
        #   3. Skip card (no usable price data)
        wholesale = float(wholesale_raw or 0.0)

        if wholesale > 0:
            retail = round(wholesale * 1.3, 2)
            print(f"[pipeline]   [{trade}] Retail from wholesale: ${wholesale:,.2f} × 1.3 = ${retail:,.2f}")
        elif flow_retail:
            # flow_retail includes O&P — back it out to get pure retail
            retail = round(float(flow_retail) / 1.2, 2)
            print(f"[pipeline]   [{trade}] Retail from Flow (O&P backed out): ${float(flow_retail):,.2f} ÷ 1.2 = ${retail:,.2f}")
        else:
            retail = 0.0

        scope   = card.get("content") or ""
        folder_link = card.get("folder_link") or ""

        sub_name = _get_sub_name_from_folder(folder_link) if folder_link else ""
        bid_scope = ""
        bid_line_items_text = ""

        # Always try Original Bids folder for sub name + scope + bid amounts
        # Bids from PDFs are the source of truth — Flow card amounts are secondary
        if health_folder_ids and health_folder_ids.get("original_bids"):
            bid_info = _get_bid_info_from_original_bids(health_folder_ids["original_bids"], trade, temp_dir)
            if bid_info:
                if not sub_name:
                    sub_name = bid_info.get("sub_name", "")
                bid_scope = bid_info.get("scope", "")
                bid_line_items_text = bid_info.get("line_items_text", "")
                # If Flow had no price but bid PDF has an amount, use it
                bid_amount = bid_info.get("amount", 0.0)
                if retail == 0.0 and bid_amount > 0:
                    wholesale = bid_amount
                    retail = round(bid_amount * 1.3, 2)
                    print(f"[pipeline]   [{trade}] Retail from bid PDF: ${bid_amount:,.2f} × 1.3 = ${retail:,.2f}")

        # Now decide: skip if no bid data at all
        has_bid = retail > 0
        if not has_bid:
            print(f"[pipeline]   [{trade}] skipped — no bid amount from Flow or PDF")
            continue

        # Skip Xactimate trades that have no actual bid (just reference totals)
        if trade in XACTIMATE_TRADES and not has_bid:
            print(f"[pipeline]   [{trade}] skipped — Xactimate line-item trade, no bid")
            continue
        if trade in XACTIMATE_TRADES and has_bid:
            print(f"[pipeline]   [{trade}] has bid but is Xactimate trade — skipping bid item (${retail:,.2f}). Measurements only.")
            continue

        if not sub_name:
            sub_name = _tag_to_trade_label(trade)

        # Use bid PDF scope over Flow card content (which is often just "@tag")
        effective_scope = bid_scope or scope or _tag_to_trade_label(trade)

        bid = {
            "sub_name": sub_name,
            "trade": trade,
            "scope": effective_scope,
            "wholesale_total": wholesale,
            "retail_total": float(retail),
            "flow_card_id": card.get("id"),
            "folder_link": folder_link,
            "line_items": [],
            "bid_line_items_text": bid_line_items_text,
            "supplement_notes": card.get("supplement_notes") or "",
        }
        bids.append(bid)
        print(f"[pipeline]   [{trade}] {sub_name} — ${wholesale:,.2f} cost → ${float(retail):,.2f} retail (Flow)")

    return bids


def _get_bid_info_from_original_bids(original_bids_folder_id: str, trade_tag: str, temp_dir: str) -> dict:
    """
    Fallback: search the Original Bids folder for a PDF matching the trade tag.
    Extract sub name AND scope description from the found PDF.
    Returns {"sub_name": str, "scope": str, "line_items_text": str} or empty dict.
    """
    # Reverse tag_from_name: map trade tags to search keywords (for PDF filename matching)
    tag_keywords = {
        "@gutter": ["gutter", "downspout"],
        "@fence": ["fence", "fencing", "grizzly"],
        "@woodfence": ["fence", "wood"],
        "@window": ["window", "screen", "glass"],
        "@chimney": ["chimney", "hitech", "copper"],
        "@sheetrock": ["sheetrock", "drywall"],
        "@hvac": ["hvac", "air", "heat", "service"],
        "@packout": ["packout", "pack out"],
        "@flat_roof": ["flat", "tpo", "modified"],
        "@metal": ["metal", "copper", "flashing"],
        "@pergola": ["pergola", "gazebo", "porch"],
        "@gazebo/pergola": ["pergola", "gazebo", "porch", "grizzly"],
        "@skylight": ["skylight", "velux"],
        "@pool": ["pool"],
        "@garage": ["garage", "garage door", "overhead door"],
        "@garage_door": ["garage", "garage door", "overhead door"],
        "@siding": ["siding"],
        "@paint": ["paint"],
        "@interior": ["interior", "drywall", "paint"],
    }
    keywords = tag_keywords.get(trade_tag, [])

    try:
        from googleapiclient.discovery import build
        creds = get_service_account()
        service = build("drive", "v3", credentials=creds)

        def _search_folder(fid):
            resp = service.files().list(
                q=f"'{fid}' in parents and trashed=false and mimeType='application/pdf'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=20
            ).execute()
            return resp.get("files", [])

        def _list_subfolders(fid):
            resp = service.files().list(
                q=f"'{fid}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=20
            ).execute()
            return resp.get("files", [])

        # STRATEGY 1: Match subfolder name to trade tag (most reliable)
        # Folders are named @chimney, @metal, @skylight, @hvac, etc.
        trade_clean = trade_tag.lower().lstrip("@").replace("/", "")  # "@gazebo/pergola" → "gazebopergola"
        subfolders = _list_subfolders(original_bids_folder_id)
        matched_folder = None
        for sf in subfolders:
            sf_clean = sf["name"].lower().lstrip("@").replace("/", "")
            if sf_clean == trade_clean or trade_clean in sf_clean or sf_clean in trade_clean:
                matched_folder = sf
                break
        # Also try partial match (e.g. "chimney" in "@chimney")
        if not matched_folder:
            trade_word = trade_tag.lower().lstrip("@").split("/")[0]  # "gazebo/pergola" → "gazebo"
            for sf in subfolders:
                if trade_word in sf["name"].lower():
                    matched_folder = sf
                    break

        pdf_file = None
        if matched_folder:
            # Found the trade folder — take first non-archive PDF
            pdfs = _search_folder(matched_folder["id"])
            if pdfs:
                pdf_file = pdfs[0]
                print(f"[pipeline]   Matched folder '{matched_folder['name']}' for {trade_tag} → {pdf_file['name']}")

        # STRATEGY 2: Search all PDFs by filename keywords (fallback)
        if not pdf_file and keywords:
            all_pdfs = _search_folder(original_bids_folder_id)
            for sf in subfolders:
                if sf.get("name", "").lower() != "archive":
                    all_pdfs.extend(_search_folder(sf["id"]))
            for pf in all_pdfs:
                name_lower = pf["name"].lower()
                if any(kw in name_lower for kw in keywords):
                    pdf_file = pf
                    print(f"[pipeline]   Keyword match for {trade_tag} → {pdf_file['name']}")
                    break

        if pdf_file:
            tmp_path = os.path.join(temp_dir, f"ob_bid_{pdf_file['id']}.pdf")
            data = service.files().get_media(fileId=pdf_file["id"], supportsAllDrives=True).execute()
            with open(tmp_path, "wb") as f:
                f.write(data)
            try:
                import fitz
                doc = fitz.open(tmp_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                if text.strip():
                    name = _extract_sub_name(text, pdf_file["name"])
                    scope = _extract_scope(text, trade_tag)
                    # Extract line item descriptions for AI context
                    line_items = _extract_bid_line_items(text)
                    line_items_text = "; ".join(f"{li['description']} (${li['amount']:,.2f})" for li in line_items) if line_items else ""
                    if name:
                        # Sum line items to get total bid amount
                        bid_total = sum(li.get("amount", 0.0) for li in line_items) if line_items else 0.0
                        print(f"[pipeline]   Bid info from Original Bids: '{name}' | scope: '{scope}' | amount: ${bid_total:,.2f} (file: {pdf_file['name']})")
                        return {"sub_name": name, "scope": scope, "line_items_text": line_items_text, "amount": bid_total}
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    except Exception as e:
        print(f"[pipeline] Original Bids bid info fallback failed: {e}")

    return {}


def _ai_split_bid_scopes(pdf_text: str, sub_name: str, original_trade: str) -> list:
    """
    Use AI (Sonnet) to extract line items from a bid PDF and classify each
    into a trade tag. Returns list of:
      {"description": str, "amount": float, "trade_tag": str}

    Returns empty list if the bid is single-scope (no splitting needed).
    """
    TRADE_TAG_GUIDE = """
@fence       — fence, wood fence, power wash + stain fence, board-on-board, cedar, picket
@garage_door — garage door painting/staining/washing, overhead door
@pergola     — pergola, arbor, gazebo, patio cover
@window      — window screens, glass, sliding doors
@chimney     — chimney cap, chase cover, flashing (chimney)
@hvac        — HVAC, AC unit, condenser, air handler
@paint       — exterior painting, stucco, trim painting
@siding      — siding, hardie board, lap siding
@interior    — interior drywall, sheetrock, interior painting
@pool        — pool coping, pool deck, pool equipment
@skylight    — skylight replacement
@metal       — metal pan, copper flashing, metal balcony
@concrete    — concrete flatwork, driveway, sidewalk
@other       — anything that doesn't clearly fit above
"""

    prompt = f"""Extract line items from this contractor bid and classify each item into a trade category.

Sub: {sub_name}
Original trade tag: {original_trade}

## BID TEXT
{pdf_text[:3000]}

## TRADE TAG GUIDE
{TRADE_TAG_GUIDE}

## YOUR TASK
1. Extract every line item that has a dollar amount (the line item total, not unit rate)
2. Assign each a trade_tag from the guide above
3. If ALL items belong to the same trade, return an empty array [] (no split needed)
4. If items span 2+ trades, return all of them

Return a JSON array:
[
  {{"description": "Power Wash & Stain fence (179 LF)", "amount": 1745.70, "trade_tag": "@fence"}},
  {{"description": "Power Wash and Stain 16x7 Garage Door", "amount": 425.00, "trade_tag": "@garage_door"}}
]

Rules:
- amount = the line item TOTAL (not unit rate, not qty)
- Skip totals, subtotals, taxes, deposits
- If you can't determine amounts clearly, return []
- Respond with ONLY the JSON array"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        _log_anthropic_usage(resp, "bid_scope_extract")
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        scopes = json.loads(raw)
        if not isinstance(scopes, list):
            return []
        # Validate each item has required fields
        valid = []
        for s in scopes:
            if s.get("description") and s.get("amount") and s.get("trade_tag"):
                valid.append({"description": s["description"], "amount": float(s["amount"]), "trade_tag": s["trade_tag"]})
        return valid
    except Exception as e:
        print(f"[pipeline] _ai_split_bid_scopes failed: {e}")
        return []


def _split_multi_scope_bids(bids: list, original_bids_folder_id: str, temp_dir: str) -> list:
    """
    Check every bid PDF for multiple trade scopes (e.g. Grizzly has fence + garage door).
    When found, split into separate bid objects — one per scope — each with its own:
      - trade tag
      - retail_total (only that scope's wholesale × 1.3)
      - scope/description
      - bid_pdf_ref (shared — same PDF, used in F9)

    Flow cards carry a total for the whole bid, not per scope. So we read the actual PDF
    to extract line items, detect scope buckets, and split the retail accordingly.

    Returns the expanded bids list (original single-scope bids pass through unchanged).
    """
    # Map keywords in bid line item descriptions → trade tags
    SCOPE_KEYWORDS = {
        "@fence":        ["fence", "fencing", "power wash", "stain", "stain and seal", "wood", "board"],
        "@garage_door":  ["garage door", "garage", "door"],
        "@pergola":      ["pergola", "arbor", "gazebo", "patio cover"],
        "@window":       ["window", "screen", "glass", "sliding"],
        "@chimney":      ["chimney", "flashing", "cap"],
        "@hvac":         ["hvac", "air condition", "condenser", "unit"],
        "@paint":        ["paint", "painting", "stucco", "exterior"],
        "@siding":       ["siding", "hardie", "board and batten"],
        "@interior":     ["interior", "drywall", "sheetrock"],
        "@pool":         ["pool", "coping", "deck"],
        "@skylight":     ["skylight"],
        "@metal":        ["metal", "copper", "pan", "balcony"],
        "@concrete":     ["concrete", "flatwork", "driveway", "sidewalk"],
    }

    # Trades that should NOT become bid items (handled as Xactimate line items)
    SKIP_TRADES = XACTIMATE_TRADES

    result = []

    for bid in bids:
        folder_link = bid.get("folder_link", "")
        sub_name = bid.get("sub_name", "")
        trade = bid.get("trade", "@other")
        retail_total = bid.get("retail_total", 0.0)

        # Try to find and read the bid PDF from the trade subfolder
        pdf_text = None
        pdf_line_items = []

        try:
            from googleapiclient.discovery import build
            creds = get_service_account()
            service = build("drive", "v3", credentials=creds)

            # Look in the matching trade subfolder under Original Bids
            trade_clean = trade.lower().lstrip("@").replace("/", "")
            subfolders_resp = service.files().list(
                q=f"'{original_bids_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=30
            ).execute()
            subfolders = subfolders_resp.get("files", [])

            # Find the matching subfolder for this bid's trade tag
            matched_folder = None
            for sf in subfolders:
                sf_clean = sf["name"].lower().lstrip("@").replace("/", "")
                if sf_clean == trade_clean or trade_clean in sf_clean or sf_clean in trade_clean:
                    matched_folder = sf
                    break

            if matched_folder:
                pdfs_resp = service.files().list(
                    q=f"'{matched_folder['id']}' in parents and trashed=false and mimeType='application/pdf'",
                    fields="files(id, name)", supportsAllDrives=True,
                    includeItemsFromAllDrives=True, corpora="allDrives", pageSize=10
                ).execute()
                pdfs = pdfs_resp.get("files", [])

                if pdfs:
                    # Use the first (main) bid PDF
                    pdf_file = pdfs[0]
                    tmp_path = os.path.join(temp_dir, f"split_bid_{pdf_file['id']}.pdf")
                    try:
                        data = service.files().get_media(fileId=pdf_file["id"], supportsAllDrives=True).execute()
                        with open(tmp_path, "wb") as f:
                            f.write(data)
                        try:
                            import fitz
                            doc = fitz.open(tmp_path)
                            pdf_text = "\n".join(page.get_text() for page in doc)
                            doc.close()
                        except Exception as e:
                            print(f"[pipeline] _split_multi_scope_bids: fitz read failed: {e}")
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

        except Exception as e:
            print(f"[pipeline] _split_multi_scope_bids: Drive read failed for {sub_name}: {e}")

        if not pdf_text or not pdf_text.strip():
            # Can't read the PDF — pass through unchanged
            result.append(bid)
            continue

        # Extract line items with dollar amounts from the PDF text
        pdf_line_items = _extract_bid_line_items(pdf_text)

        # Use AI to extract line items + detect trade scopes from the raw PDF text
        # (more robust than regex — handles all the weird bid table formats)
        ai_scopes = _ai_split_bid_scopes(pdf_text, sub_name, trade)

        if not ai_scopes:
            # AI couldn't split — pass through with updated line items context
            bid["bid_line_items_text"] = "; ".join(
                f"{li['description']} (${li['amount']:,.2f})" for li in pdf_line_items
            ) if pdf_line_items else bid.get("bid_line_items_text", "")
            result.append(bid)
            continue

        # Group by trade
        from collections import defaultdict
        scope_groups = defaultdict(list)
        for scope_item in ai_scopes:
            t = scope_item.get("trade_tag", trade)
            if t not in SKIP_TRADES:
                scope_groups[t].append(scope_item)

        if not scope_groups:
            result.append(bid)
            continue

        if len(scope_groups) <= 1:
            # Single scope — enrich with AI-extracted line items context
            single_items = list(scope_groups.values())[0] if scope_groups else ai_scopes
            bid["bid_line_items_text"] = "; ".join(
                f"{s['description']} (${s['amount']:,.2f})" for s in single_items
            )

            # Cross-check: if PDF total differs from Flow retail, use PDF amount
            if single_items:
                pdf_wholesale = sum(s["amount"] for s in single_items)
                pdf_retail = round(pdf_wholesale * 1.3, 2)
                flow_retail = bid.get("retail_total", 0)
                if pdf_wholesale > 0 and abs(pdf_retail - flow_retail) > 1.0:
                    print(f"[pipeline] _split_multi_scope_bids: {sub_name} PDF wholesale ${pdf_wholesale:,.2f} → retail ${pdf_retail:,.2f} differs from Flow ${flow_retail:,.2f} — using PDF amount")
                    bid["wholesale_total"] = pdf_wholesale
                    bid["retail_total"] = pdf_retail

            result.append(bid)
            continue

        # Multiple scopes — split the bid
        print(f"[pipeline] _split_multi_scope_bids: {sub_name} has {len(scope_groups)} scopes — splitting")

        # Calculate wholesale total from AI-extracted amounts (more accurate than PDF regex)
        total_wholesale_in_pdf = sum(s["amount"] for scopes in scope_groups.values() for s in scopes)
        bid_wholesale = bid.get("wholesale_total", 0)

        for t_tag, scope_items in scope_groups.items():
            scope_wholesale = sum(s["amount"] for s in scope_items)

            # Scale to match Flow card total if there's a discrepancy
            if total_wholesale_in_pdf > 0 and bid_wholesale > 0:
                scale = bid_wholesale / total_wholesale_in_pdf
                scope_wholesale_scaled = round(scope_wholesale * scale, 2)
            else:
                scope_wholesale_scaled = scope_wholesale

            scope_retail = round(scope_wholesale_scaled * 1.3, 2)
            scope_desc = "; ".join(s["description"] for s in scope_items)
            scope_line_items_text = "; ".join(
                f"{s['description']} (${s['amount']:,.2f})" for s in scope_items
            )

            split_bid = {
                "sub_name": sub_name,
                "trade": t_tag,
                "scope": scope_desc,
                "wholesale_total": scope_wholesale_scaled,
                "retail_total": scope_retail,
                "flow_card_id": bid.get("flow_card_id"),
                "folder_link": bid.get("folder_link", ""),
                "line_items": [],
                "bid_line_items_text": scope_line_items_text,
                "supplement_notes": bid.get("supplement_notes", ""),
                "split_from": trade,
            }
            result.append(split_bid)
            print(f"[pipeline]   → {t_tag}: ${scope_wholesale_scaled:,.2f} wholesale → ${scope_retail:,.2f} retail | {scope_desc[:60]}")

    return result


def _get_sub_name_from_folder(folder_link: str) -> str:
    """Download the first bid PDF from the folder and extract the real company name.
    Rule-based extraction first; AI fallback (Claude Haiku) if that returns nothing.
    """
    import re as _re
    import tempfile
    m = _re.search(r'/folders/([a-zA-Z0-9_-]+)', folder_link)
    if not m:
        return ""
    folder_id = m.group(1)
    try:
        from googleapiclient.discovery import build
        creds = get_service_account()
        service = build("drive", "v3", credentials=creds)
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType='application/pdf'",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            fields="files(id, name)",
            pageSize=3
        ).execute()
        files = resp.get("files", [])
        if not files:
            return ""

        # Download first PDF to a temp file and read its text
        file_info = files[0]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        request = service.files().get_media(fileId=file_info["id"], supportsAllDrives=True)
        with open(tmp_path, "wb") as f:
            f.write(request.execute())

        try:
            import fitz
            doc = fitz.open(tmp_path)
            text = doc[0].get_text() if len(doc) > 0 else ""
            doc.close()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        if not text.strip():
            return ""

        # Try rule-based extraction first
        name = _extract_sub_name(text, file_info["name"])

        # If rule-based returned something suspicious, try AI
        fname_clean = _re.sub(r'[_\-\.pdf]+', ' ', file_info["name"]).strip().title()
        _suspicious = (
            not name
            or name.lower() == fname_clean.lower()
            or len(name.split()) > 5  # too many words = probably a description
            or any(w in name.lower() for w in ["comb", "straighten", "install", "repair", "replace", "remove", "sent on", "due to"])
            or _re.search(r'^\d', name)  # starts with number = address/qty
        )
        if _suspicious:
            try:
                import anthropic
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if api_key:
                    client = anthropic.Anthropic(api_key=api_key)
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    # Send both head and tail — company name may be at bottom
                    head = "\n".join(lines[:15])
                    tail = "\n".join(lines[-10:]) if len(lines) > 15 else ""
                    snippet = head + ("\n...\n" + tail if tail else "")
                    msg = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=50,
                        messages=[{
                            "role": "user",
                            "content": (
                                "What is the contractor or company name on this bid/invoice? "
                                "Reply with ONLY the company name, nothing else.\n\n"
                                f"{snippet}"
                            )
                        }]
                    )
                    _log_anthropic_usage(msg, "sub_name_extract")
                    ai_name = msg.content[0].text.strip()
                    if ai_name and len(ai_name) < 80:
                        name = ai_name
            except Exception:
                pass

        return name

    except Exception:
        return ""


def _tag_to_trade_label(tag: str) -> str:
    mapping = {
        "@gutter": "Gutter System",
        "@fence": "Iron Fence",
        "@woodfence": "Wood Fence",
        "@window": "Window Screens",
        "@metal": "Metal / Copper Work",
        "@gazebo/pergola": "Pergola",
        "@chimney": "Chimney",
        "@porch": "Porch",
        "@shingle_roof": "Shingle Roof",
        "@garage": "Garage Roof",
        "@other": "Specialty Work",
    }
    return mapping.get(tag, tag.replace("@", "").replace("_", " ").title())


def _parse_bid_pdf(pdf_path: str, trade_tag: str, file_name: str) -> Optional[dict]:
    """Extract sub name, scope, total from a bid PDF. Returns None if unparseable."""
    import fitz

    doc = fitz.open(pdf_path)
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    if not full_text.strip():
        return None

    # ── Extract total ──────────────────────────────────────────────────────────
    # Pattern 1: "Total\n$X,XXX.XX" or "Total $X,XXX.XX"
    total_patterns = [
        re.compile(r'(?:^|\n)\s*Total\s*\n?\s*\$\s*([\d,]+\.?\d*)'),
        re.compile(r'(?:^|\n)\s*TOTAL\s*\n?\s*\$\s*([\d,]+\.?\d*)'),
        re.compile(r'Total Amount[:\s]*\$\s*([\d,]+\.?\d*)'),
        re.compile(r'Grand Total[:\s]*\$\s*([\d,]+\.?\d*)'),
        re.compile(r'Balance Due[:\s]*\$\s*([\d,]+\.?\d*)'),
        # Last dollar amount in the document (often the total)
        re.compile(r'\$([\d,]+\.\d{2})(?=[^$]*$)', re.DOTALL),
    ]

    wholesale_total = None
    for pattern in total_patterns:
        m = pattern.search(full_text)
        if m:
            try:
                wholesale_total = float(m.group(1).replace(",", ""))
                if wholesale_total > 0:
                    break
            except ValueError:
                continue

    if not wholesale_total:
        return None

    # ── Extract sub/company name ───────────────────────────────────────────────
    sub_name = _extract_sub_name(full_text, file_name)

    # ── Extract scope description ──────────────────────────────────────────────
    scope = _extract_scope(full_text, trade_tag)

    # ── Extract line items ────────────────────────────────────────────────────
    line_items = _extract_bid_line_items(full_text)

    retail_total = round(wholesale_total * (1 + MARKUP_RATE), 2)

    return {
        "sub_name": sub_name,
        "trade": trade_tag,
        "scope": scope,
        "wholesale_total": wholesale_total,
        "retail_total": retail_total,
        "markup_rate": MARKUP_RATE,
        "file_name": file_name,
        "line_items": line_items,
        "raw_text": full_text[:800],  # keep for AI context
    }


def _extract_sub_name(text: str, file_name: str) -> str:
    """Extract subcontractor company name from bid text.
    Uses AI extraction with heuristic fallback."""
    # Try AI extraction first (fast, single-shot)
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=60,
                messages=[{
                    "role": "user",
                    "content": (
                        "Extract the subcontractor company name from this bid/estimate. "
                        "NOT the customer or recipient (IFC Roofing is the customer). "
                        "Reply with ONLY the company name, nothing else. "
                        "If you can't find it, reply UNKNOWN.\n\n"
                        f"{text[:1500]}"
                    )
                }]
            )
            _log_anthropic_usage(msg, "sub_name_vision")
            ai_name = msg.content[0].text.strip().strip('"').strip("'")
            if ai_name and ai_name != "UNKNOWN" and len(ai_name) > 2 and len(ai_name) < 80:
                print(f"[pipeline] Sub name via AI: '{ai_name}'")
                return ai_name
    except Exception as e:
        print(f"[pipeline] AI sub name extraction failed: {e}")

    # Heuristic fallback
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    def _is_address(s: str) -> bool:
        """Check if a string looks like a street address or location line."""
        if re.search(r'^\d+\s+[A-Za-z]', s) and re.search(r'(Trail|St|Ave|Blvd|Dr|Ln|Rd|Way|Ct|Pl|Circle|Pkwy|Hwy)', s, re.IGNORECASE):
            return True
        # City, State ZIP pattern (handles both "TX 76092" and "Texas 76092")
        if re.search(r'[A-Za-z]+,?\s+[A-Za-z]{2,15}\s+\d{5}', s):
            return True
        # Phone number
        if re.match(r'^[\+\d\s\-\(\)]{7,}$', s.strip()):
            return True
        # Email
        if '@' in s and '.' in s and len(s.split()) <= 2:
            return True
        # "Zia 3412 Bear Creek Dr." style (contains a number + street suffix)
        if re.search(r'\d+\s+[\w\s]+(Dr|St|Ave|Blvd|Ln|Rd|Way|Ct|Trail|Pkwy|Hwy)\.?\s*$', s, re.IGNORECASE):
            return True
        return False

    def _is_ifc(s: str) -> bool:
        return any(skip in s.upper() for skip in ["IFC", "ROOFING AND CONSTRUCTION", "COLLEYVILLE", "5115", "RECIPIENT"])

    def _is_junk(s: str) -> bool:
        """Check if a string is a common PDF artifact, not a company name."""
        s_lower = s.lower().strip()
        # "Page 1 of 2", "Page 1/2", etc.
        if re.match(r'^page\s+\d+\s*(of|/)\s*\d+$', s_lower):
            return True
        # Pure date patterns
        if re.match(r'^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$', s_lower):
            return True
        # "Prepared for", "Prepared by", "Submitted to", etc.
        if re.match(r'^(prepared|submitted|sent|billed|issued)\s+(for|to|by)\b', s_lower):
            return True
        return False

    # Pattern 0: Company name BEFORE "ESTIMATE/QUOTE" header (HiTech, etc.)
    for i, line in enumerate(lines[:15]):
        if line.upper() in ("ESTIMATE", "QUOTE", "PROPOSAL", "INVOICE"):
            # Look backwards for company name (first non-address, non-IFC line with mixed case)
            for j in range(i - 1, -1, -1):
                candidate = lines[j]
                if _is_address(candidate) or _is_ifc(candidate) or _is_junk(candidate):
                    continue
                if len(candidate) > 4:
                    # Skip pure numbers, dates, phone numbers
                    if not re.match(r'^[\d\s\-\(\)\+\./:]+$', candidate):
                        return candidate
            # Also look forward — very strict: only if next line looks like a proper company name
            for j in range(i + 1, min(i + 3, len(lines))):
                candidate = lines[j]
                if _is_ifc(candidate) or _is_address(candidate):
                    continue
                cand_lower = candidate.lower().strip()
                skip_set = {"services", "service", "address", "mr.", "mrs.", "qty", "description",
                           "unit price", "amount", "bill to", "ship to", "for", "recipient"}
                if cand_lower in skip_set:
                    continue
                # Must look like a company name: contains "&", "LLC", "Inc", "Co", or is Title Case with 2-4 words
                if re.search(r'(&|LLC|Inc|Corp|Co\b|Ltd|Group|Solutions|Systems)', candidate, re.IGNORECASE):
                    return candidate
                if len(candidate.split()) <= 4 and re.search(r'^[A-Z][a-z]', candidate):
                    return candidate
            break

    # Pattern 1: Company name in first 10 lines (skip addresses, IFC refs, labels)
    skip_words = {"ifc", "roofing", "recipient:", "construction", "5115", "colleyville",
                  "total", "estimate", "date", "address", "phone", "email",
                  "po box", "invoice", "quote", "proposal", "bill to", "ship to",
                  "for", "to", "from", "issued", "valid", "subtotal", "page"}
    for line in lines[:10]:
        # Skip lines that are labels (end with ":" or are all-caps single words)
        if line.endswith(":") or (line.isupper() and len(line.split()) <= 2):
            continue
        if _is_address(line) or _is_ifc(line) or _is_junk(line):
            continue
        if len(line) > 4 and not any(s in line.lower() for s in skip_words):
            if re.search(r'[A-Z][a-z]', line):  # mixed case = company name
                # Extra check: not a generic word like "Services"
                if line.lower().strip() not in {"services", "service", "address", "mr.", "mrs."}:
                    return line

    # Pattern 2: Company name in LAST 15 lines (footer — Skylight Solutions, Rambros, etc.)
    for line in reversed(lines[-15:]):
        if line.endswith(":") or (line.isupper() and len(line.split()) <= 2):
            continue
        if _is_address(line) or _is_ifc(line) or _is_junk(line):
            continue
        if len(line) > 4 and not any(s in line.lower() for s in skip_words):
            if re.search(r'[A-Z][a-z]', line):  # mixed case = company name
                if line.lower().strip() not in {"services", "service", "address", "mr.", "mrs.", "signature", "accepted by", "accepted date"}:
                    # Extra validation: should look like a company name (not a sentence)
                    if len(line.split()) <= 6 and not line.endswith('.'):
                        return line

    # Fallback: derive from file name (clean up common patterns)
    name = re.sub(r'(?:Copy_of_|Estimate_\d+_from_)', '', file_name)
    name = re.sub(r'[_\-\.pdf]+', ' ', name).strip()
    name = re.sub(r'\s+', ' ', name)
    return name.title()


def _extract_scope(text: str, trade_tag: str) -> str:
    """Extract scope description from bid text."""
    # Look for product/service lines
    patterns = [
        re.compile(r'(?:Product/Service|Description|Scope of Work|Scope)[:\s]*\n([^\n]+)'),
        re.compile(r'(?:Service|Work)[:\s]*\n([^\n]+)'),
    ]
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            scope = m.group(1).strip()
            if scope and len(scope) > 4:
                return scope[:120]

    # Fallback: use trade tag
    trade_map = {
        "@fence": "Fence", "@gutter": "Gutters", "@metal": "Metal/Copper Work",
        "@window": "Windows", "@paint": "Painting", "@chimney": "Chimney",
        "@roof": "Roofing", "@siding": "Siding", "@pergola": "Pergola",
        "@gazebo/pergola": "Pergola/Gazebo", "@woodfence": "Wood Fence",
        "@garage": "Garage", "@shingle_roof": "Shingles", "@other": "Specialty Work",
    }
    return trade_map.get(trade_tag, trade_tag.lstrip("@").title())


def _extract_bid_line_items(text: str) -> list[dict]:
    """Extract line items from bid text (best effort)."""
    items = []
    # Look for lines with a dollar amount
    pattern = re.compile(r'^(.+?)\s+\$?([\d,]+\.\d{2})\s*$', re.MULTILINE)
    for m in pattern.finditer(text):
        desc = m.group(1).strip()
        try:
            amount = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        # Skip header/label lines
        if len(desc) > 3 and not any(skip in desc.lower() for skip in ["total", "subtotal", "tax", "deposit", "balance"]):
            items.append({"description": desc, "amount": amount})
    return items[:20]  # cap at 20


# ─── Parsers ───────────────────────────────────────────────────────────────────

PIPELINE_CACHE_DIR = Path(__file__).parent / ".pipeline_cache"


def _ins_cache_path(project_id: int) -> Path:
    PIPELINE_CACHE_DIR.mkdir(exist_ok=True)
    return PIPELINE_CACHE_DIR / f"ins_{project_id}.json"


def _file_hash(path: str) -> str:
    """MD5 hash of a file for cache invalidation."""
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_ins_estimate(pdf_path: str, project_id: int = 0) -> dict:
    """
    Parse insurance estimate PDF → structured data with flattened items list.
    Caches by project_id to avoid re-calling AI on repeat runs for the same project.
    Cache is invalidated if the PDF file hash changes (new INS version downloaded).
    """
    cache_path = _ins_cache_path(project_id)
    pdf_hash = _file_hash(pdf_path)

    if cache_path.exists():
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            if cached.get("_pdf_hash") == pdf_hash:
                print(f"[pipeline] INS parse cache hit (project {project_id}) — skipping AI call")
                return cached
            else:
                print(f"[pipeline] INS PDF changed (hash mismatch) — re-parsing")
        except Exception:
            pass

    from parse_insurance import parse_insurance_estimate
    result = parse_insurance_estimate(pdf_path, provider="anthropic")

    # Flatten sections[].items[] into a single items[] list
    all_items = []
    for section in result.get("sections", []):
        section_name = section.get("name", "")
        for item in section.get("items", []):
            item["section"] = section_name
            all_items.append(item)
    result["items"] = all_items

    # Save cache
    result["_pdf_hash"] = pdf_hash
    result["_project_id"] = project_id
    try:
        with open(cache_path, "w") as f:
            json.dump(result, f)
        print(f"[pipeline] INS parse cached → {cache_path.name}")
    except Exception as e:
        print(f"[pipeline] WARNING: Could not write INS cache: {e}")

    return result


def _normalize_ev_data(ev_data: dict):
    """Ensure roofing_summary has measured_sq/drip_edge_lf from summary data when missing."""
    rs = ev_data.get("roofing_summary", {})
    summary = ev_data.get("summary", {})
    lengths = ev_data.get("lengths", {})

    # measured_sq from summary.total_area_sf
    if not rs.get("measured_sq") and summary.get("total_area_sf"):
        rs["measured_sq"] = round(summary["total_area_sf"] / 100, 2)
        print(f"[pipeline] Normalized EV: measured_sq = {rs['measured_sq']} (from summary.total_area_sf)")

    # ridges_hips_lf
    if not rs.get("ridges_hips_lf") and summary.get("ridges_hips_lf"):
        rs["ridges_hips_lf"] = summary["ridges_hips_lf"]

    # valleys_lf
    if not rs.get("valleys_lf") and summary.get("valleys_lf"):
        rs["valleys_lf"] = summary["valleys_lf"]

    # drip_edge_lf = eaves + rakes
    if not rs.get("drip_edge_lf"):
        eaves = summary.get("eaves_lf") or lengths.get("eaves_lf") or 0
        rakes = summary.get("rakes_lf") or lengths.get("rakes_lf") or 0
        if eaves or rakes:
            rs["drip_edge_lf"] = round(float(eaves) + float(rakes), 2)

    # eaves_lf / rakes_lf
    if not rs.get("eaves_lf"):
        rs["eaves_lf"] = summary.get("eaves_lf") or lengths.get("eaves_lf")
    if not rs.get("rakes_lf"):
        rs["rakes_lf"] = summary.get("rakes_lf") or lengths.get("rakes_lf")

    # step_flashing_lf / flashing_lf
    if not rs.get("step_flashing_lf"):
        rs["step_flashing_lf"] = lengths.get("step_flashing_lf")
    if not rs.get("flashing_lf"):
        rs["flashing_lf"] = lengths.get("flashing_lf")

    ev_data["roofing_summary"] = rs


def parse_eagleview(pdf_path: str) -> dict:
    """Parse EagleView PDF → measurements."""
    from parse_eagleview import parse_eagleview as _parse_ev
    return _parse_ev(pdf_path)


# ─── Main Pipeline ─────────────────────────────────────────────────────────────

def run(project_name: str, temp_dir: str = None) -> dict:
    """
    Full data pipeline. Returns everything estimate_builder needs.
    
    Returns:
    {
        "project": {...},          # IFC API project record
        "notes": {                 # tagged post notes
            "ifc": [...],
            "supplement": [...],
            "momentum": [...]
        },
        "ins_data": {...},         # parsed insurance estimate
        "ev_data": {...},          # parsed EagleView measurements
        "pricelist": {...},        # pricelist lookup function (callable)
        "ins_pdf_path": "...",     # path to downloaded INS PDF
        "ev_pdf_path": "...",      # path to downloaded EV PDF
        "project_folder_id": "...",  # Drive folder ID for uploads
    }
    """
    print(f"[pipeline] Starting for: {project_name}")
    td = temp_dir or tempfile.mkdtemp(prefix="sup_pdf_")

    # 1. IFC API
    print("[pipeline] Fetching project from IFC API...")
    project = fetch_project(project_name)
    project_id = project.get("id")
    print(f"[pipeline] Found project ID: {project_id} — {project.get('name', '')}")

    # 2. Posts → tagged notes
    print("[pipeline] Fetching project posts...")
    posts = fetch_posts(project_id)
    notes = extract_tagged_notes(posts)
    print(f"[pipeline] Notes: {len(notes['ifc'])} @ifc, {len(notes['supplement'])} @supplement, {len(notes['momentum'])} @momentum")

    # 3. Drive — find project folder
    project_folder_id = find_project_folder(project)

    # 2b. If no @ifc notes, try to read a Game Plan Google Doc from the project folder
    if not notes["ifc"] and project_folder_id:
        game_plan_text = _fetch_game_plan_doc(project_folder_id)
        if game_plan_text:
            notes["ifc"].append(game_plan_text)
            print(f"[pipeline] @ifc notes empty — loaded game plan doc ({len(game_plan_text)} chars)")
    print(f"[pipeline] Project Drive folder: {project_folder_id}")

    # 4. Download INS estimate
    # Naming convention: {LASTNAME}_INS X.0.pdf or similar
    lastname = _extract_lastname(project_name, project)
    ins_pdf_path = None
    ins_image_paths = []
    ins_data = {}

    ins_by_tag = {}
    ins_file_id = None
    for pattern in [f"{lastname}_INS", f"{lastname.upper()}_INS", "INS"]:
        ins_file_id = search_drive_file(pattern, project_folder_id)
        if ins_file_id:
            break

    if ins_file_id:
        ins_pdf_path = os.path.join(td, "ins_estimate.pdf")
        print(f"[pipeline] Downloading INS estimate...")
        download_drive_file(ins_file_id, ins_pdf_path)
        print(f"[pipeline] Parsing INS estimate...")
        ins_data = parse_ins_estimate(ins_pdf_path, project_id=project_id)
        print(f"[pipeline] INS items parsed: {len(ins_data.get('items', []))}")
        print("[pipeline] Attributing INS totals to @tags...")
        ins_by_tag = attribute_ins_to_tags(ins_data)
        print(f"[pipeline] INS attributed: {list(ins_by_tag.keys())}")
    else:
        supplement_folder_id = find_drive_subfolder("Supplement", project_folder_id) if project_folder_id else None
        ins_images_folder_id = find_drive_subfolder("INS_IMAGES", supplement_folder_id) if supplement_folder_id else None
        if ins_images_folder_id:
            ins_images = list_drive_images(ins_images_folder_id)
            if ins_images:
                print(f"[pipeline] No INS PDF found. Using explicit Supplement/INS_IMAGES fallback ({len(ins_images)} images)")
                for idx, img in enumerate(ins_images, start=1):
                    local_path = os.path.join(td, f"ins_image_{idx:02d}_{img['name']}")
                    download_drive_file(img["id"], local_path)
                    ins_image_paths.append(local_path)
                print(f"[pipeline] Parsing INS images...")
                from parse_insurance import parse_insurance_images
                ins_data = parse_insurance_images(ins_image_paths, verbose=False, batch_size=3)
                print(f"[pipeline] INS items parsed from images: {len(ins_data.get('items', []))}")
                print("[pipeline] Attributing INS totals to @tags...")
                ins_by_tag = attribute_ins_to_tags(ins_data)
                print(f"[pipeline] INS attributed: {list(ins_by_tag.keys())}")
            else:
                print(f"[pipeline] WARNING: Supplement/INS_IMAGES exists but contains no images for {lastname}")
                ins_by_tag = {}
        else:
            print(f"[pipeline] WARNING: No INS estimate found in Drive for {lastname}")
            ins_by_tag = {}

    # 5. Download EagleView
    ev_pdf_path = None
    ev_data = {}

    ev_file_id = None
    for pattern in [f"{lastname}_EagleView", f"{lastname.upper()}_EagleView", "EagleView"]:
        ev_file_id = search_drive_file(pattern, project_folder_id)
        if ev_file_id:
            break

    if ev_file_id:
        ev_pdf_path = os.path.join(td, "eagleview.pdf")
        print(f"[pipeline] Downloading EagleView...")
        download_drive_file(ev_file_id, ev_pdf_path)
        print(f"[pipeline] Parsing EagleView...")
        ev_data = parse_eagleview(ev_pdf_path)
        # Normalize: ensure roofing_summary has measured_sq from summary.total_area_sf
        _normalize_ev_data(ev_data)
        print(f"[pipeline] EV measurements: {list(ev_data.keys())}")
    else:
        print(f"[pipeline] WARNING: No EagleView found in Drive for {lastname}")

    # 5b. Drive health check — audit folder structure, log warnings
    print("[pipeline] Running Drive health check...")
    health = drive_health_check(project_folder_id)
    if health["issues"]:
        for iss in health["issues"]:
            print(f"[pipeline] ⚠️  ISSUE: {iss}")
    if health["warnings"]:
        for w in health["warnings"]:
            print(f"[pipeline] ⚠️  WARNING: {w}")
    if not health["issues"] and not health["warnings"]:
        print("[pipeline] ✅ Drive folder structure looks good")

    # 5c. Fetch ITEL report
    print("[pipeline] Searching for ITEL report...")
    itel_data = fetch_itel_report(project_folder_id, td)

    # 6. All action trackers + sub bids
    print("[pipeline] Fetching action trackers from Flow...")
    action_trackers = fetch_action_trackers(project_id)
    print(f"[pipeline] Action trackers: {len(action_trackers)} cards")

    print("[pipeline] Fetching sub bids from Flow...")
    bids = fetch_bids_from_flow(project_id, td, project_folder_id=project_folder_id, health_folder_ids=health.get("folder_ids"))
    print(f"[pipeline] Flow bids found: {len(bids)}")

    if not bids:
        print("[pipeline] No Flow bids — falling back to Drive scan...")
        bids = fetch_bids_from_drive(project_folder_id, td)
        print(f"[pipeline] Drive bids found: {len(bids)}")
        if bids:
            print("[pipeline] ⚠️  Using Drive bids — prices are 30% marked up from PDF totals. Verify against Flow.")
        else:
            print("[pipeline] ⚠️  No bids found in Flow or Drive — estimate will be INS-only")

    # 6b. Split multi-scope bids (e.g. Grizzly bid has fence + garage door)
    if bids and health.get("folder_ids", {}).get("original_bids"):
        print("[pipeline] Checking for multi-scope bids...")
        bids = _split_multi_scope_bids(bids, health["folder_ids"]["original_bids"], td)
        print(f"[pipeline] Bids after scope split: {len(bids)}")

    # 7. Load pricelist
    print("[pipeline] Loading pricelist...")
    pricelist = load_pricelist()
    print(f"[pipeline] Pricelist loaded: {len(pricelist)} items")

    # 8. Extract structured metadata
    claims = extract_claims(project)
    address = extract_address(project)
    print(f"[pipeline] Claim: {claims.get('claim_number', 'N/A')} | Insurer: {claims.get('insurance_company', 'N/A')}")
    print(f"[pipeline] Address: {address.get('full', '')}")

    # 9. Prior estimate corrections — read reviewer comments from previous PDF
    prior_corrections = []
    prev_estimate_id = find_previous_estimate(lastname)
    if prev_estimate_id:
        print("[pipeline] Reading reviewer comments from previous estimate...")
        comments = read_pdf_comments(prev_estimate_id)
        # Only include unresolved comments that have actual content
        prior_corrections = [c for c in comments if not c["resolved"] and c["comment"]]
        if prior_corrections:
            print(f"[pipeline] ✅ {len(prior_corrections)} unresolved reviewer correction(s) found")
        else:
            print(f"[pipeline] No unresolved corrections — clean slate")

    # 10. Parse gutter bid for measurements (gutters use Xactimate pricing, not bid price)
    gutter_measurements = None
    ob_folder = health.get("folder_ids", {}).get("original_bids")
    if ob_folder:
        print(f"[pipeline] Checking for gutter bid measurements (Original Bids: {ob_folder})...")
        gutter_measurements = parse_gutter_bid(ob_folder, td)
        if gutter_measurements:
            print(f"[pipeline] ✅ Gutter measurements from bid: {gutter_measurements}")
        else:
            print("[pipeline] No gutter bid found — gutter scope from INS/EV only")
    else:
        print("[pipeline] ⚠️ No Original Bids folder found — skipping gutter bid search")

    return {
        "project": project,
        "project_id": project_id,
        "project_folder_id": project_folder_id,
        "notes": notes,
        "claims": claims,
        "address": address,
        "ins_data": ins_data,
        "ins_pdf_path": ins_pdf_path,
        "ins_by_tag": ins_by_tag,          # INS totals keyed by @tag
        "action_trackers": action_trackers, # all Flow cards (raw)
        "ev_data": ev_data,
        "ev_pdf_path": ev_pdf_path,
        "bids": bids,
        "pricelist": pricelist,
        "prior_corrections": prior_corrections,
        "itel_data": itel_data,
        "gutter_measurements": gutter_measurements,
        "temp_dir": td,
        "lastname": lastname,
        "firstname": project.get("name", "").split()[0] if project.get("name") else "",
    }


GENERATED_SUPPLEMENTS_FOLDER = "1tWeZivnrRjDtZq1eG6dHu4vHkBwgMWop"

def find_previous_estimate(lastname: str) -> Optional[str]:
    """Find the most recent generated estimate PDF for this project in Sup AI."""
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=get_service_account())
        resp = service.files().list(
            q=(f"'{GENERATED_SUPPLEMENTS_FOLDER}' in parents and trashed=false "
               f"and name contains '{lastname.upper()}' and mimeType='application/pdf'"),
            fields="files(id, name, createdTime)",
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
            orderBy="createdTime desc", pageSize=5
        ).execute()
        files = resp.get("files", [])
        if files:
            latest = files[0]
            print(f"[pipeline] Previous estimate found: {latest['name']} [{latest['id']}]")
            return latest["id"]
    except Exception as e:
        print(f"[pipeline] Could not find previous estimate: {e}")
    return None


def read_pdf_comments(file_id: str) -> list[dict]:
    """
    Read Drive comments (and highlighted text) from a PDF file.
    Returns list of {comment, quoted_text, author, resolved}
    """
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=get_service_account())
        resp = service.comments().list(
            fileId=file_id,
            includeDeleted=False,
            fields="comments(id,content,author,createdTime,resolved,quotedFileContent,replies)",
        ).execute()
        results = []
        for c in resp.get("comments", []):
            quoted = c.get("quotedFileContent", {}).get("value", "").strip()
            # Strip HTML tags from quoted text
            quoted = re.sub(r'<[^>]+>', '', quoted).strip()
            results.append({
                "comment": c.get("content", "").strip(),
                "quoted_text": quoted,
                "author": c.get("author", {}).get("displayName", ""),
                "resolved": c.get("resolved", False),
                "replies": [r.get("content", "") for r in c.get("replies", [])],
            })
        return results
    except Exception as e:
        print(f"[pipeline] Could not read PDF comments: {e}")
        return []


def fetch_itel_report(project_folder_id: str, temp_dir: str) -> Optional[str]:
    """
    Search the Drive folder (and Supplement subfolder) for files containing 'ITEL'
    in the name (case insensitive). Downloads the PDF, extracts text using PyMuPDF,
    and returns the text content (first 3000 chars) or None.
    """
    if not project_folder_id:
        return None
    try:
        import fitz as _fitz
        from googleapiclient.discovery import build
        creds = get_service_account()
        service = build("drive", "v3", credentials=creds)

        folders_to_search = [project_folder_id]
        # Also search Supplement subfolder
        resp = service.files().list(
            q=f"'{project_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)", supportsAllDrives=True,
            includeItemsFromAllDrives=True, corpora="allDrives", pageSize=20
        ).execute()
        for sf in resp.get("files", []):
            if "supplement" in sf["name"].lower():
                folders_to_search.append(sf["id"])

        for fid in folders_to_search:
            file_resp = service.files().list(
                q=f"'{fid}' in parents and trashed=false and mimeType='application/pdf'",
                fields="files(id, name)", supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives", pageSize=50
            ).execute()
            for f in file_resp.get("files", []):
                if "itel" in f["name"].lower():
                    print(f"[pipeline] Found ITEL report: {f['name']}")
                    tmp_path = os.path.join(temp_dir, f"itel_{f['id']}.pdf")
                    data = service.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
                    with open(tmp_path, "wb") as outf:
                        outf.write(data)
                    try:
                        doc = _fitz.open(tmp_path)
                        text = ""
                        for page in doc:
                            text += page.get_text()
                        doc.close()
                        text = text.strip()
                        if text:
                            print(f"[pipeline] ITEL report extracted: {len(text)} chars")
                            return text[:3000]
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

        print("[pipeline] No ITEL report found in Drive")
        return None

    except Exception as e:
        print(f"[pipeline] ITEL report fetch failed: {e}")
        return None


def parse_gutter_bid(original_bids_folder_id: str, temp_dir: str) -> Optional[dict]:
    """
    Find and parse a gutter bid PDF from the Original Bids/@gutter folder.
    Extracts measurements (LF of gutters, LF of downspouts, miters, etc.)
    so they can be used with Xactimate pricing instead of the bid total.
    
    Returns dict: {
        "sub_name": "C&S Seamless Gutter",
        "gutter_lf": 432,
        "downspout_lf": 223,
        "miters": 14,
        "other_items": [...],
        "wholesale_total": 3429.00,
        "raw_text": "..."
    } or None
    """
    if not original_bids_folder_id:
        return None
    try:
        import fitz as _fitz
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        import io
        creds = get_service_account()
        service = build("drive", "v3", credentials=creds)

        # Find @gutter subfolder
        resp = service.files().list(
            q=f"'{original_bids_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives"
        ).execute()
        
        gutter_folder_id = None
        subfolders = resp.get("files", [])
        print(f"[gutter_bid] Subfolders in Original Bids: {[f['name'] for f in subfolders]}")
        for f in subfolders:
            if "gutter" in f["name"].lower():
                gutter_folder_id = f["id"]
                print(f"[gutter_bid] Found @gutter folder: {f['name']} ({f['id']})")
                break
        
        if not gutter_folder_id:
            print("[gutter_bid] No @gutter subfolder found, searching root Original Bids")
            gutter_folder_id = original_bids_folder_id

        # Find PDF in gutter folder (skip Archive subfolder)
        resp = service.files().list(
            q=f"'{gutter_folder_id}' in parents and trashed=false and mimeType='application/pdf'",
            fields="files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives",
            pageSize=5
        ).execute()
        
        pdf_file = None
        for f in resp.get("files", []):
            if "gutter" in f["name"].lower() or gutter_folder_id != original_bids_folder_id:
                pdf_file = f
                break
        # If we're in the @gutter folder, just take the first PDF
        if not pdf_file and gutter_folder_id != original_bids_folder_id:
            files = resp.get("files", [])
            if files:
                pdf_file = files[0]

        if not pdf_file:
            print(f"[gutter_bid] No gutter PDF found in folder {gutter_folder_id}")
            return None
        print(f"[gutter_bid] Using PDF: {pdf_file['name']} ({pdf_file['id']})")

        # Download
        tmp_path = os.path.join(temp_dir, f"gutter_bid_{pdf_file['id']}.pdf")
        request = service.files().get_media(fileId=pdf_file["id"], supportsAllDrives=True)
        fh = io.BytesIO()
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        with open(tmp_path, "wb") as f:
            f.write(fh.getvalue())

        # Render first page to image for vision extraction
        doc = _fitz.open(tmp_path)
        if len(doc) == 0:
            doc.close()
            return None

        # Grab text for sub name extraction
        full_text = "\n".join(page.get_text() for page in doc)
        sub_name = _extract_sub_name(full_text, pdf_file["name"])

        # Render page 1 to PNG for vision
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        img_path = os.path.join(temp_dir, f"gutter_bid_{pdf_file['id']}.png")
        pix.save(img_path)
        doc.close()

        # Read image as base64
        import base64
        with open(img_path, "rb") as img_f:
            img_b64 = base64.b64encode(img_f.read()).decode()

        # Vision extraction via Sonnet
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("[gutter_bid] No ANTHROPIC_API_KEY - cannot parse gutter bid")
            return None

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64}
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract gutter measurements from this bid image. Reply with ONLY a JSON object:\n"
                            '{"gutter_lf": 0, "downspout_lf": 0, "miters": 0, "splashguards": 0, "wholesale_total": 0}\n'
                            "Fill in the actual numbers from the bid. LF = linear feet. "
                            "wholesale_total = the bid total amount. If a measurement isn't listed, use 0."
                        )
                    }
                ]
            }]
        )
        _log_anthropic_usage(msg, "gutter_vision")
        ai_text = msg.content[0].text.strip()
        print(f"[gutter_bid] Vision response: {ai_text}")

        # Parse JSON - handle markdown code blocks
        if "```" in ai_text:
            ai_text = ai_text.split("```")[1]
            if ai_text.startswith("json"):
                ai_text = ai_text[4:]
            ai_text = ai_text.strip()

        gutter_lf = 0
        downspout_lf = 0
        miters = 0
        splashguards = 0
        wholesale_total = 0.0

        if ai_text.startswith("{"):
            parsed = json.loads(ai_text)
            gutter_lf = parsed.get("gutter_lf", 0)
            downspout_lf = parsed.get("downspout_lf", 0)
            miters = parsed.get("miters", 0)
            splashguards = parsed.get("splashguards", 0)
            wholesale_total = float(parsed.get("wholesale_total", 0))
            print(f"[gutter_bid] Vision parsed: {gutter_lf} LF gutter, {downspout_lf} LF downspout, {miters} miters, {splashguards} splashguards (${wholesale_total:,.2f})")
        else:
            print(f"[gutter_bid] Vision response not JSON - parse failed")

        if gutter_lf == 0 and downspout_lf == 0:
            print(f"[pipeline] WARNING: Found gutter bid PDF but couldn't extract measurements")
            return None

        result = {
            "sub_name": sub_name,
            "gutter_lf": int(gutter_lf),
            "downspout_lf": int(downspout_lf),
            "miters": int(miters),
            "splashguards": int(splashguards),
            "other_items": [],
            "wholesale_total": wholesale_total,
            "raw_text": full_text[:1500],
        }
        print(f"[pipeline] Gutter bid parsed: {sub_name} — {int(gutter_lf)} LF gutter, {int(downspout_lf)} LF downspout, {int(miters)} miters, {int(splashguards)} splashguards (${wholesale_total:,.2f} wholesale)")
        return result

    except Exception as e:
        import traceback
        print(f"[gutter_bid] Gutter bid parse failed: {e}")
        traceback.print_exc()
        return None


def _extract_lastname(project_name: str, project: dict) -> str:
    """Extract last name from project name or project record."""
    # Try from project name directly (e.g. "Rose Brock" → "BROCK")
    parts = project_name.strip().split()
    if len(parts) >= 2:
        return parts[-1].upper()
    # Try from project record
    for key in ["last_name", "lastname", "name", "homeowner", "insured", "title"]:
        val = project.get(key, "")
        if val:
            return str(val).split()[-1].upper()
    return project_name.upper().replace(" ", "_")


if __name__ == "__main__":
    import sys
    name = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Rose Brock"
    result = run(name)
    print(json.dumps({k: v for k, v in result.items() if k != "pricelist"}, indent=2, default=str))
