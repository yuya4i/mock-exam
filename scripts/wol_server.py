#!/usr/bin/env python3
"""Tiny web trigger to wake the GPU PC from a phone (stdlib only).

Runs on the always-on node (pi-calc). Open the page on your phone and
tap a button; it fires a Wake-on-LAN magic packet at the GPU PC. No
pip install — pure ``http.server`` + the shared ``wol`` core.

Config (env, typically via the systemd EnvironmentFile):
    GPU_MAC        target MAC (required), e.g. 2C-FD-A1-DE-74-DD
    GPU_BROADCAST  subnet broadcast (default 255.255.255.255),
                   recommended 192.168.10.255
    WOL_BIND       listen address (default 0.0.0.0)
    WOL_PORT       listen port (default 8787)
    WOL_TOKEN      optional shared secret. When set, /wake requires
                   ?token=<value> (or X-Token header). The index page
                   passes through whatever ?token= you opened it with,
                   so bookmarking http://host:8787/?token=XXX on your
                   phone makes the button "just work" while keeping
                   random tailnet/LAN peers out.

Endpoints:
    GET  /            mobile-friendly page with a Wake button
    GET|POST /wake    send the magic packet → JSON {ok, mac, broadcast}
    GET  /health      {status:"ok"} (no token required)

Security model: this only emits a LAN broadcast that powers a machine
ON. There is no data and nothing destructive. On a trusted LAN / tailnet
the default (no token) is fine; set WOL_TOKEN if the port is reachable
by parties you don't trust.
"""
from __future__ import annotations

import hmac
import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wol import send_wol  # noqa: E402

GPU_MAC       = os.getenv("GPU_MAC", "")
GPU_BROADCAST = os.getenv("GPU_BROADCAST", "255.255.255.255")
WOL_BIND      = os.getenv("WOL_BIND", "0.0.0.0")
WOL_PORT      = int(os.getenv("WOL_PORT", "8787"))
WOL_TOKEN     = os.getenv("WOL_TOKEN", "")

PAGE = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPU-PC を起こす</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; min-height:100vh; display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:24px;
    font-family:-apple-system,'Hiragino Sans','Segoe UI',sans-serif;
    background:#0b1220; color:#f1f5f9; }}
  h1 {{ font-size:18px; font-weight:600; margin:0; color:#94a3b8; }}
  button {{ font-size:22px; font-weight:700; padding:22px 40px; border:none;
    border-radius:18px; color:#fff; cursor:pointer;
    background:linear-gradient(135deg,#6366f1,#5256e8);
    box-shadow:0 8px 30px rgba(99,102,241,.45); -webkit-tap-highlight-color:transparent; }}
  button:active {{ transform:translateY(2px); }}
  button:disabled {{ opacity:.5; }}
  #msg {{ font-size:14px; min-height:1.4em; color:#94a3b8; text-align:center; padding:0 20px; }}
  .ok {{ color:#4ade80; }} .err {{ color:#f87171; }}
  .mac {{ font-size:12px; color:#64748b; }}
</style></head><body>
  <h1>GPU-PC Wake-on-LAN</h1>
  <button id="b" onclick="wake()">⚡ 起こす</button>
  <div id="msg"></div>
  <div class="mac">target: {mac} via {bcast}</div>
<script>
  const token = new URLSearchParams(location.search).get('token') || '';
  async function wake() {{
    const b = document.getElementById('b'), m = document.getElementById('msg');
    b.disabled = true; m.className=''; m.textContent = '送信中…';
    try {{
      const u = '/wake' + (token ? ('?token=' + encodeURIComponent(token)) : '');
      const r = await fetch(u, {{ method:'POST' }});
      const d = await r.json();
      if (r.ok && d.ok) {{ m.className='ok'; m.textContent = '✅ magic packet 送信した。起きるまで10〜30秒待ってね'; }}
      else {{ m.className='err'; m.textContent = '⚠ ' + (d.error || ('HTTP ' + r.status)); }}
    }} catch (e) {{ m.className='err'; m.textContent = '⚠ ' + e; }}
    finally {{ setTimeout(()=>{{ b.disabled=false; }}, 3000); }}
  }}
</script></body></html>"""


def _token_ok(parsed_qs: dict, headers) -> bool:
    if not WOL_TOKEN:
        return True
    supplied = (parsed_qs.get("token", [""])[0]) or headers.get("X-Token", "")
    return hmac.compare_digest(supplied, WOL_TOKEN)


class Handler(BaseHTTPRequestHandler):
    server_version = "quizgpu-wol/1.0"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"status": "ok", "mac_configured": bool(GPU_MAC)})
        if path == "/":
            page = PAGE.format(mac=html.escape(GPU_MAC or "(未設定)"),
                               bcast=html.escape(GPU_BROADCAST))
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path == "/wake":
            return self._handle_wake()
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path == "/wake":
            return self._handle_wake()
        return self._json(404, {"error": "not found"})

    def _handle_wake(self):
        qs = parse_qs(urlparse(self.path).query)
        if not _token_ok(qs, self.headers):
            return self._json(403, {"ok": False, "error": "token が不正です"})
        if not GPU_MAC:
            return self._json(500, {"ok": False, "error": "GPU_MAC が未設定です"})
        try:
            send_wol(GPU_MAC, GPU_BROADCAST)
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "error": str(e)})
        return self._json(200, {"ok": True, "mac": GPU_MAC, "broadcast": GPU_BROADCAST})

    def log_message(self, fmt, *args):  # quieter, single-line
        sys.stderr.write(f"[wol-server] {self.address_string()} {fmt % args}\n")


def main() -> int:
    srv = ThreadingHTTPServer((WOL_BIND, WOL_PORT), Handler)
    print(f"[wol-server] listening on {WOL_BIND}:{WOL_PORT} "
          f"target={GPU_MAC or '(未設定)'} bcast={GPU_BROADCAST} "
          f"token={'on' if WOL_TOKEN else 'off'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
