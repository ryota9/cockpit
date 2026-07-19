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

import importlib, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(cockpit.__file__)), "edu"))
try:
    import raven   # 教育係（edu/raven.py）。無くてもCockpit本体は動く
except Exception as _e:  # noqa: BLE001
    raven = None
    print(f"! raven unavailable: {_e}")
_COCKPIT_MTIME = os.path.getmtime(cockpit.__file__)


def _reload_if_changed() -> None:
    """開発利便: cockpit.py が変わったら自動リロード（サーバ再起動不要でCSS/コード反映）。
    ACTIONS/呼び出しは全て call-time に cockpit.X を引くのでリロード安全。"""
    global _COCKPIT_MTIME
    try:
        m = os.path.getmtime(cockpit.__file__)
    except OSError:
        return
    if m != _COCKPIT_MTIME:
        try:
            importlib.reload(cockpit)
            _COCKPIT_MTIME = m
        except Exception as exc:   # リロード失敗時は旧コードで動作継続（落とさない）
            print(f"! reload cockpit: {exc}")


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
    # ✅ 完了の確認（AI提案の"完了側"）。propose-done は CLI 専用＝ここに無い＝HITLゲート（approve と対称）。
    "/confirm-done": lambda f: cockpit.confirm_done(f["tid"][0]),
    "/reject-done": lambda f: cockpit.reject_done(f["tid"][0]),
    "/set-status": lambda f: cockpit.set_status(f["tid"][0], f["status"][0]),
    # 🅿 WIP管理（P2）: 駐機/再開はプロジェクトの動かし方の決定＝人間のボタン（HITL）
    "/set-mode": lambda f: cockpit.set_mode(f["pid"][0], f["mode"][0]),
    # 🚨 再交渉（P3）: 腐った約束を[直す/捨てる]の2択で片付ける（人間ボタン・楽観ロック付き）
    "/ms-defer": lambda f: cockpit.defer_milestone(f["pid"][0], f["name"][0], f["due"][0]),
    "/ms-drop": lambda f: cockpit.drop_milestone(f["pid"][0], f["name"][0], f["due"][0]),
    "/focus-extend": lambda f: cockpit.focus(f["pid"][0], 3),
    "/focus-clear": lambda f: cockpit.unfocus(f["pid"][0]),
    "/set-phase": lambda f: cockpit.set_phase(f["pid"][0], f["idx"][0], f["status"][0]),
    "/undo": lambda f: cockpit.undo(),
    "/request-detail": lambda f: cockpit.request_detail(f["tid"][0]),
    "/pr-posted": _pr_set_posted,
    "/pr-reject": _pr_reject,
    # 🌱 ブリーフ→種床（moc-0）。人間のボタン発＝直todo（design-hub-v2 F2）
    "/seed": lambda f: cockpit.seed(f["title"][0][:200], f.get("src", [""])[0][:120]),
}

# 押下→即「受け取った」を返す軸1（drift-phase-and-feedback.md §4）。AIに仕事を渡す系だけ受領文言を載せる
# （承認/却下など人間完結アクションは対象外）。値は cockpit.FLASH のキー＝redirect の ?msg=<key> で
# dashboard の momentum 帯に出る。処理自体は非同期のまま（軸2の自動処理は別）。
ACK = {
    "/request-detail": "received",   # ✍️手順依頼 → 秘書の受信箱へ（次の点検で処理）
}


_SERVE_MTIME = os.path.getmtime(__file__)


