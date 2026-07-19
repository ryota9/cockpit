#!/usr/bin/env python3
"""P2 Active/Parked（WIPの明示）の Eval — 実装より先に書く（検証ファースト）。

背景（consult-2026-07-12-progress-comprehension.md P2）:
14プロジェクトが全部同じ大きさで並ぶ「壁」が状況理解を殺す。人間の並行限界（WIP 2-3）を
超えた表示は「全部見える＝何も見えない」。mode は人間だけが振る（HITL）。

不変条件:
  - mutate_set_mode: active/parked のみ受理・journalに刻印・不正値は拒否
  - 後方互換: mode 無し＝active 扱い（既存 state.json は挙動不変）
  - dashboard: parked はフルカードでなく1行に畳む・activeはフルカード
  - WIP: active数がmomentumに出る・active>3 で警告
  - Focus(now): parked は due があっても出さない（意図的な眠り＝警報しない）
  - snapshot: 受信箱で parked のタスクは active の後ろ＋🅿マーカー
  - pulse: parked は 😴休眠リストに出さない（ダークコックピット: 意図した状態に警報を鳴らさない）
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


today = date.today().isoformat()
soon = (date.today() + timedelta(days=1)).isoformat()

STATE = {"projects": [
    {"id": "p-a", "name": "アクティブ甲", "priority": "high", "north_star": "g", "done_def": "d",
     "phases": [{"name": "P0", "goal": "", "status": "todo"}], "milestones": [],
     "tasks": [{"id": "t1", "desc": "仕事1", "status": "todo", "owner": "ai"}]},
    {"id": "p-b", "name": "アクティブ乙", "priority": "mid", "north_star": "g", "done_def": "d",
     "phases": [], "milestones": [{"name": "m", "due": soon, "status": "todo"}],
     "tasks": [{"id": "t2", "desc": "仕事2", "status": "todo", "owner": "ai"}]},
    {"id": "p-c", "name": "駐機中丙", "priority": "mid", "north_star": "g", "done_def": "d",
     "mode": "parked",
     "phases": [], "milestones": [{"name": "m", "due": soon, "status": "todo"}],
     "tasks": [{"id": "t3", "desc": "仕事3", "status": "todo", "owner": "ai"}]},
]}


def main():
    print("=== P2 Eval (active/parked) ===")

    # --- mutator ---
    st = copy.deepcopy(STATE)
    t = cockpit.mutate_set_mode(st, "p-a", "parked")
    check("mutate: mode=parked が入る", t.get("mode") == "parked")
    cockpit.mutate_set_mode(st, "p-a", "active")
    check("mutate: active に戻すと mode キーは消える（無印=active の正規形）",
          "mode" not in cockpit._find_project(st, "p-a"))
    try:
        cockpit.mutate_set_mode(st, "p-a", "sleeping")
        check("mutate: 不正値は拒否", False)
    except ValueError:
        check("mutate: 不正値は拒否", True)
    try:
        cockpit.mutate_set_mode(st, "p-zzz", "parked")
        check("mutate: 未知プロジェクトは拒否", False)
    except KeyError:
        check("mutate: 未知プロジェクトは拒否", True)

    # --- 判定ヘルパと後方互換 ---
    st = copy.deepcopy(STATE)
    check("is_parked: mode無し=active（後方互換）", not cockpit.is_parked(st["projects"][0]))
    check("is_parked: parked を判定", cockpit.is_parked(st["projects"][2]))

    # --- dashboard ---
    h = cockpit.render_dashboard(copy.deepcopy(STATE), served=True, active="now")
    check("dashboard: activeはフルカード（アクティブ甲）", 'アクティブ甲' in h and h.count('class="card') == 2,
          f"(cards={h.count('class=\"card')})")
    check("dashboard: parkedは1行(parkedrow)に畳む", 'class="parkedrow"' in h and '駐機中丙' in h)
    check("dashboard: parked行に[▶ 再開]ボタン（HITL・人間ボタン）", '/set-mode' in h)
    check("dashboard: momentumにWIP表示 (2 active / 1 parked)",
          '2</div><div class="lbl">active' in h.replace("\n", "") or 'active (WIP)' in h)
    check("Focus: parkedはdueが近くても出さない", '仕事3' not in h.split('pg-projects')[0])
    check("Focus: activeのdue近は出る", '仕事2' in h.split('pg-projects')[0])

    # WIP>3 警告
    big = copy.deepcopy(STATE)
    for i in range(3):
        p = copy.deepcopy(big["projects"][0])
        p["id"], p["name"] = f"p-x{i}", f"追加{i}"
        p["tasks"] = []
        big["projects"].append(p)
    hb = cockpit.render_dashboard(big, served=False, active="now")   # active=5
    check("WIP>3: 警告が出る", "WIP" in hb and ("超" in hb or "⚠" in hb))
    h2 = cockpit.render_dashboard(copy.deepcopy(STATE), served=False, active="now")
    check("WIP=2: 警告なし", "⚠ WIP" not in h2)

    # --- snapshot（受信箱の並び） ---
    md = cockpit.render_snapshot_md(cockpit.make_snapshot(copy.deepcopy(STATE)), copy.deepcopy(STATE))
    inbox = md.split("##", 2)[1]   # 最初の ## セクション（受信箱）
    check("snapshot受信箱: activeが先・parkedが後",
          0 < inbox.find("t1") < inbox.find("t3") and inbox.find("t2") < inbox.find("t3"))
    check("snapshot受信箱: parkedタスクに🅿マーカー", "🅿" in inbox and inbox.find("🅿") < inbox.find("t3") + 40)
    check("snapshotプロジェクト節: parkedは見出しに🅿", "🅿" in md.split("駐機中丙")[0].rsplit("##", 1)[-1] or "🅿 駐機中丙" in md)

    # --- pulse連携: parkedは😴に出さない ---
    # pulse_feed は任意のHub連携（feeds/、.gitignore対象・個人配線）。同梱されない環境ではこの1件だけ
    # 安全にスキップする（Cockpit本体の set-mode 機能そのものはこれに依存しない）。
    sys.path.insert(0, str(Path(__file__).resolve().parent / "feeds"))
    try:
        import pulse_feed
    except ImportError:
        pulse_feed = None
    if pulse_feed is not None:
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "events.jsonl"
            stf = Path(d) / "state.json"
            ev.write_text("", encoding="utf-8")   # 全プロジェクトがイベントゼロ
            stf.write_text(json.dumps(copy.deepcopy(STATE), ensure_ascii=False), encoding="utf-8")
            feed = pulse_feed.build(events_path=ev, state_path=stf, now=today)
            ids = {q["pid"] for q in feed["dormant"]}
            check("pulse: parked(p-c)は😴休眠に出さない（意図した眠りに警報しない）",
                  "p-c" not in ids and {"p-a", "p-b"} <= ids, f"(dormant={sorted(ids)})")
    else:
        print("  ⏭  pulse連携チェックはスキップ（feeds/pulse_feed.py が無い環境＝OSS配布物では正常）")

    print(f"\nMode Verdict: {PASS}/{PASS + FAIL} → {'✅ pass' if FAIL == 0 else '❌ FAIL'}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
