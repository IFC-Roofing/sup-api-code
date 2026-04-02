#!/usr/bin/env python3
"""
Sup AI Microservice with Learning
Handles supplement generation + learning feedback loop
"""

import os
import subprocess
import json
import re
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from learning_service import learning_service
from enhanced_learning import enhanced_learning
from pricelist_manager import pricelist_manager

app = Flask(__name__)
CORS(app)

# Path to the PDF generator
PDF_GENERATOR_PATH = "/Users/IFCSUP/.openclaw/workspace/tools/pdf-generator"
PYTHON_BIN = f"{PDF_GENERATOR_PATH}/.venv/bin/python"
GENERATE_SCRIPT = f"{PDF_GENERATOR_PATH}/generate.py"

@app.route('/v1/estimate', methods=['POST'])
def generate_estimate():
    """Generate supplement estimate PDF with learning integration"""
    try:
        data = request.get_json()
        project_name = data.get('project_name')
        project_id = data.get('project_id')
        skip_upload = data.get('skip_upload', False)
        context = data.get('context', {})
        
        if not project_name:
            return jsonify({
                'success': False,
                'error': 'project_name is required'
            }), 400
        
        carrier = context.get('carrier', 'Unknown')
        
        # PRICELIST: Select appropriate pricelist for this supplement
        version = data.get('version', '1.0')  # Default to 1.0 if not specified
        manual_pricelist = data.get('pricelist_override')  # Optional manual override
        
        selected_pricelist, pricelist_reason = pricelist_manager.select_pricelist_for_supplement(
            project_id or 0, project_name, version, manual_pricelist
        )
        print(f"Selected pricelist: {selected_pricelist} ({pricelist_reason})")
        
        # LEARNING: Get learned intelligence for this context
        learned_intelligence = {}
        strategies = ['steep_on_waste', 'full_fence_scope', 'O&P']  # Common strategies
        
        if carrier != 'Unknown':
            learned_intelligence = learning_service.get_learned_patterns(carrier, strategies)
            print(f"Providing {len(learned_intelligence)} learned insights for {carrier}")
        
        # Build command with learning context and pricelist
        cmd = [PYTHON_BIN, GENERATE_SCRIPT, project_name]
        if skip_upload:
            cmd.append('--skip-upload')
        
        # Pass learned intelligence + pricelist selection
        env = os.environ.copy()
        env['SELECTED_PRICELIST'] = selected_pricelist
        env['PRICELIST_REASON'] = pricelist_reason
        
        if learned_intelligence:
            env['LEARNED_INTELLIGENCE'] = json.dumps({
                'type': 'recommendations',
                'carrier': carrier,
                'insights': learned_intelligence,
                'note': 'These are suggestions based on historical data, not mandatory rules'
            })
            env['CARRIER_CONTEXT'] = carrier
        
        # Run the PDF generator
        result = subprocess.run(
            cmd,
            cwd=PDF_GENERATOR_PATH,
            capture_output=True,
            text=True,
            env=env,
            timeout=600  # 10 minutes
        )
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'PDF generation failed: {result.stderr}'
            }), 500
        
        # Parse output for details
        output = result.stdout
        total_rcv_str, trade_count, strategies_used = parse_supplement_output(output)
        total_rcv = parse_amount(total_rcv_str)
        
        # LEARNING: Track this generation event
        event_id = None
        if project_id:
            event_id = learning_service.track_supplement_generation(
                project_id=int(project_id),
                project_name=project_name,
                carrier=carrier,
                strategies=strategies_used,
                amount_requested=total_rcv
            )
        
        return jsonify({
            'success': True,
            'pdf_url': f'Generated locally in {PDF_GENERATOR_PATH}',
            'total_rcv': total_rcv_str,
            'trade_count': trade_count,
            'strategies_used': strategies_used,
            'intelligence_provided': list(learned_intelligence.keys()),
            'pricelist_used': selected_pricelist,
            'pricelist_reason': pricelist_reason,
            'event_id': event_id,  # For tracking responses
            'output': output
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'PDF generation timed out'
        }), 504
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500

@app.route('/v1/track_response', methods=['POST'])
def track_response():
    """Track insurance response for learning"""
    try:
        data = request.get_json()
        event_id = data.get('event_id')
        approved_items = data.get('approved_items', [])
        denied_items = data.get('denied_items', [])
        
        if not event_id:
            return jsonify({
                'success': False,
                'error': 'event_id is required'
            }), 400
        
        # Calculate total approved amount
        total_approved = 0
        for item in approved_items:
            total_approved += float(item.get('amount', 0))
        
        for item in denied_items:
            # Partial approvals
            total_approved += float(item.get('approved_amount', 0))
        
        # Track the response
        learning_service.track_insurance_response(
            event_id=int(event_id),
            approved_items=approved_items,
            denied_items=denied_items,
            total_approved=total_approved
        )
        
        return jsonify({
            'success': True,
            'message': 'Response tracked successfully',
            'total_approved': total_approved
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to track response: {str(e)}'
        }), 500

