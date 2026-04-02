import http.server
import json
import ctypes
import time
import base64
import io

# Set DPI awareness BEFORE any other user32 calls
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

u = ctypes.windll.user32

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', ctypes.c_ushort), ('wScan', ctypes.c_ushort),
                 ('dwFlags', ctypes.c_ulong), ('time', ctypes.c_ulong),
                 ('dwExtraInfo', ULONG_PTR)]

class INPUT_UNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [('type', ctypes.c_ulong), ('union', INPUT_UNION)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', ctypes.c_long), ('dy', ctypes.c_long),
                 ('mouseData', ctypes.c_ulong), ('dwFlags', ctypes.c_ulong),
                 ('time', ctypes.c_ulong), ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))]

class INPUT_MOUSE_UNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT)]

class MINPUT(ctypes.Structure):
    _fields_ = [('type', ctypes.c_ulong), ('union', INPUT_MOUSE_UNION)]


def take_screenshot():
    """Capture full screen using PIL ImageGrab, return base64 PNG."""
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def do_move(x, y):
    screen_w = u.GetSystemMetrics(0)
    screen_h = u.GetSystemMetrics(1)
    abs_x = int(x * 65535 / screen_w)
    abs_y = int(y * 65535 / screen_h)
    inp = MINPUT()
    inp.type = 0
    inp.union.mi.dx = abs_x
    inp.union.mi.dy = abs_y
    inp.union.mi.dwFlags = 0x0001 | 0x8000
    u.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(MINPUT))


def do_click(x, y):
    screen_w = u.GetSystemMetrics(0)
    screen_h = u.GetSystemMetrics(1)
    abs_x = int(x * 65535 / screen_w)
    abs_y = int(y * 65535 / screen_h)

    inp = MINPUT()
    inp.type = 0
    inp.union.mi.dx = abs_x
    inp.union.mi.dy = abs_y
    inp.union.mi.dwFlags = 0x0001 | 0x8000
    u.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(MINPUT))
    time.sleep(0.05)

    inp2 = MINPUT()
    inp2.type = 0
    inp2.union.mi.dx = abs_x
    inp2.union.mi.dy = abs_y
    inp2.union.mi.dwFlags = 0x0002 | 0x8000
    u.SendInput(1, ctypes.pointer(inp2), ctypes.sizeof(MINPUT))
    time.sleep(0.03)

    inp3 = MINPUT()
    inp3.type = 0
    inp3.union.mi.dx = abs_x
    inp3.union.mi.dy = abs_y
    inp3.union.mi.dwFlags = 0x0004 | 0x8000
    u.SendInput(1, ctypes.pointer(inp3), ctypes.sizeof(MINPUT))


VK_MAP = {
    'return': 0x0D, 'enter': 0x0D, 'tab': 0x09, 'escape': 0x1B,
    'backspace': 0x08, 'delete': 0x2E, 'space': 0x20,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
    'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
    'f11': 0x7A, 'f12': 0x7B,
    'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B,
}


def send_unicode_char(ch):
    inp = INPUT()
    inp.type = 1
    inp.union.ki.wScan = ord(ch)
    inp.union.ki.dwFlags = 0x0004
    u.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(INPUT))
    time.sleep(0.01)
    inp.union.ki.dwFlags = 0x0004 | 0x0002
    u.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(INPUT))
    time.sleep(0.01)


def press_key(key_str):
    keys = [k.strip().lower() for k in key_str.split('+')]
    held = []
    for k in keys:
        vk = VK_MAP.get(k, 0)
        if vk:
            u.keybd_event(vk, 0, 0, 0)
            held.append(vk)
        else:
            for ch in k:
                send_unicode_char(ch)
    time.sleep(0.05)
    for vk in reversed(held):
        u.keybd_event(vk, 0, 0x0002, 0)


class ClickHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/screenshot':
            try:
                data = take_screenshot()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(data.encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(str(e).encode())
        elif self.path == '/screen_size':
            w = u.GetSystemMetrics(0)
            h = u.GetSystemMetrics(1)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f'{w}x{h}'.encode())
        elif self.path == '/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'pong')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        action = body.get('action', 'click')
        x, y = body.get('x', 0), body.get('y', 0)
        resp = 'ok'

        if action == 'click':
            do_click(x, y)
            resp = f'clicked {x},{y}'
        elif action == 'double_click':
            do_click(x, y)
            time.sleep(0.05)
            do_click(x, y)
            resp = 'double_clicked'
        elif action == 'right_click':
            screen_w = u.GetSystemMetrics(0)
            screen_h = u.GetSystemMetrics(1)
            u.SetCursorPos(x, y)
            time.sleep(0.05)
            u.mouse_event(0x0008, 0, 0, 0, 0)
            time.sleep(0.03)
            u.mouse_event(0x0010, 0, 0, 0, 0)
            resp = 'right_clicked'
        elif action == 'triple_click':
            do_click(x, y)
            time.sleep(0.05)
            do_click(x, y)
            time.sleep(0.05)
            do_click(x, y)
            resp = 'triple_clicked'
        elif action == 'type':
            text = body.get('text', '')
            for ch in text:
                send_unicode_char(ch)
            resp = f'typed {len(text)} chars'
        elif action == 'key':
            press_key(body.get('key', ''))
            resp = 'key_pressed'
        elif action == 'scroll':
            u.SetCursorPos(x, y)
            time.sleep(0.05)
            amount = body.get('amount', 3)
            direction = body.get('direction', 'down')
            delta = 120 * amount if direction == 'up' else -120 * amount
            u.mouse_event(0x0800, 0, 0, delta, 0)
            resp = 'scrolled'
        elif action == 'move':
            do_move(x, y)
            resp = 'moved'
        elif action == 'ping':
            resp = 'pong'

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(resp.encode())

    def log_message(self, fmt, *args):
        pass  # quiet


print('Click server starting on port 9877...')
server = http.server.HTTPServer(('0.0.0.0', 9877), ClickHandler)
print('Ready! Listening on http://0.0.0.0:9877')
print('Endpoints: GET /screenshot  GET /screen_size  GET /ping  POST / (actions)')
server.serve_forever()
