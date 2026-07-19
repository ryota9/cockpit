#!/usr/bin/env python3
"""完了提案キュー 検証（検証ファースト・ADR-0006の"完了側"）: propose-done / confirm-done / reject-done。

作成の propose→approve と対称の完了フロー。AIが検証済みの作業を終えたら done_proposed マーカーを
出し（status は変えない＝人間ゲート維持）、王がワンクリックで confirm-done → status=done。
先にこの Eval を書き、cockpit.py / serve.py / dashboard がこれを満たすよう実装する。
純粋関数中心（正本 state.json を書かない＝eval_h1.py / eval_grouping.py と同じ規律）・data-agnostic。

  D1 propose_done : mutate_propose_done は done_proposed マーカー(evidence/at)を付けるが status は不変。
  D2 confirm_done : mutate_confirm_done は status=done かつ status_changed 刻印＋マーカー消去。
  D3 後方互換     : マーカー無しタスクは各ミューテータで不変・snapshot/dashboard/validate が例外なし。
  D4 validate     : done_proposed を含む state で validate() が通る（新フィールドを不正としない）。
  D5 表示網羅     : done_proposed が snapshot(md) と dashboard(html・served) に evidence 付きで現れる。
  D6 reject_done  : マーカーのみ消去＝status は不変（実は未完だった時の差し戻し）。
  D7 決定論/journal: now 引数で at が決まる・2回で同一・journal に op が1行。
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


def _proj(tasks, pid="p1", name="Proj"):
    return {"id": pid, "name": name, "phases": [], "tasks": tasks}


def main():
    print("=== Done-propose Eval (verification-first · ADR-0006の完了側) ===")

    # --- D1 propose_done: マーカーを付けるが status は変えない ---
    st = {"projects": [_proj([
        {"id": "t1", "desc": "検証済みの実装", "status": "todo", "owner": "ai",
         "created": "2026-07-01", "status_changed": "2026-07-01"},
    ])]}
    t = cockpit.mutate_propose_done(st, "t1", "eval緑・手動確認OK", now="2026-07-10")
    t1 = st["projects"][0]["tasks"][0]
    check("D1 propose_done: done_proposed マーカーが付く", isinstance(t1.get("done_proposed"), dict))
    check("D1 propose_done: evidence を保持", t1["done_proposed"].get("evidence") == "eval緑・手動確認OK")
    check("D1 propose_done: at は now 引数の日付", t1["done_proposed"].get("at") == "2026-07-10")
    check("D1 propose_done: status は不変（todo のまま＝人間ゲート維持）", t1["status"] == "todo")
    check("D1 propose_done: status_changed は刻印しない（提案は状態遷移でない）",
          t1["status_changed"] == "2026-07-01")

    # --- D2 confirm_done: status=done かつマーカー消去 ---
    cockpit.mutate_confirm_done(st, "t1", now="2026-07-11")
    check("D2 confirm_done: status=done", t1["status"] == "done")
    check("D2 confirm_done: status_changed を now で刻印", t1["status_changed"] == "2026-07-11")
    check("D2 confirm_done: done_proposed マーカーが消える", "done_proposed" not in t1)

    # --- D3 後方互換: マーカー無しタスクは各操作で不変・生成関数が落ちない ---
    legacy = {"projects": [_proj([
        {"id": "t1", "desc": "old A", "status": "todo", "owner": "ai"},
        {"id": "t2", "desc": "old B", "status": "done", "owner": "human"},
    ])]}
    before = copy.deepcopy(legacy)
    # 対象1件のみ触る（他タスク不変）
    cockpit.mutate_propose_done(legacy, "t1", "ev", now="2026-07-10")
    check("D3 後方互換: propose_done は対象t1のみ変更・t2不変",
          legacy["projects"][0]["tasks"][1] == before["projects"][0]["tasks"][1])
    # reject で戻せば完全に元通り（マーカーが唯一の差分）
    cockpit.mutate_reject_done(legacy, "t1")
    check("D3 後方互換: reject_done でマーカーが外れ元の state と一致", legacy == before)
    try:
        cockpit.make_snapshot(legacy)
        cockpit.render_snapshot_md(cockpit.make_snapshot(legacy), legacy)
        cockpit.render_dashboard(legacy)
        check("D3 後方互換: マーカー無し state で snapshot/dashboard 例外なし", True)
    except Exception as e:
        check("D3 後方互換: snapshot/dashboard 例外なし", False, f"例外: {e}")

    # --- D4 validate: done_proposed を含む state が通る ---
    stv = {"projects": [_proj([
        {"id": "t1", "desc": "d", "status": "todo", "owner": "ai",
         "done_proposed": {"evidence": "ok", "at": "2026-07-10"}},
    ])]}
    check("D4 validate: done_proposed を含む state でエラー0", cockpit.validate(stv) == [])

    # --- D5 表示網羅: snapshot(md) と dashboard(html) に evidence 付きで現れる ---
    std = {"projects": [_proj([
        {"id": "t1", "desc": "READYTASK", "status": "todo", "owner": "ai",
         "created": "2026-07-01", "status_changed": "2026-07-01",
         "done_proposed": {"evidence": "EVIDENCE_MARK", "at": "2026-07-10"}},
    ])]}
    md = cockpit.render_snapshot_md(cockpit.make_snapshot(std), std)
    check("D5 snapshot: done_proposed タスク(t1)が現れる", "t1" in md and "READYTASK" in md)
    check("D5 snapshot: evidence が現れる", "EVIDENCE_MARK" in md)
    H = cockpit.render_dashboard(std, served=True)
    check("D5 dashboard: confirm-done ボタン(POST /confirm-done)がある", "/confirm-done" in H)
    check("D5 dashboard: evidence が描画される", "EVIDENCE_MARK" in H)
    check("D5 dashboard: 完了確認待ちの視覚バッジ（🤖作業所有と区別）",
          "完了確認" in H or "confirm-done" in H)
    # 非served（CLI閲覧）でも done_proposed が可視（コマンド提示）
    Hc = cockpit.render_dashboard(std, served=False)
    check("D5 dashboard(非served): confirm-done コマンドが提示される", "confirm-done" in Hc)

    # --- D6 reject_done: マーカーのみ消去・status は不変 ---
    st6 = {"projects": [_proj([
        {"id": "t1", "desc": "d", "status": "todo", "owner": "ai",
         "status_changed": "2026-07-01",
         "done_proposed": {"evidence": "実は未完だった", "at": "2026-07-10"}},
    ])]}
    cockpit.mutate_reject_done(st6, "t1")
    r1 = st6["projects"][0]["tasks"][0]
    check("D6 reject_done: マーカーが消える", "done_proposed" not in r1)
    check("D6 reject_done: status は不変（done にしない＝差し戻し）", r1["status"] == "todo")
    check("D6 reject_done: status_changed 不変", r1["status_changed"] == "2026-07-01")

    # --- D7 決定論 & journal ---
    sa = {"projects": [_proj([{"id": "t1", "desc": "d", "status": "todo", "owner": "ai"}])]}
    sb = copy.deepcopy(sa)
    cockpit.mutate_propose_done(sa, "t1", "ev", now="2026-07-10")
    cockpit.mutate_propose_done(sb, "t1", "ev", now="2026-07-10")
    check("D7 決定論: 同じ入力で同じ結果（2回で一致）", sa == sb)
    with tempfile.TemporaryDirectory() as d:
        jpath = os.path.join(d, "events.jsonl")
        cockpit.journal_append(jpath, {"op": "propose-done", "tid": "t1"}, now="2026-07-10T10:00:00")
        cockpit.journal_append(jpath, {"op": "confirm-done", "tid": "t1"}, now="2026-07-11T10:00:00")
        lines = [json.loads(x) for x in open(jpath).read().splitlines() if x.strip()]
        check("D7 journal: propose-done / confirm-done が追記される（op一致）",
              [l["op"] for l in lines] == ["propose-done", "confirm-done"])

    # --- 存在しない tid はどのミューテータも KeyError ---
    for fn in (lambda: cockpit.mutate_propose_done(sa, "zzz", "e"),
               lambda: cockpit.mutate_confirm_done(sa, "zzz"),
               lambda: cockpit.mutate_reject_done(sa, "zzz")):
        try:
            fn(); check("存在しないtidで KeyError", False, "例外が出なかった")
        except KeyError:
            check("存在しないtidで KeyError", True)

    print(f"\nDone-propose Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