@app.route('/v1/insights', methods=['GET'])
def get_insights():
    """Get learning insights for team dashboard"""
    try:
        days = int(request.args.get('days', 30))
        carrier = request.args.get('carrier')
        
        insights = learning_service.get_insights_summary(days)
        
        # Add carrier-specific insights if requested
        if carrier:
            carrier_patterns = learning_service.get_learned_patterns(carrier, [])
            insights['carrier_specific'] = carrier_patterns
        
        return jsonify(insights)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get insights: {str(e)}'
        }), 500

@app.route('/v1/intelligence', methods=['GET'])
def get_strategy_intelligence():
    """Get comprehensive strategy intelligence and recommendations"""
    try:
        carrier = request.args.get('carrier')
        strategies = request.args.getlist('strategy')  # Can pass multiple ?strategy=X&strategy=Y
        
        if not carrier:
            return jsonify({
                'success': False,
                'error': 'carrier parameter required'
            }), 400
        
        if not strategies:
            strategies = ['steep_on_waste', 'full_fence_scope', 'O&P']  # Default strategies
        
        # Get comprehensive intelligence
        intelligence = enhanced_learning.get_comprehensive_intelligence(carrier, strategies)
        
        return jsonify({
            'success': True,
            'intelligence': intelligence,
            'note': 'These are recommendations based on historical data, not mandatory rules'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get intelligence: {str(e)}'
        }), 500

@app.route('/v1/pricelists', methods=['GET'])
def list_pricelists():
    """Get all available pricelists"""
    try:
        region = request.args.get('region', 'TX')
        pricelists = pricelist_manager.list_available_pricelists(region)
        latest = pricelist_manager.get_latest_pricelist(region)
        
        return jsonify({
            'success': True,
            'pricelists': pricelists,
            'latest_pricelist': latest,
            'region': region
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get pricelists: {str(e)}'
        }), 500

@app.route('/v1/pricelists/<pricelist_code>', methods=['GET'])
def get_pricelist_info(pricelist_code):
    """Get information about a specific pricelist"""
    try:
        info = pricelist_manager.get_pricelist_info(pricelist_code)
        
        if not info:
            return jsonify({
                'success': False,
                'error': f'Pricelist {pricelist_code} not found'
            }), 404
        
        return jsonify({
            'success': True,
            'pricelist': info
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get pricelist info: {str(e)}'
        }), 500

@app.route('/v1/projects/<int:project_id>/pricelists', methods=['GET'])
def get_project_pricelist_history(project_id):
    """Get pricelist usage history for a project"""
    try:
        history = pricelist_manager.get_project_pricelist_history(project_id)
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'pricelist_history': history
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get pricelist history: {str(e)}'
        }), 500

@app.route('/v1/pricelists', methods=['POST'])
def register_pricelist():
    """Register a new pricelist"""
    try:
        data = request.get_json()
        required_fields = ['code', 'date']
        
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        pricelist_manager.register_available_pricelist(
            code=data['code'],
            date=data['date'],
            region=data.get('region', 'TX'),
            description=data.get('description'),
            sheet_tab=data.get('sheet_tab')
        )
        
        return jsonify({
            'success': True,
            'message': f'Pricelist {data["code"]} registered successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to register pricelist: {str(e)}'
        }), 500

def parse_supplement_output(output: str) -> tuple:
    """Parse supplement generation output for key data"""
    total_rcv = "Unknown"
    trade_count = 0
    strategies_used = []
    
    for line in output.split('\n'):
        # Extract RCV total
        if 'RCV Total:' in line:
            total_rcv = line.split('RCV Total:')[1].strip()
        
        # Extract trade count
        elif 'Cards:' in line:
            try:
                trade_count = int(line.split('Cards:')[1].split()[0])
            except:
                pass
        
        # Extract strategies from output (looking for F9 mentions, etc.)
        elif any(keyword in line.lower() for keyword in ['steep', 'fence', 'o&p', 'f9']):
            if 'steep' in line.lower():
                strategies_used.append('steep_on_waste')
            if 'fence' in line.lower():
                strategies_used.append('full_fence_scope')
            if 'o&p' in line.lower():
                strategies_used.append('O&P')
    
    # Remove duplicates
    strategies_used = list(set(strategies_used))
    
    return total_rcv, trade_count, strategies_used

def parse_amount(amount_str: str) -> float:
    """Parse dollar amount string to float"""
    if not amount_str or amount_str == "Unknown":
        return 0.0
    
    # Remove currency symbols and commas
    cleaned = re.sub(r'[$,\s]', '', str(amount_str))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

@app.route('/v1/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'pdf_generator_path': PDF_GENERATOR_PATH,
        'python_bin_exists': os.path.exists(PYTHON_BIN),
        'generate_script_exists': os.path.exists(GENERATE_SCRIPT)
    })

if __name__ == '__main__':
    print(f"Starting Sup API server...")
    print(f"PDF Generator: {PDF_GENERATOR_PATH}")
    print(f"Python Binary: {PYTHON_BIN}")
    print(f"Generate Script: {GENERATE_SCRIPT}")
    
    app.run(host='0.0.0.0', port=8090, debug=True)