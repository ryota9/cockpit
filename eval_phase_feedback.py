#!/usr/bin/env python3
"""Phase-drift & handoff-feedback eval (verification-first · docs/drift-phase-and-feedback.md).

先にこの Eval を書き、cockpit.py / serve.py がこれを満たすよう実装する。data-agnostic・
純粋関数中心（正本 state.json / snapshot.md / dashboard.html は書かない＝一時ファイルに退避）。

① set-phase を UI ボタン化（王: Phase ドリフト対策）
  P1 adapter    : set_phase(pid, idx, done/todo) が対象 Phase の status だけ変える・validate 通過・往復（done↔todo）。
  P2 range/型   : idx 範囲外・不正 status は例外（決定論ガード）。
  P3 dashboard  : served=True の Journey に POST /set-phase の「✅ 完了」ボタン（pid+idx+status=done+pg=projects）。
                  完了済み Phase には「↺ todo」戻すボタン。served=False では出ない（HITL: サーバ経由のみ）。
  P4 視覚区別   : 完了 Phase=jstep done / 現在=jstep cur を描画（既存バッジ規約）。

② 「秘書に届きました」即時フィードバック（王: 押しても届かないモヤモヤ対策=軸1）
  F1 flash 表示 : render_dashboard(flash=...) が momentum の .msg 帯に受領文言を出す。
  F2 既定不変   : flash 無しでは受領文言が出ない（既定テーマ/レイアウト不変）。
  F3 文言定義   : cockpit.FLASH["received"] が「受信箱に届き」を含む（i18n を1箇所に集約・OSS汎用）。
  F4 serve 配線 : serve.ACK が /request-detail → "received"。redirect に msg を載せる（do_POST に msg= 配線）。
                  /set-phase も serve.ACTIONS にある（王ゲート操作＝serve 経由 OK・ADR-0006）。
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


def _state():
    return {"projects": [{
        "id": "p1", "name": "Proj One", "priority": "high",
        "north_star": "ship it", "done_def": "all phases done",
        "phases": [
            {"name": "設計", "goal": "decide", "status": "done"},
            {"name": "実装", "goal": "build", "status": "todo"},
            {"name": "検証", "goal": "verify", "status": "todo"},
        ],
        "tasks": [
            {"id": "t1", "desc": "手順未記入タスク", "status": "todo", "owner": "human",
             "created": "2026-07-10", "status_changed": "2026-07-10"},
        ],
        "milestones": [], "groups": [],
    }]}


def main():
    print("=== Phase-drift & Feedback Eval (verification-first) ===")

    # ---------- ① set-phase adapter（一時ファイルに退避して正本を汚さない） ----------
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        saved = {k: getattr(cockpit, k) for k in ("STATE", "BAK", "JOURNAL", "SNAP_MD", "DASH_HTML")}
        try:
            cockpit.STATE = d / "state.json"
            cockpit.BAK = d / "state.json.bak"
            cockpit.JOURNAL = d / "events.jsonl"
            cockpit.SNAP_MD = d / "snapshot.md"
            cockpit.DASH_HTML = d / "dashboard.html"
            cockpit.save_state(_state())

            cockpit.set_phase("p1", 1, "done")
            st = cockpit.load_state()
            phs = st["projects"][0]["phases"]
            check("P1 set-phase: 対象 Phase[1] のみ status=done",
                  phs[1]["status"] == "done" and phs[0]["status"] == "done" and phs[2]["status"] == "todo",
                  f"(statuses={[p['status'] for p in phs]})")
            check("P1 set-phase: validate 通過（台帳整合）", cockpit.validate(st) == [])

            cockpit.set_phase("p1", 1, "todo")     # 往復（↺ todo に戻す）
            phs = cockpit.load_state()["projects"][0]["phases"]
            check("P1 set-phase: done↔todo 往復可（Phase[1]→todo）", phs[1]["status"] == "todo")

            # P2 ガード
            for bad, why in [(("p1", 9, "done"), "idx 範囲外"),
                             (("p1", 0, "bogus"), "不正 status"),
                             (("nope", 0, "done"), "存在しない project")]:
                try:
                    cockpit.set_phase(*bad)
                    check(f"P2 ガード: {why} は例外", False, "(例外が出なかった)")
                except (ValueError, IndexError, KeyError):
                    check(f"P2 ガード: {why} は例外", True)
        finally:
            for k, v in saved.items():
                setattr(cockpit, k, v)

    # ---------- ①/② dashboard 描画（純粋・正本を書かない render_dashboard） ----------
    st = _state()
    Hs = cockpit.render_dashboard(st, served=True, active="projects")
    Hc = cockpit.render_dashboard(st, served=False, active="projects")

    check("P3 dashboard(served): POST /set-phase ボタンがある", 'action="/set-phase"' in Hs)
    # 現在 Phase(idx=1) を done にする「✅ 完了」ボタン：pid/idx/status=done/pg=projects の hidden が揃う
    form_ok = bool(re.search(
        r'action="/set-phase".*?name="pid"\s+value="p1".*?name="idx"\s+value="1".*?'
        r'name="status"\s+value="done".*?name="pg"\s+value="projects"', Hs, re.S))
    check("P3 dashboard(served): 現在 Phase の完了ボタンに pid+idx+status=done+pg=projects", form_ok)
    check("P3 dashboard(served): 完了済み Phase に「↺ todo」戻すボタン（status=todo の POST）",
          'value="todo"' in Hs and "↺" in Hs)
    check("P3 dashboard(served=False): Phase ボタンは出ない（HITL: サーバ経由のみ）",
          'action="/set-phase"' not in Hc)
    check("P4 視覚区別: 完了=jstep done / 現在=jstep cur が描画",
          'class="jstep done"' in Hs and 'class="jstep cur"' in Hs)

    # ---------- ② 受領フィードバック（flash → momentum .msg 帯） ----------
    check("F3 文言定義: cockpit.FLASH['received'] が受領文言（受信箱に届き）",
          "received" in getattr(cockpit, "FLASH", {}) and "受信箱に届き" in cockpit.FLASH.get("received", ""))
    flash_txt = cockpit.FLASH.get("received", "🕓 秘書の受信箱に届きました")
    Hf = cockpit.render_dashboard(st, served=True, active="now", flash=flash_txt)
    Hn = cockpit.render_dashboard(st, served=True, active="now")
    # momentum 帯（.msg）の中に受領文言が入る
    msg_has_flash = bool(re.search(r'class="msg[^"]*">[^<]*' + re.escape(flash_txt[:6]), Hf))
    check("F1 flash: momentum の .msg 帯に受領文言が出る", msg_has_flash, f"(found={flash_txt[:12]!r})")
    check("F2 既定不変: flash 無しでは受領文言が出ない", flash_txt not in Hn)

    # ---------- ② serve 配線 ----------
    import serve
    check("F4 serve.ACTIONS: /set-phase が human ゲートとして公開（ADR-0006）",
          "/set-phase" in serve.ACTIONS)
    check("F4 serve.ACTIONS: /request-detail が公開", "/request-detail" in serve.ACTIONS)
    ack = getattr(serve, "ACK", {})
    check("F4 serve.ACK: /request-detail → 'received'（押下→即受領文言）",
          ack.get("/request-detail") == "received")
    # do_POST が redirect に msg を載せる配線になっている（ソース確認・軸1）
    serve_src = Path(serve.__file__).read_text(encoding="utf-8")
    check("F4 serve.do_POST: redirect に msg= を載せる配線がある", "msg=" in serve_src and "ACK" in serve_src)

    print(f"\nPhase/Feedback Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    raise SystemExit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
