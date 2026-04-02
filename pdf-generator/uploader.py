"""
uploader.py — Uploads completed PDF to the project's Supplement folder on Drive.

Production routing:
    {Project Folder}/
      Supplement/
        LASTNAME_IFC Supp 1.0.pdf      ← initial estimate
        LASTNAME_IFC Supp 1.1.pdf      ← correction
        LASTNAME_IFC Supp 1.2.pdf      ← another correction
        LASTNAME_IFC Supp 2.0.pdf      ← Phase 2 estimate
        LASTNAME_IFC Supp 2.1.pdf      ← Phase 2 correction
        Generated Markups/             ← marked-up bids (handled by markup_bids.py)

Versioning:
    - First estimate for a phase: X.0 (e.g. 1.0, 2.0)
    - Corrections within same phase: X.1, X.2, X.3...
    - Phase 2 starts at 2.0, Phase 3 at 3.0, etc.
    - Pass phase=2 to start a new major version

NEVER sends to insurance — this is file storage for human review.
"""

import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")


IMPERSONATE_USER = "sup@ifcroofing.com"

def get_service_account():
    creds_path = ROOT / "google-drive-key.json"
    from google.oauth2 import service_account
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return creds.with_subject(IMPERSONATE_USER)


def _find_supplement_folder(service, project_folder_id: str) -> str:
    """Find the Supplement subfolder in the project folder. Returns folder ID or None."""
    resp = service.files().list(
        q=f"'{project_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)", supportsAllDrives=True,
        includeItemsFromAllDrives=True, corpora="allDrives"
    ).execute()
    for f in resp.get("files", []):
        if "supplement" in f["name"].lower():
            return f["id"]
    return None


def _determine_version(service, supplement_folder_id: str, lastname: str, phase: int = None) -> str:
    """
    Determine the next version number for a supplement PDF.
    
    Logic:
      - Lists existing LASTNAME_IFC Supp X.Y.pdf files
      - If phase is specified, starts a new major version (phase.0) if none exists for that phase
      - Otherwise, increments the minor version of the highest existing major version
      - First ever upload = 1.0
    
    Examples:
      Nothing exists          → 1.0
      1.0 exists              → 1.1
      1.0, 1.1 exist          → 1.2
      1.0, 1.1, phase=2       → 2.0
      2.0 exists              → 2.1
    """
    q = f"'{supplement_folder_id}' in parents and name contains '{lastname}_IFC Supp' and trashed=false"
    resp = service.files().list(
        q=q, spaces="drive", supportsAllDrives=True,
        includeItemsFromAllDrives=True, fields="files(id, name)"
    ).execute()
    existing = resp.get("files", [])

    if not existing:
        return f"{phase or 1}.0"

    # Parse all existing versions
    versions = []
    for f in existing:
        m = re.search(r"Supp (\d+)\.(\d+)", f["name"])
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            versions.append((major, minor))

    if not versions:
        return f"{phase or 1}.0"

    versions.sort()

    if phase is not None:
        # Check if this phase already has versions
        phase_versions = [(maj, min_) for maj, min_ in versions if maj == phase]
        if phase_versions:
            # Increment minor within this phase
            max_minor = max(min_ for _, min_ in phase_versions)
            return f"{phase}.{max_minor + 1}"
        else:
            # New phase
            return f"{phase}.0"
    else:
        # No phase specified — increment minor of highest major
        max_major = max(maj for maj, _ in versions)
        major_versions = [(maj, min_) for maj, min_ in versions if maj == max_major]
        max_minor = max(min_ for _, min_ in major_versions)
        return f"{max_major}.{max_minor + 1}"


def upload(pdf_path: str, project_name: str, lastname: str, version: str = None,
           address_street: str = "", project_folder_id: str = None, phase: int = None) -> str:
    """
    Upload PDF to the project's Supplement folder on Drive.
    Names it: {LASTNAME}_IFC Supp {version}.pdf
    Returns the uploaded file's Drive ID.

    Args:
        pdf_path: Local path to PDF
        project_name: Full project name (e.g. "Becky Braswell")
        lastname: Last name for file naming
        version: Override version (auto-detected if None)
        address_street: (unused, kept for backward compat)
        project_folder_id: The project's Drive folder ID (required for production routing)
        phase: Phase number for new major version (e.g. 2 for Phase 2)

    NEVER sends to insurance — this is just file storage for human review.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_service_account()
    service = build("drive", "v3", credentials=creds)

    if not project_folder_id:
        raise ValueError("project_folder_id is required for upload. Pass the project's Drive folder ID.")

    # Find the Supplement folder
    supplement_folder_id = _find_supplement_folder(service, project_folder_id)
    if not supplement_folder_id:
        raise ValueError(f"No 'Supplement' folder found in project folder {project_folder_id}")

    if version is None:
        version = _determine_version(service, supplement_folder_id, lastname, phase)

    file_name = f"{lastname}_IFC Supp {version}.pdf"
    print(f"[uploader] Uploading as: {file_name}")

    file_metadata = {
        "name": file_name,
        "parents": [supplement_folder_id],
    }
    media = MediaFileUpload(pdf_path, mimetype="application/pdf")
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        supportsAllDrives=True,
        fields="id, name, webViewLink"
    ).execute()

    file_id = uploaded.get("id")
    link = uploaded.get("webViewLink", "")
    print(f"[uploader] Uploaded: {file_name} → Supplement/")
    print(f"[uploader] Drive link: {link}")
    return file_id


if __name__ == "__main__":
    pdf_path = sys.argv[1]
    project_name = sys.argv[2] if len(sys.argv) > 2 else "Test Project"
    lastname = sys.argv[3] if len(sys.argv) > 3 else "TEST"
    folder_id = sys.argv[4] if len(sys.argv) > 4 else None
    upload(pdf_path, project_name, lastname, project_folder_id=folder_id)
