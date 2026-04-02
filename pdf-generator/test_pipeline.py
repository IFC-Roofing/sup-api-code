#!/usr/bin/env python3
"""Test script to debug pipeline issues"""

import sys
from pathlib import Path

# Add root to path for imports
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "parsers"))

print("Starting test...")

try:
    print("1. Importing data_pipeline...")
    from data_pipeline import run as pipeline_run
    print("✓ Import successful")
    
    print("2. Running pipeline for Rose Brock...")
    result = pipeline_run("Rose Brock")
    print(f"✓ Pipeline result keys: {list(result.keys())}")
    
    print("3. Test complete!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()