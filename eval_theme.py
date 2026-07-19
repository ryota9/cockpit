#!/usr/bin/env python3
"""テーマ（着せ替え）Eval — 検証ファースト（実装より先にこのファイルを書く）。

王FB(v2): 各テーマに「反対カラーのバージョン」を追加＝合計8テーマ。
オルカ/衛星/風にエフェクト追加・各テーマにCSS背景・テーマタイル選択UI。
デフォルトは phoenix(黒+炎金)のまま。切替はクライアント側(localStorage)で正本 state.json には
一切書かない(ADR-0006: UI好みは状態ではない)。全て自己完結(外部画像/フォント/CDN禁止・CSP)。

  T1: THEMES 定義 — 8テーマ・phoenix が先頭(=デフォルト)・各に日本語ラベル・反転4種を含む
  T2: 決定論 — 同じ state から render_dashboard が同一HTML
  T3: デフォルト — body class に th-phoenix(炎金背景 bg-d も維持)
  T4: 切替UI — テーマタイルのグリッド(thgrid/thtile・8タイル)＋cycleTheme＋localStorage("cockpit-theme")
  T5: CSS — 各テーマの上書きブロック(body.th-*)・パレット(--bg)・粒子(embers)・背景(background)
  T6: スコープ — phoenix(黒)以外では炎金写真レイヤと🎨背景ボタンが無効化される
  T7: エフェクト — orca=大きな泡 / satellite=小石(無重力) / wind=風の筋＋葉。class/keyframes/DOM要素が存在
  T8: prefers-reduced-motion 尊重(アニメ抑制ブロック)
  T9: 明暗の反転 — 各ペアで --bg 輝度が反転(明↔暗)
"""
from __future__ import annotations

import base64
import re
import sys

import cockpit

PASS = FAIL = 0

# 黒フェニックス以外＝Canva製タイル/背景の対象7テーマ
TARGETS = ["th-phoenix-l", "th-satellite", "th-satellite-l",
           "th-orca", "th-orca-l", "th-wind", "th-wind-d"]


def _b64head(path, n=64):
    """ファイルの base64 先頭 n 文字（HTML内に実バイトが埋め込まれたかの照合用）。"""
    return base64.b64encode(path.read_bytes()).decode("ascii")[:n]


def check(name, ok, detail=""):
    global PASS, FAIL
    print(("  ✅" if ok else "  ❌"), name, detail)
    PASS += ok
    FAIL += (not ok)


STATE = {"projects": [{"id": "p1", "name": "テーマ検証", "north_star": "着せ替え", "priority": "high",
                       "repo": "", "depends_on": [], "done_def": "", "phases": [], "milestones": [],
                       "tasks": [{"id": "t1", "desc": "x", "status": "todo", "owner": "human"}]}]}

# 8テーマ(class, label)・phoenix が先頭=デフォルト。ペア=[暗, 明] or [基準, 反転]。
EXPECT_CLASSES = ["th-phoenix", "th-phoenix-l", "th-satellite", "th-satellite-l",
                  "th-orca", "th-orca-l", "th-wind", "th-wind-d"]
EXPECT_LABELS = ["フェニックス", "白フェニックス", "衛星", "衛星（暁）",
                 "オルカ", "オルカ（浅瀬）", "風（山）", "風（夜）"]

# 明色テーマ(--bg 平均輝度が明るい) / 暗色テーマ
LIGHT = {"th-phoenix-l", "th-satellite-l", "th-orca-l", "th-wind"}
DARK = {"th-phoenix", "th-satellite", "th-orca", "th-wind-d"}


def _bg_avg(html, cls):
    """body.CLS{--bg:#RRGGBB … の平均輝度を返す(phoenixは:rootの既定)。"""
    if cls == "th-phoenix":
        m = re.search(r":root\{--bg:#([0-9a-fA-F]{6})", html)
    else:
        m = re.search(r"body\." + re.escape(cls) + r"\{--bg:#([0-9a-fA-F]{6})", html)
    if not m:
        return None
    h = m.group(1)
    return sum(int(h[i:i + 2], 16) for i in (0, 2, 4)) / 3


