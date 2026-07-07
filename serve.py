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

def _guard_fname(fname: str) -> str:
    if "/" in fname or "\\" in fname or fname.startswith("."):   # path traversal guard
        raise ValueError(f"bad filename: {fname}")
    return fname


def _pr_adapter(op: str, fname: str) -> None:
    """Hub feed action (F1): run the deterministic pr feed adapter, then refresh feeds.
    Cockpit stays a broker — it never owns the PR queue's state (design-hub-v2 §2.1)."""
    import subprocess
    script = cockpit.FEEDS_DIR / "pr_feed.py"
    if not script.exists():
        raise KeyError("pr feed not configured")
    r = subprocess.run([sys.executable, str(script), op, _guard_fname(fname)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or f"{op} failed")


def _pr_set_posted(form):
    _pr_adapter("set-posted", form["file"][0])


def _pr_reject(form):
    """不採用: 正本のstatusをrejectedに更新し、広報官（feedのproject）へ
    「次の記事を作成」タスクを agent inbox に置く（人間ボタン=HITL）。"""
    fname = _guard_fname(form["file"][0])
    _pr_adapter("reject", fname)
    feed = cockpit._load_feed("pr") or {}
    pid = feed.get("project")
    if pid:
        cockpit.assign(pid, f"広報: {fname} は不採用。却下を踏まえて次の記事案を作成する")


# Only actions a human may take from the browser (the agent's propose is NOT here = HITL gate).
ACTIONS = {
    "/approve": lambda f: cockpit.approve(f["tid"][0]),
    "/reject": lambda f: cockpit.reject(f["tid"][0]),
    "/set-status": lambda f: cockpit.set_status(f["tid"][0], f["status"][0]),
    "/set-phase": lambda f: cockpit.set_phase(f["pid"][0], f["idx"][0], f["status"][0]),
    "/undo": lambda f: cockpit.undo(),
    "/request-detail": lambda f: cockpit.request_detail(f["tid"][0]),
    "/pr-posted": _pr_set_posted,
    "/pr-reject": _pr_reject,
    # 🌱 ブリーフ→種床（moc-0）。人間のボタン発＝直todo（design-hub-v2 F2）
    "/seed": lambda f: cockpit.seed(f["title"][0][:200], f.get("src", [""])[0][:120]),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/pr-preview":
            # 👁 原稿プレビュー（md→整形HTML・読取専用。コピー範囲はユーザーが選ぶ）
            import subprocess
            try:
                fname = _guard_fname(parse_qs(url.query).get("file", [""])[0])
                script = cockpit.FEEDS_DIR / "pr_feed.py"
                r = subprocess.run([sys.executable, str(script), "render", fname],
                                   capture_output=True, text=True, timeout=30)
                if r.returncode != 0:
                    raise ValueError(r.stderr.strip())
                body = r.stdout
                self.send_response(200)
            except Exception as exc:
                body = f"<h1>preview error</h1><p>{exc}</p>"
                self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            return
        pg = parse_qs(url.query).get("pg", ["now"])[0]   # open the tab the action returned to
        html = cockpit.render_dashboard(cockpit.load_state(), served=True, active=pg)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")   # always serve fresh (no stale browser cache)
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
        pg = form.get("pg", ["now"])[0]   # each button says which tab to return to (stay put, no jump)
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
