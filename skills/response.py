#!/usr/bin/env python3
"""
IFC @response Skill — Phase 2 insurance response analysis.
Compares previous vs new INS estimates, identifies approvals/denials,
calculates momentum totals, generates per-item action table with rewritten F9s.

Usage:
    python3 response.py "Client Name"
    python3 response.py --id 894
    python3 response.py --dir /path/to/already/downloaded/files
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

IFC_BASE = 'https://omni.ifc.shibui.ar'
IFC_TOKEN = 'ea6d402f02e42090a8ab9b34d06d0864f00e9b252719ca244f9963b1334bb226'
CONTEXT_TAGS = ['@momentum', '@ifc', '@supplement', '@ins_responded', '@supp_sent']
FILE_PULLER = os.path.join(WORKSPACE, 'tools', 'file-puller', 'pull_files.py')
PARSE_SUPP = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_supplement.py')
PARSE_INS = os.path.join(WORKSPACE, 'tools', 'parsers', 'parse_insurance.py')
PIPELINE_CACHE = os.path.join(WORKSPACE, 'tools', 'pdf-generator', '.pipeline_cache')


def load_cached(cache_key, project_id):
    """Check pipeline cache for a previously parsed result. Returns dict or None."""
    if not project_id:
        return None
    cache_path = os.path.join(PIPELINE_CACHE, f'{cache_key}_{project_id}.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                data = json.load(f)
            print(f"[response] Using cached {cache_key} for project {project_id}", file=sys.stderr)
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
    download_dir = tempfile.mkdtemp(prefix='response_')
    cmd = [sys.executable, FILE_PULLER]
    if project_id:
        cmd += ['--id', str(project_id)]
    elif project:
        cmd += [project]
    # Use --archive-ins to get previous insurance versions
    cmd += ['--download', download_dir, '--archive-ins', '--json']
    
    result = run_cmd(cmd)
    if result.returncode != 0:
        print(f"Failed to pull files: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    
    return download_dir, json.loads(result.stdout)


def parse_file(parser_script, filepath, extra_args=None):
    cmd = [sys.executable, parser_script, filepath]
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


def strip_html(text):
    if not text:
        return ''
    text = re.sub(r"<span class='user-mention-message'>(.*?)</span>", r'\1', text)
    text = re.sub(r'<span[^>]*class="mention-tag"[^>]*>(.*?)</span>', r'\1', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_convo(project_id):
    headers = {'Authorization': f'Bearer {IFC_TOKEN}'}
    try:
        r = http_requests.get(
            f'{IFC_BASE}/posts',
            headers=headers,
            params={'project_id': project_id, 'user': 'sup'},
            timeout=30
        )
        if r.status_code != 200:
            return []
        posts = r.json().get('posts', [])
    except Exception:
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


def get_files_by_version(file_list):
    """Sort files by version, return list sorted ascending."""
    versioned = [f for f in file_list if f.get('version') is not None]
    return sorted(versioned, key=lambda f: f['version'])


def main():
    parser = argparse.ArgumentParser(description='IFC @response — insurance response analysis')
    parser.add_argument('project', nargs='?', help='Project name')
    parser.add_argument('--id', type=int, help='Project ID')
    parser.add_argument('--dir', help='Use already-downloaded files directory')
    args = parser.parse_args()
    
    if not args.project and not args.id and not args.dir:
        parser.error('Provide project name, --id, or --dir')
    
    # Step 1: Pull files (with archive for previous INS versions)
    if args.dir:
        download_dir = args.dir
        manifest_path = os.path.join(args.dir, 'manifest.json')
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        download_dir, manifest = pull_files(args.project, args.id)
    
    files = manifest.get('files', {})
    project_info = manifest.get('project', {})
    
    # Step 2: Identify files — need at least 2 INS versions + latest SUPP
    ins_files = get_files_by_version(files.get('insurance_estimate', []))
    supp_files = files.get('ifc_supplement', [])
    
    if len(ins_files) < 1:
        print("STOP: Missing insurance estimate. Cannot proceed with @response.")
        sys.exit(1)
    
    if not supp_files:
        print("STOP: Missing IFC supplement. Cannot proceed with @response.")
        sys.exit(1)
    
    # Current INS = highest version, Previous INS = second highest
    current_ins = ins_files[-1]
    previous_ins = ins_files[-2] if len(ins_files) >= 2 else None
    
    # Latest SUPP
    supp_versioned = [f for f in supp_files if f.get('version') is not None]
    latest_supp = max(supp_versioned, key=lambda f: f['version']) if supp_versioned else supp_files[0]
    
    # Step 3: Parse all three (use pipeline cache when available)
    project_id = project_info.get('id') or args.id
    current_ins_path = os.path.join(download_dir, current_ins['name'])
    parsed_current_ins = load_cached('ins', project_id) or parse_file(PARSE_INS, current_ins_path)
    
    parsed_previous_ins = None
    if previous_ins:
        prev_ins_path = os.path.join(download_dir, previous_ins['name'])
        parsed_previous_ins = parse_file(PARSE_INS, prev_ins_path)
    
    supp_path = os.path.join(download_dir, latest_supp['name'])
    parsed_supp = parse_file(PARSE_SUPP, supp_path)
    
    # Step 4: Fetch convo context from IFC API
    convo_context = []
    project_id = project_info.get('id')
    if project_id:
        convo_context = fetch_convo(project_id)

    momentum_notes = [n for n in convo_context if '@momentum' in n['tags']]
    ifc_notes = [n for n in convo_context if '@ifc' in n['tags']]
    supplement_notes = [n for n in convo_context if '@supplement' in n['tags']]

    # Step 5: Output structured data for AI skill
    output = {
        'skill': '@response',
        'project': project_info,
        'download_dir': download_dir,
        'files_found': {
            'current_insurance': current_ins['name'],
            'current_ins_version': current_ins.get('version'),
            'previous_insurance': previous_ins['name'] if previous_ins else None,
            'previous_ins_version': previous_ins.get('version') if previous_ins else None,
            'ifc_supplement': latest_supp['name'],
            'supp_version': latest_supp.get('version'),
            'total_ins_versions': len(ins_files),
        },
        'parsed': {
            'current_insurance': parsed_current_ins,
            'previous_insurance': parsed_previous_ins,
            'supplement': parsed_supp,
        },
        'convo_context': {
            'total_tagged_notes': len(convo_context),
            'momentum': momentum_notes[:20],
            'ifc_gameplan': ifc_notes[:10],
            'supplement_strategy': supplement_notes[:10],
        }
    }
    
    print(json.dumps(output, indent=2, default=str))


if __name__ == '__main__':
    main()
