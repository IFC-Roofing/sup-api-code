#!/usr/bin/env python3
"""
Xactimate Computer Use Agent
Uses Claude's computer use API to drive Xactimate on Windows via the click_server.py bridge.

Architecture:
  - This script runs in WSL
  - click_server.py runs on Windows (python.exe), listens on port 9877
  - All screenshots and mouse/keyboard actions go through the HTTP bridge

Usage:
  python3 xact_agent.py "Add line item RFG STEEP with quantity 24.5 SQ"

Environment:
  CLICK_SERVER_HOST — Windows host IP from WSL (auto-detected if not set)
  CLICK_SERVER_PORT — default 9877
  ANTHROPIC_API_KEY — required
"""

import anthropic
import base64
import json
import sys
import time
import os
import subprocess
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/.openclaw/workspace/.env'), override=True)

client = anthropic.Anthropic()

# Model config
MODEL = "claude-sonnet-4-20250514"
BETA_FLAG = "computer-use-2025-01-24"
TOOL_VERSION = "computer_20250124"


def get_windows_host():
    """Auto-detect the Windows host IP from WSL via /etc/resolv.conf."""
    host = os.environ.get('CLICK_SERVER_HOST')
    if host:
        return host
    try:
        with open('/etc/resolv.conf') as f:
            for line in f:
                if line.startswith('nameserver'):
                    return line.split()[1].strip()
    except Exception:
        pass
    return 'localhost'


SERVER_HOST = get_windows_host()
SERVER_PORT = int(os.environ.get('CLICK_SERVER_PORT', '9877'))
SERVER_BASE = f'http://{SERVER_HOST}:{SERVER_PORT}'


def server_get(path):
    """GET request to click server, return response body as string."""
    url = SERVER_BASE + path
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode()


def server_post(body: dict):
    """POST action to click server, return response body as string."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        SERVER_BASE + '/',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def check_server():
    """Verify the click server is reachable."""
    try:
        resp = server_get('/ping')
        if resp == 'pong':
            return True
    except Exception as e:
        print(f"❌ Click server not reachable at {SERVER_BASE}: {e}")
        print("   Make sure click_server.py is running on Windows.")
    return False


def get_screen_size():
    """Get Windows screen dimensions from the click server."""
    try:
        resp = server_get('/screen_size')
        w, h = resp.strip().split('x')
        return int(w), int(h)
    except Exception:
        return 1920, 1080  # fallback


def take_screenshot():
    """Capture Windows screen via click server, return base64 PNG."""
    return server_get('/screenshot').strip()


def execute_action(action):
    """
    Execute a computer use action via the click server.
    Returns base64 screenshot for screenshot/zoom actions, else None.
    """
    action_type = action.get("action")

    if action_type == "screenshot":
        return take_screenshot()

    elif action_type == "zoom":
        # Capture full screenshot then crop region around the coordinate
        x, y = action["coordinate"]
        zoom = action.get("zoom_level", 2)
        b64 = take_screenshot()
        # Crop using PIL in WSL
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            w, h = img.size
            half_w = int(w / zoom / 2)
            half_h = int(h / zoom / 2)
            x1 = max(0, x - half_w)
            y1 = max(0, y - half_h)
            x2 = min(w, x + half_w)
            y2 = min(h, y + half_h)
            cropped = img.crop((x1, y1, x2, y2))
            buf = io.BytesIO()
            cropped.save(buf, format='PNG')
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return b64  # fall back to full screenshot

    elif action_type == "mouse_move":
        x, y = action["coordinate"]
        server_post({"action": "move", "x": x, "y": y})

    elif action_type == "left_click":
        x, y = action["coordinate"]
        server_post({"action": "click", "x": x, "y": y})
        time.sleep(0.3)

    elif action_type == "left_click_drag":
        # Not natively supported yet — move to start, then click end
        sx, sy = action["startCoordinate"]
        ex, ey = action["coordinate"]
        server_post({"action": "move", "x": sx, "y": sy})
        time.sleep(0.1)
        server_post({"action": "click", "x": ex, "y": ey})

    elif action_type == "right_click":
        x, y = action["coordinate"]
        server_post({"action": "right_click", "x": x, "y": y})
        time.sleep(0.3)

    elif action_type == "double_click":
        x, y = action["coordinate"]
        server_post({"action": "double_click", "x": x, "y": y})
        time.sleep(0.3)

    elif action_type == "triple_click":
        x, y = action["coordinate"]
        server_post({"action": "triple_click", "x": x, "y": y})
        time.sleep(0.3)

    elif action_type == "type":
        text = action["text"]
        server_post({"action": "type", "text": text})
        time.sleep(0.2)

    elif action_type == "key":
        key = action.get("key", "")
        if not key:
            print("  [!] Empty key action, skipping")
            return None
        # Normalize key names to match VK_MAP in click_server
        key_map = {
            "Return": "return", "Tab": "tab", "Escape": "escape",
            "Backspace": "backspace", "Delete": "delete", "space": "space",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "Home": "home", "End": "end", "Page_Up": "pageup", "Page_Down": "pagedown",
            "super": "win", "ctrl": "ctrl", "alt": "alt", "shift": "shift",
        }
        normalized = "+".join(key_map.get(p.strip(), p.strip().lower()) for p in key.split("+"))
        server_post({"action": "key", "key": normalized})
        time.sleep(0.2)

    elif action_type == "scroll":
        x, y = action["coordinate"]
        direction = action["direction"]
        amount = action.get("amount", 3)
        server_post({"action": "scroll", "x": x, "y": y, "direction": direction, "amount": amount})
        time.sleep(0.3)

    elif action_type == "wait":
        time.sleep(action.get("duration", 1))

    else:
        print(f"  [!] Unknown action: {action_type}")

    return None


def run_agent(task, max_steps=50):
    """Run the computer use agent loop."""
    print(f"\n🏗️  Sup Xactimate Agent")
    print(f"📋 Task: {task}")
    print(f"🤖 Model: {MODEL}")
    print(f"🌐 Click server: {SERVER_BASE}")

    if not check_server():
        sys.exit(1)

    # Get actual screen dimensions
    display_width, display_height = get_screen_size()
    print(f"🖥️  Screen: {display_width}x{display_height}")
    print(f"{'='*60}\n")

    # Initial screenshot
    print("📸 Taking initial screenshot...")
    screenshot_b64 = take_screenshot()

    system_prompt = f"""You are controlling a Windows machine ({display_width}x{display_height}) running Xactimate.