class Handler(BaseHTTPRequestHandler):
    def _reexec_if_serve_changed(self) -> bool:
        """serve.py 自身が変わったらプロセスを入れ替える。cockpit.py はリロードで追従できるが、
        serve.py（ACTIONS等）は再起動しないと**新ボタンが黙って空振りする**（2026-07-12 実事故:
        王が再交渉ボタンを押しても旧プロセスに /ms-defer が無く無反応だった）。
        PEP446でリスンソケットはCLOEXEC＝exec後に解放されるので同ポートで安全に再bindできる。"""
        try:
            if os.path.getmtime(__file__) == _SERVE_MTIME:
                return False
        except OSError:
            return False
        body = ("<meta http-equiv='refresh' content='1'>"
                "<p style='font-family:sans-serif'>🔄 serve.py が更新されたので再起動中… そのまま待てば戻ります</p>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
        self.wfile.flush()
        os.execv(sys.executable, [sys.executable, __file__] + sys.argv[1:])

    def do_GET(self):
        if self._reexec_if_serve_changed():
            return
        _reload_if_changed()   # cockpit.py の編集を再起動なしで反映（開発利便）
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
        if url.path == "/raven-explain":
            # 🐦‍⬛ Raven 解説ページ（採点結果の全文・読取専用）
            try:
                pid = parse_qs(url.query).get("id", [""])[0]
                body = raven.render_explanation_page(pid) if raven else "<h1>raven unavailable</h1>"
                self.send_response(200)
            except Exception as exc:  # noqa: BLE001
                body = f"<h1>explain error</h1><p>{exc}</p>"
                self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
            return
        q = parse_qs(url.query)
        pg = q.get("pg", ["now"])[0]   # open the tab the action returned to
        # 🕓 受領フィードバック（軸1）: 直前アクションが載せた ?msg=<key> を FLASH 文言に解決して帯に出す。
        # 未知キーは "" ＝ no-op（既定表示のまま）。文言は cockpit 側の辞書由来なので注入面も安全。
        flash = cockpit.FLASH.get(q.get("msg", [""])[0], "")
        html = cockpit.render_dashboard(cockpit.load_state(), served=True, active=pg, flash=flash)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")   # always serve fresh (no stale browser cache)
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        # 🐦‍⬛ Raven（教育係）: 独自リダイレクト先を持つので汎用ACTIONSの手前で処理
        if path in ("/raven-submit", "/raven-next", "/raven-goto") and raven:
            loc = "/?pg=now"
            try:
                if path == "/raven-submit":
                    pid = form["pid"][0]
                    raven.grade(pid, form.get("answer", [""])[0])   # 即時採点（claude -p）
                    loc = f"/raven-explain?id={pid}"                # 採点後は解説ページへ
                elif path == "/raven-next":
                    p = raven.generate()                            # 今日の問題を出す
                    loc = "/?pg=now" if "error" not in p else "/?pg=learn"
                elif path == "/raven-goto":
                    loc = "/?pg=now"                                # 差し替え問題はNowに出ている
            except Exception as exc:  # noqa: BLE001
                print(f"! {path}: {exc}")
            self.send_response(303)
            self.send_header("Location", loc)
            self.end_headers()
            return
        ok = False
        try:
            ACTIONS[path](form)   # the deterministic adapter does save_state + emit_snapshot
        except (KeyError, ValueError, IndexError) as exc:
            print(f"! {path}: {exc}")
        else:
            ok = True
            # 状態が変わった → 安いフィード（drift/pr/brief/surprises）を再生成して Now を最新に保つ。
            # 失敗してもユーザーの操作結果（redirect）は返す（フィードは装飾・非致命）。
            try:
                cockpit.refresh_feeds()
            except Exception as exc:
                print(f"! refresh_feeds: {exc}")
        pg = form.get("pg", ["now"])[0]   # each button says which tab to return to (stay put, no jump)
        loc = f"/?pg={pg}"
        code = ACK.get(path) if ok else None   # 成功時だけ受領文言を載せる（軸1: 押下→即「届いた」）
        if code:
            loc += f"&msg={code}"
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def log_message(self, *args):   # keep the console quiet
        pass


def run(port: int = 8765):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno == 48:   # Address already in use = 既に誰かが動かしている（二重起動）
            print(f"🛰  Cockpit はもう動いています → http://127.0.0.1:{port} を開くだけでOK")
            print(f"   自分のターミナルで持ち直したい場合:  lsof -ti :{port} | xargs kill  してから再実行")
            print(f"   別ポートで並行起動する場合:          python3 serve.py {port + 1}")
            return
        raise
    print(f"🛰  Cockpit serving at http://127.0.0.1:{port}   (Ctrl+C to stop)")
    print("   Clicking [✅ Approve] calls the deterministic adapter and reaches the agent's snapshot inbox (the HITL loop).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
