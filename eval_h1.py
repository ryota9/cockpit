#!/usr/bin/env python3
"""H1 検証（検証ファースト・design-hub-v2 §3）: 時間メタデータ・journal・stale・--why・後方互換。

先にこのEvalを書き、cockpit.py がこれを満たすよう実装する。data-agnostic（どのstateでも動く）。
  E1: 決定論 — 同じ操作列で stale 判定・時間刻印ロジックが一致（時刻はモック注入）
  E2: 後方互換 — 時間メタの無い旧タスクを読んでもクラッシュしない／既存 eval.py の不変式は別途維持
  E3: journal — mutation ごとに events.jsonl へ1行追記（追記専用・順序保存）
  E4: propose --why — 根拠が保存され snapshot/承認面から読める
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


def main():
    print("=== H1 Eval (verification-first) ===")

    # --- E2: 後方互換 — 時間メタ無しの最小タスクで各関数が落ちないこと ---
    legacy = {"projects": [{"id": "p1", "name": "Legacy", "tasks": [
        {"id": "t1", "desc": "old task", "status": "todo", "owner": "ai"},  # created 無し
    ]}]}
    try:
        cockpit.make_snapshot(legacy)                    # snapshot生成が落ちない
        days = cockpit.stale_days(legacy["projects"][0]["tasks"][0], now="2026-07-07")
        check("E2 後方互換: created無しタスクで snapshot生成＋stale_days が例外を出さない",
              days is None, f"(stale_days={days} = 不明扱い)")
    except Exception as e:
        check("E2 後方互換", False, f"例外: {e}")

    # --- E1: 決定論 stale 判定（時刻はモック注入） ---
    task = {"id": "t2", "desc": "x", "status": "todo", "owner": "ai",
            "created": "2026-07-01", "status_changed": "2026-07-01"}
    d1 = cockpit.stale_days(task, now="2026-07-08")
    d2 = cockpit.stale_days(task, now="2026-07-08")
    check("E1 決定論: 同一入力で stale_days が一致", d1 == d2 == 7, f"(={d1})")
    check("E1 stale判定: 7日更新なし → is_stale True（閾値6日）",
          cockpit.is_stale(task, now="2026-07-08", threshold=6) is True)
    check("E1 stale判定: 当日更新 → is_stale False",
          cockpit.is_stale({**task, "status_changed": "2026-07-08"}, now="2026-07-08", threshold=6) is False)

    # --- E4: propose --why が保存される ---
    st = {"projects": [{"id": "p1", "name": "P", "tasks": []}]}
    cockpit.mutate_propose(st, "p1", "新タスク", why="根拠テスト", now="2026-07-07")
    t = st["projects"][0]["tasks"][0]
    check("E4 propose: why が保存される", t.get("why") == "根拠テスト")
    check("E4 propose: created/status_changed が刻印される",
          t.get("created") == "2026-07-07" and t.get("status_changed") == "2026-07-07")
    check("E4 propose: status=proposed・owner=ai（HITLゲート不変）",
          t.get("status") == "proposed" and t.get("owner") == "ai")

    # --- E1(続き): set_status で status_changed だけ更新（created は不変） ---
    cockpit.mutate_set_status(st, t["id"], "todo", now="2026-07-09")
    check("E1 set_status: status_changed 更新・created 不変",
          t["status_changed"] == "2026-07-09" and t["created"] == "2026-07-07")

    # --- E3: journal 追記（追記専用・順序保存） ---
    with tempfile.TemporaryDirectory() as d:
        jpath = os.path.join(d, "events.jsonl")
        cockpit.journal_append(jpath, {"op": "propose", "tid": "t2"}, now="2026-07-07T10:00:00")
        cockpit.journal_append(jpath, {"op": "approve", "tid": "t2"}, now="2026-07-07T10:01:00")
        lines = [json.loads(x) for x in open(jpath).read().splitlines() if x.strip()]
        check("E3 journal: 2操作で2行・追記専用", len(lines) == 2)
        check("E3 journal: 順序保存（propose→approve）",
              lines[0]["op"] == "propose" and lines[1]["op"] == "approve")
        check("E3 journal: 各行に時刻", all("ts" in l for l in lines))

    # --- E9: 手順依頼パイプライン（王FB: 手順はAIが書く） ---
    d = cockpit.detail_request_desc("t59", "見守りWorkerのデプロイ")
    check("E9 依頼文: tid・set-detailへの導線を含む（AIが迷わない定型）",
          "t59" in d and "set-detail t59" in d)
    st2 = {"projects": [{"id": "p1", "name": "P", "tasks": [
        {"id": "t1", "desc": "detailなし", "status": "todo", "owner": "ai"},
        {"id": "t2", "desc": "detailあり", "status": "todo", "owner": "ai", "detail": "手順1"},
    ]}]}
    md = cockpit.render_snapshot_md(cockpit.make_snapshot(st2), st2)
    check("E9 snapshotマーカー: detail未記載のai-todoに注意書きが付く",
          "t1: detailなし  ※detail未記載" in md)
    check("E9 snapshotマーカー: detail済みには付かない",
          "t2: detailあり  ※" not in md)

    print(f"\nH1 Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
