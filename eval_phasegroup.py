#!/usr/bin/env python3
"""P5 phase×group結合（正直な物差し）の Eval — 実装より先に書く（検証ファースト）。

背景（consult v3 P5）: 10/14のプロジェクトが phase 1/3 のまま＝物差しとして死んでいる。
milestoneの追加記入を王に求めず、**実装済みの grouping を phase に結合**して
「Phase1: 3/7 tasks」という進捗を導出する。実データ調査で phase↔group は1対多と判明
（moc-1 Phase1 = retrieval＋eval）→ phaseに groups リストを持たせる。

不変条件:
  - mutate_set_phase_groups: 存在するgroup idのみ受理・未知group/idxは拒否・空リストで解除
  - _phase_task_progress: 紐づくgroupのタスクで done/total を導出。
    total は承認済みスコープのみ（todo+done。proposedは未承認・dropped等は捨てた約束＝母数に入れない）
  - 未紐づけphase → None（0/0という嘘の物差しを出さない）
  - dashboard: 紐づけphaseのjstepに「n/m tasks」・未紐づけは従来表示のまま
  - snapshot: current phaseが紐づけ済みなら phase行に [n/m tasks]
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


STATE = {"projects": [
    {"id": "p-a", "name": "甲", "priority": "high", "north_star": "g", "done_def": "d",
     "groups": [{"id": "ret", "name": "検索", "order": 1}, {"id": "ev", "name": "Eval", "order": 2}],
     "phases": [
         {"name": "Phase0", "goal": "", "status": "done"},
         {"name": "Phase1 検索とEval", "goal": "", "status": "todo", "groups": ["ret", "ev"]},
         {"name": "Phase2 未紐づけ", "goal": "", "status": "todo"},
     ],
     "milestones": [],
     "tasks": [
         {"id": "t1", "desc": "a", "status": "done", "owner": "ai", "group": "ret"},
         {"id": "t2", "desc": "b", "status": "todo", "owner": "ai", "group": "ret"},
         {"id": "t3", "desc": "c", "status": "done", "owner": "ai", "group": "ev"},
         {"id": "t4", "desc": "d", "status": "proposed", "owner": "ai", "group": "ev"},   # 未承認→母数外
         {"id": "t5", "desc": "e", "status": "dropped", "owner": "ai", "group": "ev"},    # 捨てた→母数外
         {"id": "t6", "desc": "f", "status": "todo", "owner": "ai"},                       # 無group→どのphaseにも入らない
     ]},
]}


def main():
    print("=== P5 Eval (phase×group yardstick) ===")

    # --- setter ---
    st = copy.deepcopy(STATE)
    ph = cockpit.mutate_set_phase_groups(st, "p-a", 2, ["ev"])
    check("setter: groupsが入る", ph.get("groups") == ["ev"])
    ph = cockpit.mutate_set_phase_groups(st, "p-a", 2, [])
    check("setter: 空リストで解除（キー消滅）", "groups" not in ph)
    try:
        cockpit.mutate_set_phase_groups(st, "p-a", 1, ["nope"])
        check("setter: 未知groupは拒否", False)
    except ValueError:
        check("setter: 未知groupは拒否", True)
    try:
        cockpit.mutate_set_phase_groups(st, "p-a", 99, ["ev"])
        check("setter: 未知phase idxは拒否", False)
    except (KeyError, IndexError):
        check("setter: 未知phase idxは拒否", True)

    # --- 物差しの導出 ---
    st = copy.deepcopy(STATE)
    p = st["projects"][0]
    prog = cockpit._phase_task_progress(p, p["phases"][1])
    check("導出: Phase1 = done2/total3 (t1,t3 done / t2 todo)", prog == (2, 3), f"(={prog})")
    check("導出: proposed(t4)/dropped(t5)は母数外・無group(t6)は入らない", prog == (2, 3))
    check("導出: 未紐づけphase → None（0/0の嘘を出さない）",
          cockpit._phase_task_progress(p, p["phases"][2]) is None)

    # --- dashboard ---
    h = cockpit.render_dashboard(copy.deepcopy(STATE), served=False, active="projects")
    check("dashboard: 紐づけphaseに n/m tasks", "2/3 tasks" in h)
    check("dashboard: 未紐づけphaseには出ない", "0/0" not in h)

    # --- snapshot ---
    md = cockpit.render_snapshot_md(cockpit.make_snapshot(copy.deepcopy(STATE)), copy.deepcopy(STATE))
    check("snapshot: current phase行に [n/m tasks]", "[2/3 tasks]" in md)

    print(f"\nPhaseGroup Verdict: {PASS}/{PASS + FAIL} → {'✅ pass' if FAIL == 0 else '❌ FAIL'}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
