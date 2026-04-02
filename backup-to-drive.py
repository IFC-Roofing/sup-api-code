#!/usr/bin/env python3
"""Zip the OpenClaw workspace and upload to Google Drive."""

import os
import sys
import zipfile
import tempfile
from datetime import datetime

WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
KEY_PATH = os.path.join(WORKSPACE, 'google-drive-key.json')

# Files/folders to include
INCLUDE = [
    'SOUL.md', 'IDENTITY.md', 'USER.md', 'MEMORY.md',
    'AGENTS.md', 'TOOLS.md', 'HEARTBEAT.md',
    '.env', 'google-drive-key.json',
    'memory/',
    'tools/',
]

# Skip these patterns
SKIP = ['__pycache__', '.pyc', 'node_modules', '.git', 'tmp/', '.venv', 'discovery_cache', 'Zone.Identifier', '.pipeline_cache']


def should_skip(path):
    for s in SKIP:
        if s in path:
            return True
    return False


def make_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            full = os.path.join(WORKSPACE, item)
            if os.path.isfile(full):
                zf.write(full, item)
                print(f"  + {item}")
            elif os.path.isdir(full):
                for root, dirs, files in os.walk(full):
                    for f in files:
                        fp = os.path.join(root, f)
                        arcname = os.path.relpath(fp, WORKSPACE)
                        if not should_skip(arcname):
                            zf.write(fp, arcname)
                            print(f"  + {arcname}")
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"\nZip created: {size_mb:.1f} MB")


def upload(zip_path, folder_id):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import warnings
    warnings.filterwarnings("ignore")

    creds = service_account.Credentials.from_service_account_file(
        KEY_PATH, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)

    # Create "Sup Backup" folder if it doesn't exist
    q = f"name='Sup Backup' and '{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(
        q=q, fields='files(id,name)',
        supportsAllDrives=True, includeItemsFromAllDrives=True, corpora='allDrives'
    ).execute()
    
    if results.get('files'):
        backup_folder_id = results['files'][0]['id']
    else:
        meta = {
            'name': 'Sup Backup',
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [folder_id]
        }
        folder = service.files().create(
            body=meta, fields='id', supportsAllDrives=True
        ).execute()
        backup_folder_id = folder['id']
        print(f"Created 'Sup Backup' folder")

    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M')
    filename = f"sup-workspace-{timestamp}.zip"

    media = MediaFileUpload(zip_path, mimetype='application/zip')
    file_meta = {
        'name': filename,
        'parents': [backup_folder_id]
    }
    f = service.files().create(
        body=file_meta, media_body=media,
        fields='id,name,webViewLink', supportsAllDrives=True
    ).execute()
    
    print(f"\n✅ Uploaded: {f['name']}")
    if f.get('webViewLink'):
        print(f"   Link: {f['webViewLink']}")
    return f


if __name__ == '__main__':
    # Default: upload to the same Shared Drive output folder used by markup
    PARENT_FOLDER_ID = '1CyvDHMY8GPv160c9puYw0_6qo1u_bUaz'  # Sup Backup in Sup AI
    
    if len(sys.argv) > 1:
        PARENT_FOLDER_ID = sys.argv[1]

    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        zip_path = tmp.name

    try:
        print("Zipping workspace...")
        make_zip(zip_path)
        print("\nUploading to Drive...")
        upload(zip_path, PARENT_FOLDER_ID)
    finally:
        os.unlink(zip_path)
