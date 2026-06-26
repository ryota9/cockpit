#!/usr/bin/env python3
"""Cockpit local server — 1-click approve in the browser (Python standard library only, zero deps).

Browser buttons ([✅ Approve] [🗑 Reject] [Done] [✅ Complete phase]) POST here
  -> call the deterministic adapter (cockpit.py) -> update state.json + regenerate snapshot/dashboard
  -> 303 redirect back to the same tab (?pg=).
state.json stays the single source of truth (ADR-0006). No LLM is involved (the core is deterministic).
Only approval-side actions are exposed to the browser = the HITL gate (the agent's `propose` is CLI-only).

Run:  python3 serve.py [port]   or   python3 cockpit.py serve [port]
      -> http://127.0.0.1:8765  (Ctrl+C to stop)
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cockpit

# Only actions a human may take from the browser (the agent's propose is NOT here = HITL gate).
ACTIONS = {
    "/approve": lambda f: cockpit.approve(f["tid"][0]),
    "/reject": lambda f: cockpit.reject(f["tid"][0]),
    "/set-status": lambda f: cockpit.set_status(f["tid"][0], f["status"][0]),
    "/set-phase": lambda f: cockpit.set_phase(f["pid"][0], f["idx"][0], f["status"][0]),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        html = cockpit.render_dashboard(cockpit.load_state(), served=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            ACTIONS[path](form)   # the deterministic adapter does save_state + emit_snapshot
        except (KeyError, ValueError, IndexError) as exc:
            print(f"! {path}: {exc}")
        pg = "approve" if path in ("/approve", "/reject") else "projects"   # return to the right tab
        self.send_response(303)
        self.send_header("Location", f"/?pg={pg}")
        self.end_headers()

    def log_message(self, *args):   # keep the console quiet
        pass


def run(port: int = 8765):
    print(f"🛰  Cockpit serving at http://127.0.0.1:{port}   (Ctrl+C to stop)")
    print("   Clicking [✅ Approve] calls the deterministic adapter and reaches the agent's snapshot inbox (the HITL loop).")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
