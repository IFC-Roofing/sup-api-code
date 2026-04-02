#!/usr/bin/env python3
"""
IFC @precall Skill — Pre-supplement consultation script builder.
Pulls SUPP + INS + EV + photos + bids + convo context (@ifc, @momentum, @supplement),
then outputs structured data for AI to generate the precall script.

Usage:
    python3 precall.py "Client Name"
    python3 precall.py --id 894
    python3 precall.py --dir /path/to/already/downloaded/files
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

import requests as http_requests

PYTHON = sys.executable

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FILE_PULLER = os.path.join(WORKSPACE, 'tools', 'file-puller', 'pull_files.py')
PARSE_SUPP = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_supplement.py')
PARSE_INS = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_insurance.py')
PARSE_EV = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_eagleview.py')
PARSE_PHOTOS = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_photos.py')
PIPELINE_CACHE = os.path.join(WORKSPACE, 'tools', 'pdf-generator', '.pipeline_cache')

IFC_BASE = 'https://omni.ifc.shibui.ar'
IFC_TOKEN = 'ea6d402f02e42090a8ab9b34d06d0864f00e9b252719ca244f9963b1334bb226'

# Tags we care about for precall context
CONTEXT_TAGS = ['@momentum', '@ifc', '@supplement', '@ins_responded', '@supp_sent', '@client']


def load_cached(cache_key, project_id):
    """Check pipeline cache for a previously parsed result. Returns dict or None."""
    if not project_id:
        return None
    cache_path = os.path.join(PIPELINE_CACHE, f'{cache_key}_{project_id}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                data = json.load(f)
            print(f"[precall] Using cached {cache_key} for project {project_id}", file=sys.stderr)
            return data
        except Exception:
            pass
    return None


def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE)
    if check and result.returncode != 0:
        print(f"ERROR running {' '.join(cmd)}:\n{result.stderr}", file=sys.stderr)
    return result


def pull_files(project=None, project_id=None):
    download_dir = tempfile.mkdtemp(prefix='precall_')
    cmd = [PYTHON, FILE_PULLER]
    if project_id:
        cmd += ['--id', str(project_id)]
    elif project:
        cmd += [project]
    cmd += ['--download', download_dir, '--json']

    result = run_cmd(cmd)
    if result.returncode != 0:
        print(f"Failed to pull files: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    return download_dir, json.loads(result.stdout)


def parse_file(parser_script, filepath, extra_args=None):
    cmd = [PYTHON, parser_script, filepath]
    if extra_args:
        cmd.extend(extra_args)
    out_path = filepath + '.parsed.json'
    cmd.extend(['-o', out_path])

    result = run_cmd(cmd, check=False)
    if result.returncode != 0:
        return None
    try:
        with open(out_path) as f:
            return json.load(f)
    except:
        return None


def get_latest_file(file_list):
    if not file_list:
        return None
    versioned = [f for f in file_list if f.get('version') is not None]
    if versioned:
        return max(versioned, key=lambda f: f['version'])
    return file_list[0]


def strip_html(text):
    """Strip HTML tags and clean up mention spans."""
    if not text:
        return ''
    text = re.sub(r"<span class='user-mention-message'>(.*?)</span>", r'\1', text)
    text = re.sub(r'<span[^>]*class="mention-tag"[^>]*>(.*?)</span>', r'\1', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_convo(project_id):
    """Fetch convo threads from IFC API, extract tagged posts."""
    headers = {'Authorization': f'Bearer {IFC_TOKEN}'}
    try:
        r = http_requests.get(
            f'{IFC_BASE}/posts',
            headers=headers,
            params={'project_id': project_id, 'user': 'sup'},
            timeout=30
        )
        if r.status_code != 200:
            print(f"Warning: Could not fetch convo (HTTP {r.status_code})", file=sys.stderr)
            return []

        posts = r.json().get('posts', [])
    except Exception as e:
        print(f"Warning: Could not fetch convo: {e}", file=sys.stderr)
        return []

    tagged_notes = []
    for post in posts:
        for note in post.get('post_notes', []):
            body_raw = note.get('body', '')
            body_clean = strip_html(body_raw)

            tags_found = [t for t in CONTEXT_TAGS if t.lower() in body_raw.lower()]
            if tags_found:
                tagged_notes.append({
                    'id': note.get('id'),
                    'tags': tags_found,
                    'body': body_clean,
                    'author': note.get('user', {}).get('name', 'Unknown'),
                    'date': note.get('created_at', ''),
                })

    tagged_notes.sort(key=lambda n: n['date'], reverse=True)
    return tagged_notes


def main():
    parser = argparse.ArgumentParser(description='IFC @precall — pre-supplement consultation script')
    parser.add_argument('project', nargs='?', help='Project name')
    parser.add_argument('--id', type=int, help='Project ID')
    parser.add_argument('--dir', help='Use already-downloaded files directory')
    args = parser.parse_args()

    if not args.project and not args.id and not args.dir:
        parser.error('Provide project name, --id, or --dir')

    # Step 1: Pull files
    if args.dir:
        download_dir = args.dir
        manifest_path = os.path.join(args.dir, 'manifest.json')
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        download_dir, manifest = pull_files(args.project, args.id)

    files = manifest.get('files', {})
    project_info = manifest.get('project', {})

    # Step 2: Get all relevant files
    supp_files = files.get('ifc_supplement', [])
    ins_files = files.get('insurance_estimate', [])
    ev_files = files.get('eagleview', [])
    bid_files = files.get('marked_bid', [])
    photo_files = files.get('photo_report', [])

    latest_supp = get_latest_file(supp_files)
    latest_ins = get_latest_file(ins_files)
    latest_ev = get_latest_file(ev_files)

    if not latest_supp:
        print("STOP: Missing IFC supplement with F9s. Cannot proceed with @precall.")
        sys.exit(1)

    if not latest_ins:
        print("STOP: Missing insurance estimate. Cannot proceed with @precall.")
        sys.exit(1)

    # Step 3: Parse all files
    parsed_supp = None
    if latest_supp:
        supp_path = os.path.join(download_dir, latest_supp['name'])
        parsed_supp = parse_file(PARSE_SUPP, supp_path)

    project_id = project_info.get('id') or args.id

    parsed_ins = None
    if latest_ins:
        ins_path = os.path.join(download_dir, latest_ins['name'])
        parsed_ins = load_cached('ins', project_id) or parse_file(PARSE_INS, ins_path)

    parsed_ev = None
    if latest_ev:
        ev_path = os.path.join(download_dir, latest_ev['name'])
        parsed_ev = load_cached('ev', project_id) or parse_file(PARSE_EV, ev_path)

    parsed_bids = []
    for bid in bid_files:
        bid_path = os.path.join(download_dir, bid['name'])
        parsed = parse_file(PARSE_SUPP, bid_path)
        if parsed:
            parsed_bids.append({'file': bid['name'], 'data': parsed})

    parsed_photos = None
    if photo_files:
        latest_photo = photo_files[0]
        photo_path = os.path.join(download_dir, latest_photo['name'])
        parsed_photos = parse_file(PARSE_PHOTOS, photo_path, extra_args=['--evidence'])

    # Step 4: Fetch convo context from IFC API
    convo_context = []
    project_id = project_info.get('id')
    if project_id:
        convo_context = fetch_convo(project_id)

    momentum_notes = [n for n in convo_context if '@momentum' in n['tags']]
    ifc_notes = [n for n in convo_context if '@ifc' in n['tags']]
    supplement_notes = [n for n in convo_context if '@supplement' in n['tags']]
    client_notes = [n for n in convo_context if '@client' in n['tags']]

    # Step 5: Output structured data
    output = {
        'skill': '@precall',
        'project': project_info,
        'download_dir': download_dir,
        'files_found': {
            'ifc_supplement': latest_supp['name'] if latest_supp else None,
            'supp_version': latest_supp.get('version') if latest_supp else None,
            'insurance_estimate': latest_ins['name'] if latest_ins else None,
            'ins_version': latest_ins.get('version') if latest_ins else None,
            'eagleview': latest_ev['name'] if latest_ev else None,
            'sub_bids': [b['name'] for b in bid_files],
            'photo_reports': [p['name'] for p in photo_files],
        },
        'parsed': {
            'supplement': parsed_supp,
            'insurance': parsed_ins,
            'eagleview': parsed_ev,
            'sub_bids': parsed_bids,
            'photos': parsed_photos,
        },
        'convo_context': {
            'total_tagged_notes': len(convo_context),
            'momentum': momentum_notes[:20],
            'ifc_gameplan': ifc_notes[:10],
            'supplement_strategy': supplement_notes[:10],
            'client_notes': client_notes[:10],
            'all_tagged': convo_context[:30],
        }
    }

    print(json.dumps(output, indent=2, default=str))


if __name__ == '__main__':
    main()
