#!/usr/bin/env python3
"""
IFC Project File Puller
Pulls and categorizes files from a project's Supplement folder on Google Drive.

Usage:
    python3 pull_files.py "Chris Isbell"
    python3 pull_files.py --id 4965
    python3 pull_files.py "Chris Isbell" --download /tmp/isbell_files
    python3 pull_files.py "Chris Isbell" --json
"""

import argparse
import io
import json
import os
import re
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests as http_requests

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DRIVE_KEY = os.path.join(WORKSPACE, 'google-drive-key.json')

IFC_BASE = 'https://omni.ifc.shibui.ar'
IFC_TOKEN = 'ea6d402f02e42090a8ab9b34d06d0864f00e9b252719ca244f9963b1334bb226'

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# File classification patterns
# Order matters — first match wins
FILE_PATTERNS = [
    # Insurance estimates: ins 1.0, ins 2.0, INS 3.0, etc.
    ('insurance_estimate', re.compile(r'(?:_|\b)ins\s*(\d+\.?\d*)', re.IGNORECASE)),
    # IFC supplements: supp 1.0, IFC Supp 1.0, etc.
    ('ifc_supplement', re.compile(r'(?:_|\b)(?:ifc\s*)?supp(?:lement)?\s*(\d+\.?\d*)', re.IGNORECASE)),
    # EagleView
    ('eagleview', re.compile(r'eagleview|eagle[\s_]?view', re.IGNORECASE)),
    # Photo reports
    ('photo_report', re.compile(r'photo\s*report', re.IGNORECASE)),
    # Gutter diagram
    ('gutter_diagram', re.compile(r'gutter\s*diagram', re.IGNORECASE)),
    # Contract
    ('contract', re.compile(r'contract', re.IGNORECASE)),
    # Summary of Loss
    ('summary_of_loss', re.compile(r'summary\s*of\s*loss|SOL', re.IGNORECASE)),
    # Appraisal documents
    ('appraisal', re.compile(r'appraisal|AD\b', re.IGNORECASE)),
    # Sub-bids (trade bids in supplement folder — these are marked up versions)
    ('marked_bid', re.compile(r'(?:gutter|fence|window|glass|copper|metal|roof|siding|hvac|paint|door|chimney|grizzly|gladiator|foglass|rambros)', re.IGNORECASE)),
]

# Files/patterns to skip
SKIP_PATTERNS = [
    re.compile(r'final[\s_]*draft[\s_]*car', re.IGNORECASE),  # Old drafts
]


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(DRIVE_KEY, scopes=SCOPES).with_subject('sup@ifcroofing.com')
    return build('drive', 'v3', credentials=creds)


def get_project(search=None, project_id=None):
    """Find project via IFC API."""
    headers = {'Authorization': f'Bearer {IFC_TOKEN}'}
    
    if project_id:
        r = http_requests.get(f'{IFC_BASE}/projects/{project_id}', headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        # Try search fallback
        r = http_requests.get(f'{IFC_BASE}/projects', headers=headers, params={'search': str(project_id)}, timeout=30)
    else:
        r = http_requests.get(f'{IFC_BASE}/projects', headers=headers, params={'search': search}, timeout=30)
    
    data = r.json()
    projects = data.get('projects', data if isinstance(data, list) else [])
    
    if not projects:
        print(f"No projects found for '{search or project_id}'", file=sys.stderr)
        sys.exit(1)
    
    if len(projects) > 1:
        print(f"Multiple projects found:", file=sys.stderr)
        for p in projects[:10]:
            print(f"  ID {p['id']}: {p['name']} — {p.get('full_address', '?')} [{p.get('record_status', '?')}]", file=sys.stderr)
        print(f"\nUse --id <id> to pick one.", file=sys.stderr)
        sys.exit(1)
    
    return projects[0]


def extract_folder_id(drive_link):
    """Extract folder ID from Google Drive URL."""
    if not drive_link:
        return None
    m = re.search(r'folders/([a-zA-Z0-9_-]+)', drive_link)
    return m.group(1) if m else None


def list_folder(drive, folder_id, recursive=False, skip_archive=True):
    """List files in a Drive folder. Returns list of {id, name, mimeType, path}."""
    results = []
    
    r = drive.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields='files(id,name,mimeType)',
        pageSize=200
    ).execute()
    
    for f in r.get('files', []):
        if f['mimeType'] == 'application/vnd.google-apps.folder':
            folder_name = f['name'].lower().strip()
            
            # Skip Archive folder
            if skip_archive and folder_name == 'archive':
                continue
            
            # Recurse into non-archive subfolders (like @ifc)
            if recursive:
                sub_files = list_folder(drive, f['id'], recursive=True, skip_archive=skip_archive)
                for sf in sub_files:
                    sf['path'] = f"{f['name']}/{sf.get('path', sf['name'])}"
                results.extend(sub_files)
        else:
            results.append({
                'id': f['id'],
                'name': f['name'],
                'mimeType': f['mimeType'],
                'path': f['name']
            })
    
    return results


