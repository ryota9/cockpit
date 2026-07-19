#!/usr/bin/env python3
"""P4 意図入り受信箱＋read-back の Eval — 実装より先に書く（検証ファースト）。

背景（consult v3 P4）:
- 受信箱は37タスクのフラットリストで、エージェントは「何のためのタスクか」を知らずに泳ぐ
  → 軍事の mission command: **意図（commander's intent）が共有されていれば部下は自走できる**。
  north_star/done_def は全プロジェクト記入済み＝流すだけ・追加記入ゼロ。
- approve後、AIの解釈が合っているか確かめる仕組みが無い（t2/t3の85%取り違え）
  → 航空の **read-back/hear-back**: 着手時に解釈1行を復唱し、王が一瞥して違ったら止める。

不変条件:
  - 受信箱: プロジェクト見出し（**[pid] 名前** 🎯 north_star → 🏁 done_def）でグループ化
  - 見出しは ## を使わない（他Evalの ## 分割を壊さない）・parked見出しは🅿
  - snapshotヘッダに read-back の作法が書いてある（次セッションのAIが自習できる＝自己伝播）
  - mutate_readback: text/at を刻む・200字で切る・空は拒否・未知tidは拒否
  - 受信箱の行: readback済みタスクに 💬 が付く
  - dashboard: カードモーダルのタスク行と Now詳細に 💬 解釈が出る
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
    {"id": "p-a", "name": "甲", "priority": "high", "north_star": "北極星A", "done_def": "完了定義A",
     "phases": [], "milestones": [],
     "tasks": [{"id": "t1", "desc": "仕事1", "status": "todo", "owner": "ai",
                "readback": {"text": "スコア集計を書く", "at": "2026-07-12"}},
               {"id": "t2", "desc": "仕事2", "status": "todo", "owner": "ai"}]},
    {"id": "p-b", "name": "乙(駐機)", "priority": "mid", "north_star": "北極星B", "done_def": "完了定義B",
     "mode": "parked", "phases": [], "milestones": [],
     "tasks": [{"id": "t3", "desc": "仕事3", "status": "todo", "owner": "ai"}]},
]}


def main():
    print("=== P4 Eval (intent inbox + read-back) ===")

    # --- 受信箱の意図見出し ---
    st = copy.deepcopy(STATE)
    md = cockpit.render_snapshot_md(cockpit.make_snapshot(st), st)
    inbox = md.split("## 🤖")[1].split("\n## ")[0]   # 受信箱セクションだけ
    check("見出し: **[pid] 名前** 形式（##でない）", "**[p-a] 甲**" in inbox)
    check("見出し: 🎯 north_star が入る", "🎯 北極星A" in inbox)
    check("見出し: 🏁 done_def が入る", "🏁 完了定義A" in inbox)
    check("グループ化: t1/t2 は甲見出しの後・乙見出しの前",
          inbox.find("**[p-a]") < inbox.find("t1:") < inbox.find("**") + len(inbox)
          and inbox.find("t2:") < inbox.find("🅿 [p-b]"))
    check("parked見出しに🅿・activeの後", "🅿 [p-b] 乙(駐機)" in inbox
          and inbox.find("[p-a]") < inbox.find("🅿 [p-b]"))
    check("ヘッダに read-back の作法（自己伝播）", "readback" in md.split("## 🤖")[0])
    check("受信箱の行: readback済みに💬", "💬" in inbox and inbox.find("💬") > inbox.find("t1:"))

    # --- mutate_readback ---
    st = copy.deepcopy(STATE)
    t = cockpit.mutate_readback(st, "t2", "解釈: 集計スクリプトを書いて動かす", now="2026-07-12")
    check("readback: text/at が刻まれる", t["readback"]["text"].startswith("解釈")
          and t["readback"]["at"] == "2026-07-12")
    t = cockpit.mutate_readback(st, "t2", "あ" * 300, now="2026-07-12")
    check("readback: 200字で切る", len(t["readback"]["text"]) == 200)
    try:
        cockpit.mutate_readback(st, "t2", "   ")
        check("readback: 空文字は拒否", False)
    except ValueError:
        check("readback: 空文字は拒否", True)
    try:
        cockpit.mutate_readback(st, "t999", "x")
        check("readback: 未知tidは拒否", False)
    except KeyError:
        check("readback: 未知tidは拒否", True)

    # --- dashboard表示 ---
    h = cockpit.render_dashboard(copy.deepcopy(STATE), served=False, active="projects")
    check("カードモーダルのタスク行に💬解釈", "💬" in h and "スコア集計を書く" in h)

    print(f"\nIntent Verdict: {PASS}/{PASS + FAIL} → {'✅ pass' if FAIL == 0 else '❌ FAIL'}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