KEY FACTS:
- You are seeing the Windows desktop directly — no VM or emulation layer.
- Xactimate is a web-based desktop app (ClickOnce). It may be on the taskbar or already open.
- After EVERY action, take a screenshot to verify the result before proceeding.
- Be patient — Xactimate can be slow. Wait 1-2 seconds after clicks on buttons/menus.
- If a click doesn't register, try again with slightly adjusted coordinates.
- Use the zoom action to inspect small or dense UI areas before clicking.
- For text input, use the 'type' action.
- Report what you see and what you're doing at each step."""

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Here is the current screen. Your task: {task}"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
            ],
        }
    ]

    tools = [
        {
            "type": TOOL_VERSION,
            "name": "computer",
            "display_width_px": display_width,
            "display_height_px": display_height,
            "display_number": 1,
        }
    ]

    for step in range(max_steps):
        print(f"\n--- Step {step + 1}/{max_steps} ---")

        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
            betas=[BETA_FLAG],
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Print text blocks
        for block in assistant_content:
            if hasattr(block, "text") and block.text:
                print(f"  💭 {block.text}")

        # Check if done
        if response.stop_reason == "end_turn":
            print(f"\n{'='*60}")
            print("✅ Task complete!")
            return True

        # Process tool calls
        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue

            tool_input = block.input
            action_type = tool_input.get("action", "unknown")
            coord = tool_input.get("coordinate", "")

            if action_type == "screenshot":
                print("  📸 Taking screenshot...")
            elif action_type == "zoom":
                print(f"  🔍 Zooming at {coord}")
            elif action_type in ("left_click", "right_click", "double_click", "triple_click"):
                print(f"  🖱️  {action_type} at {coord}")
            elif action_type == "type":
                print(f"  ⌨️  Typing: {tool_input.get('text', '')[:60]}")
            elif action_type == "key":
                print(f"  ⌨️  Key: {tool_input.get('key', '')}")
            elif action_type == "scroll":
                print(f"  📜 Scroll {tool_input.get('direction', '')} at {coord}")
            else:
                print(f"  🔧 {action_type} {coord}")

            result = execute_action(tool_input)

            if action_type in ("screenshot", "zoom") and result:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": [{
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": result},
                    }],
                })
            else:
                time.sleep(0.5)
                new_screenshot = take_screenshot()
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": [{
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": new_screenshot},
                    }],
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            print("  ⚠️  No tool calls, ending.")
            break

    print(f"\n⚠️  Reached max steps ({max_steps})")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 xact_agent.py \"<task description>\"")
        print()
        print("Examples:")
        print('  python3 xact_agent.py "Open Xactimate and create a new project named SUP_TEST"')
        print('  python3 xact_agent.py "Add line item RFG STEEP with quantity 24.5 SQ"')
        print()
        print(f"Click server: {SERVER_BASE} (override with CLICK_SERVER_HOST env var)")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    run_agent(task)