def classify_file(filename):
    """Classify a file by its name. Returns (category, version) or (None, None)."""
    # Check skip patterns first
    for pattern in SKIP_PATTERNS:
        if pattern.search(filename):
            return ('skip', None)
    
    for category, pattern in FILE_PATTERNS:
        m = pattern.search(filename)
        if m:
            version = None
            if m.groups():
                try:
                    version = float(m.group(1))
                except (ValueError, IndexError):
                    pass
            return (category, version)
    
    return ('other', None)


def find_supplement_folder(drive, project_folder_id):
    """Find the Supplement subfolder in a project folder."""
    r = drive.files().list(
        q=f"'{project_folder_id}' in parents and name = 'Supplement' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields='files(id,name)'
    ).execute()
    
    files = r.get('files', [])
    if files:
        return files[0]['id']
    return None


def find_archive_folder(drive, supplement_folder_id):
    """Find the Archive subfolder inside the Supplement folder (for @response previous INS)."""
    r = drive.files().list(
        q=f"'{supplement_folder_id}' in parents and name = 'Archive' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields='files(id,name)'
    ).execute()
    
    files = r.get('files', [])
    if files:
        return files[0]['id']
    return None


def pull_previous_ins_from_archive(drive, archive_folder_id):
    """Only pull insurance estimates from Archive (for @response). Nothing else."""
    if not archive_folder_id:
        return []
    
    files = list_folder(drive, archive_folder_id, recursive=False, skip_archive=False)
    ins_files = []
    for f in files:
        cat, ver = classify_file(f['name'])
        if cat == 'insurance_estimate':
            f['category'] = cat
            f['version'] = ver
            f['source'] = 'archive'
            ins_files.append(f)
    
    return ins_files


def download_file(drive, file_id, dest_path):
    """Download a file from Drive to local path."""
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    content = request.execute()
    
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'wb') as f:
        if isinstance(content, bytes):
            f.write(content)
        else:
            f.write(content.read() if hasattr(content, 'read') else str(content).encode())
    
    return dest_path


def pull_project_files(project_name=None, project_id=None, download_dir=None, include_archive_ins=False):
    """Main function: find project, list supplement files, classify them."""
    
    # 1. Find project
    project = get_project(search=project_name, project_id=project_id)
    project_info = {
        'id': project['id'],
        'name': project['name'],
        'address': project.get('full_address', ''),
        'status': project.get('record_status', ''),
        'drive_link': project.get('google_drive_link', ''),
    }
    
    # 2. Get Drive folder
    folder_id = extract_folder_id(project_info['drive_link'])
    if not folder_id:
        print(f"No Drive folder found for {project_info['name']}", file=sys.stderr)
        sys.exit(1)
    
    drive = get_drive_service()
    
    # 3. Find Supplement folder
    supp_folder_id = find_supplement_folder(drive, folder_id)
    if not supp_folder_id:
        print(f"No 'Supplement' folder found in project Drive", file=sys.stderr)
        sys.exit(1)
    
    # 4. List and classify files (skip Archive)
    raw_files = list_folder(drive, supp_folder_id, recursive=True, skip_archive=True)
    
    classified = {
        'insurance_estimate': [],
        'ifc_supplement': [],
        'eagleview': [],
        'photo_report': [],
        'gutter_diagram': [],
        'contract': [],
        'summary_of_loss': [],
        'appraisal': [],
        'marked_bid': [],
        'other': [],
    }
    
    for f in raw_files:
        cat, ver = classify_file(f['name'])
        if cat == 'skip':
            continue
        f['category'] = cat or 'other'
        f['version'] = ver
        f['source'] = 'supplement'
        classified.setdefault(f['category'], []).append(f)
    
    # Sort versioned files by version (highest = latest)
    for cat in ['insurance_estimate', 'ifc_supplement']:
        classified[cat].sort(key=lambda x: x.get('version') or 0, reverse=True)
    
    # 5. Optionally pull previous INS from Archive (for @response)
    archive_ins = []
    if include_archive_ins:
        archive_folder_id = find_archive_folder(drive, supp_folder_id)
        archive_ins = pull_previous_ins_from_archive(drive, archive_folder_id)
        archive_ins.sort(key=lambda x: x.get('version') or 0, reverse=True)
    
    # 6. Download files if requested
    if download_dir:
        os.makedirs(download_dir, exist_ok=True)
        for cat, files in classified.items():
            for f in files:
                dest = os.path.join(download_dir, f['path'])
                try:
                    download_file(drive, f['id'], dest)
                    f['local_path'] = dest
                    print(f"  ✓ {f['name']}", file=sys.stderr)
                except Exception as e:
                    f['local_path'] = None
                    print(f"  ✗ {f['name']}: {e}", file=sys.stderr)
        
        for f in archive_ins:
            dest = os.path.join(download_dir, 'archive', f['name'])
            try:
                download_file(drive, f['id'], dest)
                f['local_path'] = dest
                print(f"  ✓ [archive] {f['name']}", file=sys.stderr)
            except Exception as e:
                f['local_path'] = None
                print(f"  ✗ [archive] {f['name']}: {e}", file=sys.stderr)
    
    return {
        'project': project_info,
        'supplement_folder_id': supp_folder_id,
        'files': classified,
        'archive_insurance': archive_ins,
        'summary': {
            cat: len(files) for cat, files in classified.items() if files
        }
    }


