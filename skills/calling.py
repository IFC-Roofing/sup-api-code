#!/usr/bin/env python3
"""
IFC @calling Skill — Carrier phone script builder.
Pulls SUPP + INS + convo context (especially @momentum and @ifc tags),
then outputs structured data for AI to generate the call script.

Usage:
    python3 calling.py "Client Name"
    python3 calling.py --id 894
    python3 calling.py --dir /path/to/already/downloaded/files
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

import requests as http_requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FILE_PULLER = os.path.join(WORKSPACE, 'tools', 'file-puller', 'pull_files.py')
PARSE_SUPP = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_supplement.py')
PARSE_INS = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_insurance.py')

IFC_BASE = 'https://omni.ifc.shibui.ar'
IFC_TOKEN = 'ea6d402f02e42090a8ab9b34d06d0864f00e9b252719ca244f9963b1334bb226'
PIPELINE_CACHE = os.path.join(WORKSPACE, 'tools', 'pdf-generator', '.pipeline_cache')

# Tags we care about for call context
CONTEXT_TAGS = ['@momentum', '@ifc', '@supplement', '@calling', '@ins_responded', '@supp_sent']


PYTHON = sys.executable  # Use the same python that's running this script


def run_cmd(cmd, check=True):
    print(f"[calling] Running: {os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]}...", file=sys.stderr, flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE)
    if check and result.returncode != 0:
        print(f"ERROR running {' '.join(cmd)}:\n{result.stderr}", file=sys.stderr)
    return result


def pull_files(project=None, project_id=None):
    download_dir = tempfile.mkdtemp(prefix='calling_')
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
    # Extract user mentions
    text = re.sub(r"<span class='user-mention-message'>(.*?)</span>", r'\1', text)
    # Extract @tags from mention-tag spans
    text = re.sub(r'<span[^>]*class="mention-tag"[^>]*>(.*?)</span>', r'\1', text)
    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
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

    # Extract all post_notes, filter for relevant tags
    tagged_notes = []
    for post in posts:
        for note in post.get('post_notes', []):
            body_raw = note.get('body', '')
            body_clean = strip_html(body_raw)

            # Check if any context tag appears
            tags_found = [t for t in CONTEXT_TAGS if t.lower() in body_raw.lower()]
            if tags_found:
                tagged_notes.append({
                    'id': note.get('id'),
                    'tags': tags_found,
                    'body': body_clean,
                    'author': note.get('user', {}).get('name', 'Unknown'),
                    'date': note.get('created_at', ''),
                })

    # Sort by date descending (most recent first)
    tagged_notes.sort(key=lambda n: n['date'], reverse=True)
    return tagged_notes


def main():
    parser = argparse.ArgumentParser(description='IFC @calling — carrier phone script builder')
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

    # Step 2: Get latest SUPP and INS
    supp_files = files.get('ifc_supplement', [])
    ins_files = files.get('insurance_estimate', [])

    latest_supp = get_latest_file(supp_files)
    latest_ins = get_latest_file(ins_files)

    if not latest_supp:
        print("STOP: Missing IFC supplement with F9s. Cannot proceed with @calling.")
        sys.exit(1)

    # Step 3: Parse files
    parsed_supp = None
    if latest_supp:
        supp_path = os.path.join(download_dir, latest_supp['name'])
        parsed_supp = parse_file(PARSE_SUPP, supp_path)

    parsed_ins = None
    if latest_ins:
        # Check pipeline cache first (INS parsing via vision API is slow)
        project_id_for_cache = project_info.get('id')
        cache_path = os.path.join(PIPELINE_CACHE, f'ins_{project_id_for_cache}.json') if project_id_for_cache else None
        if cache_path and os.path.exists(cache_path):
            print(f"[calling] Using cached INS parse for project {project_id_for_cache}", file=sys.stderr, flush=True)
            with open(cache_path) as f:
                parsed_ins = json.load(f)
        else:
            ins_path = os.path.join(download_dir, latest_ins['name'])
            parsed_ins = parse_file(PARSE_INS, ins_path)

    # Step 4: Fetch convo context from IFC API
    convo_context = []
    project_id = project_info.get('id')
    if project_id:
        convo_context = fetch_convo(project_id)

    # Separate by tag type for easier consumption
    momentum_notes = [n for n in convo_context if '@momentum' in n['tags']]
    ifc_notes = [n for n in convo_context if '@ifc' in n['tags']]
    supplement_notes = [n for n in convo_context if '@supplement' in n['tags']]

    # Step 5: Output structured data
    output = {
        'skill': '@calling',
        'project': project_info,
        'download_dir': download_dir,
        'files_found': {
            'ifc_supplement': latest_supp['name'] if latest_supp else None,
            'supp_version': latest_supp.get('version') if latest_supp else None,
            'insurance_estimate': latest_ins['name'] if latest_ins else None,
            'ins_version': latest_ins.get('version') if latest_ins else None,
        },
        'parsed': {
            'supplement': parsed_supp,
            'insurance': parsed_ins,
        },
        'convo_context': {
            'total_tagged_notes': len(convo_context),
            'momentum': momentum_notes[:20],  # Cap at 20 most recent
            'ifc_gameplan': ifc_notes[:10],
            'supplement_strategy': supplement_notes[:10],
            'all_tagged': convo_context[:30],
        }
    }

    print(json.dumps(output, indent=2, default=str))


if __name__ == '__main__':
    main()
