#!/usr/bin/env python3
"""テーマ（着せ替え）Eval — 検証ファースト（実装より先にこのファイルを書く）。

王の要望: 衛星・フェニックス・オルカ・風（山）の4テーマ。フェニックスの背景は炎金（お気に入り）
= デフォルトテーマは phoenix のまま。切替はクライアント側（localStorage）で正本 state.json には
一切書かない（ADR-0006: UI好みは状態ではない）。

  T1: THEMES 定義 — 4テーマ・phoenix が先頭（=デフォルト）・日本語ラベル
  T2: 決定論 — 同じ state から render_dashboard が同一HTML（テーマ機構がランダム性を持ち込まない）
  T3: デフォルト — body class に th-phoenix（炎金背景 bg-d も維持）
  T4: 切替UI — テーマボタン＋ラベル＋localStorage("cockpit-theme") が script に含まれる
  T5: CSS — 各テーマの上書きブロック（body.th-*）と粒子スタイル（星/泡/木の葉）が存在
  T6: スコープ — 非phoenixテーマでは炎金写真レイヤと🎨背景ボタンが無効化される
  T7: 風（山）は明色テーマ（--bg が明るい）
"""
from __future__ import annotations

import sys

import cockpit

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


STATE = {"projects": [{"id": "p1", "name": "テーマ検証", "north_star": "着せ替え", "priority": "high",
                       "repo": "", "depends_on": [], "done_def": "", "phases": [], "milestones": [],
                       "tasks": [{"id": "t1", "desc": "x", "status": "todo", "owner": "human"}]}]}


def main():
    print("=== Theme Eval (verification-first) ===")

    # --- T1: THEMES 定義 ---
    th = getattr(cockpit, "THEMES", None)
    check("T1 THEMES が定義されている", th is not None)
    if th is None:
        sys.exit(1)
    classes = [c for c, _ in th]
    labels = [l for _, l in th]
    check("T1 4テーマ（phoenix/satellite/orca/wind）",
          classes == ["th-phoenix", "th-satellite", "th-orca", "th-wind"], f"({classes})")
    check("T1 日本語ラベル（フェニックス/衛星/オルカ/風（山））",
          labels == ["フェニックス", "衛星", "オルカ", "風（山）"], f"({labels})")

    html = cockpit.render_dashboard(STATE)
    html2 = cockpit.render_dashboard(STATE)

    # --- T2: 決定論 ---
    check("T2 決定論: 同一stateで同一HTML", html == html2)

    # --- T3: デフォルトは phoenix（炎金） ---
    check("T3 body デフォルト class に th-phoenix と bg-d",
          'class="bg-d th-phoenix"' in html)

    # --- T4: 切替UI ---
    check("T4 テーマ切替ボタン（thbtn/thlabel）", 'id="thlabel"' in html and "cycleTheme" in html)
    check("T4 localStorage キー cockpit-theme", "cockpit-theme" in html)
    check("T4 JS に全テーマclassとラベル", all(c in html for c in classes) and all(l in html for l in labels))

    # --- T5: 各テーマの CSS 上書きブロック＋粒子 ---
    for cls in ["th-satellite", "th-orca", "th-wind"]:
        check(f"T5 CSS: body.{cls} パレット定義", f"body.{cls}{{--bg:" in html)
        check(f"T5 CSS: body.{cls} 粒子スタイル", f"body.{cls} .embers i{{" in html)

    # --- T6: 非phoenixでは写真背景と🎨ボタンを無効化 ---
    check("T6 写真レイヤは phoenix 限定", "body:not(.th-phoenix)::before{opacity:0" in html)
    check("T6 🎨背景ボタンは phoenix 限定", "body:not(.th-phoenix) .bgbtn{display:none" in html)

    # --- T7: 風（山）は明色 ---
    import re
    m = re.search(r"body\.th-wind\{--bg:#([0-9a-fA-F]{6})", html)
    ok = False
    if m:
        r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
        ok = (r + g + b) / 3 > 180   # 平均輝度が明るい＝ライトテーマ
    check("T7 風（山）は明色テーマ（--bg 平均輝度>180）", ok, f"(#{m.group(1) if m else '??'})")

    print(f"\nTheme Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
