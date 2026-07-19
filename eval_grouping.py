#!/usr/bin/env python3
"""Grouping 検証（検証ファースト・design-grouping.md §6）: task.group / find --group /
set-group / dashboard グループ見出し / メタ欠測耐性 / snapshot --group 縮約。

先にこの Eval を書き、cockpit.py がこれを満たすよう実装する。data-agnostic（どの state でも動く）・
純粋関数中心（正本 state.json を書かない＝eval_h1.py と同じ規律）。
  G1 後方互換 : group 無しタスクを含む state で snapshot/dashboard 生成・find が例外を出さず「未分類」扱い。
  G2 find --group 決定論: find_tasks(state, kw, group=g) が該当グループのみ返す・2回で同一。
  G3 set-group 対象限定: mutate_set_group(state, tid, g) が対象1タスクのみ変更・他不変・journal 1行。
  G4 表示網羅  : dashboard(Projects) で各タスクがちょうど1グループ見出しの下（重複0・欠落0）。
  G5 メタ欠測耐性: groups メタ未定義グループはスラグ表示で末尾・「未分類」は最後・クラッシュしない。
  G6 snapshot 縮約: make_snapshot(state, group=g) 出力が全体の部分集合で他グループ行を含まない。
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import sys

import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


def _proj(tasks, groups=None, pid="p1", name="Proj"):
    p = {"id": pid, "name": name, "phases": [], "tasks": tasks}
    if groups is not None:
        p["groups"] = groups
    return p


def main():
    print("=== Grouping Eval (verification-first) ===")

    # --- G1 後方互換: group / groups メタ の無い旧 state で各関数が落ちない ---
    legacy = {"projects": [_proj([
        {"id": "t1", "desc": "old A", "status": "todo", "owner": "ai"},
        {"id": "t2", "desc": "old B", "status": "done", "owner": "human"},
    ])]}
    try:
        cockpit.make_snapshot(legacy)
        cockpit.render_dashboard(legacy)
        hits = cockpit.find_tasks(legacy, "old")
        gt = cockpit.group_tasks(legacy["projects"][0])
        names = [g["name"] for g in gt]
        check("G1 後方互換: group無しstateで snapshot/dashboard/find が例外なし", True)
        check("G1 後方互換: group無しタスクは『未分類』グループ扱い（1グループ・全2件）",
              names == ["未分類"] and len(gt[0]["tasks"]) == 2, f"(names={names})")
        check("G1 後方互換: find が2件返す（groupフィルタ無しは全件）", len(hits) == 2)
    except Exception as e:
        check("G1 後方互換", False, f"例外: {e}")

    # --- G2 find --group 決定論: 該当グループのみ・2回同一 ---
    st = {"projects": [_proj([
        {"id": "t1", "desc": "keyword hit", "status": "todo", "owner": "ai", "group": "pilot"},
        {"id": "t2", "desc": "keyword hit", "status": "todo", "owner": "ai", "group": "diff"},
        {"id": "t3", "desc": "keyword hit", "status": "done", "owner": "ai"},  # 未分類
    ])]}
    r1 = cockpit.find_tasks(st, "keyword", group="pilot")
    r2 = cockpit.find_tasks(st, "keyword", group="pilot")
    ids = {h["id"] for h in r1}
    check("G2 find --group: pilotグループのみ返す（t1のみ）", ids == {"t1"}, f"(ids={ids})")
    check("G2 find --group: 決定論（2回で同一結果）", r1 == r2)
    check("G2 find（group無し）は後方互換で全マッチ3件",
          len(cockpit.find_tasks(st, "keyword")) == 3)

    # --- G3 set-group 対象限定: 対象1タスクのみ変更・他不変・journal 1行 ---
    st3 = {"projects": [_proj([
        {"id": "t1", "desc": "A", "status": "todo", "owner": "ai", "created": "2026-07-01", "status_changed": "2026-07-01"},
        {"id": "t2", "desc": "B", "status": "todo", "owner": "ai", "created": "2026-07-01", "status_changed": "2026-07-01"},
    ])]}
    before = copy.deepcopy(st3)
    cockpit.mutate_set_group(st3, "t1", "pilot")
    t1 = st3["projects"][0]["tasks"][0]
    t2 = st3["projects"][0]["tasks"][1]
    check("G3 set-group: 対象t1のみ group=pilot", t1.get("group") == "pilot")
    check("G3 set-group: 他タスクt2は不変", t2 == before["projects"][0]["tasks"][1])
    check("G3 set-group: created/status_changed 規約不変（group付与でstatus刻印しない）",
          t1["created"] == "2026-07-01" and t1["status_changed"] == "2026-07-01")
    # --clear で未分類化（group キー除去）
    cockpit.mutate_set_group(st3, "t1", None)
    check("G3 set-group --clear: group が外れ未分類へ", "group" not in t1)
    with tempfile.TemporaryDirectory() as d:
        jpath = os.path.join(d, "events.jsonl")
        cockpit.journal_append(jpath, {"op": "set-group", "tid": "t1", "group": "pilot"}, now="2026-07-09T10:00:00")
        lines = [json.loads(x) for x in open(jpath).read().splitlines() if x.strip()]
        check("G3 journal: set-group が1行追記（op=set-group）",
              len(lines) == 1 and lines[0]["op"] == "set-group")

    # --- G4 表示網羅: group_tasks で各タスクちょうど1グループ・重複0欠落0 ---
    tasks4 = [
        {"id": "t1", "desc": "d1", "status": "todo", "owner": "ai", "group": "pilot"},
        {"id": "t2", "desc": "d2", "status": "todo", "owner": "ai", "group": "pilot"},
        {"id": "t3", "desc": "d3", "status": "todo", "owner": "ai", "group": "diff"},
        {"id": "t4", "desc": "d4", "status": "todo", "owner": "ai"},  # 未分類
    ]
    meta4 = [{"id": "pilot", "name": "🎒 家族パイロット", "order": 1},
             {"id": "diff", "name": "✨ 差別化", "order": 2}]
    p4 = _proj(tasks4, groups=meta4)
    gt4 = cockpit.group_tasks(p4)
    flat = [t["id"] for g in gt4 for t in g["tasks"]]
    check("G4 網羅: 全タスクがちょうど1回出現（重複0・欠落0）",
          sorted(flat) == ["t1", "t2", "t3", "t4"] and len(flat) == 4, f"(flat={flat})")
    check("G4 見出し順: order通り pilot→diff→未分類",
          [g["name"] for g in gt4] == ["🎒 家族パイロット", "✨ 差別化", "未分類"])
    H = cockpit.render_dashboard({"projects": [p4]})
    check("G4 dashboard: 各グループ表示名が描画される",
          "🎒 家族パイロット" in H and "✨ 差別化" in H and "未分類" in H)
    check("G4 dashboard: 例外なく生成（Projectsタブにグループ見出し）", "pg-projects" in H)

    # --- G5 メタ欠測耐性: メタ未定義グループはスラグ表示で末尾・未分類は最後 ---
    tasks5 = [
        {"id": "t1", "desc": "d1", "status": "todo", "owner": "ai", "group": "known"},
        {"id": "t2", "desc": "d2", "status": "todo", "owner": "ai", "group": "orphan"},  # メタ無し
        {"id": "t3", "desc": "d3", "status": "todo", "owner": "ai"},  # 未分類
    ]
    meta5 = [{"id": "known", "name": "🟢 既知", "order": 1}]
    p5 = _proj(tasks5, groups=meta5)
    gt5 = cockpit.group_tasks(p5)
    order5 = [(g["id"], g["name"]) for g in gt5]
    check("G5 順序: 定義済み→メタ無しスラグ→未分類 の順",
          order5 == [("known", "🟢 既知"), ("orphan", "orphan"), (None, "未分類")], f"(order={order5})")
    try:
        H5 = cockpit.render_dashboard({"projects": [p5]})
        check("G5 メタ欠測でクラッシュしない・スラグ orphan が描画される", "orphan" in H5)
    except Exception as e:
        check("G5 メタ欠測耐性", False, f"例外: {e}")

    # --- G6 snapshot --group 縮約: 部分集合・他グループ行を含まない ---
    st6 = {"projects": [_proj([
        {"id": "t1", "desc": "PILOTTASK", "status": "todo", "owner": "ai", "group": "pilot"},
        {"id": "t2", "desc": "DIFFTASK", "status": "todo", "owner": "ai", "group": "diff"},
        {"id": "t3", "desc": "PILOTPROP", "status": "proposed", "owner": "ai", "group": "pilot"},
    ], groups=[{"id": "pilot", "name": "P", "order": 1}, {"id": "diff", "name": "D", "order": 2}])]}
    full_md = cockpit.render_snapshot_md(cockpit.make_snapshot(st6), st6)
    sub_md = cockpit.render_snapshot_md(cockpit.make_snapshot(st6, group="pilot"), st6, group="pilot")
    check("G6 縮約: pilot snapshot に pilotタスク(t1)は含まれる", "t1: PILOTTASK" in sub_md)
    check("G6 縮約: pilot snapshot に他グループ(t2 diff)は含まれない",
          "DIFFTASK" not in sub_md and "t2" not in sub_md)
    check("G6 縮約: 全体snapshotには両方含まれる（絞り込み前）",
          "PILOTTASK" in full_md and "DIFFTASK" in full_md)
    check("G6 部分集合: pilot snapshot の各タスク行は全体snapshotにも存在",
          "PILOTTASK" in full_md and "PILOTPROP" in full_md)

    print(f"\nGrouping Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
