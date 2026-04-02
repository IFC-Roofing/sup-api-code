#!/usr/bin/env python3
"""
IFC Roofing — Trade Estimator
Estimates costs based on historical pricing data from the IFC Pricing Database.

Usage:
    python3 estimate.py --trade "@gutter" --scope "box gutters" --qty 200 --unit LF
    python3 estimate.py --trade "@fence" --scope "wrought iron painting" --qty 1000 --unit LF
    python3 estimate.py --trade "@hvac" --scope "condenser grill replacement" --qty 2 --unit EA
    python3 estimate.py --list-trades  (show available trades and data counts)
    python3 estimate.py --dump  (dump all pricing data as JSON for AI analysis)
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_ID = '13gzTw5JnF6aRntU91OThC9mvkLr6KZ2rTq63qki4jhc'


def get_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import warnings
    warnings.filterwarnings("ignore")
    
    key_path = os.path.join(SCRIPT_DIR, '..', '..', 'google-drive-key.json')
    if not os.path.exists(key_path):
        key_path = os.path.expanduser('~/.openclaw/workspace/google-drive-key.json')
    
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
    )
    return build('sheets', 'v4', credentials=creds)


def fetch_pricing_data():
    """Fetch all rows from the pricing database."""
    sheets = get_sheets_service()
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='Sheet1!A:O'
    ).execute()
    
    rows = result.get('values', [])
    if len(rows) < 2:
        return []
    
    headers = rows[0]
    data = []
    for row in rows[1:]:
        # Pad row to header length
        row += [''] * (len(headers) - len(row))
        entry = dict(zip(headers, row))
        
        # Parse numeric fields
        for field in ['Quantity', 'Unit Price', 'Line Total', 'Bid Total']:
            val = entry.get(field, '')
            if val:
                try:
                    entry[field] = float(str(val).replace(',', '').replace('$', ''))
                except:
                    entry[field] = None
            else:
                entry[field] = None
        
        data.append(entry)
    
    return data


def search_pricing(data, trade=None, scope=None, unit=None):
    """
    Search pricing data with filters.
    Returns matching entries sorted by relevance.
    """
    results = []
    
    for entry in data:
        score = 0
        
        # Trade filter (exact match on trade folder name)
        if trade:
            entry_trade = (entry.get('Trade') or '').lower().strip()
            trade_clean = trade.lower().strip()
            if trade_clean == entry_trade:
                score += 10
            elif trade_clean.replace('@', '') in entry_trade.replace('@', ''):
                score += 5
            else:
                continue  # Skip non-matching trades
        
        # Scope/description matching (fuzzy keyword match)
        if scope:
            desc = (entry.get('Line Item') or '').lower()
            scope_words = [w for w in scope.lower().split() if len(w) > 2]
            matches = sum(1 for w in scope_words if w in desc)
            if matches > 0:
                score += matches * 3
            else:
                # Partial match - check if any significant word overlaps
                desc_words = set(desc.split())
                overlap = desc_words.intersection(set(scope_words))
                if overlap:
                    score += len(overlap) * 2
        
        # Unit matching
        if unit:
            entry_unit = (entry.get('Unit') or '').upper()
            if entry_unit == unit.upper():
                score += 2
        
        if score > 0:
            entry['_score'] = score
            results.append(entry)
    
    # Sort by relevance score
    results.sort(key=lambda x: x.get('_score', 0), reverse=True)
    return results


def estimate(trade=None, scope=None, qty=None, unit=None):
    """
    Generate a cost estimate based on historical pricing data.
    
    Returns dict with:
    - price_range: {low, avg, high} per unit
    - estimated_total: {low, avg, high} if qty provided
    - data_points: number of matching entries
    - subs: list of subcontractors with their pricing
    - confidence: low/medium/high based on data volume
    - matches: the raw matching data
    """
    data = fetch_pricing_data()
    
    if not data:
        return {'error': 'No pricing data available. Run extract_pricing.py on some projects first.'}
    
    matches = search_pricing(data, trade=trade, scope=scope, unit=unit)
    
    if not matches:
        # Try broader search without scope
        if scope and trade:
            matches = search_pricing(data, trade=trade)
            if matches:
                return _build_estimate(matches, qty, unit, 
                                       note=f"No exact match for '{scope}'. Showing all {trade} pricing.")
        
        return {
            'error': f'No pricing data found for trade={trade}, scope={scope}',
            'suggestion': 'Try --list-trades to see available data',
            'total_rows': len(data),
        }
    
    return _build_estimate(matches, qty, unit)


def _build_estimate(matches, qty=None, unit=None, note=None):
    """Build estimate result from matching entries."""
    
    # Collect unit prices
    unit_prices = []
    line_totals = []
    subs = {}
    
    for entry in matches:
        up = entry.get('Unit Price')
        lt = entry.get('Line Total')
        sub_name = entry.get('Subcontractor', 'Unknown')
        
        if up and up > 0:
            unit_prices.append(up)
        if lt and lt > 0:
            line_totals.append(lt)
        
        # Track per-sub pricing
        if sub_name not in subs:
            subs[sub_name] = {
                'name': sub_name,
                'phone': entry.get('Sub Phone', ''),
                'email': entry.get('Sub Email', ''),
                'unit_prices': [],
                'totals': [],
                'projects': set(),
                'items': [],
            }
        if up and up > 0:
            subs[sub_name]['unit_prices'].append(up)
        if lt and lt > 0:
            subs[sub_name]['totals'].append(lt)
        subs[sub_name]['projects'].add(entry.get('Project Name', ''))
        subs[sub_name]['items'].append({
            'description': entry.get('Line Item', ''),
            'qty': entry.get('Quantity'),
            'unit': entry.get('Unit', ''),
            'unit_price': up,
            'line_total': lt,
            'project': entry.get('Project Name', ''),
            'date': entry.get('Date Extracted', ''),
        })
    
    result = {
        'data_points': len(matches),
        'confidence': 'high' if len(matches) >= 10 else 'medium' if len(matches) >= 4 else 'low',
    }
    
    # Unit price stats
    if unit_prices:
        result['unit_price_range'] = {
            'low': round(min(unit_prices), 2),
            'avg': round(sum(unit_prices) / len(unit_prices), 2),
            'high': round(max(unit_prices), 2),
            'count': len(unit_prices),
        }
        
        if qty:
            avg_up = sum(unit_prices) / len(unit_prices)
            result['estimated_total'] = {
                'low': round(min(unit_prices) * qty, 2),
                'avg': round(avg_up * qty, 2),
                'high': round(max(unit_prices) * qty, 2),
            }
    
    # Line total stats (for lump-sum items)
    if line_totals:
        result['line_total_range'] = {
            'low': round(min(line_totals), 2),
            'avg': round(sum(line_totals) / len(line_totals), 2),
            'high': round(max(line_totals), 2),
            'count': len(line_totals),
        }
    
    # Subcontractor breakdown
    sub_list = []
    for sub_name, sub_data in subs.items():
        sub_entry = {
            'name': sub_data['name'],
            'phone': sub_data['phone'],
            'email': sub_data['email'],
            'projects': list(sub_data['projects']),
            'items': sub_data['items'],
        }
        if sub_data['unit_prices']:
            sub_entry['avg_unit_price'] = round(sum(sub_data['unit_prices']) / len(sub_data['unit_prices']), 2)
        if sub_data['totals']:
            sub_entry['avg_total'] = round(sum(sub_data['totals']) / len(sub_data['totals']), 2)
        sub_list.append(sub_entry)
    
    # Sort subs by avg unit price (cheapest first)
    sub_list.sort(key=lambda s: s.get('avg_unit_price', s.get('avg_total', float('inf'))))
    result['subcontractors'] = sub_list
    
    if note:
        result['note'] = note
    
    return result


def list_trades(data):
    """List available trades and their data counts."""
    trades = {}
    for entry in data:
        trade = entry.get('Trade', 'Unknown')
        if trade not in trades:
            trades[trade] = {'count': 0, 'subs': set(), 'projects': set()}
        trades[trade]['count'] += 1
        trades[trade]['subs'].add(entry.get('Subcontractor', ''))
        trades[trade]['projects'].add(entry.get('Project Name', ''))
    
    result = []
    for trade, info in sorted(trades.items()):
        result.append({
            'trade': trade,
            'data_points': info['count'],
            'subcontractors': len(info['subs']),
            'projects': len(info['projects']),
        })
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='IFC Trade Estimator')
    parser.add_argument('--trade', help='Trade folder (e.g., @gutter, @roof, @fence)')
    parser.add_argument('--scope', help='Scope/description keywords (e.g., "box gutters")')
    parser.add_argument('--qty', type=float, help='Quantity')
    parser.add_argument('--unit', help='Unit (LF, SF, EA, SQ)')
    parser.add_argument('--list-trades', action='store_true', help='List available trades')
    parser.add_argument('--dump', action='store_true', help='Dump all data as JSON')
    
    args = parser.parse_args()
    
    if args.list_trades:
        data = fetch_pricing_data()
        trades = list_trades(data)
        print(f"\nIFC Pricing Database: {len(data)} total entries\n")
        print(f"{'Trade':<20} {'Data Points':>12} {'Subs':>6} {'Projects':>10}")
        print("-" * 52)
        for t in trades:
            print(f"{t['trade']:<20} {t['data_points']:>12} {t['subcontractors']:>6} {t['projects']:>10}")
    
    elif args.dump:
        data = fetch_pricing_data()
        print(json.dumps(data, indent=2, default=str))
    
    elif args.trade or args.scope:
        result = estimate(trade=args.trade, scope=args.scope, qty=args.qty, unit=args.unit)
        print(json.dumps(result, indent=2, default=str))
    
    else:
        parser.print_help()