def main():
    print("=== Theme Eval (verification-first · 8 themes) ===")

    # --- T1: THEMES 定義(8) ---
    th = getattr(cockpit, "THEMES", None)
    check("T1 THEMES が定義されている", th is not None)
    if th is None:
        sys.exit(1)
    classes = [c for c, _ in th]
    labels = [l for _, l in th]
    check("T1 8テーマ・phoenix先頭・反転4種を含む", classes == EXPECT_CLASSES, f"({classes})")
    check("T1 日本語ラベル8種", labels == EXPECT_LABELS, f"({labels})")

    html = cockpit.render_dashboard(STATE)
    html2 = cockpit.render_dashboard(STATE)

    # --- T2: 決定論 ---
    check("T2 決定論: 同一stateで同一HTML", html == html2)

    # --- T3: デフォルトは phoenix(炎金) ---
    check("T3 body デフォルト class に th-phoenix と bg-d", 'class="bg-d th-phoenix"' in html)

    # --- T4: 切替UI(タイルグリッド＋cycleTheme＋localStorage) ---
    check("T4 テーマタイルのグリッド(thgrid)", 'id="thgrid"' in html)
    check("T4 8タイル(thtile・各テーマ data-th)",
          html.count('class="thtile"') == 8 and all(f'data-th="{c}"' in html for c in classes))
    # T4b: 各タイルにブランドエンブレム。黒フェニックス=既存ロゴ / 他7テーマ=Canva製タイル画像(data URI)。
    # アートアセット（jpg/png）は配布物に同梱しない環境がある（.gitignore）ため、cockpit.py 側は
    # ファイル欠落時にインラインSVGへ自動フォールバックする（_tile_emblem）。ここではその両方の
    # 状態を「実際に存在するファイル数」から動的に検証する＝どちらの環境でも green になるのが正しい。
    tiles = cockpit._theme_tiles_html()
    n_tile_assets = sum(1 for p in cockpit.THEME_TILE_IMG.values() if p.exists())
    n_svg_fallback = len(cockpit.THEME_TILE_IMG) - n_tile_assets
    check("T4b 各タイルにエンブレム枠(themb×8)", tiles.count('class="themb"') == 8, f"({tiles.count('class=\"themb\"')})")
    check("T4b 黒フェニックスのエンブレム(ロゴ画像 or SVG退避)",
          tiles.count('class="thlogo"') == (1 if cockpit.LOGO.exists() else 0),
          f"(logo.exists={cockpit.LOGO.exists()})")
    check(f"T4b タイル画像アセットあり{n_tile_assets}件は Canva タイル画像(thimg)",
          tiles.count('class="thimg"') == n_tile_assets, f"({tiles.count('class=\"thimg\"')}/{n_tile_assets})")
    check(f"T4b タイル画像アセットなし{n_svg_fallback}件はインラインSVGへ退避",
          tiles.count("<svg") >= n_svg_fallback, f"(svg={tiles.count('<svg')}, expect>={n_svg_fallback})")
    check("T4b タイル画像は data URI(base64) で自己完結",
          tiles.count('src="data:image/jpeg;base64,') == n_tile_assets)
    check("T4b 丸ポチ羅列(thsw)は廃止", 'class="thsw"' not in tiles)
    check("T4 現テーマ表示ラベル(thlabel)＋cycleTheme", 'id="thlabel"' in html and "cycleTheme" in html)
    check("T4 applyTheme＋localStorage キー cockpit-theme",
          "applyTheme" in html and "cockpit-theme" in html)
    check("T4 JS に全テーマclassとラベル",
          all(c in html for c in classes) and all(l in html for l in labels))

    # --- T5: 各テーマ CSS 上書き(パレット・粒子・背景) ---
    for cls in classes:
        if cls == "th-phoenix":
            # phoenix は :root 既定パレット・base .embers i・body 既定背景
            check(f"T5 {cls}: パレット(:root --bg)", bool(re.search(r":root\{--bg:#", html)))
            check(f"T5 {cls}: 背景(body radial-gradient)",
                  bool(re.search(r"body\{[^}]*background:radial", html)))
            continue
        check(f"T5 {cls}: パレット(body.{cls} --bg)", f"body.{cls}{{--bg:" in html)
        check(f"T5 {cls}: 粒子(embers i)", f"body.{cls} .embers i{{" in html)
        check(f"T5 {cls}: 背景(background:)",
              bool(re.search(r"body\." + re.escape(cls) + r"\{[^}]*background:", html)))

    # --- T6: 黒フェニックスの炎金写真は他テーマに漏れない（各テーマが ::before を自画像で上書き）＋🎨は限定 ---
    # 背景アセットが存在するテーマだけ ::before の上書きルールが出る（cockpit.py _bg_css: `if fn.exists()`）。
    # アセットが無いテーマは上書きルール自体が出ない＝T5の既定背景のみで green（これも正しい設計）。
    targets_with_bg = [c for c in TARGETS if cockpit.THEME_BG_IMG.get(c, (None, None))[0].exists()]
    check(f"T6 背景アセットあり{len(targets_with_bg)}テーマは ::before を自分のCanva画像で上書き(!important)",
          all(f"body.{c}::before{{background-image:url(data:image/jpeg;base64," in html for c in targets_with_bg))
    check("T6 上書きは !important で opacity も指定（炎金写真を確実に置換）",
          all(re.search(r"body\." + re.escape(c) + r"::before\{background-image:url\(data:image/jpeg;base64,"
                        r"[^)]+\)!important;opacity:", html) for c in targets_with_bg))
    check("T6 🎨背景ボタンは phoenix 限定", "body:not(.th-phoenix) .bgbtn{display:none" in html)

    # --- T13: Canva製 タイル/背景の実バイトが、存在するファイルについてのみ data URI で埋め込まれている ---
    # （画像アセットは .gitignore で除外されうる＝無い環境があるのは正常。無ければ埋め込まれないことを確認する）
    for cls in TARGETS:
        tpath = cockpit.THEME_TILE_IMG.get(cls)
        bpath = cockpit.THEME_BG_IMG.get(cls, (None, None))[0]
        if tpath and tpath.exists():
            check(f"T13 {cls}: タイル画像の実バイトが HTML に埋込", _b64head(tpath) in tiles)
        else:
            check(f"T13 {cls}: タイル画像アセットなし→SVG退避（埋込なし）",
                  'src="data:image/jpeg;base64,' not in tiles.split(f'data-th="{cls}"')[-1][:400]
                  if f'data-th="{cls}"' in tiles else True)
        if bpath and bpath.exists():
            check(f"T13 {cls}: 背景画像の実バイトが HTML に埋込", _b64head(bpath) in html)
        else:
            check(f"T13 {cls}: 背景画像アセットなし→上書きルールなし",
                  f"body.{cls}::before{{background-image:url(data:image/jpeg;base64," not in html)

    # --- T7: 追加エフェクト(class/keyframes/DOM) ---
    check("T7 fxfield レイヤが body に存在", 'class="fxfield"' in html)
    for kf in ("orca-bubble", "sat-pebble", "wind-streak", "wind-leaf"):
        check(f"T7 keyframes {kf}", f"@keyframes {kf}" in html)
    for elc in ("fx bubble", "fx pebble", "fx streak", "fx leaf"):
        check(f"T7 DOM要素 {elc}", f'class="{elc}"' in html)
    check("T7 orca(泡)は両バリアントで有効",
          "body.th-orca .fxfield .bubble,body.th-orca-l .fxfield .bubble{display:block}" in html)
    check("T7 satellite(小石)は両バリアントで有効",
          "body.th-satellite .fxfield .pebble,body.th-satellite-l .fxfield .pebble{display:block}" in html)
    check("T7 wind(筋＋葉)は両バリアントで有効",
          "body.th-wind .fxfield .streak,body.th-wind-d .fxfield .streak,"
          "body.th-wind .fxfield .leaf,body.th-wind-d .fxfield .leaf{display:block}" in html)

    # --- T8: prefers-reduced-motion ---
    check("T8 prefers-reduced-motion 尊重ブロック",
          "@media (prefers-reduced-motion:reduce)" in html)

    # --- T10: h1 の👋絵文字がグラデクリップから外れている（バグ修正） ---
    check("T10 h1 の👋は .wave span で分離", 'class="wave">👋</span>' in html)
    check("T10 挨拶テキストは #greet span（JSで差し替え可能）", 'id="greet"' in html)
    check("T10 .wave は fill-color:initial でクリップ外",
          bool(re.search(r"h1 \.wave[^}]*-webkit-text-fill-color:initial", html)))

    # --- T11: 時刻対応の挨拶JS（👋 spanは保持） ---
    check("T11 時刻で挨拶を出し分けるJS(getHours)", "getHours" in html)
    check("T11 朝/昼/夜の挨拶が存在",
          all(g in html for g in ("Good morning", "Good afternoon", "Good evening")))

    # --- T12: 帯化(オレンジ帯)の再発を構造で防ぐ ---
    # 原因: -webkit-background-clip:text は「その要素の直下テキスト」にしか効かない。
    # 文字が子span(#greet / .brandtx)にあるのに gradient+clip を親(h1 / .brand)に載せると
    # 親の箱がグラデ帯で塗られ、子は透明fill継承で不可視になる。
    # 対策: gradient+clip+transparent は「文字span自身」に、親には gradient背景を置かない、fallback色を付ける。
    check("T12 h1(親箱)に gradient 背景が無い（帯を作らない）",
          re.search(r"h1\{[^}]*background(?:-image)?:linear", html) is None)
    check("T12 #greet(文字span)に gradient+clip",
          bool(re.search(r"h1 #greet[^{}]*\{[^}]*background(?:-image)?:linear[^}]*-webkit-background-clip:text", html)))
    check("T12 #greet に fallback 単色 color",
          bool(re.search(r"h1 #greet[^{}]*\{[^}]*;color:#[0-9a-fA-F]{3,6}", html)))
    check("T12 .brand(親)に gradient 背景が無い（帯を作らない）",
          re.search(r"\.brand\{[^}]*background(?:-image)?:linear", html) is None)
    # 各テーマの h1 グラデは #greet を対象（phoenixは base 規則）
    for cls in classes:
        if cls == "th-phoenix":
            continue
        check(f"T12 {cls}: h1グラデは #greet 対象",
              f"body.{cls} .head h1 #greet" in html or f"body.{cls} .main h1 #greet" in html)

    # --- T13: 左上ブランドを全テーマで画像ロゴに（brandtx は sr-only でアクセシブル名維持） ---
    # 既存の Canvaタイル画像を流用（phoenix=実ロゴ png / 他7テーマ=THEME_TILE_IMG の jpeg＝pickerと同じ）。
    # applyTheme のクラス付替でリロードなしにロゴも切替。png は CSS変数で1回だけ埋込（picker と共有）。
    # ロゴpng（cockpit-logo-sidebar.png）が無い環境では、cockpit.py は sr-only 解除でテキストブランド
    # 「Cockpit」を代わりに表示する（_brand_css）。ここもファイル有無に応じて期待値を切り替える。
    have_logo = cockpit.LOGO.exists()
    check("T13 実ロゴpngをCSS変数に1回だけ埋込" if have_logo else "T13 ロゴpngなし→CSS変数は埋め込まれない",
          (':root{--logo-png:url("data:image/png;base64,' in html) == have_logo)
    check("T13 既定(phoenix)brandlogoは実ロゴpng" if have_logo else "T13 ロゴpngなし→brandtxテキストが可視化",
          (".brandlogo{background-image:var(--logo-png)}" in html) == have_logo
          and (have_logo or "font-weight:800;font-size:20px" in html))
    for cls in classes:
        if cls == "th-phoenix":     # 黒フェニックス=実ロゴpng（存在すれば既定ルール）
            ok = (".brandlogo{background-image:var(--logo-png)}" in html) == have_logo
        else:                        # 他7テーマ=THEME_TILE_IMG の Canva タイル画像を流用（存在すれば）
            timg = cockpit.THEME_TILE_IMG.get(cls)
            has_asset = bool(timg and timg.exists())
            ok = (f'body.{cls} .brandlogo{{background-image:url("data:image/jpeg;base64,' in html) == has_asset
        check(f"T13 {cls}: brandlogo が画像を持つ", ok)
    check("T13 タイル画像アセットは全部揃うか全部無いか（部分欠落は無い＝流用元は一貫してTHEME_TILE_IMGのみ）",
          all(p.exists() for p in cockpit.THEME_TILE_IMG.values())
          or not any(p.exists() for p in cockpit.THEME_TILE_IMG.values()))
    check("T13 brandtx は sr-only（視覚非表示・可読名維持）" if have_logo else "T13 ロゴなし→brandtxを可視化(sr-only解除)",
          bool(re.search(r"\.brandtx\{[^}]*position:absolute[^}]*clip:rect", html)) if have_logo
          else "font-weight:800;font-size:20px" in html)
    check("T13 非phoenixの brandlogo 非表示ルールを撤廃",
          "body:not(.th-phoenix) .brandlogo{display:none" not in html)
    check("T13 アクセシブル名 Cockpit を維持",
          'aria-label="Cockpit"' in html and 'class="brandtx">Cockpit</span>' in html)

    # --- T9: 明暗の反転(各ペア) ---
    for cls in classes:
        avg = _bg_avg(html, cls)
        if cls in LIGHT:
            check(f"T9 {cls} は明色(--bg 輝度>180)", avg is not None and avg > 180,
                  f"({avg})")
        else:
            check(f"T9 {cls} は暗色(--bg 輝度<110)", avg is not None and avg < 110,
                  f"({avg})")

    print(f"\nTheme Verdict: {PASS}/{PASS+FAIL} → {'✅ pass' if FAIL == 0 else '❌ fail'}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
