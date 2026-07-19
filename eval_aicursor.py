#!/usr/bin/env python3
"""AIカーソル（差分読み）検証（検証ファースト・design-sync-diff-architecture.md §3.2/§4 S2）。

欠陥B（AIが「差分」を持たない）の解消。events.jsonl を変更ストリームとして使い、AIが
「前回見た地点(カーソル)以降の差分」だけを行オフセットで読む。カーソルは feeds/ai_cursor.json
（私物・gitignore）。feeds/ が無ければ機能OFF＝OSSコアは no-op（汎用のまま）。
先にこの Eval を書き、cockpit.py がこれを満たすよう実装する。純粋関数中心・data-agnostic
（正本 state.json を書かない＝eval_h1.py / eval_donepropose.py と同じ規律）。

  A1 diff       : cursor_diff はカーソル以降の journal イベントだけを順序どおり返す。
  A2 --advance  : 出力後にカーソルを最新(総行数)へ進める＝既読化（read→write→再readで確認）。
  A3 差分ゼロ    : カーソルが最新なら events は空・total と一致。
  A4 追記で増える: journal に1行追記すると diff が1件増える（前回既読分は再掲しない）。
  A5 no-op/初期化: cursor欠如なら seen=0（＝全部が差分の初期化）。feeds/欠如なら write_cursor は
                  何もしない no-op（OSSコアは汎用）。CLI dispatch も feeds/欠如で沈黙。
"""
from __future__ import annotations

import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


def _seed_journal(jpath, ops):
    for i, op in enumerate(ops):
        cockpit.journal_append(jpath, {"op": op, "tid": f"t{i+1}"},
                               now=f"2026-07-11T10:{i:02d}:00")


def main():
    print("=== AI-cursor Eval (verification-first · design-sync-diff §3.2/§4 S2) ===")

    with tempfile.TemporaryDirectory() as d:
        feeds = Path(d) / "feeds"
        feeds.mkdir()
        jpath = str(Path(d) / "events.jsonl")
        cpath = str(feeds / "ai_cursor.json")
        _seed_journal(jpath, ["propose", "approve", "set-status", "set-phase"])  # 4件

        # --- A5(init): カーソルファイル欠如 → seen=0（全部が差分） ---
        check("A5 init: cursorファイル欠如で read_cursor=0", cockpit.read_cursor(cpath) == 0)
        events, seen, total = cockpit.cursor_diff(jpath, cpath)
        check("A1 diff: カーソル無し(seen=0)で全4件を返す", len(events) == 4 and total == 4)
        check("A1 diff: 順序保存（propose→approve→set-status→set-phase）",
              [e["op"] for e in events] == ["propose", "approve", "set-status", "set-phase"])
        check("A1 diff: seen起点は0", seen == 0)

        # --- A2 --advance 相当: read→write(total)→再read でカーソルが最新へ ---
        wrote = cockpit.write_cursor(cpath, total)
        check("A2 --advance: feeds/存在下で write_cursor が書き込む", wrote is True)
        check("A2 --advance: 保存後 read_cursor が最新(4)を返す", cockpit.read_cursor(cpath) == 4)

        # --- A3 差分ゼロ: カーソルが最新なら空 ---
        events2, seen2, total2 = cockpit.cursor_diff(jpath, cpath)
        check("A3 差分ゼロ: 既読最新なら events は空", events2 == [] and seen2 == total2 == 4)

        # --- A4 追記で増える: 1行足すと diff が1件だけ増える（既読分は再掲しない） ---
        cockpit.journal_append(jpath, {"op": "approve", "tid": "t99"}, now="2026-07-11T11:00:00")
        events3, seen3, total3 = cockpit.cursor_diff(jpath, cpath)
        check("A4 追記: diff が1件だけ増える（既読4件は再掲しない）",
              len(events3) == 1 and events3[0]["tid"] == "t99" and total3 == 5)
        check("A4 追記: seen起点は前回カーソル(4)", seen3 == 4)

        # --- 表示: 人が読める（op・tid・件数） ---
        rendered = cockpit.render_diff(events3, seen3, total3, feeds_on=True)
        check("表示: op と tid と件数を含む",
              "approve" in rendered and "t99" in rendered and "1" in rendered)
        empty_render = cockpit.render_diff([], 5, 5, feeds_on=True)
        check("表示: 差分ゼロ時は『差分なし』", "差分なし" in empty_render)

    # --- A5 no-op: feeds/（親ディレクトリ）欠如なら write_cursor は何もしない ---
    with tempfile.TemporaryDirectory() as d2:
        missing_cursor = str(Path(d2) / "nofeeds" / "ai_cursor.json")  # 親が存在しない
        wrote2 = cockpit.write_cursor(missing_cursor, 3)
        check("A5 no-op: 親(feeds/)欠如で write_cursor は書かず False", wrote2 is False)
        check("A5 no-op: ファイルは作られない", not os.path.exists(missing_cursor))
        check("A5 no-op: 欠如 cursor の read は 0（クラッシュしない）",
              cockpit.read_cursor(missing_cursor) == 0)

    # --- CLI dispatch: feeds/欠如で diff は no-op を print（OSSコア汎用・state.jsonに触れない） ---
    #     モジュールグローバルを一時退避して差し替え、main(["diff"]) の配線を確認。
    saved = (cockpit.FEEDS_DIR, cockpit.JOURNAL, cockpit.CURSOR)
    try:
        with tempfile.TemporaryDirectory() as d3:
            cockpit.FEEDS_DIR = Path(d3) / "feeds"          # 存在しない → 機能OFF
            cockpit.JOURNAL = Path(d3) / "events.jsonl"
            cockpit.CURSOR = cockpit.FEEDS_DIR / "ai_cursor.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                cockpit.main(["diff"])
            out = buf.getvalue()
            check("A5 CLI: feeds/欠如で diff は no-op を告知（例外なし）",
                  "no-op" in out or "無効" in out)

            # feeds/ を用意し journal を積むと、CLI diff が件数を出す
            cockpit.FEEDS_DIR.mkdir(parents=True)
            cockpit.CURSOR = cockpit.FEEDS_DIR / "ai_cursor.json"
            _seed_journal(str(cockpit.JOURNAL), ["propose", "approve"])
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                cockpit.main(["diff", "--advance"])
            out2 = buf2.getvalue()
            check("A2 CLI: diff --advance が差分を出しカーソルを進める",
                  "2" in out2 and cockpit.CURSOR.exists() and
                  json.loads(cockpit.CURSOR.read_text())["seen"] == 2)
            # 直後の diff は差分ゼロ
            buf3 = io.StringIO()
            with redirect_stdout(buf3):
                cockpit.main(["diff"])
            check("A3 CLI: --advance 直後の diff は差分なし", "差分なし" in buf3.getvalue())
    finally:
        cockpit.FEEDS_DIR, cockpit.JOURNAL, cockpit.CURSOR = saved

    print(f"\nAI-cursor Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    raise SystemExit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