def print_summary(result):
    """Print a human-readable summary."""
    p = result['project']
    print(f"\n{'='*60}")
    print(f"Project: {p['name']}")
    print(f"Address: {p['address']}")
    print(f"Status:  {p['status']}")
    print(f"{'='*60}")
    
    categories = {
        'insurance_estimate': '📋 Insurance Estimates',
        'ifc_supplement': '📄 IFC Supplements',
        'eagleview': '🏠 EagleView',
        'photo_report': '📸 Photo Reports',
        'gutter_diagram': '🔧 Gutter Diagrams',
        'contract': '📝 Contract',
        'summary_of_loss': '📊 Summary of Loss',
        'appraisal': '⚖️ Appraisal',
        'marked_bid': '💰 Marked Up Bids',
        'other': '❓ Other Files',
    }
    
    for cat, label in categories.items():
        files = result['files'].get(cat, [])
        if not files:
            continue
        print(f"\n{label}:")
        for f in files:
            ver = f" (v{f['version']})" if f.get('version') else ''
            local = f" → {f['local_path']}" if f.get('local_path') else ''
            print(f"  • {f['name']}{ver}{local}")
    
    if result.get('archive_insurance'):
        print(f"\n📁 Archive Insurance (for @response):")
        for f in result['archive_insurance']:
            ver = f" (v{f['version']})" if f.get('version') else ''
            print(f"  • {f['name']}{ver}")
    
    # Readiness check
    print(f"\n{'─'*40}")
    has_ins = bool(result['files'].get('insurance_estimate'))
    has_supp = bool(result['files'].get('ifc_supplement'))
    has_ev = bool(result['files'].get('eagleview'))
    has_bids = bool(result['files'].get('marked_bid'))
    has_photos = bool(result['files'].get('photo_report'))
    
    print(f"{'✅' if has_ins else '❌'} Insurance Estimate")
    print(f"{'✅' if has_supp else '❌'} IFC Supplement")
    print(f"{'✅' if has_ev else '❌'} EagleView")
    print(f"{'✅' if has_bids else '❌'} Marked Bids")
    print(f"{'✅' if has_photos else '❌'} Photo Report")
    
    ready_for_review = has_ins and has_supp
    print(f"\n{'✅ READY for @review' if ready_for_review else '❌ NOT READY for @review — missing required files'}")


def main():
    parser = argparse.ArgumentParser(description='Pull and categorize IFC project files from Drive')
    parser.add_argument('project', nargs='?', help='Project name to search')
    parser.add_argument('--id', type=int, help='Project ID')
    parser.add_argument('--download', '-d', help='Download files to this directory')
    parser.add_argument('--archive-ins', action='store_true', help='Also pull insurance estimates from Archive (for @response)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if not args.project and not args.id:
        parser.error("Provide a project name or --id")
    
    result = pull_project_files(
        project_name=args.project,
        project_id=args.id,
        download_dir=args.download,
        include_archive_ins=args.archive_ins
    )
    
    if args.json:
        # Clean for JSON serialization
        print(json.dumps(result, indent=2, default=str))
    else:
        print_summary(result)


if __name__ == '__main__':
    main()
