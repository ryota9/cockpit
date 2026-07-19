#!/usr/bin/env python3
"""P3 ダークコックピットNow（逸脱ファースト＋再交渉）の Eval — 実装より先に書く（検証ファースト）。

背景（consult v3 P3）: 期限切れmilestoneが19日、失効focusが17日、普通の顔で表示され続けた。
腐った約束が再交渉されないまま残ると計器全体への信頼が下がる。航空の警報哲学（ダークコックピット）:
**正常なら消灯・逸脱だけ光る・光ったら2択（直すか捨てるか）に追い込む**。

不変条件:
  - _deviations: 期限切れms＋失効focusを列挙。parked除外・未来ms除外・done/dropped ms除外
  - mutate_defer_milestone: dueを更新・楽観ロック（表示時のdueと不一致なら拒否）・done/droppedは拒否
  - mutate_drop_milestone: status=dropped（履歴は残す・削除しない）
  - _next_due: dropped は期限計算から外れる（取り下げたのに🚨OVERDUEが残ったら再交渉の意味がない）
  - dashboard: 逸脱カードは最上段（Focusより前）・逸脱ゼロなら完全に消える（静か＝順調）
  - ボタン: [⏰延期][🗑取下][🔥再点火][解除] は served時のみ（HITL・人間ボタン）
"""
from __future__ import annotations

import copy
import sys
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


today = date.today()
past = (today - timedelta(days=10)).isoformat()
past2 = (today - timedelta(days=3)).isoformat()
future = (today + timedelta(days=30)).isoformat()

STATE = {"projects": [
    {"id": "p-a", "name": "甲", "priority": "high", "north_star": "g", "done_def": "d",
     "focus_until": past2,   # 失効focus → 逸脱
     "phases": [], "tasks": [],
     "milestones": [
         {"name": "期限切れの約束", "due": past, "status": "todo"},      # → 逸脱
         {"name": "未来の約束", "due": future, "status": "todo"},        # 出ない
         {"name": "済んだ約束", "due": past, "status": "done"},          # 出ない
     ]},
    {"id": "p-b", "name": "乙(駐機)", "priority": "mid", "north_star": "g", "done_def": "d",
     "mode": "parked", "phases": [], "tasks": [],
     "milestones": [{"name": "駐機中の期限切れ", "due": past, "status": "todo"}]},   # parked→出ない
    {"id": "p-c", "name": "丙(順調)", "priority": "mid", "north_star": "g", "done_def": "d",
     "phases": [], "tasks": [], "milestones": []},
]}


def main():
    print("=== P3 Eval (deviations / dark cockpit) ===")

    # --- 逸脱の列挙 ---
    devs = cockpit._deviations(copy.deepcopy(STATE), today.isoformat())
    kinds = [(d["kind"], d["pid"]) for d in devs]
    check("逸脱: 期限切れms(p-a)を検出", ("milestone", "p-a") in kinds)
    check("逸脱: 失効focus(p-a)を検出", ("focus", "p-a") in kinds)
    check("逸脱: parked(p-b)は除外・未来/done msは除外", len(devs) == 2, f"(={kinds})")
    ms = next(d for d in devs if d["kind"] == "milestone")
    check("逸脱: 超過日数を持つ", ms["days"] == 10, f"(={ms['days']})")

    # --- 再交渉ミューテータ ---
    st = copy.deepcopy(STATE)
    new_due = (today + timedelta(days=14)).isoformat()
    m = cockpit.mutate_defer_milestone(st, "p-a", "期限切れの約束", past, new_due)
    check("延期: dueが更新される", m["due"] == new_due)
    check("延期: statusは触らない", m["status"] == "todo")
    try:
        cockpit.mutate_defer_milestone(st, "p-a", "期限切れの約束", past, new_due)   # dueはもう変わっている
        check("延期: 楽観ロック（表示時dueと不一致→拒否）", False)
    except ValueError:
        check("延期: 楽観ロック（表示時dueと不一致→拒否）", True)
    try:
        cockpit.mutate_defer_milestone(st, "p-a", "済んだ約束", past, new_due)
        check("延期: done/droppedのmsは拒否", False)
    except ValueError:
        check("延期: done/droppedのmsは拒否", True)
    try:
        cockpit.mutate_defer_milestone(st, "p-a", "存在しない約束", past, new_due)
        check("延期: 未知msは拒否", False)
    except KeyError:
        check("延期: 未知msは拒否", True)

    st = copy.deepcopy(STATE)
    m = cockpit.mutate_drop_milestone(st, "p-a", "期限切れの約束", past)
    check("取下: status=dropped（削除はしない＝履歴）", m["status"] == "dropped"
          and len(cockpit._find_project(st, "p-a")["milestones"]) == 3)
    check("_next_due: droppedは期限計算から外れる",
          cockpit._next_due(cockpit._find_project(st, "p-a")) == future)

    # --- dashboard（ダークコックピット） ---
    h = cockpit.render_dashboard(copy.deepcopy(STATE), served=True, active="now")
    check("逸脱カードが出る（🚨・件数）", 'class="devcard"' in h and "期限切れの約束" in h)
    check("逸脱カードはFocusより前（最上段）",
          h.find('devcard') < h.find('🔥 Focus'))
    check("ボタン4種（served）: 延期/取下/再点火/解除",
          all(a in h for a in ("/ms-defer", "/ms-drop", "/focus-extend", "/focus-clear")))
    check("parkedの期限切れは光らない", "駐機中の期限切れ" not in h.split("pg-projects")[0])

    calm = copy.deepcopy(STATE)
    calm["projects"] = [calm["projects"][2]]   # 順調な丙だけ
    hc = cockpit.render_dashboard(calm, served=True, active="now")
    check("逸脱ゼロ → カード自体が消える（静か＝順調）", 'class="devcard"' not in hc)

    hv = cockpit.render_dashboard(copy.deepcopy(STATE), served=False, active="now")
    check("served=False: 逸脱は見えるがボタンは無い（プレビュー安全）",
          'class="devcard"' in hv and "/ms-defer" not in hv)

    print(f"\nDeviations Verdict: {PASS}/{PASS + FAIL} → {'✅ pass' if FAIL == 0 else '❌ FAIL'}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
