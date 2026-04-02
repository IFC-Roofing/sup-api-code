#!/usr/bin/env python3
"""Test AI connectivity"""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

print("Testing AI connectivity...")

try:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    print("Making simple AI call...")
    response = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello, can you respond with just 'AI working'?"}]
    )
    
    print(f"✓ AI Response: {response.content[0].text}")
    
except Exception as e:
    print(f"❌ AI Error: {e}")
    import traceback
    traceback.print_exc()