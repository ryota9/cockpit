#!/usr/bin/env python3
"""Cockpit — a deterministic HITL sync layer between you and your coding agent.

State Store (canonical JSON) <-> Snapshot (read-only, what the agent reads).
The core is deterministic code (no LLM). Roles are split by API = the HITL gate:
  human  -> set-status / approve / reject / add / add-project ...
  agent  -> propose (only). The agent never writes canonical state directly (ADR-0006).

CLI:
  snapshot                          # compact, priority-sorted view (writes snapshot.md)
  dashboard                         # human HTML dashboard (writes dashboard.html)
  serve [port]                      # local server: 1-click approve in the browser (stdlib only)
  detail <pid>                      # deep view of one project
  list                              # all tasks
  add-project <id> "<name>" ["<goal>"] [high|mid|low]   # human: create a project
  add-phase <pid> "<name>" ["<goal>"]                   # human: append a Journey phase
  add <pid> "<desc>" [prio]         # human: add your own task (your task = owner human, todo)
  propose <pid> "<desc>"            # agent: propose a task (proposed = awaiting approval)
  approve <tid> / reject <tid>      # human: confirm / drop a proposal
  set-status <tid> <todo|done|skip|dropped>             # human
  set-priority <pid> <high|mid|low>                     # human
  set-phase <pid> <phase# from 0> <done|todo>           # human: advance the Journey
  focus <pid> [days] / unfocus <pid>                    # human: mark hot for a few days
  now [days]                        # what's hot in the next N days (default 3)
  diff [--advance]                  # agent: journal changes since the AI cursor (--advance = mark read)
  validate                          # check the canonical state for errors
"""
from __future__ import annotations
import base64
import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "edu"))
try:
    import raven as _raven   # 教育係（edu/raven.py）。無くてもCockpit本体は動く
except Exception as _e:      # noqa: BLE001
    _raven = None
STATE = HERE / "state.json"
EXAMPLE = HERE / "state.example.json"
BAK = HERE / "state.json.bak"
SNAP_MD = HERE / "snapshot.md"
DASH_HTML = HERE / "dashboard.html"
LOGO = HERE / "cockpit-logo-sidebar.png"   # phoenix golden-bird brand mark (optional; falls back to text)
BG_D = HERE / "bg-phoenix-d.jpg"           # backdrop "D" (gold/ember) — default
BG_B = HERE / "bg-phoenix-b.jpg"           # backdrop "B" (magenta/violet embers)

# Canva製のテーマ別ブランドタイル（黒フェニックス以外の7テーマ）。中央にモチーフ＋"Cockpit"文字。
# 黒フェニックス(th-phoenix)は既存の cockpit-logo-sidebar.png のまま（不変）。CSP自己完結=base64埋込。
THEME_TILE_IMG = {
    "th-phoenix-l":   HERE / "tile-phoenix-l.jpg",    # 白地に金の不死鳥
    "th-satellite":   HERE / "tile-satellite.jpg",    # 軌道・惑星（宇宙）
    "th-satellite-l": HERE / "tile-satellite-l.jpg",  # 暁の惑星
    "th-orca":        HERE / "tile-orca.jpg",         # シャチ・波（深海）
    "th-orca-l":      HERE / "tile-orca-l.jpg",        # シャチ・波（浅瀬）
    "th-wind":        HERE / "tile-wind.jpg",          # 朝の山
    "th-wind-d":      HERE / "tile-wind-d.jpg",        # 夜の山
}
# Canva製のテーマ別背景（class -> (画像, ::before の不透明度)）。黒フェニックスの炎金写真は別管理で不変。
THEME_BG_IMG = {
    "th-phoenix-l":   (HERE / "bg-phoenix-l.jpg",   0.70),  # 白地に金の羽根
    "th-satellite":   (HERE / "bg-satellite.jpg",   0.90),  # 星空
    "th-satellite-l": (HERE / "bg-satellite-l.jpg", 0.72),  # 夜明けの成層圏
    "th-orca":        (HERE / "bg-orca.jpg",        0.90),  # 濃紺の深海
    "th-orca-l":      (HERE / "bg-orca-l.jpg",      0.60),  # 明るいターコイズの浅瀬
    "th-wind":        (HERE / "bg-wind.jpg",        0.68),  # 朝もやの山
    "th-wind-d":      (HERE / "bg-wind-d.jpg",      0.90),  # 藍の夜山
}

# 着せ替えテーマ（クライアント側切替・localStorage。正本 state.json には書かない）
# phoenix が先頭＝デフォルト（王のお気に入り: 炎金背景）。CSSは DASH_CSS 末尾の上書きブロック。
# 8テーマ = 基準4 + 反対カラー4（-l=明反転 / -d=暗反転）。ペアで明↔暗が反転する。
THEMES = (("th-phoenix", "フェニックス"), ("th-phoenix-l", "白フェニックス"),
          ("th-satellite", "衛星"), ("th-satellite-l", "衛星（暁）"),
          ("th-orca", "オルカ"), ("th-orca-l", "オルカ（浅瀬）"),
          ("th-wind", "風（山）"), ("th-wind-d", "風（夜）"))

# テーマタイル（選択UI）のミニプレビュー: class -> (タイル背景, 3スウォッチ, エフェクト絵文字)
THEME_TILES = {
    "th-phoenix":     ("linear-gradient(160deg,#1a1024,#120c1d)", ("#ffc629", "#ff6a13", "#ff3d2e"), "🔥"),
    "th-phoenix-l":   ("linear-gradient(160deg,#fffaf0,#ffe9c7)", ("#e8920f", "#ff6a13", "#c0392b"), "🔥"),
    "th-satellite":   ("linear-gradient(160deg,#0d2a52,#050a16)", ("#5ec8ff", "#8f7bff", "#bfe6ff"), "🪨"),
    "th-satellite-l": ("linear-gradient(160deg,#eaf4ff,#cfe6ff)", ("#3d8fe0", "#7b8fff", "#ffd59e"), "🪨"),
    "th-orca":        ("linear-gradient(160deg,#0c3146,#04090e)", ("#6fd8ff", "#bfeafc", "#ffffff"), "🫧"),
    "th-orca-l":      ("linear-gradient(160deg,#e6f7f6,#c7ecef)", ("#0f9bb3", "#2fc6c0", "#ffca7a"), "🫧"),
    "th-wind":        ("linear-gradient(160deg,#d8e9f4,#e4efe8)", ("#2f8f76", "#5aa9d6", "#a9d8b8"), "🍃"),
    "th-wind-d":      ("linear-gradient(160deg,#131b3c,#0b1024)", ("#6f8fe0", "#3b4a86", "#8fa6d6"), "🍃"),
}

HUMAN_STATUS = {"todo", "done", "skip", "dropped"}
ALL_STATUS = HUMAN_STATUS | {"proposed"}
PRIO_ORDER = {"high": 0, "mid": 1, "low": 2}
PRIO_MARK = {"high": "🔴 High", "mid": "🟡 Mid", "low": "⚪ Low"}

# 押下→即「受け取った」を見せる受領文言（軸1: 非同期の断絶を即時フィードバックで埋める・
# docs/drift-phase-and-feedback.md §4.2）。serve が redirect の ?msg=<key> でこのキーを指し、
# dashboard の momentum(.msg)帯に出す。i18n をここ1箇所に集約＝OSS 汎用（未知キーは no-op）。
FLASH = {
    "received": "🕓 秘書の受信箱に届きました（次の点検で処理します）",
}

# ===== H1: time metadata / journal / stale (design-hub-v2 §1.2 C1-C3) =====
JOURNAL = HERE / "events.jsonl"          # append-only audit log (gitignored: private data)
STALE_THRESHOLD_DAYS = 7                 # a todo untouched longer than this is "quietly rotting"


def load_state() -> dict:
    if not STATE.exists():                       # first run: seed from the example, or start empty
        if EXAMPLE.exists():
            STATE.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            return {"projects": []}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"state.json is not valid JSON: {exc}")
    data.setdefault("projects", [])
    return data


def save_state(state: dict) -> None:
    if STATE.exists():                           # one-level backup before every write (cheap insurance)
        BAK.write_text(STATE.read_text(encoding="utf-8"), encoding="utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_task(state, tid):
    for p in state["projects"]:
        for t in p.get("tasks", []):
            if t["id"] == tid:
                return p, t
    return None, None


def _find_project(state, pid):
    return next((p for p in state["projects"] if p["id"] == pid), None)


def _next_id(state) -> str:
    nums = [int(t["id"][1:]) for p in state["projects"] for t in p.get("tasks", []) if t["id"][1:].isdigit()]
    return f"t{(max(nums) if nums else 0) + 1}"


# ===== H1: 時間メタデータ・stale判定・journal（純粋関数＝テスト容易・決定論） =====
JOURNAL = HERE / "events.jsonl"           # 追記専用の操作履歴（gitignore対象・私物）
STALE_THRESHOLD_DAYS = 7                   # これ以上更新の無い todo を「停滞」とみなす既定


def _today() -> str:
    return date.today().isoformat()


def stale_days(task: dict, now: str | None = None):
    """タスクが最後に動いてから経過した日数。時間メタが無ければ None（不明・後方互換）。"""
    ref = task.get("status_changed") or task.get("created")
    if not ref:
        return None
    try:
        d0 = date.fromisoformat(ref[:10])
        d1 = date.fromisoformat((now or _today())[:10])
    except ValueError:
        return None
    return (d1 - d0).days


def is_stale(task: dict, now: str | None = None, threshold: int = STALE_THRESHOLD_DAYS) -> bool:
    """todo のまま threshold 日以上動いていないか。時間不明・非todoは False（誤検知を出さない）。"""
    if task.get("status") != "todo":
        return False
    d = stale_days(task, now)
    return d is not None and d >= threshold


def journal_append(path, entry: dict, now: str | None = None) -> None:
    """操作を events.jsonl へ1行追記（追記専用・順序保存）。now は ISO 文字列 or None。"""
    rec = {"ts": now or datetime.now().isoformat(timespec="seconds"), **entry}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- state を直接受け取る純粋なミューテータ（I/Oなし・テストから直接呼べる） ---
def mutate_propose(state: dict, pid: str, desc: str, why: str = "", now: str | None = None,
                   group: str | None = None) -> dict:
    proj = _find_project(state, pid)
    if not proj:
        raise KeyError(f"project {pid} not found")
    ts = now or _today()
    tid = _next_id(state)
    task = {"id": tid, "desc": desc, "status": "proposed", "owner": "ai",
            "created": ts, "status_changed": ts}
    if why:
        task["why"] = why
    g = (group or "").strip()
    if g:
        task["group"] = g
    proj.setdefault("tasks", []).append(task)
    return task


def is_parked(p: dict) -> bool:
    """駐機中か。mode無し＝active（後方互換: 既存stateは挙動不変）。"""
    return p.get("mode") == "parked"


def mutate_set_mode(state: dict, pid: str, mode: str) -> dict:
    """プロジェクトの mode（active/parked）を振る。人間だけが呼ぶ（HITL）。
    WIPの明示（consult v3 P2）: 14枚の壁を「いま動かしている数枚」に畳むための正本フィールド。
    active は正規形としてキーを消す（無印=active）＝古いstateとdiffが揺れない。"""
    if mode not in ("active", "parked"):
        raise ValueError(f"mode must be active|parked; got: {mode}")
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    if mode == "parked":
        p["mode"] = "parked"
    else:
        p.pop("mode", None)
    return p


def mutate_set_status(state: dict, tid: str, status: str, now: str | None = None) -> dict:
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["status"] = status
    t["status_changed"] = now or _today()      # created は不変
    return t


# ===== phase×group結合（P5・正直な物差し）: phaseの進捗をタスクから導出する ==========
def mutate_set_phase_groups(state: dict, pid: str, idx: int, group_ids: list) -> dict:
    """phase に group を紐づける（1対多）。以後そのphaseの進捗は紐づくgroupのタスクから導出。
    記述メタデータ（set-detailと同格）。存在しないgroupは拒否＝ぶら下がり参照を作らない。"""
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    phases = p.get("phases", [])
    idx = int(idx)
    if not (0 <= idx < len(phases)):
        raise KeyError(f"{pid} phase[{idx}] not found (phases: {len(phases)})")
    known = {g["id"] for g in p.get("groups", [])}
    bad = [g for g in group_ids if g not in known]
    if bad:
        raise ValueError(f"unknown group(s) {bad} — 先に add-group で定義（known: {sorted(known)}）")
    if group_ids:
        phases[idx]["groups"] = list(group_ids)
    else:
        phases[idx].pop("groups", None)   # 空＝解除（正規形はキー無し）
    return phases[idx]


def _phase_task_progress(p: dict, phase: dict):
    """紐づくgroupのタスクで (done, total) を導出。未紐づけは None（0/0という嘘を出さない）。
    total=承認済みスコープのみ: todo+done（proposedは未承認・dropped/不要/破棄/skipは捨てた約束）。"""
    gids = phase.get("groups")
    if not gids:
        return None
    ts = [t for t in p.get("tasks", []) if t.get("group") in gids
          and t.get("status") in ("todo", "done")]
    return (sum(t["status"] == "done" for t in ts), len(ts))


# ===== read-back（P4・航空のICAO復唱）: approve→着手の引き渡しで解釈のズレを殺す ==========
def mutate_readback(state: dict, tid: str, text: str, now: str | None = None) -> dict:
    """AI: 着手時に「このタスクをこう解釈した／最初の一手はこれ」を1行で刻む。
    statusは触らない（記述メタデータ）。王はカードの💬を一瞥し、違ったら止める＝hear-back。"""
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    text = (text or "").strip()
    if not text:
        raise ValueError("readback text is empty — 解釈か最初の一手を1行で")
    t["readback"] = {"text": text[:200], "at": now or _today()}
    return t


def readback(tid, text):   # agent: CLI専用（着手の宣言・復唱）
    state = load_state()
    mutate_readback(state, tid, text)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "readback", "tid": tid})
    return f"💬 {tid} read-back 刻印（王が一瞥→違ったら止める）"


# ===== 再交渉（P3 ダークコックピット）: 腐った約束を「直すか捨てるか」の2択へ ==========
def _find_milestone(state: dict, pid: str, name: str) -> dict:
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    m = next((m for m in p.get("milestones", []) if m.get("name") == name), None)
    if not m:
        raise KeyError(f"milestone not found: {pid}/{name}")
    return m


def mutate_defer_milestone(state: dict, pid: str, name: str, expect_due: str, new_due: str) -> dict:
    """⏰ 延期: due を new_due へ。expect_due は楽観ロック（ボタン描画時の due と一致しなければ
    裏で変わっている＝拒否してリロードさせる）。done/dropped の再交渉は無意味なので拒否。"""
    m = _find_milestone(state, pid, name)
    if m.get("status") in ("done", "dropped"):
        raise ValueError(f"milestone {name} is {m.get('status')} — 再交渉の対象外")
    if m.get("due") != expect_due:
        raise ValueError(f"milestone {name} due changed ({m.get('due')} != {expect_due}) — reload")
    m["due"] = new_due
    return m


def mutate_drop_milestone(state: dict, pid: str, name: str, expect_due: str) -> dict:
    """🗑 取り下げ: status=dropped。削除はしない（何を約束して何を捨てたかは履歴）。"""
    m = _find_milestone(state, pid, name)
    if m.get("status") in ("done", "dropped"):
        raise ValueError(f"milestone {name} is already {m.get('status')}")
    if m.get("due") != expect_due:
        raise ValueError(f"milestone {name} due changed — reload")
    m["status"] = "dropped"
    return m


def _deviations(state: dict, today: str) -> list:
    """逸脱＝再交渉が必要な腐った約束の列挙（決定論・読取のみ）。
    parked は対象外（意図した眠り）。返す形: {kind, pid, pname, name, due, days}。"""
    out = []
    for p in state.get("projects", []):
        if is_parked(p):
            continue
        for m in p.get("milestones", []):
            if m.get("status") in ("done", "dropped") or not m.get("due"):
                continue
            if m["due"] < today:
                days = (date.fromisoformat(today) - date.fromisoformat(m["due"])).days
                out.append({"kind": "milestone", "pid": p["id"], "pname": p.get("name", ""),
                            "name": m.get("name", ""), "due": m["due"], "days": days})
        fu = p.get("focus_until")
        if fu and fu < today:
            days = (date.fromisoformat(today) - date.fromisoformat(fu)).days
            out.append({"kind": "focus", "pid": p["id"], "pname": p.get("name", ""),
                        "name": "focus失効", "due": fu, "days": days})
    out.sort(key=lambda d: -d["days"])   # 腐りが古い順＝一番放置された約束が先頭
    return out


# ===== 完了提案キュー（ADR-0006の"完了側"）: propose-done → 王が confirm-done ==========
# 作成の propose→approve と対称。AIは done_proposed マーカーを付けるだけで status は動かせない
# （＝完了も人間ゲート）。マーカー無し = 従来どおり（後方互換）。純粋ミューテータ（I/Oなし）。
def mutate_propose_done(state: dict, tid: str, evidence: str = "", now: str | None = None) -> dict:
    """AI: 検証済みタスクに done_proposed マーカー(evidence/at)を付ける。status は変えない
    （人間の confirm-done を待つ＝HITLゲート）。対象1タスクのみ・他は不変。"""
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["done_proposed"] = {"evidence": (evidence or "").strip(), "at": now or _today()}
    return t


def mutate_confirm_done(state: dict, tid: str, now: str | None = None) -> dict:
    """王: 完了を確定。status=done を刻印し done_proposed マーカーを消す（承認＝状態遷移）。"""
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["status"] = "done"
    t["status_changed"] = now or _today()
    t.pop("done_proposed", None)
    return t


def mutate_reject_done(state: dict, tid: str) -> dict:
    """王: 差し戻し（実は未完だった）。マーカーだけ外し status は不変＝タスクは元のまま残る。"""
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t.pop("done_proposed", None)
    return t


# ===== Grouping: task.group（任意・後方互換）と表示メタ（design-grouping.md §1-2） =====
UNGROUPED = "未分類"                             # group 無しタスクの仮想グループ（欠測に強い既定）


def mutate_set_group(state: dict, tid: str, group: str | None, now: str | None = None) -> dict:
    """タスクにグループを付与/除去する純粋ミューテータ（対象1件のみ・group は status と直交）。
    group が空/None なら group キーを外して『未分類』へ。status_changed は刻印しない（規約踏襲）。"""
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    g = (group or "").strip()
    if g:
        t["group"] = g
    else:
        t.pop("group", None)
    return t


def mutate_add_group(state: dict, pid: str, gid: str, name: str, order=None) -> dict:
    """プロジェクトに group 表示メタ（id/name/order）を追加・更新（任意・欠測に強い）。"""
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    groups = p.setdefault("groups", [])
    existing = next((g for g in groups if g.get("id") == gid), None)
    if existing:
        existing["name"] = name
        if order is not None:
            existing["order"] = int(order)
    else:
        groups.append({"id": gid, "name": name, "order": int(order) if order is not None else len(groups) + 1})
    return p


def group_tasks(project: dict):
    """プロジェクトのタスクをグループ順に束ねる（決定論・data-agnostic）。
    順序: groups[].order の定義済み → メタ無しスラグ(昇順) → 未分類(最後)。
    戻り値: [{"id": slug|None, "name": 表示名, "tasks": [...]}]（各タスクはちょうど1グループに属す）。"""
    meta = {g.get("id"): g for g in project.get("groups", []) if g.get("id")}
    buckets: dict = {}
    seen = []                                   # 出現順を保持（決定論）
    for t in project.get("tasks", []):
        gid = t.get("group") or None
        if gid not in buckets:
            buckets[gid] = []
            seen.append(gid)
        buckets[gid].append(t)
    defined = sorted([g for g in seen if g is not None and g in meta],
                     key=lambda g: (meta[g].get("order", 10 ** 9), g))
    undefined = sorted([g for g in seen if g is not None and g not in meta])
    ordered = defined + undefined + ([None] if None in buckets else [])
    out = []
    for gid in ordered:
        name = UNGROUPED if gid is None else (meta[gid].get("name", gid) if gid in meta else gid)
        out.append({"id": gid, "name": name, "tasks": buckets[gid]})
    return out


def _filter_state_by_group(state: dict, group: str) -> dict:
    """group 縮約用: 指定グループのタスクだけを残した state のシャロー複製（他グループ行を落とす）。"""
    out = {"projects": []}
    for p in state.get("projects", []):
        tasks = [t for t in p.get("tasks", []) if (t.get("group") or None) == (group or None)]
        if tasks:
            np = dict(p)
            np["tasks"] = tasks
            out["projects"].append(np)
    return out


def validate(state) -> list:
    errs, ids = [], []
    for p in state.get("projects", []):
        if p.get("priority") not in (None, "high", "mid", "low"):
            errs.append(f'{p["id"]}: invalid priority {p.get("priority")}')
        for t in p.get("tasks", []):
            ids.append(t.get("id"))
            if t.get("status") not in ALL_STATUS:
                errs.append(f'{t.get("id")}: invalid status {t.get("status")}')
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        errs.append(f"duplicate task ids: {dup}")
    return errs


# --- derived ---
def _phase_progress(p):
    phs = p.get("phases", [])
    done = sum(1 for ph in phs if ph.get("status") == "done")
    cur = next((ph for ph in phs if ph.get("status") != "done"), None)
    label = f'{cur["name"]} — {cur["goal"]}' if cur else "(all phases done)"
    return label, done, len(phs)


def _next_due(p):
    # dropped（取り下げた約束）は期限計算から外す — 取り下げたのに🚨OVERDUEが残ると再交渉の意味がない
    dues = [m["due"] for m in p.get("milestones", []) if m.get("status") not in ("done", "dropped") and m.get("due")]
    dues += [t["due"] for t in p.get("tasks", []) if t.get("status") == "todo" and t.get("due")]
    return min(dues) if dues else None


def _todos(p):
    return [t for t in p.get("tasks", []) if t.get("status") == "todo"]


def _next_task(p):
    ts = sorted(_todos(p), key=lambda t: (PRIO_ORDER.get(t.get("priority", "mid"), 1), t.get("due") or "9999"))
    return ts[0] if ts else None


def _next_action(p):
    t = _next_task(p)
    return f'{t["id"]}: {t["desc"]}' if t else None


def _sorted_projects(state):
    # parked は常に最後（受信箱・カード・snapshot節すべてで「いま動かすもの」が先に来る）
    return sorted(state["projects"],
                  key=lambda p: (is_parked(p), PRIO_ORDER.get(p.get("priority", "mid"), 1), _next_due(p) or "9999"))


# --- Snapshot (the thin layer the agent reads) ---
def snapshot_project(p):
    phase, dn, tot = _phase_progress(p)
    cur_ph = next((ph for ph in p.get("phases", []) if ph.get("status") != "done"), None)
    ptp = _phase_task_progress(p, cur_ph) if cur_ph else None
    return {
        "id": p["id"], "name": p["name"], "goal": p.get("north_star", ""),
        "priority": p.get("priority", "mid"), "parked": is_parked(p),
        "phase_tasks": f"{ptp[0]}/{ptp[1]}" if ptp else None,
        "phase": phase, "phase_progress": f"{dn}/{tot}" if tot else "—",
        "next_due": _next_due(p), "next_action": _next_action(p),
        "open_tasks": [f'{t["id"]}: {t["desc"]}' for t in _todos(p)],
        "proposed": [f'{t["id"]}: {t["desc"]}' for t in p.get("tasks", []) if t.get("status") == "proposed"],
    }


def make_snapshot(state, group=None):
    """全体スナップショット。group 指定時はそのグループのタスクだけに縮約（AIのトークン節約・§3.2）。"""
    src = _filter_state_by_group(state, group) if group else state
    snap = {"generated": str(date.today()), "projects": [snapshot_project(p) for p in _sorted_projects(src)]}
    if group:
        snap["group"] = group
    return snap


def render_snapshot_md(snap, state=None, group=None) -> str:
    title = f"# Cockpit Snapshot ({snap['generated']} · read-only · by priority"
    title += f" · group={group})" if group else ")"
    out = [title,
           "> The agent reads this. Deep info: `detail <pid>`. Changes: agent proposes -> human approves.",
           "> 着手時の作法: `readback <tid> \"解釈 or 最初の一手を1行\"` を刻んでから始める（王が💬を一瞥＝復唱確認）。", ""]
    # 受信箱: プロジェクト見出し＋意図1行（P4 commander's intent — 何のためのタスクかを添えて自走の質を上げる）。
    # active優先・parked後置🅿（P2）。見出しに ## は使わない（セクション構造を壊さない）。
    by_proj = []
    for p in _sorted_projects(state or {"projects": []}):
        ts = [t for t in p.get("tasks", []) if t.get("owner") == "ai" and t.get("status") == "todo"
              and (group is None or (t.get("group") or None) == group)]
        if ts:
            by_proj.append((p, ts))
    if by_proj:
        out.append("## 🤖 Ready for the agent (approved, owner=ai todos = my inbox)")
        for p, ts in by_proj:
            pk = "🅿 " if is_parked(p) else ""
            intent = " → ".join(x for x in (p.get("north_star") and f"🎯 {p['north_star']}",
                                            p.get("done_def") and f"🏁 {p['done_def']}") if x)
            out.append(f"**{pk}[{p['id']}] {p['name']}** {intent}".rstrip())
            # detail未記載マーカー: 実行前に手順を書く運用（王FB: 手順はAIの仕事）を毎セッション想起させる
            out += [f"- {pk}{t['id']}: {t['desc']}"
                    + (f"  ｜💬 {t['readback']['text']}" if t.get("readback") else "")
                    + ("" if t.get("detail") else "  ※detail未記載→着手前に set-detail で手順を書く")
                    for t in ts]
        out.append("")
    # ✅🕓 完了確認待ち（done-proposed）: AIが検証済みで王の confirm-done 待ち。王/エージェント双方に可視化。
    done_prop = [(p["id"], t) for p in (state or {}).get("projects", [])
                 for t in p.get("tasks", []) if t.get("done_proposed")
                 and (group is None or (t.get("group") or None) == group)]
    if done_prop:
        out.append("## ✅🕓 Done-proposed (awaiting the king's confirm-done)")
        for pid, t in done_prop:
            ev = (t["done_proposed"] or {}).get("evidence", "")
            out.append(f"- [{pid}] {t['id']}: {t['desc']}" + (f"  — 証跡: {ev}" if ev else ""))
        out.append("")
    for p in snap["projects"]:
        due = f" | due {p['next_due']}" if p["next_due"] else ""
        pk = "🅿 " if p.get("parked") else ""
        out.append(f"## {PRIO_MARK.get(p['priority'],'')} {pk}{p['name']} ({p['id']}){due}")
        out.append(f"- Goal: {p['goal']}")
        out.append(f"- phase({p['phase_progress']}): {p['phase']}"
                   + (f"  [{p['phase_tasks']} tasks]" if p.get("phase_tasks") else ""))
        if p["next_action"]:
            out.append(f"- 👉 next: {p['next_action']}")
        out.append("- open (todo): " + (", ".join(p["open_tasks"]) if p["open_tasks"] else "none"))
        if p["proposed"]:
            out.append("- 🟡 awaiting approval: " + ", ".join(p["proposed"]))
        out.append("")
    return "\n".join(out)


def emit_snapshot(state=None) -> dict:
    state = state or load_state()
    snap = make_snapshot(state)
    SNAP_MD.write_text(render_snapshot_md(snap, state), encoding="utf-8")
    DASH_HTML.write_text(render_dashboard(state), encoding="utf-8")
    return snap


def detail(pid) -> str:
    """Deep view of one project (on demand = read only the project you need = saves tokens)."""
    state = load_state()
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    phase, dn, tot = _phase_progress(p)
    o = [f"# {p['name']} ({p['id']})  priority: {PRIO_MARK.get(p.get('priority','mid'),'')}",
         f"- Goal: {p.get('north_star','')}",
         f"- phase({dn}/{tot}): {phase}",
         f"- next due: {_next_due(p) or 'none'}",
         f"- repo: {p.get('repo','—')}",
         f"- deps: {', '.join(p.get('depends_on', [])) or 'none'}",
         f"- done def: {p.get('done_def','—')}",
         "- tasks:"]
    for t in p.get("tasks", []):
        extra = " ".join(filter(None, [f"[{t['priority']}]" if t.get("priority") else "", f"due {t['due']}" if t.get("due") else ""]))
        o.append(f"    [{t['status']:>8}] {t['id']}: {t['desc']}  ({t.get('owner','?')}) {extra}")
    return "\n".join(o)


# --- mutations (deterministic · HITL gate) ---
def add_project(pid, name, goal="", prio="mid"):   # human: create a project
    if prio not in PRIO_ORDER:
        raise ValueError(f"priority must be one of {list(PRIO_ORDER)}; got: {prio}")
    state = load_state()
    if _find_project(state, pid):
        raise ValueError(f"project {pid} already exists")
    state["projects"].append({
        "id": pid, "name": name, "north_star": goal, "priority": prio,
        "repo": "", "depends_on": [], "done_def": "",
        "phases": [], "milestones": [], "tasks": []})
    save_state(state); emit_snapshot(state)
    return f"✅ project {pid} created: {name}  (add phases with: add-phase {pid} \"Phase 0\" \"...\")"


def add_phase(pid, name, goal=""):   # human: append a Journey phase
    state = load_state()
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    p.setdefault("phases", []).append({"name": name, "goal": goal, "status": "todo"})
    save_state(state); emit_snapshot(state)
    return f"✅ {pid} phase added: {name}"


def set_status(tid, status):
    if status not in HUMAN_STATUS:
        raise ValueError(f"humans can set {sorted(HUMAN_STATUS)} (proposed is agent-only). got: {status}")
    state = load_state()
    mutate_set_status(state, tid, status)          # status_changed を刻印（stale計測の起点）
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "set-status", "tid": tid, "to": status})
    return f"✅ {tid} → {status}"


def defer_milestone(pid, name, expect_due, days=14):   # human: renegotiate a rotten promise (⏰)
    state = load_state()
    new_due = (date.today() + timedelta(days=int(days))).isoformat()
    mutate_defer_milestone(state, pid, name, expect_due, new_due)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "ms-defer", "pid": pid, "to": new_due})
    return f"⏰ {pid}「{name}」→ {new_due} に延期"


def drop_milestone(pid, name, expect_due):   # human: withdraw a promise (🗑, keeps history)
    state = load_state()
    mutate_drop_milestone(state, pid, name, expect_due)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "ms-drop", "pid": pid})
    return f"🗑 {pid}「{name}」を取り下げ（履歴は残る）"


def set_phase_groups(pid, idx, groups_csv=""):   # link a phase to groups → progress derived from tasks (P5)
    state = load_state()
    gids = [g.strip() for g in groups_csv.split(",") if g.strip()]
    ph = mutate_set_phase_groups(state, pid, idx, gids)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "set-phase-groups", "pid": pid})
    return (f"🔗 {pid} phase[{idx}]「{ph.get('name','')}」 ← groups {gids}" if gids
            else f"🔗 {pid} phase[{idx}] の紐づけを解除")


def set_mode(pid, mode):   # human: park / reactivate a project (WIP management)
    state = load_state()
    mutate_set_mode(state, pid, mode)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "set-mode", "pid": pid, "to": mode})
    return f"{'🅿' if mode == 'parked' else '▶'} {pid} → {mode}"


def set_detail(tid, text):   # author a task's concrete next-steps (descriptive metadata, not a status gate)
    state = load_state(); _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["detail"] = text.replace("\\n", "\n"); save_state(state); emit_snapshot(state)
    return f"✅ {tid} detail set ({len([s for s in t['detail'].splitlines() if s.strip()])} step(s))"


def set_overview(pid, text):   # one-paragraph project overview so the modal replaces reading raw md (#4)
    state = load_state(); p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    p["overview"] = text; save_state(state); emit_snapshot(state)
    return f"✅ {pid} overview set"


def add_doc(pid, label, path):   # attach a doc link (label + path) shown in the project modal (#4)
    state = load_state(); p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    p.setdefault("docs", []).append({"label": label, "path": path}); save_state(state); emit_snapshot(state)
    return f"✅ {pid} doc added: {label} → {path}"


def propose(pid, desc, why="", group=None):
    state = load_state()
    t = mutate_propose(state, pid, desc, why=why, group=group)   # created/status_changed/why を刻印・HITLゲート不変
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "propose", "tid": t["id"], "pid": pid, "why": why})
    tail = (f"  [why: {why}]" if why else "") + (f"  [group: {t['group']}]" if t.get("group") else "")
    return f"🟡 proposed {t['id']} (awaiting approval): {desc}" + tail


def add_task(pid, desc, prio=None, group=None):   # human: add your own task (agent-uninvolved = owner human todo)
    state = load_state()
    proj = _find_project(state, pid)
    if not proj:
        raise KeyError(f"project {pid} not found")
    tid = _next_id(state)
    ts = _today()
    t = {"id": tid, "desc": desc, "status": "todo", "owner": "human",
         "created": ts, "status_changed": ts}
    if prio in PRIO_ORDER:
        t["priority"] = prio
    g = (group or "").strip()
    if g:
        t["group"] = g
    proj.setdefault("tasks", []).append(t)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "add", "tid": tid, "pid": pid})
    return f"✅ added {tid} (your task · todo): {desc}" + (f"  [group: {g}]" if g else "")


def set_group(tid, group):   # human/agent: attach or clear a task's group (I/O wrapper · ADR-0006)
    state = load_state()
    mutate_set_group(state, tid, group)
    save_state(state); emit_snapshot(state)
    g = (group or "").strip()
    journal_append(JOURNAL, {"op": "set-group", "tid": tid, "group": g or None})
    return f"✅ {tid} group → {g}" if g else f"✅ {tid} group cleared (未分類)"


def mutate_set_owner(state: dict, tid: str, owner: str) -> dict:
    if owner not in ("ai", "human"):
        raise ValueError(f"owner must be ai|human, got {owner!r}")
    _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["owner"] = owner
    return t


def set_owner(tid, owner):   # human: reassign who owns a task (🤖 ai ⇄ 👤 human) · ADR-0006
    state = load_state()
    mutate_set_owner(state, tid, owner)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "set-owner", "tid": tid, "owner": owner})
    return f"✅ {tid} owner → {owner}"


def add_group(pid, gid, name, order=None):   # define a group's display meta (name/order) on a project
    state = load_state()
    mutate_add_group(state, pid, gid, name, order)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "add-group", "pid": pid, "gid": gid})
    return f"✅ {pid} group '{gid}' → {name}"


def approve(tid):
    state = load_state(); _, t = _find_task(state, tid)
    if not t or t.get("status") != "proposed":
        raise ValueError(f"{tid} is not proposed")
    mutate_set_status(state, tid, "todo"); save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "approve", "tid": tid})
    return f"✅ approved {tid} → todo"


def reject(tid):
    state = load_state(); _, t = _find_task(state, tid)
    if not t or t.get("status") != "proposed":
        raise ValueError(f"{tid} is not proposed")
    mutate_set_status(state, tid, "dropped"); save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "reject", "tid": tid})
    return f"🗑 rejected {tid} → dropped"


# --- 完了提案の I/O ラッパ（ADR-0006: LLMは正本を直接書かず決定論アダプタ経由のみ） ---
def propose_done(tid, evidence=""):   # agent: 検証済みタスクを「完了確認待ち」にする（status不変・CLI専用）
    state = load_state()
    t = mutate_propose_done(state, tid, evidence)   # done_proposed マーカーのみ・人間ゲート維持
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "propose-done", "tid": tid, "why": evidence})
    tail = f"  [evidence: {t['done_proposed']['evidence']}]" if t["done_proposed"]["evidence"] else ""
    return f"✅🕓 done-proposed {tid} (awaiting the king's confirm): {t['desc']}" + tail


def confirm_done(tid):   # human: 完了を確定（HITLゲート＝ここだけが done への遷移を許す）
    state = load_state(); _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    mutate_confirm_done(state, tid); save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "confirm-done", "tid": tid})
    return f"✅ confirmed {tid} → done"


def reject_done(tid):   # human: 差し戻し（実は未完だった）。マーカーだけ外す＝タスクは残る
    state = load_state(); _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    mutate_reject_done(state, tid); save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "reject-done", "tid": tid})
    return f"↩ done-proposal for {tid} sent back (still open)"


def undo():   # human: revert the last state-changing action (one level, from the auto-backup)
    # save_state() writes state.json.bak before every write, so the backup always holds the
    # state from *before* the last action. Restoring it = a single-step undo. We restore the file
    # directly (not via save_state), so the backup is left intact and a second undo is a safe no-op.
    if not BAK.exists():
        return "↩ nothing to undo"
    STATE.write_text(BAK.read_text(encoding="utf-8"), encoding="utf-8")
    emit_snapshot(load_state())
    return "↩ reverted the last change"


def set_phase(pid, idx, status):   # human: advance a Journey phase
    if status not in ("done", "todo"):
        raise ValueError("phase status must be done/todo")
    state = load_state()
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    phs = p.get("phases", [])
    i = int(idx)
    if not (0 <= i < len(phs)):
        raise IndexError(f"phase index must be 0..{len(phs) - 1}")
    phs[i]["status"] = status
    save_state(state); emit_snapshot(state)
    return f"✅ {pid} phase[{i}] {phs[i]['name']} → {status}"


def set_priority(pid, prio):   # human: strategic priority
    if prio not in PRIO_ORDER:
        raise ValueError(f"priority must be one of {list(PRIO_ORDER)}; got: {prio}")
    state = load_state()
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    p["priority"] = prio; save_state(state); emit_snapshot(state)
    return f"✅ {pid} priority → {prio}"


def focus(pid, days=3):   # human: mark hot for a few days (urgency not captured by due dates)
    state = load_state()
    p = _find_project(state, pid)
    if not p:
        raise KeyError(f"project {pid} not found")
    until = (date.today() + timedelta(days=int(days))).isoformat()
    p["focus_until"] = until; save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "focus", "pid": pid, "to": until})   # 誰がいつ点けたか追える（2026-07-12の教訓）
    return f"🔥 {pid} focused (until {until})"


def unfocus(pid):
    state = load_state()
    p = _find_project(state, pid)
    if p and p.pop("focus_until", None) is not None:
        save_state(state); emit_snapshot(state)
        journal_append(JOURNAL, {"op": "unfocus", "pid": pid})
    return f"focus cleared {pid}"


def near_term(p, days=3) -> bool:
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=days)).isoformat()
    nd = _next_due(p)
    return (nd is not None and nd <= horizon) or (p.get("focus_until", "") >= today and p.get("focus_until"))


def now_view(days=3) -> str:
    days = int(days)
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=days)).isoformat()
    hot = [p for p in _sorted_projects(load_state()) if near_term(p, days)]
    out = [f"# 🔥 Focus — next {days} days ({date.today()})", ""]
    if not hot:
        out.append("(nothing due soon or focused)")
    for p in hot:
        why = []
        nd = _next_due(p)
        if nd and nd <= horizon:
            why.append(f"due {nd}")
        if p.get("focus_until", "") >= today and p.get("focus_until"):
            why.append(f"focus until {p['focus_until']}")
        out.append(f"## {PRIO_MARK.get(p.get('priority','mid'),'')} {p['name']} ({p['id']})  [{' / '.join(why)}]")
        out.append(f"- 👉 {_next_action(p) or 'none'}")
        out.append("")
    return "\n".join(out)


# ===== Dashboard (human HTML · Simple theme · auto-generated from state.json) =====
DASH_CSS = (
    "<style>*{box-sizing:border-box}"
    ":root{--bg:#0a0710;--surface:#181222;--surface2:#211733;--ink:#f6ecd6;--muted:#a99a86;--line:#3a2d4d;--accent:#ffc629;--accent2:#ff6a13;--ember:#ff3d2e;--hi:#ff3b6b;--mid:#ffa726;--low:#7d7489;--radius:16px;--shadow:0 8px 28px rgba(0,0,0,.55),0 0 0 1px rgba(255,198,41,.04)}"
    "body{margin:0;font-family:'Hiragino Sans','Yu Gothic UI','Noto Sans JP',system-ui,sans-serif;color:var(--ink);background:radial-gradient(1100px 700px at 12% -8%,#3a1206 0%,transparent 55%),radial-gradient(900px 600px at 92% 0%,#2a0a3d 0%,transparent 50%),radial-gradient(1200px 800px at 50% 120%,#1a0530 0%,transparent 60%),var(--bg);background-attachment:fixed}"
    ".wrap{display:grid;grid-template-columns:210px 1fr;min-height:100vh}"
    ".side{padding:18px 14px;border-right:1px solid var(--line);background:#ffffffaa}.brand{font-weight:800;font-size:20px;margin:4px 8px 18px}"
    ".nav a{display:block;padding:10px 12px;border-radius:12px;color:var(--ink);text-decoration:none;font-size:14px;margin-bottom:4px;opacity:.85}.nav a.active{background:#2563eb26;color:var(--accent);font-weight:700}"
    ".main{padding:20px 26px}.head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}.head h1{font-size:22px;margin:0}.date{color:var(--muted);font-size:13px}"
    ".momentum{display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:linear-gradient(90deg,#eef4ff,#fff);border:1px solid var(--line);border-radius:14px;padding:12px 18px;margin-bottom:22px}"
    ".momentum .big{font-size:22px;font-weight:800;color:var(--accent)}.momentum .lbl{font-size:12px;color:var(--muted)}.momentum .sep{width:1px;height:30px;background:var(--line)}.momentum .msg{margin-left:auto;font-weight:700}"
    ".momentum .msg.flash{color:var(--accent);font-weight:800;animation:flashin .32s ease-out}@keyframes flashin{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}"
    ".pulsecard{background:var(--panel,#fff);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:18px}"
    ".pulserow{display:flex;gap:10px;align-items:center;padding:5px 0;border-bottom:1px dashed var(--line)}.pulserow:last-of-type{border-bottom:none}"
    ".pulserow .pulsename{flex:1;font-size:13px;font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
    ".pulserow .pulsenum{font-size:12.5px;font-weight:700;white-space:nowrap}.pulserow svg{flex-shrink:0}"
    ".parkedwrap{background:var(--panel,#fff);border:1px solid var(--line);border-radius:14px;padding:6px 16px;opacity:.75}"
    ".parkedrow{display:flex;gap:10px;align-items:center;padding:7px 0;border-bottom:1px dashed var(--line)}.parkedrow:last-child{border-bottom:none}"
    ".parkedrow .nm{flex:1;font-size:13px;font-weight:600}.parkedrow .id{font-size:11px;color:var(--muted)}"
    ".devcard{background:linear-gradient(90deg,rgba(192,57,43,.07),transparent 60%);border:1px solid rgba(192,57,43,.35);border-left:4px solid #c0392b;border-radius:14px;padding:12px 16px;margin-bottom:18px}"
    ".devtitle{font-size:13.5px;font-weight:800;color:#c0392b;margin-bottom:4px}"
    ".devrow{display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px dashed var(--line)}.devrow:last-child{border-bottom:none}"
    ".devrow .devname{flex:1;font-size:13px;font-weight:600;min-width:0}.devrow .devdays{font-size:12px;font-weight:800;color:#c0392b;white-space:nowrap}"
    ".sectitle{font-size:14px;color:var(--muted);font-weight:700;margin:6px 2px 10px}"
    ".now{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px}.nowcard{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--hi);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow)}"
    ".nowcard .why{font-size:12px;color:var(--hi);font-weight:700;min-height:16px}.nowcard .nm{font-weight:800;margin:3px 0 8px}.nowcard .act{font-size:13px}.nowcard code{background:#2563eb12;color:var(--accent);padding:2px 6px;border-radius:5px;font-size:12px}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:15px 16px;box-shadow:var(--shadow)}"
    ".card .top{display:flex;align-items:center;gap:8px;margin-bottom:6px}.dot{width:9px;height:9px;border-radius:50%}.dot.high{background:var(--hi)}.dot.mid{background:var(--mid)}.dot.low{background:var(--low)}"
    ".nm{font-weight:800;font-size:15px}.id{margin-left:auto;font-size:11px;color:var(--muted)}.goal{font-size:12px;color:var(--muted);min-height:32px;margin:0 0 8px}.ph{font-size:12px;margin-bottom:8px}"
    ".next{font-size:13px;background:#2563eb17;border-radius:8px;padding:6px 8px;margin-bottom:8px}.bar{height:6px;border-radius:6px;background:var(--line);overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2))}"
    ".due{font-size:11px;color:var(--muted);margin-top:7px}.foot{margin-top:20px;color:var(--muted);font-size:11px}"
    ".card{cursor:pointer;transition:box-shadow .12s,transform .12s}.card:hover{box-shadow:0 12px 30px rgba(31,45,61,.16);transform:translateY(-1px)}.cdetail{display:none}"
    ".jrow{display:flex;gap:3px;align-items:center;margin:8px 0 6px}.seg{height:7px;flex:1;border-radius:3px;background:var(--line)}.seg.done{background:var(--accent2)}.seg.cur{background:repeating-linear-gradient(45deg,var(--accent) 0 3px,transparent 3px 6px),var(--line)}.jlbl{font-size:11px;color:var(--muted);margin-left:6px;white-space:nowrap}"
    ".detail{padding:4px 16px 16px;font-size:13px}.jfull{margin:6px 0 8px}.jstep{padding:4px 0 4px 10px;border-left:3px solid var(--line);margin-left:2px}.jstep.done{border-color:var(--accent2);color:var(--muted)}.jstep.cur{border-color:var(--accent);font-weight:700}.jstep.future{color:var(--muted)}.jgoal{padding:6px 0 2px 13px;color:var(--accent);font-weight:700}"
    ".ato{background:#2563eb0d;border-radius:8px;padding:7px 10px;margin:6px 0;font-size:12px}.tl{margin:8px 0}.tl b{font-size:12px;color:var(--muted)}.ti{padding:3px 0}.meta{font-size:11px;color:var(--muted);margin-top:8px;border-top:1px dashed var(--line);padding-top:8px}.apr-wrap{margin-bottom:24px}.apr{display:flex;justify-content:space-between;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--mid);border-radius:12px;padding:11px 14px;margin-bottom:8px;font-size:13px}.apr code{background:#0f1f33;color:#d6e6ff;padding:5px 9px;border-radius:6px;font-size:12px;white-space:nowrap}.apr-empty{color:var(--muted);font-size:13px}.apr.work{border-left-color:var(--accent)}.apr.donep{border-left-color:#22c55e;background:linear-gradient(90deg,#22c55e0f,var(--surface))}.dpbadge{display:inline-block;background:#22c55e;color:#04210f;font-size:11px;font-weight:800;padding:2px 8px;border-radius:999px;margin-right:6px;vertical-align:middle}.page{display:none}.page.active{display:block}.kpi{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;margin-bottom:22px}.kpi .box{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow)}.kpi .n{font-size:26px;font-weight:800;color:var(--accent)}.kpi .l{font-size:12px;color:var(--muted)}.kblock{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px;box-shadow:var(--shadow)}.kbar{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}.kbar .bn{width:96px;color:var(--muted)}.kbar .bt{flex:1;height:14px;background:var(--line);border-radius:7px;overflow:hidden}.kbar .bt i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2))}.kbar .bv{width:40px;text-align:right;font-weight:700}.setbox{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:var(--shadow);font-size:13px;line-height:1.8}.setbox code{background:#2563eb12;color:var(--accent);padding:2px 6px;border-radius:5px;font-size:12px}.act-f{display:inline}.btn{cursor:pointer;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:5px 11px;font-size:12px;font-weight:700;margin-right:6px}.btn:hover{filter:brightness(.97)}.btn.ok{background:var(--accent);color:#fff;border-color:var(--accent)}.btn.no{color:var(--hi);border-color:#f3c9d2}.btn.ph{background:var(--accent2);color:#fff;border-color:var(--accent2);font-size:11px;padding:3px 9px;margin-left:10px}.ov{position:fixed;inset:0;background:rgba(15,23,42,.45);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:none;align-items:flex-start;justify-content:center;padding:48px 20px;z-index:50;overflow:auto}.ov.open{display:flex}.modal{background:var(--surface);border-radius:18px;max-width:720px;width:100%;padding:26px 30px;box-shadow:0 24px 70px rgba(0,0,0,.3);position:relative;animation:pop .14s ease-out}@keyframes pop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}.modal .mhead{font-size:20px;font-weight:800;margin:0 0 14px;padding-right:30px}.modal .jstep{font-size:14px;padding:6px 0 6px 12px}.modal .jgoal{font-size:14px}.modal .ti{padding:5px 0;font-size:14px}.modal .ato{font-size:13px}.modal .tl b{font-size:13px}.modal .meta{font-size:12px}.mx{position:absolute;top:12px;right:16px;border:none;background:transparent;font-size:26px;line-height:1;cursor:pointer;color:var(--muted)}.mx:hover{color:var(--ink)}.hint{color:var(--muted);font-size:11px;font-weight:400}.cmds{margin-top:8px}.cmds div{margin:6px 0;font-size:12px;color:var(--muted)}.cmds code{background:#0f1f33;color:#d6e6ff;padding:3px 7px;border-radius:5px;font-size:12px}.cmd{cursor:pointer}.cmd:hover{filter:brightness(1.25)}"
    # ===== PHOENIX GOLDEN BIRD: ultimate skin (override) =====
    "@keyframes phx-shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}"
    "@keyframes phx-pulse{0%,100%{box-shadow:0 0 0 0 rgba(255,59,107,.55)}50%{box-shadow:0 0 0 7px rgba(255,59,107,0)}}"
    "@keyframes phx-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}"
    "@keyframes phx-flow{0%{background-position:0% 50%}100%{background-position:200% 50%}}"
    ".side{background:linear-gradient(180deg,#1a1024,#120c1d)!important;border-right:1px solid var(--line)!important;box-shadow:1px 0 24px rgba(255,106,19,.06)}"
    # 親(.brand)にはグラデ背景を載せない。-webkit-background-clip:text は「その要素の直下テキスト」に
    # しか効かず、文字は子span(.brandtx)にあるため、親に載せると箱全体がオレンジ帯化＋文字が透明で消える。
    # グラデ＋clip＋transparent＋fallback単色は .brandtx 自身に載せる（下の .brandtx 規則）。
    ".brand{font-size:21px!important;background:none;text-shadow:0 0 18px rgba(255,106,19,.25)}"
    ".brand::after{content:' \\1F525\\1F426';-webkit-text-fill-color:initial;font-size:15px;display:inline-block;animation:phx-float 2.6s ease-in-out infinite}"
    ".brand:has(.brandlogo)::after{content:none}"
    # 全テーマで画像ロゴを表示する div（背景画像はテーマ毎に _brand_css で切替）。正方タイルが崩れないよう aspect 1:1。
    ".brandlogo{width:100%;max-width:188px;aspect-ratio:1/1;display:block;margin:0 auto 6px;border-radius:16px;background-size:contain;background-position:center;background-repeat:no-repeat;box-shadow:0 0 28px rgba(255,106,19,.30),inset 0 0 0 1px rgba(255,198,41,.18);animation:phx-float 3.6s ease-in-out infinite}"
    ".bgbtn{margin:14px 8px 0;width:calc(100% - 16px);cursor:pointer;border:1px solid rgba(255,198,41,.28);background:linear-gradient(160deg,var(--surface2),var(--surface));color:var(--ink);border-radius:10px;padding:8px 10px;font-size:12px;font-weight:700;transition:filter .15s,box-shadow .15s}.bgbtn:hover{filter:brightness(1.12);box-shadow:0 0 16px rgba(255,106,19,.3)}.bgbtn #bglabel{color:var(--accent)}"
    ".nav a.active{background:linear-gradient(90deg,rgba(255,198,41,.22),rgba(255,106,19,.10))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent2)}"
    ".nav a:hover{background:rgba(255,198,41,.07)}"
    # 挨拶グラデは h1(親箱)ではなく #greet(文字span自身)に載せる（clip:text は直下テキスト限定のため、
    # 親に載せると箱がオレンジ帯化＋#greetは透明fillで不可視になる）。h1 は背景なし・fallback単色付き。
    ".main h1,.head h1{background:none}"
    ".main h1 #greet,.head h1 #greet{background-image:linear-gradient(92deg,#ffe9a8,#ffc629);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#ffc629}"
    # 👋絵文字はグラデ text-clip の対象外（.wave は #greet の兄弟なので元々クリップされないが、明示的に保険）
    ".main h1 .wave,.head h1 .wave{-webkit-text-fill-color:initial;-webkit-background-clip:border-box;background-clip:border-box;background:none}"
    ".momentum{background:linear-gradient(100deg,rgba(255,61,46,.14),rgba(255,106,19,.05) 45%,rgba(42,10,61,.2))!important;border:1px solid rgba(255,198,41,.22)!important;box-shadow:0 0 30px rgba(255,106,19,.08),inset 0 1px 0 rgba(255,255,255,.04)}"
    ".momentum .big{color:var(--accent)!important;text-shadow:0 0 14px rgba(255,198,41,.45)}"
    ".card,.kblock,.kpi .box,.setbox,.nowcard,.apr{background:linear-gradient(160deg,var(--surface2),var(--surface))!important}"
    ".card:hover{box-shadow:0 14px 40px rgba(0,0,0,.6),0 0 22px rgba(255,106,19,.22)!important;border-color:rgba(255,198,41,.35)!important}"
    ".nowcard{border-left-width:4px}.nowcard:hover{box-shadow:0 0 26px rgba(255,59,107,.25)}"
    ".kpi .n{color:var(--accent)!important;text-shadow:0 0 16px rgba(255,198,41,.4)}"
    ".dot.high{background:var(--hi)!important;animation:phx-pulse 1.8s ease-out infinite}"
    ".bar i,.kbar .bt i,.seg.done{background:linear-gradient(90deg,#ffc629,#ff6a13,#ff3d2e,#ffc629)!important;background-size:200% auto;animation:phx-flow 3s linear infinite}"
    ".next{background:rgba(255,198,41,.10)!important;border:1px solid rgba(255,198,41,.18)}"
    ".nowcard code,.setbox code,.nowcard .act code{background:rgba(255,198,41,.12)!important;color:var(--accent)!important}"
    ".btn.ok{background:linear-gradient(92deg,#ffc629,#ff6a13)!important;border-color:transparent!important;color:#1a0a02!important;box-shadow:0 3px 14px rgba(255,106,19,.35)}"
    ".btn.ph{background:linear-gradient(92deg,#ff6a13,#ff3d2e)!important;border-color:transparent!important;color:#fff!important}"
    ".btn{background:var(--surface2);color:var(--ink)}.btn.no{background:var(--surface2);color:var(--hi);border-color:rgba(255,59,107,.4)}"
    ".modal{background:linear-gradient(160deg,var(--surface2),var(--surface))!important;border:1px solid rgba(255,198,41,.2)}"
    "::selection{background:rgba(255,106,19,.35);color:#fff}"
    "*::-webkit-scrollbar{width:11px;height:11px}*::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent2),var(--ember));border-radius:6px}*::-webkit-scrollbar-track{background:#120c1d}"
    # ----- FIRE MAXED: rising embers + flicker + flame gauge -----
    ".wrap{position:relative;z-index:2}"
    ".embers{position:fixed;inset:0;pointer-events:none;z-index:1;overflow:hidden}"
    ".embers i{position:absolute;bottom:-14px;border-radius:50%;background:radial-gradient(circle,#fff1b8 0%,#ffd75e 35%,#ff6a13 65%,transparent 72%);box-shadow:0 0 9px 2px rgba(255,106,19,.7);opacity:0;animation-name:ember-rise;animation-timing-function:ease-in;animation-iteration-count:infinite}"
    "@keyframes ember-rise{0%{transform:translate(0,0) scale(.5);opacity:0}8%{opacity:1}55%{transform:translate(var(--dx),-52vh) scale(1);opacity:.95}100%{transform:translate(calc(var(--dx)*-1),-106vh) scale(.3);opacity:0}}"
    "@keyframes phx-flicker{0%,100%{opacity:1;filter:brightness(1)}25%{opacity:.85;filter:brightness(1.25)}50%{opacity:.95;filter:brightness(.9)}75%{opacity:.8;filter:brightness(1.3)}}"
    "@keyframes glow-breathe{0%,100%{box-shadow:0 0 22px rgba(255,106,19,.28),inset 0 0 0 1px rgba(255,198,41,.18)}50%{box-shadow:0 0 40px rgba(255,61,46,.55),inset 0 0 0 1px rgba(255,198,41,.4)}}"
    ".brandlogo{animation:phx-float 3.6s ease-in-out infinite,glow-breathe 2.4s ease-in-out infinite}"
    ".bar i,.kbar .bt i,.seg.done{animation:phx-flow 3s linear infinite,phx-flicker 1.3s steps(2,end) infinite!important;box-shadow:0 0 10px rgba(255,106,19,.6),0 0 4px rgba(255,213,94,.8)}"
    ".dot.high{box-shadow:0 0 10px 2px rgba(255,59,107,.7)}"
    ".nowcard{border-left-color:var(--ember)!important}"
    ".momentum{position:relative;overflow:hidden}"
    ".momentum::after{content:'';position:absolute;left:0;right:0;bottom:0;height:5px;background:linear-gradient(90deg,#ffc629,#ff6a13,#ff3d2e,#ff6a13,#ffc629);background-size:200% 100%;animation:phx-flow 2.2s linear infinite,phx-flicker 1.1s steps(2,end) infinite;box-shadow:0 0 14px rgba(255,106,19,.8)}"
    # ----- DEADLINE OVERDUE: red alarm -----
    "@keyframes overdue-pulse{0%,100%{box-shadow:0 0 0 0 rgba(255,59,107,.0),0 8px 28px rgba(0,0,0,.55)}50%{box-shadow:0 0 26px 3px rgba(255,59,107,.55),0 8px 28px rgba(0,0,0,.55)}}"
    "@keyframes badge-blink{0%,100%{opacity:1}50%{opacity:.45}}"
    ".card.overdue,.nowcard.overdue{position:relative;border:1px solid rgba(255,59,107,.65)!important;border-left:4px solid var(--hi)!important;background:linear-gradient(160deg,#2a1322,#1c0f1a)!important;animation:overdue-pulse 1.6s ease-in-out infinite}"
    ".card.overdue::before,.nowcard.overdue::before{content:'\\1F6A8 OVERDUE';position:absolute;top:-1px;right:-1px;font-size:10px;font-weight:800;letter-spacing:.5px;color:#fff;background:linear-gradient(92deg,var(--hi),var(--ember));padding:3px 9px;border-radius:0 var(--radius) 0 12px;box-shadow:0 2px 10px rgba(255,59,107,.5);animation:badge-blink 1.2s steps(2,end) infinite;z-index:3}"
    ".card.overdue .due{color:#ff8aa6!important;font-weight:800}"
    ".card.overdue .dot{box-shadow:0 0 12px 3px rgba(255,59,107,.8)!important}"
    ".momentum .big{position:relative;text-shadow:0 0 16px rgba(255,198,41,.45)}"
    ".momentum>div:not(.sep):not(.msg){position:relative}"
    ".momentum>div:not(.sep):not(.msg)::after{content:'';position:absolute;left:50%;transform:translateX(-50%);bottom:-3px;width:26px;height:3px;border-radius:3px;background:linear-gradient(90deg,transparent,var(--accent),var(--accent2),transparent);opacity:.55;filter:blur(.3px)}"
    # ----- Your Turn button FX (approve=phoenix burst / reject=ash burn / done=gold pop) + Undo -----
    ".head{align-items:center!important}.undo-f{margin-left:auto}"
    ".undobtn{cursor:pointer;border:1px solid rgba(255,198,41,.3);background:linear-gradient(160deg,var(--surface2),var(--surface));color:var(--ink);border-radius:9px;padding:7px 14px;font-size:12.5px;font-weight:700;transition:filter .15s,box-shadow .15s}"
    ".undobtn:hover{filter:brightness(1.14);box-shadow:0 0 15px rgba(255,106,19,.32);border-color:var(--accent)}.undobtn:active{transform:translateY(1px)}"
    "@keyframes approve-flash{0%{box-shadow:0 0 0 0 rgba(255,198,41,0)}22%{box-shadow:0 0 46px 12px rgba(255,198,41,.9);background:linear-gradient(160deg,#3a2c12,#211733)}100%{box-shadow:0 0 0 0 rgba(255,198,41,0);transform:scale(1.02)}}"
    ".apr.fx-approve{animation:approve-flash .82s ease-out forwards;border-color:var(--accent)!important;position:relative;z-index:2}"
    "@keyframes ash-burn{0%{filter:none}28%{filter:grayscale(1) brightness(.7)}100%{filter:grayscale(1) brightness(.22) blur(1.4px);opacity:0;transform:translateY(12px) scale(.97)}}"
    ".apr.fx-ash{animation:ash-burn .78s ease-in forwards;border-color:#555!important}"
    "@keyframes done-pop{0%{box-shadow:0 0 0 0 rgba(255,198,41,0)}30%{box-shadow:0 0 28px 5px rgba(255,198,41,.6)}100%{box-shadow:0 0 0 0 rgba(255,198,41,0);transform:scale(1.01)}}"
    ".apr.fx-done{animation:done-pop .64s ease-out forwards;border-color:var(--accent)!important}"
    ".fxlayer{position:fixed;z-index:60;pointer-events:none;overflow:visible}"
    ".fxlayer .spark{position:absolute;width:9px;height:9px;margin:-4.5px;border-radius:50%;background:radial-gradient(circle,#fff7d6,#ffc629 45%,#ff6a13 75%,transparent);box-shadow:0 0 12px 2px rgba(255,150,20,.85);animation:spark-fly .85s ease-out forwards}"
    ".fxlayer .spark.g{width:7px;height:7px;background:radial-gradient(circle,#fff,#ffd75e 50%,#ffb300 80%,transparent)}"
    "@keyframes spark-fly{0%{transform:translate(0,0) scale(.4);opacity:0}15%{opacity:1}100%{transform:translate(var(--tx),var(--ty)) scale(1);opacity:0}}"
    ".fxlayer .ash{position:absolute;top:0;width:5px;height:5px;border-radius:1px;background:#5f5f5f;box-shadow:0 0 3px #000;animation:ash-fall .76s ease-in forwards}"
    "@keyframes ash-fall{0%{transform:translate(0,0) rotate(0);opacity:.9}100%{transform:translate(var(--dx),74px) rotate(140deg);opacity:0}}"
    # ----- W1 Now-detail (t55): make Now cards open a concrete-action modal -----
    ".nowcard{cursor:pointer}.nowcard .nm{display:flex;align-items:center;gap:6px}"
    ".nowcard .info{margin-left:auto;font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:50%;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}"
    ".nowcard:hover .info{color:var(--accent);border-color:var(--accent)}.ndetail{display:none}"
    ".nd-sec{margin:10px 0 2px;font-size:12px;color:var(--muted);font-weight:700}.nd-body{font-size:14px;line-height:1.7}"
    ".nd-step{padding:4px 0 4px 12px;border-left:3px solid var(--accent);margin:6px 0;font-size:14px}"
    ".nd-hint{color:var(--muted);font-size:12px;font-style:italic}"
    # ----- W-docs: project overview + doc links in the Projects modal (#4 stop reading raw md) -----
    ".pv{font-size:13px;line-height:1.75;background:#2563eb0d;border-radius:8px;padding:9px 12px;margin:8px 0}"
    ".docs{display:flex;flex-wrap:wrap;gap:7px;margin:8px 0 2px}.docchip{cursor:pointer;font-size:12px;background:#0f1f33;color:#d6e6ff;border:1px solid var(--line);border-radius:7px;padding:5px 9px}.docchip:hover{filter:brightness(1.25);border-color:var(--accent)}"
    # ----- Your-turn grouping (#1 too many, unstructured) -----
    ".grp{margin:12px 0 4px;font-size:12px;font-weight:800;color:var(--accent);display:flex;align-items:center;gap:8px}.grp .cnt{font-size:11px;color:var(--muted);font-weight:600}.grp:first-child{margin-top:0}"
    # ----- Task grouping (design-grouping.md §3.1): group headings inside a project's task list -----
    ".tgrp{margin:9px 0 3px;font-size:12px;font-weight:800;color:var(--accent);display:flex;align-items:center;gap:7px}.tgrp .cnt{font-size:11px;color:var(--muted);font-weight:600}.tl .tgrp:first-of-type{margin-top:2px}"
    # ----- H4: 品質チップ（Evals横断）・外部リンク集（F3） -----
    ".evalsbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}"
    ".evalchip{font-size:12.5px;font-weight:700;padding:7px 12px;border-radius:10px;border:1px solid var(--line);background:var(--surface)}"
    ".evalchip.ok{border-color:rgba(80,200,120,.45);color:#6fcf97}.evalchip.ng{border-color:rgba(255,59,107,.5);color:var(--hi)}.evalchip.skip{color:var(--muted);border-style:dashed}"
    ".extlinks{margin:12px 8px 0;display:flex;flex-direction:column;gap:4px}"
    ".extlinks a{font-size:12px;color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:8px;border:1px dashed var(--line)}"
    ".extlinks a:hover{color:var(--accent);border-color:var(--accent)}"
    # ===== 着せ替えテーマ（衛星/オルカ/風（山））— phoenix がデフォルト、以下は上書きブロック =====
    # 共通: テーマ切替ボタン／非phoenixではフェニックス専用装飾（鳥ロゴ・炎金写真・🎨ボタン）を無効化
    ".thbtn{margin:14px 8px 0;width:calc(100% - 16px);cursor:pointer;border:1px solid var(--line);background:linear-gradient(160deg,var(--surface2),var(--surface));color:var(--ink);border-radius:10px;padding:8px 10px;font-size:12px;font-weight:700;transition:filter .15s,box-shadow .15s}.thbtn:hover{filter:brightness(1.12)}.thbtn #thlabel{color:var(--accent)}"
    # .brandtx(文字span自身)にグラデ＋clip＋transparent＋fallback単色を載せる（phoenix既定色）。
    # ::before の絵文字はクリップ対象外。fallback color は clip 非対応時に透明化で消えない保険。
    # 全テーマで画像ロゴ(.brandlogo)を表示するため、.brandtx は視覚非表示(sr-only)にしてアクセシブル名だけ維持。
    ".brandtx{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}"
    "body:not(.th-phoenix) .brand::after{content:none}"
    "body:not(.th-phoenix) .bgbtn{display:none}"
    "body:not(.th-phoenix) .brand,body:not(.th-phoenix) .main h1,body:not(.th-phoenix) .head h1{text-shadow:none}"
    # ----- 衛星: 深宇宙ネイビー×シアン/紫、星の粒子 -----
    "body.th-satellite{--bg:#050a16;--surface:#0c1526;--surface2:#122036;--ink:#dceafc;--muted:#8296b4;--line:#24374f;--accent:#5ec8ff;--accent2:#8f7bff;--ember:#3fa9f5;--hi:#ff5f8f;--mid:#ffc857;--low:#5f7189;--shadow:0 8px 28px rgba(0,0,0,.5),0 0 0 1px rgba(94,200,255,.05);"
    "background:radial-gradient(1000px 650px at 15% -10%,#0d2a52 0%,transparent 55%),radial-gradient(800px 550px at 90% 5%,#1b1145 0%,transparent 50%),radial-gradient(1100px 750px at 50% 120%,#071d38 0%,transparent 60%),var(--bg);background-attachment:fixed}"
    "body.th-satellite .side{background:linear-gradient(180deg,#0b1424,#08101d)!important;box-shadow:1px 0 24px rgba(94,200,255,.05)}"
    "body.th-satellite .brandtx{background-image:linear-gradient(92deg,#bfe6ff,#5ec8ff,#8f7bff,#5ec8ff);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#5ec8ff}"
    "body.th-satellite .brandtx::before{content:'\\1F6F0\\FE0F  '}"
    "body.th-satellite .nav a.active{background:linear-gradient(90deg,rgba(94,200,255,.2),rgba(143,123,255,.1))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent2)}"
    "body.th-satellite .nav a:hover{background:rgba(94,200,255,.07)}"
    "body.th-satellite .main h1 #greet,body.th-satellite .head h1 #greet{background-image:linear-gradient(92deg,#dff1ff,#5ec8ff);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#5ec8ff}"
    "body.th-satellite .momentum{background:linear-gradient(100deg,rgba(63,169,245,.13),rgba(143,123,255,.06) 45%,rgba(13,42,82,.25))!important;border:1px solid rgba(94,200,255,.22)!important;box-shadow:0 0 30px rgba(94,200,255,.07)}"
    "body.th-satellite .momentum::after{background:linear-gradient(90deg,#5ec8ff,#8f7bff,#5ec8ff);background-size:200% 100%;animation:phx-flow 3s linear infinite;box-shadow:0 0 12px rgba(94,200,255,.7)}"
    "body.th-satellite .momentum .big{color:var(--accent)!important;text-shadow:0 0 14px rgba(94,200,255,.45)}"
    "body.th-satellite .kpi .n{color:var(--accent)!important;text-shadow:0 0 14px rgba(94,200,255,.4)}"
    "body.th-satellite .bar i,body.th-satellite .kbar .bt i,body.th-satellite .seg.done{background:linear-gradient(90deg,#5ec8ff,#8f7bff,#5ec8ff)!important;background-size:200% auto;animation:phx-flow 3s linear infinite!important;box-shadow:0 0 8px rgba(94,200,255,.55)}"
    "body.th-satellite .btn.ok{background:linear-gradient(92deg,#5ec8ff,#8f7bff)!important;color:#04122a!important;box-shadow:0 3px 14px rgba(94,200,255,.35)}"
    "body.th-satellite .btn.ph{background:linear-gradient(92deg,#8f7bff,#5e6dff)!important}"
    "body.th-satellite .next{background:rgba(94,200,255,.09)!important;border:1px solid rgba(94,200,255,.16)}"
    "body.th-satellite .nowcard code,body.th-satellite .setbox code{background:rgba(94,200,255,.1)!important;color:var(--accent)!important}"
    "body.th-satellite .undobtn{border-color:var(--line)}body.th-satellite .modal{border-color:rgba(94,200,255,.2)}"
    "body.th-satellite ::selection{background:rgba(94,200,255,.35)}"
    "body.th-satellite *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2))}body.th-satellite *::-webkit-scrollbar-track{background:#08101d}"
    "body.th-satellite .embers i{background:radial-gradient(circle,#fff,#bfe6ff 55%,transparent 75%);box-shadow:0 0 6px 1px rgba(150,220,255,.8);animation-name:star-drift}"
    "@keyframes star-drift{0%{transform:translate(0,0) scale(.4);opacity:0}10%{opacity:.9}50%{transform:translate(var(--dx),-50vh) scale(.9);opacity:.55}100%{transform:translate(calc(var(--dx)*-1),-104vh) scale(.5);opacity:0}}"
    # ----- オルカ: 黒×白×氷海ブルー、泡の粒子 -----
    "body.th-orca{--bg:#04090e;--surface:#0b141c;--surface2:#101d28;--ink:#e8f2f8;--muted:#7e93a1;--line:#1e3240;--accent:#6fd8ff;--accent2:#bfeafc;--ember:#4ab3d8;--hi:#ff6b81;--mid:#ffb454;--low:#54707f;--shadow:0 8px 28px rgba(0,0,0,.55),0 0 0 1px rgba(111,216,255,.04);"
    "background:radial-gradient(1000px 700px at 50% 120%,#0c3146 0%,transparent 60%),radial-gradient(700px 500px at 85% -5%,#0a1e2c 0%,transparent 55%),linear-gradient(180deg,#071119,var(--bg));background-attachment:fixed}"
    "body.th-orca .side{background:linear-gradient(180deg,#0a141c,#060d13)!important;box-shadow:1px 0 24px rgba(111,216,255,.05)}"
    "body.th-orca .brandtx{background-image:linear-gradient(92deg,#ffffff,#bfeafc,#6fd8ff,#ffffff);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#bfeafc}"
    "body.th-orca .brandtx::before{content:'\\1F40B '}"
    "body.th-orca .nav a.active{background:linear-gradient(90deg,rgba(111,216,255,.18),rgba(255,255,255,.06))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent)}"
    "body.th-orca .nav a:hover{background:rgba(111,216,255,.06)}"
    "body.th-orca .main h1 #greet,body.th-orca .head h1 #greet{background-image:linear-gradient(92deg,#ffffff,#6fd8ff);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#6fd8ff}"
    "body.th-orca .momentum{background:linear-gradient(100deg,rgba(111,216,255,.12),rgba(255,255,255,.04) 45%,rgba(12,49,70,.3))!important;border:1px solid rgba(111,216,255,.2)!important;box-shadow:0 0 30px rgba(111,216,255,.06)}"
    "body.th-orca .momentum::after{background:linear-gradient(90deg,#6fd8ff,#ffffff,#6fd8ff);background-size:200% 100%;animation:phx-flow 3.2s linear infinite;box-shadow:0 0 12px rgba(111,216,255,.6)}"
    "body.th-orca .momentum .big{color:var(--accent)!important;text-shadow:0 0 14px rgba(111,216,255,.4)}"
    "body.th-orca .kpi .n{color:var(--accent)!important;text-shadow:0 0 14px rgba(111,216,255,.35)}"
    "body.th-orca .bar i,body.th-orca .kbar .bt i,body.th-orca .seg.done{background:linear-gradient(90deg,#6fd8ff,#e9f6fb,#6fd8ff)!important;background-size:200% auto;animation:phx-flow 3.2s linear infinite!important;box-shadow:0 0 8px rgba(111,216,255,.5)}"
    "body.th-orca .btn.ok{background:linear-gradient(92deg,#6fd8ff,#bfeafc)!important;color:#03202e!important;box-shadow:0 3px 14px rgba(111,216,255,.3)}"
    "body.th-orca .btn.ph{background:linear-gradient(92deg,#3d9dc4,#6fd8ff)!important;color:#03202e!important}"
    "body.th-orca .next{background:rgba(111,216,255,.08)!important;border:1px solid rgba(111,216,255,.15)}"
    "body.th-orca .nowcard code,body.th-orca .setbox code{background:rgba(111,216,255,.1)!important;color:var(--accent)!important}"
    "body.th-orca .undobtn{border-color:var(--line)}body.th-orca .modal{border-color:rgba(111,216,255,.18)}"
    "body.th-orca ::selection{background:rgba(111,216,255,.32)}"
    "body.th-orca *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),#2b5a72)}body.th-orca *::-webkit-scrollbar-track{background:#060d13}"
    "body.th-orca .embers i{background:radial-gradient(circle at 32% 30%,rgba(255,255,255,.95),rgba(190,235,255,.18) 45%,transparent 72%);border:1px solid rgba(210,240,255,.55);box-shadow:inset 0 0 4px rgba(255,255,255,.35);animation-name:bubble-rise}"
    "@keyframes bubble-rise{0%{transform:translate(0,0) scale(.5);opacity:0}10%{opacity:.85}55%{transform:translate(var(--dx),-54vh) scale(1);opacity:.7}100%{transform:translate(calc(var(--dx)*-1),-106vh) scale(1.15);opacity:0}}"
    # ----- 風（山）: 明色・山霧と新緑、木の葉の粒子（ライトテーマ） -----
    "body.th-wind{--bg:#eef4f1;--surface:#ffffff;--surface2:#f3faf6;--ink:#26343c;--muted:#6d8089;--line:#d5e2de;--accent:#2f8f76;--accent2:#5aa9d6;--ember:#4a9e8a;--hi:#e05c7a;--mid:#e8a13c;--low:#9fb0ac;--shadow:0 8px 24px rgba(70,110,100,.12),0 0 0 1px rgba(47,143,118,.04);"
    "background:linear-gradient(180deg,#d8e9f4 0%,#eef4f1 45%,#e4efe8 100%);background-attachment:fixed}"
    "body.th-wind .side{background:linear-gradient(180deg,#f7fbf9,#eef4f0)!important;box-shadow:1px 0 18px rgba(70,110,100,.08)}"
    "body.th-wind .brandtx{background-image:linear-gradient(92deg,#2b6a58,#2f8f76,#5aa9d6);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#2f8f76}"
    "body.th-wind .brandtx::before{content:'\\1F3D4\\FE0F  '}"
    "body.th-wind .nav a.active{background:linear-gradient(90deg,rgba(47,143,118,.14),rgba(90,169,214,.08))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent2)}"
    "body.th-wind .nav a:hover{background:rgba(47,143,118,.06)}"
    "body.th-wind .main h1 #greet,body.th-wind .head h1 #greet{background-image:linear-gradient(92deg,#2b6a58,#3d7fa8);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#2f8f76}"
    "body.th-wind .momentum{background:linear-gradient(100deg,rgba(90,169,214,.12),rgba(255,255,255,.6) 45%,rgba(47,143,118,.08))!important;border:1px solid rgba(47,143,118,.22)!important;box-shadow:0 4px 18px rgba(70,110,100,.1)}"
    "body.th-wind .momentum::after{background:linear-gradient(90deg,#2f8f76,#5aa9d6,#2f8f76);background-size:200% 100%;animation:phx-flow 3.4s linear infinite;box-shadow:0 0 10px rgba(47,143,118,.4)}"
    "body.th-wind .momentum .big{color:var(--accent)!important;text-shadow:none}"
    "body.th-wind .kpi .n{color:var(--accent)!important;text-shadow:none}"
    "body.th-wind .bar i,body.th-wind .kbar .bt i,body.th-wind .seg.done{background:linear-gradient(90deg,#2f8f76,#5aa9d6,#2f8f76)!important;background-size:200% auto;animation:phx-flow 3.4s linear infinite!important;box-shadow:none}"
    "body.th-wind .btn.ok{background:linear-gradient(92deg,#2f8f76,#5aa9d6)!important;color:#fff!important;box-shadow:0 3px 12px rgba(47,143,118,.3)}"
    "body.th-wind .btn.ph{background:linear-gradient(92deg,#3d7fa8,#5aa9d6)!important;color:#fff!important}"
    "body.th-wind .next{background:rgba(47,143,118,.08)!important;border:1px solid rgba(47,143,118,.15)}"
    "body.th-wind .nowcard code,body.th-wind .setbox code{background:rgba(47,143,118,.1)!important;color:var(--accent)!important}"
    "body.th-wind .undobtn{border-color:var(--line)}body.th-wind .modal{border-color:rgba(47,143,118,.18)}"
    "body.th-wind .ov{background:rgba(70,95,88,.32)}"
    "body.th-wind .card.overdue,body.th-wind .nowcard.overdue{background:linear-gradient(160deg,#fdf0f3,#fff)!important;border-color:rgba(224,92,122,.5)!important}"
    "body.th-wind ::selection{background:rgba(47,143,118,.25)}"
    "body.th-wind *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2))}body.th-wind *::-webkit-scrollbar-track{background:#e2ece8}"
    "body.th-wind .embers i{background:linear-gradient(135deg,#a9d8b8,#6db98a);border-radius:62% 38% 55% 45%;box-shadow:none;animation-name:leaf-drift}"
    "@keyframes leaf-drift{0%{transform:translate(0,-2vh) rotate(0deg);opacity:0}12%{opacity:.75}55%{transform:translate(var(--dx),-52vh) rotate(160deg);opacity:.6}100%{transform:translate(calc(var(--dx)*-1),-104vh) rotate(320deg);opacity:0}}"
    # ===== 反対カラー4バリアント（白フェニックス/衛星・暁/オルカ・浅瀬/風・夜）=====
    # 各バリアントは兄弟テーマの構造を反転パレットで踏襲。gradientは可能な限り var(--accent) 系を使用。
    # ----- 白フェニックス（phoenix明）: アイボリー地＋金・炎アクセント -----
    "body.th-phoenix-l{--bg:#fbf6ec;--surface:#fffdf8;--surface2:#fdf3e2;--ink:#3a2a18;--muted:#9a8360;--line:#ecdcc2;--accent:#e8920f;--accent2:#ff6a13;--ember:#d63a1e;--hi:#e0325a;--mid:#e8920f;--low:#b7a582;--shadow:0 8px 24px rgba(180,120,40,.15),0 0 0 1px rgba(232,146,15,.06);"
    "background:radial-gradient(1100px 700px at 12% -8%,#ffe9c7 0%,transparent 55%),radial-gradient(900px 600px at 92% 0%,#ffdcb4 0%,transparent 50%),linear-gradient(180deg,#fffaf0,#fbf6ec);background-attachment:fixed}"
    "body.th-phoenix-l .side{background:linear-gradient(180deg,#fffaf0,#fdf3e2)!important;box-shadow:1px 0 18px rgba(200,140,50,.08)}"
    "body.th-phoenix-l .brandtx{background-image:linear-gradient(92deg,#e0620f,#e8920f,#ff6a13,#c0392b,#e8920f)!important;background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#c0392b}"
    "body.th-phoenix-l .brandtx::before{content:'\\1F525  '}"
    "body.th-phoenix-l .main h1 #greet,body.th-phoenix-l .head h1 #greet{background-image:linear-gradient(92deg,#c0392b,#e8920f)!important;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#c0392b}"
    "body.th-phoenix-l .momentum{background:linear-gradient(100deg,rgba(255,106,19,.10),rgba(255,255,255,.6) 45%,rgba(232,146,15,.10))!important;border:1px solid rgba(232,146,15,.28)!important;box-shadow:0 4px 18px rgba(200,140,50,.12)}"
    "body.th-phoenix-l .momentum .big,body.th-phoenix-l .kpi .n{text-shadow:none}"
    "body.th-phoenix-l .btn.ok{color:#fff!important}"
    "body.th-phoenix-l .card.overdue,body.th-phoenix-l .nowcard.overdue{background:linear-gradient(160deg,#fde8e0,#fff)!important;border-color:rgba(214,58,30,.5)!important}"
    "body.th-phoenix-l .ov{background:rgba(140,90,40,.26)}"
    "body.th-phoenix-l ::selection{background:rgba(255,106,19,.28);color:#3a2a18}"
    "body.th-phoenix-l .modal{border-color:rgba(232,146,15,.25)}"
    "body.th-phoenix-l *::-webkit-scrollbar-track{background:#f3e6cf}"
    "body.th-phoenix-l .embers i{background:radial-gradient(circle,#ffd75e 0%,#ff8a2b 40%,#e0530f 68%,transparent 74%);box-shadow:0 0 7px 1px rgba(224,83,15,.55)}"
    # ----- 衛星・暁（satellite明）: 淡い水色→白のグラデ（軌道から見た夜明け・成層圏） -----
    "body.th-satellite-l{--bg:#dfeefc;--surface:#ffffff;--surface2:#eef6ff;--ink:#26384f;--muted:#6d84a3;--line:#d2e2f4;--accent:#2f80d8;--accent2:#7b6fe0;--ember:#4a9be8;--hi:#e0507f;--mid:#e8a13c;--low:#9db1cb;--shadow:0 8px 24px rgba(80,120,180,.14),0 0 0 1px rgba(47,128,216,.05);"
    "background:linear-gradient(180deg,#eaf4ff 0%,#dfeefc 42%,#ffffff 100%);background-attachment:fixed}"
    "body.th-satellite-l .side{background:linear-gradient(180deg,#f4f9ff,#e9f2fc)!important;box-shadow:1px 0 18px rgba(80,120,180,.08)}"
    "body.th-satellite-l .brandtx{background-image:linear-gradient(92deg,#2f80d8,#7b6fe0,#2f80d8)!important;background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#2f80d8}"
    "body.th-satellite-l .brandtx::before{content:'\\1F305  '}"
    "body.th-satellite-l .nav a.active{background:linear-gradient(90deg,rgba(47,128,216,.14),rgba(123,111,224,.08))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent2)}"
    "body.th-satellite-l .nav a:hover{background:rgba(47,128,216,.06)}"
    "body.th-satellite-l .main h1 #greet,body.th-satellite-l .head h1 #greet{background-image:linear-gradient(92deg,#2f80d8,#7b6fe0)!important;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#2f80d8}"
    "body.th-satellite-l .momentum{background:linear-gradient(100deg,rgba(47,128,216,.10),rgba(255,255,255,.6) 45%,rgba(123,111,224,.08))!important;border:1px solid rgba(47,128,216,.24)!important;box-shadow:0 4px 18px rgba(80,120,180,.1)}"
    "body.th-satellite-l .momentum::after{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;box-shadow:0 0 10px rgba(47,128,216,.4)}"
    "body.th-satellite-l .momentum .big,body.th-satellite-l .kpi .n{color:var(--accent)!important;text-shadow:none}"
    "body.th-satellite-l .bar i,body.th-satellite-l .kbar .bt i,body.th-satellite-l .seg.done{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;background-size:200% auto;box-shadow:none}"
    "body.th-satellite-l .btn.ok{background:linear-gradient(92deg,#2f80d8,#7b6fe0)!important;color:#fff!important;box-shadow:0 3px 12px rgba(47,128,216,.3)}"
    "body.th-satellite-l .btn.ph{background:linear-gradient(92deg,#7b6fe0,#5e6dff)!important;color:#fff!important}"
    "body.th-satellite-l .next{background:rgba(47,128,216,.08)!important;border:1px solid rgba(47,128,216,.15)}"
    "body.th-satellite-l .nowcard code,body.th-satellite-l .setbox code{background:rgba(47,128,216,.1)!important;color:var(--accent)!important}"
    "body.th-satellite-l .undobtn{border-color:var(--line)}body.th-satellite-l .modal{border-color:rgba(47,128,216,.2)}"
    "body.th-satellite-l .ov{background:rgba(80,110,150,.28)}"
    "body.th-satellite-l .card.overdue,body.th-satellite-l .nowcard.overdue{background:linear-gradient(160deg,#fdeef2,#fff)!important;border-color:rgba(224,80,127,.5)!important}"
    "body.th-satellite-l ::selection{background:rgba(47,128,216,.22)}"
    "body.th-satellite-l *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2))}body.th-satellite-l *::-webkit-scrollbar-track{background:#e4eef9}"
    "body.th-satellite-l .embers i{background:radial-gradient(circle,#fff6d6,#ffd98a 55%,transparent 75%);box-shadow:0 0 5px 1px rgba(255,200,120,.6);animation-name:star-drift}"
    # ----- オルカ・浅瀬（orca明）: 明るいターコイズ/アクア/砂浜 -----
    "body.th-orca-l{--bg:#e6f7f6;--surface:#ffffff;--surface2:#f0fbfa;--ink:#123b40;--muted:#5f8a8e;--line:#cbebe8;--accent:#0f9bb3;--accent2:#17c0b6;--ember:#2bb5c9;--hi:#e0607a;--mid:#e8a13c;--low:#9cc0be;--shadow:0 8px 24px rgba(40,150,150,.14),0 0 0 1px rgba(15,155,179,.05);"
    "background:radial-gradient(1000px 700px at 50% 120%,#c7ecef 0%,transparent 60%),radial-gradient(700px 500px at 88% -5%,#ffe9cf 0%,transparent 55%),linear-gradient(180deg,#eefbfa,#e6f7f6);background-attachment:fixed}"
    "body.th-orca-l .side{background:linear-gradient(180deg,#f2fcfb,#e8f7f6)!important;box-shadow:1px 0 18px rgba(40,150,150,.08)}"
    "body.th-orca-l .brandtx{background-image:linear-gradient(92deg,#0f9bb3,#17c0b6,#0f9bb3)!important;background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#0f9bb3}"
    "body.th-orca-l .brandtx::before{content:'\\1F41A '}"
    "body.th-orca-l .nav a.active{background:linear-gradient(90deg,rgba(15,155,179,.14),rgba(23,192,182,.08))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent)}"
    "body.th-orca-l .nav a:hover{background:rgba(15,155,179,.06)}"
    "body.th-orca-l .main h1 #greet,body.th-orca-l .head h1 #greet{background-image:linear-gradient(92deg,#0f9bb3,#17c0b6)!important;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#0f9bb3}"
    "body.th-orca-l .momentum{background:linear-gradient(100deg,rgba(15,155,179,.10),rgba(255,255,255,.6) 45%,rgba(255,202,122,.12))!important;border:1px solid rgba(15,155,179,.22)!important;box-shadow:0 4px 18px rgba(40,150,150,.1)}"
    "body.th-orca-l .momentum::after{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;box-shadow:0 0 10px rgba(15,155,179,.4)}"
    "body.th-orca-l .momentum .big,body.th-orca-l .kpi .n{color:var(--accent)!important;text-shadow:none}"
    "body.th-orca-l .bar i,body.th-orca-l .kbar .bt i,body.th-orca-l .seg.done{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;background-size:200% auto;box-shadow:none}"
    "body.th-orca-l .btn.ok{background:linear-gradient(92deg,#0f9bb3,#17c0b6)!important;color:#fff!important;box-shadow:0 3px 12px rgba(15,155,179,.3)}"
    "body.th-orca-l .btn.ph{background:linear-gradient(92deg,#17c0b6,#0f9bb3)!important;color:#fff!important}"
    "body.th-orca-l .next{background:rgba(15,155,179,.08)!important;border:1px solid rgba(15,155,179,.15)}"
    "body.th-orca-l .nowcard code,body.th-orca-l .setbox code{background:rgba(15,155,179,.1)!important;color:var(--accent)!important}"
    "body.th-orca-l .undobtn{border-color:var(--line)}body.th-orca-l .modal{border-color:rgba(15,155,179,.2)}"
    "body.th-orca-l .ov{background:rgba(40,110,110,.28)}"
    "body.th-orca-l .card.overdue,body.th-orca-l .nowcard.overdue{background:linear-gradient(160deg,#fdeef1,#fff)!important;border-color:rgba(224,96,122,.5)!important}"
    "body.th-orca-l ::selection{background:rgba(15,155,179,.22)}"
    "body.th-orca-l *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2))}body.th-orca-l *::-webkit-scrollbar-track{background:#dcefee}"
    "body.th-orca-l .embers i{background:radial-gradient(circle at 32% 30%,rgba(255,255,255,.8),rgba(23,192,182,.15) 50%,transparent 72%);border:1px solid rgba(15,155,179,.3);box-shadow:inset 0 0 4px rgba(255,255,255,.4);animation-name:bubble-rise}"
    # ----- 風・夜（wind暗）: 藍/インディゴの夜山 -----
    "body.th-wind-d{--bg:#0e1530;--surface:#161f42;--surface2:#1d2a54;--ink:#dce4fb;--muted:#8a97c4;--line:#2c3866;--accent:#8fa6ff;--accent2:#6f7fe0;--ember:#5a6fd6;--hi:#ff6b95;--mid:#ffc857;--low:#5d6a99;--shadow:0 8px 28px rgba(0,0,0,.5),0 0 0 1px rgba(143,166,255,.05);"
    "background:radial-gradient(1000px 700px at 20% -8%,#1b2a5c 0%,transparent 55%),radial-gradient(800px 600px at 90% 10%,#241a52 0%,transparent 50%),linear-gradient(180deg,#0e1530,#0a1024);background-attachment:fixed}"
    "body.th-wind-d .side{background:linear-gradient(180deg,#131c40,#0c1330)!important;box-shadow:1px 0 24px rgba(143,166,255,.05)}"
    "body.th-wind-d .brandtx{background-image:linear-gradient(92deg,#bcc9ff,#8fa6ff,#6f7fe0,#8fa6ff)!important;background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:#8fa6ff}"
    "body.th-wind-d .brandtx::before{content:'\\1F319  '}"
    "body.th-wind-d .nav a.active{background:linear-gradient(90deg,rgba(143,166,255,.2),rgba(111,127,224,.1))!important;color:var(--accent)!important;box-shadow:inset 3px 0 0 var(--accent2)}"
    "body.th-wind-d .nav a:hover{background:rgba(143,166,255,.07)}"
    "body.th-wind-d .main h1 #greet,body.th-wind-d .head h1 #greet{background-image:linear-gradient(92deg,#dbe4ff,#8fa6ff)!important;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#8fa6ff}"
    "body.th-wind-d .momentum{background:linear-gradient(100deg,rgba(143,166,255,.13),rgba(111,127,224,.06) 45%,rgba(20,26,60,.3))!important;border:1px solid rgba(143,166,255,.22)!important;box-shadow:0 0 30px rgba(143,166,255,.07)}"
    "body.th-wind-d .momentum::after{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;box-shadow:0 0 12px rgba(143,166,255,.6)}"
    "body.th-wind-d .momentum .big,body.th-wind-d .kpi .n{color:var(--accent)!important;text-shadow:0 0 14px rgba(143,166,255,.4)}"
    "body.th-wind-d .bar i,body.th-wind-d .kbar .bt i,body.th-wind-d .seg.done{background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent))!important;background-size:200% auto;box-shadow:0 0 8px rgba(143,166,255,.5)}"
    "body.th-wind-d .btn.ok{background:linear-gradient(92deg,#8fa6ff,#6f7fe0)!important;color:#0a1024!important;box-shadow:0 3px 14px rgba(143,166,255,.35)}"
    "body.th-wind-d .btn.ph{background:linear-gradient(92deg,#6f7fe0,#5e6dff)!important;color:#fff!important}"
    "body.th-wind-d .next{background:rgba(143,166,255,.09)!important;border:1px solid rgba(143,166,255,.16)}"
    "body.th-wind-d .nowcard code,body.th-wind-d .setbox code{background:rgba(143,166,255,.1)!important;color:var(--accent)!important}"
    "body.th-wind-d .undobtn{border-color:var(--line)}body.th-wind-d .modal{border-color:rgba(143,166,255,.2)}"
    "body.th-wind-d ::selection{background:rgba(143,166,255,.32)}"
    "body.th-wind-d *::-webkit-scrollbar-thumb{background:linear-gradient(var(--accent),var(--accent2))}body.th-wind-d *::-webkit-scrollbar-track{background:#0c1330}"
    "body.th-wind-d .embers i{background:linear-gradient(135deg,#7d90d6,#4a5aa8);border-radius:62% 38% 55% 45%;box-shadow:0 0 5px rgba(143,166,255,.4);animation-name:leaf-drift}"
    # ===== 追加エフェクト（fxfield）: orca=大きな泡 / satellite=小石(無重力) / wind=風の筋＋葉 =====
    # 既定は全て display:none。各テーマが自分の粒子だけ display:block にする（非表示要素はアニメせず軽量）。
    ".fxfield{position:fixed;inset:0;pointer-events:none;z-index:1;overflow:hidden}"
    ".fxfield .fx{position:absolute;display:none;will-change:transform,opacity}"
    "body.th-orca .fxfield .bubble,body.th-orca-l .fxfield .bubble{display:block}"
    "body.th-satellite .fxfield .pebble,body.th-satellite-l .fxfield .pebble{display:block}"
    "body.th-wind .fxfield .streak,body.th-wind-d .fxfield .streak,body.th-wind .fxfield .leaf,body.th-wind-d .fxfield .leaf{display:block}"
    # 大きな水のあわ（ゆっくり上昇・半透明）
    ".fxfield .bubble{bottom:-14vh;border-radius:50%;background:radial-gradient(circle at 34% 30%,rgba(255,255,255,.42),rgba(150,220,255,.10) 55%,rgba(120,200,240,.04) 72%,transparent 74%);border:1px solid rgba(190,235,255,.30);box-shadow:inset 0 0 14px rgba(255,255,255,.22);animation-name:orca-bubble;animation-timing-function:ease-in-out;animation-iteration-count:infinite}"
    "body.th-orca-l .fxfield .bubble{background:radial-gradient(circle at 34% 30%,rgba(255,255,255,.55),rgba(23,192,182,.14) 55%,transparent 74%);border-color:rgba(15,155,179,.32)}"
    "@keyframes orca-bubble{0%{transform:translate(0,0) scale(.7);opacity:0}12%{opacity:.5}50%{transform:translate(var(--dx),-60vh) scale(1)}88%{opacity:.4}100%{transform:translate(calc(var(--dx)*-1),-124vh) scale(1.15);opacity:0}}"
    # 小石（斜めにゆっくり流れる＝無重力感）
    ".fxfield .pebble{top:0;width:5px;height:5px;border-radius:42% 58% 50% 45%;background:linear-gradient(135deg,#c7d2e0,#8494a8);box-shadow:0 0 4px rgba(180,200,230,.5);animation-name:sat-pebble;animation-timing-function:linear;animation-iteration-count:infinite}"
    "body.th-satellite-l .fxfield .pebble{background:linear-gradient(135deg,#9aa8c0,#5f6f88);box-shadow:0 0 4px rgba(120,140,175,.45)}"
    "@keyframes sat-pebble{0%{transform:translate(-8vw,8vh) rotate(0);opacity:0}10%{opacity:.85}90%{opacity:.65}100%{transform:translate(64vw,-92vh) rotate(200deg);opacity:0}}"
    # 風の筋（横に流れる）
    ".fxfield .streak{height:2px;border-radius:2px;background:linear-gradient(90deg,transparent,rgba(90,169,214,.5),transparent);animation-name:wind-streak;animation-timing-function:ease-in-out;animation-iteration-count:infinite}"
    "body.th-wind-d .fxfield .streak{background:linear-gradient(90deg,transparent,rgba(143,166,255,.5),transparent)}"
    "@keyframes wind-streak{0%{transform:translateX(-40vw);opacity:0}12%{opacity:.7}88%{opacity:.5}100%{transform:translateX(132vw);opacity:0}}"
    # たまに葉っぱ（横に流れる・回転）
    ".fxfield .leaf{width:9px;height:9px;background:linear-gradient(135deg,#a9d8b8,#5aa06f);border-radius:62% 38% 55% 45%;animation-name:wind-leaf;animation-timing-function:linear;animation-iteration-count:infinite}"
    "body.th-wind-d .fxfield .leaf{background:linear-gradient(135deg,#3a6b8a,#2b4a6b)}"
    "@keyframes wind-leaf{0%{transform:translate(-12vw,0) rotate(0);opacity:0}12%{opacity:.85}50%{transform:translate(56vw,-5vh) rotate(180deg)}100%{transform:translate(132vw,4vh) rotate(360deg);opacity:0}}"
    # ===== テーマタイル（選択UI）: サイドバーのテーマボタンで開く 8タイルのグリッド =====
    ".thgrid{display:none;grid-template-columns:1fr 1fr;gap:7px;margin:10px 8px 0}"
    ".thgrid.open{display:grid}"
    ".thtile{cursor:pointer;text-align:center;border:1px solid var(--line);border-radius:10px;padding:8px 6px;color:#fff;font-size:11px;font-weight:700;position:relative;overflow:hidden;transition:transform .12s,box-shadow .12s;text-shadow:0 1px 3px rgba(0,0,0,.55)}"
    ".thtile:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(0,0,0,.35)}"
    ".thtile.sel{outline:2px solid #fff;outline-offset:-2px}"
    ".thtile .themb{min-height:46px;display:flex;align-items:center;justify-content:center;margin-bottom:4px}"
    ".thtile .themb svg{height:40px;width:auto;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))}"
    ".thtile .thlogo{display:block;width:40px;height:40px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.35)}"
    ".thtile .thimg{display:block;width:46px;height:46px;border-radius:9px;object-fit:cover;box-shadow:0 2px 8px rgba(0,0,0,.4)}"
    ".thtile .thnm{display:block;line-height:1.2}"
    # ===== prefers-reduced-motion 尊重: 装飾アニメと粒子/エフェクトを抑制 =====
    "@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition-duration:.001s!important}.embers,.fxfield{display:none!important}}"
    "</style>"
)


def _fx_html() -> str:
    """テーマ別エフェクト粒子（大きな泡/小石/風の筋/葉）。全て自己完結・決定論パラメータ。
    既定は CSS で display:none。表示テーマだけが自分の粒子を出す（非表示要素はアニメしない）。"""
    out = []
    # 大きな泡（orca）: 24..64px・ゆっくり(14..26s)・半透明
    for i in range(9):
        left = (i * 4691) % 100
        size = 24 + (i * 11) % 40
        dur = 14 + (i * 7) % 13
        delay = (i * 9) % 20
        drift = -40 + (i * 23) % 80
        out.append(f'<i class="fx bubble" style="left:{left}%;width:{size}px;height:{size}px;'
                   f'animation-duration:{dur}s;animation-delay:-{delay}s;--dx:{drift}px"></i>')
    # 小石（satellite）: 斜めにゆっくり(18..34s)
    for i in range(14):
        top = (i * 3697) % 100
        size = 3 + (i * 3) % 5
        dur = 18 + (i * 5) % 17
        delay = (i * 11) % 30
        out.append(f'<i class="fx pebble" style="top:{top}%;width:{size}px;height:{size}px;'
                   f'animation-duration:{dur}s;animation-delay:-{delay}s"></i>')
    # 風の筋（wind）: 横に流れる(6..12s)
    for i in range(7):
        top = 6 + (i * 13) % 88
        w = 90 + (i * 37) % 150
        dur = 6 + (i * 3) % 7
        delay = (i * 5) % 10
        out.append(f'<i class="fx streak" style="top:{top}%;width:{w}px;'
                   f'animation-duration:{dur}s;animation-delay:-{delay}s"></i>')
    # 葉っぱ（wind・たまに）: 横に流れる(11..19s)
    for i in range(8):
        top = (i * 5099) % 90
        dur = 11 + (i * 7) % 9
        delay = (i * 13) % 22
        out.append(f'<i class="fx leaf" style="top:{top}%;'
                   f'animation-duration:{dur}s;animation-delay:-{delay}s"></i>')
    return '<div class="fxfield" aria-hidden="true">' + "".join(out) + "</div>"


def _tile_emblem(cls: str, c: tuple) -> str:
    """タイルのモチーフ=デザインされたエンブレム。黒フェニックスは実ロゴ(CSS背景・base64は1回だけ埋込)、
    他の7テーマは Canva製のブランドタイル画像(data URI)。画像欠落時はテーマ配色のインラインSVGへ退避。
    （宇宙=軌道/惑星, orca=クジラ/波, wind=山/月）。CSP自己完結=すべて data URI。"""
    base = cls[:-2] if cls.endswith(("-l", "-d")) else cls
    c0, c1, c2 = c
    # 黒フェニックス以外: 各テーマ専用の Canva タイル画像を出す（黒フェニックスは既存ロゴのまま）。
    timg = THEME_TILE_IMG.get(cls)
    if timg is not None and timg.exists():
        b64 = base64.b64encode(timg.read_bytes()).decode("ascii")
        return (f'<img class="thimg" src="data:image/jpeg;base64,{b64}" '
                f'alt="" aria-hidden="true" loading="lazy">')
    if cls == "th-phoenix":
        if LOGO.exists():
            return '<span class="thlogo" aria-hidden="true"></span>'   # 左上と同じフェニックスCanvaロゴ
    if base == "th-phoenix":
        # ロゴ/タイル画像 欠落時のフォールバック=炎のSVG
        return (f'<svg viewBox="0 0 76 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
                f'<path d="M38 5c7 9 2 13 5 18 2-2 3-6 2-9 5 5 8 11 8 17a17 17 0 1 1-34 0c0-7 5-13 11-17-2 5 0 8 2 10-3-9 4-14 6-19z" fill="{c1}"/>'
                f'<path d="M38 17c3 4 1 7 2 10 3-2 4-6 3-9 2 3 3 6 3 9a9 9 0 1 1-18 0c0-4 3-8 7-10-1 3 0 5 1 6-1-5 0-11 2-16z" fill="{c0}"/></svg>')
    if base == "th-satellite":   # 軌道と惑星＋星（宇宙）
        return (f'<svg viewBox="0 0 76 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
                f'<circle cx="12" cy="9" r="1.3" fill="#fff" opacity=".85"/>'
                f'<circle cx="64" cy="34" r="1" fill="#fff" opacity=".7"/>'
                f'<circle cx="54" cy="7" r="1" fill="#fff" opacity=".6"/>'
                f'<ellipse cx="38" cy="23" rx="30" ry="10" fill="none" stroke="{c0}" stroke-width="2" opacity=".75"/>'
                f'<circle cx="38" cy="23" r="11" fill="{c2}"/>'
                f'<path d="M27 23a11 11 0 0 1 22 0z" fill="{c1}" opacity=".55"/>'
                f'<circle cx="9" cy="18" r="2.6" fill="{c1}"/></svg>')
    if base == "th-orca":        # クジラ＋波
        return (f'<svg viewBox="0 0 76 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
                f'<path d="M4 34q9-5 18 0t18 0 18 0 14 0" fill="none" stroke="{c0}" stroke-width="2" opacity=".45"/>'
                f'<path d="M16 24C16 15 30 12 41 15 52 18 60 21 66 21 60 27 52 28 46 27 47 31 44 33 40 32 38 30 38 27 39 25 30 27 21 27 16 24Z" fill="{c0}"/>'
                f'<path d="M41 26c6 0 12-1 20-4-5 5-12 7-19 6z" fill="{c2}" opacity=".9"/>'
                f'<circle cx="25" cy="21" r="1.6" fill="#fff"/>'
                f'<path d="M41 15q1-6 4-9 2 4 0 9z" fill="{c1}"/></svg>')
    # th-wind: 山＋太陽/月＋風の筋
    return (f'<svg viewBox="0 0 76 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            f'<circle cx="59" cy="12" r="6" fill="{c2}" opacity=".9"/>'
            f'<path d="M0 42 20 16 34 42Z" fill="{c0}"/>'
            f'<path d="M22 42 44 10 66 42Z" fill="{c1}"/>'
            f'<path d="M38 20 44 12 50 20 46 18 44 22 42 18Z" fill="#fff" opacity=".92"/>'
            f'<path d="M5 30q11-3 21 0" stroke="#fff" stroke-width="1.5" fill="none" opacity=".5"/></svg>')


def _theme_tiles_html() -> str:
    """テーマタイル（選択UI）: 8タイルのミニプレビュー。各タイル=テーマ背景＋中央エンブレム＋名前。
    クリックで applyTheme・localStorage永続。THEMES/THEME_TILES が単一の正。CSP自己完結。"""
    # 黒フェニックスのタイルは実ロゴ png を CSS変数 --logo-png（_brand_css で1回だけ埋込）から参照（肥大回避）。
    style = ('<style>.thtile .thlogo{background-image:var(--logo-png);'
             'background-size:contain;background-repeat:no-repeat;background-position:center}</style>')
    tiles = []
    for cls, label in THEMES:
        bg, sw, _fx = THEME_TILES[cls]
        emb = _tile_emblem(cls, sw)
        tiles.append(
            f'<button class="thtile" data-th="{cls}" onclick="applyTheme(\'{cls}\')" '
            f'style="background:{bg}"><span class="themb">{emb}</span>'
            f'<span class="thnm">{label}</span></button>')
    return style + '<div id="thgrid" class="thgrid">' + "".join(tiles) + "</div>"


def _dash_stats(state):
    tk = [t for p in state["projects"] for t in p.get("tasks", [])]
    parked = sum(1 for p in state["projects"] if is_parked(p))
    return {"projects": len(state["projects"]),
            "active_n": len(state["projects"]) - parked,
            "parked_n": parked,
            "todo": sum(t.get("status") == "todo" for t in tk),
            "done": sum(t.get("status") == "done" for t in tk),
            "high": sum(p.get("priority") == "high" for p in state["projects"]),
            "proposed": sum(t.get("status") == "proposed" for t in tk)}


def _embers_html(n: int = 22) -> str:
    # Floating rising embers across the whole screen — pure CSS decoration (deterministic params).
    spans = []
    for i in range(n):
        left = (i * 4099) % 100                 # spread across width (deterministic pseudo-random)
        dur = 6 + (i * 7) % 9                    # 6..14s rise time
        delay = (i * 13) % 14                    # staggered starts
        size = 3 + (i * 5) % 5                    # 3..7px
        drift = -30 + (i * 17) % 60              # horizontal sway -30..30px
        spans.append(
            f'<i style="left:{left}%;width:{size}px;height:{size}px;'
            f'animation-duration:{dur}s;animation-delay:-{delay}s;--dx:{drift}px"></i>')
    return '<div class="embers" aria-hidden="true">' + "".join(spans) + "</div>"


def _bg_css() -> str:
    # Canva-made phoenix backdrops embedded as base64 (self-contained). A fixed body::before layer
    # sits behind the embers (z0) and content (z2); body.bg-* class selects which image / off.
    rules = ["<style>",
             "body::before{content:'';position:fixed;inset:0;z-index:0;background-size:cover;"
             "background-position:center bottom;background-repeat:no-repeat;opacity:.9;"
             "pointer-events:none;transition:opacity .45s ease}",
             "body.bg-none::before{opacity:0}"]
    # 黒フェニックス専用: 炎金/紫炎の写真背景（既存のまま・不変）。bg-d/bg-b クラスで切替。
    for cls, fn in (("bg-d", BG_D), ("bg-b", BG_B)):
        if fn.exists():
            b64 = base64.b64encode(fn.read_bytes()).decode("ascii")
            rules.append(f"body.{cls}::before{{background-image:url(data:image/jpeg;base64,{b64})}}")
    # 各テーマ専用の Canva 背景（黒フェニックス以外の7テーマ）。bg-d/bg-b の後に出して確実に上書き
    # ＝他テーマに炎金写真が漏れず、それぞれ自分の世界観の背景を ::before に敷く。CSP自己完結=data URI。
    for cls, (fn, op) in THEME_BG_IMG.items():
        if fn.exists():
            b64 = base64.b64encode(fn.read_bytes()).decode("ascii")
            rules.append(f"body.{cls}::before{{background-image:url(data:image/jpeg;base64,{b64})"
                         f"!important;opacity:{op}!important}}")
    rules.append("</style>")
    return "".join(rules)


def _brand_html() -> str:
    # 全テーマで左上に「Cockpit」画像ロゴを表示。背景画像は _brand_css がテーマ毎に data URI で切替
    # （applyTheme のクラス付替でリロードなしに切替）。brandtx は sr-only でアクセシブル名「Cockpit」を維持。
    return ('<div class="brandlogo" role="img" aria-label="Cockpit"></div>'
            '<span class="brandtx">Cockpit</span>')


def _brand_css() -> str:
    """左上ブランドロゴのテーマ別背景画像（自己完結=data URI）。既存の Canvaタイル画像を流用し新規画像はゼロ。
    黒フェニックス=実ロゴ png（CSS変数で1回だけ埋込・picker の .thlogo と共有）／他7テーマ=THEME_TILE_IMG の jpeg。"""
    rules = ["<style>"]
    have_logo = LOGO.exists()
    if have_logo:
        b64 = base64.b64encode(LOGO.read_bytes()).decode("ascii")
        # png は :root の変数に1回だけ埋め込み、picker(.thlogo) と brand(.brandlogo) で共有（肥大回避）。
        rules.append(f':root{{--logo-png:url("data:image/png;base64,{b64}")}}')
        rules.append(".brandlogo{background-image:var(--logo-png)}")   # 既定=黒フェニックス
    # 他7テーマ: pickerと同じ Canva タイル画像を左上ロゴにも流用。
    for cls, fn in THEME_TILE_IMG.items():
        if fn.exists():
            b64 = base64.b64encode(fn.read_bytes()).decode("ascii")
            rules.append(f'body.{cls} .brandlogo{{background-image:url("data:image/jpeg;base64,{b64}")}}')
    if not have_logo:
        # ロゴ画像が無い環境ではテキストブランドを表示（sr-only 解除）。
        rules.append(".brandtx{position:static;width:auto;height:auto;margin:0;clip:auto;overflow:visible;font-weight:800;font-size:20px}")
    rules.append("</style>")
    return "".join(rules)


# ===== H3: 🌱 種床（moc-0）— ブリーフ等から1クリックでアイデアを起票 =====
SEEDBED_PID = "moc-0"


def mutate_seed(state: dict, title: str, source: str = "", now: str | None = None) -> dict:
    """種を moc-0 に起票（純粋・テスト可能）。moc-0 が無ければ作る。
    人間のボタン発なので直todo（proposeを経ない＝王自身の操作・design-hub-v2 F2）。"""
    proj = _find_project(state, SEEDBED_PID)
    if not proj:
        proj = {"id": SEEDBED_PID, "name": "アイデア箱（種床）", "north_star": "月次棚卸しでMOC昇格 or 破棄",
                "priority": "low", "repo": "", "depends_on": [], "done_def": "",
                "phases": [], "milestones": [], "tasks": []}
        state["projects"].append(proj)
    ts = now or _today()
    tid = _next_id(state)
    desc = f"種: {title}" + (f"（出典: {source}）" if source else "")
    task = {"id": tid, "desc": desc, "status": "todo", "owner": "human",
            "created": ts, "status_changed": ts}
    proj["tasks"].append(task)
    return task


def seed(title, source=""):
    state = load_state()
    t = mutate_seed(state, title, source)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "seed", "tid": t["id"], "src": source})
    return f"🌱 seeded {t['id']} → {SEEDBED_PID}: {t['desc']}"


def mutate_assign(state: dict, pid: str, desc: str, now: str | None = None) -> dict:
    """人間がエージェントへ直接仕事を渡す（owner=ai・todo）。純粋・テスト可能。
    approveと同じ到達点（agentのsnapshot受信箱）に、人間の意思で直接置く操作。"""
    proj = _find_project(state, pid)
    if not proj:
        raise KeyError(f"project {pid} not found")
    ts = now or _today()
    tid = _next_id(state)
    task = {"id": tid, "desc": desc, "status": "todo", "owner": "ai",
            "created": ts, "status_changed": ts}
    proj.setdefault("tasks", []).append(task)
    return task


def assign(pid, desc):
    state = load_state()
    t = mutate_assign(state, pid, desc)
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "assign", "tid": t["id"], "pid": pid})
    return f"🤖 assigned {t['id']} → {pid} (agent inbox): {desc}"


def detail_request_desc(tid: str, desc: str) -> str:
    """手順作成依頼の定型文（純粋・Eval対象）。AIはこれを受信箱で読み set-detail で書き戻す。"""
    return (f'✍️ {tid}「{desc[:48]}」の実行手順を具体化し、'
            f'`set-detail {tid} "手順1\\n手順2..."` で反映する')


def request_detail(tid):
    """王のボタン: 「このタスクの手順はAIが書く」をパイプライン化（Now→agent受信箱→set-detail）。"""
    state = load_state()
    p, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    req = mutate_assign(state, p["id"], detail_request_desc(tid, t["desc"]))
    save_state(state); emit_snapshot(state)
    journal_append(JOURNAL, {"op": "request-detail", "tid": tid, "req": req["id"]})
    return f"✍️ {req['id']} → agent inbox: {tid} の手順作成を依頼"


# ===== H2: Hub feeds（design-hub-v2 §2）— 他MOCの読取専用プロジェクション =====
FEEDS_DIR = HERE / "feeds"      # gitignore対象（私物）。無ければ機能ごと沈黙＝OSSコアは汎用のまま


# ===== S2: AIカーソル（差分読み）— design-sync-diff-architecture.md §3.2/§4 =====
# events.jsonl（全mutationの追記journal）を「変更ストリーム」として使い、AIが「前回見た地点
# (カーソル)以降の差分」だけを行オフセットで読む＝欠陥B（AIが差分を持たない）の解消。
# カーソルは feeds/ai_cursor.json（私物・gitignore）に {"seen": <既読行数>} で持つ。
# feeds/ が無ければ機能OFF＝OSSコアは no-op（feeds私物依存はガード・汎用のまま）。
CURSOR = FEEDS_DIR / "ai_cursor.json"


def read_journal_lines(path) -> list:
    """journal の非空行を順序どおりに返す（ファイル欠如なら空）。"""
    p = Path(path)
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_cursor(cursor_path) -> int:
    """既読行数(seen)を返す。ファイル欠如/破損時は 0（初期化＝全部が差分・クラッシュしない）。"""
    p = Path(cursor_path)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("seen", 0))
    except (ValueError, OSError):
        return 0


def write_cursor(cursor_path, seen: int) -> bool:
    """カーソルを保存。親(feeds/)が無ければ何もしない no-op＝OSSコアは汎用。戻り値=書けたか。"""
    p = Path(cursor_path)
    if not p.parent.exists():
        return False
    p.write_text(json.dumps({"seen": int(seen)}, ensure_ascii=False), encoding="utf-8")
    return True


def cursor_diff(journal_path, cursor_path):
    """カーソル以降の journal イベントを返す。カーソルは動かさない（覗くだけ）。
    戻り値 (events, seen, total):
      events = 既読行以降の新着イベント（パース済み・順序保存）
      seen   = 既読行数（起点カーソル）  total = journal 総行数
    journal が縮小/ローテートして seen>total の時は取りこぼさぬよう 0 起点に戻す。
    """
    lines = read_journal_lines(journal_path)
    total = len(lines)
    seen = read_cursor(cursor_path)
    if seen > total:
        seen = 0
    events = []
    for ln in lines[seen:]:
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return events, seen, total


def render_diff_event(ev: dict) -> str:
    """1イベントを人が読める1行に（op・tid・要点フィールド）。"""
    ts = ev.get("ts", "")
    op = ev.get("op", "?")
    head = f"{ts}  {op:>13}"
    tid = ev.get("tid")
    if tid:
        head += f"  {tid}"
    extra = [f"{k}={ev[k]}" for k in ("to", "owner", "group", "phase", "pid", "gid", "src",
             "why", "evidence", "req") if ev.get(k) not in (None, "")]
    if extra:
        head += "  (" + ", ".join(extra) + ")"
    return head


def render_diff(events, seen: int, total: int, feeds_on: bool = True) -> str:
    """diff の人間可読出力。feeds/欠如(feeds_on=False)は no-op を告知。"""
    if not feeds_on:
        return "（feeds/ 未配置のため AIカーソルは無効＝no-op。OSSコアは差分読みを持ちません）"
    if not events:
        return f"✅ 差分なし（最新まで既読・全{total}件）"
    out = [f"📥 前回から {len(events)} 件（既読 {seen} → 最新 {total}）:"]
    out += ["  " + render_diff_event(ev) for ev in events]
    return "\n".join(out)


def _load_feed(feed_id: str):
    p = FEEDS_DIR / f"{feed_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def refresh_feeds() -> list:
    """feeds/内の *_feed.py を実行してフィードを再生成（失敗は握りつぶさず名前を返す・古いキャッシュ表示）。"""
    import subprocess
    failed = []
    if not FEEDS_DIR.exists():
        return failed
    for script in sorted(FEEDS_DIR.glob("*_feed.py")):
        r = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=30)
        if r.returncode != 0:
            failed.append(script.name)
    return failed


def _pulse_momentum_html() -> str:
    """momentum帯の「今週done（先週比）」セグメント。feeds無し（OSS素）なら沈黙。"""
    feed = _load_feed("pulse")
    if not feed:
        return ""
    t = feed["total"]
    diff = t["done7"] - t["done_prev7"]
    arrow = f'▲+{diff}' if diff > 0 else (f'▼{diff}' if diff < 0 else '±0')
    return (f'<div class="sep"></div><div><div class="big">{t["done7"]} <small style="font-size:13px">{arrow}</small></div>'
            f'<div class="lbl">done this week</div></div>')


def _feed_pulse_html() -> str:
    """🛰 進捗パルス（P1導出計器）: velocity・burnup・休眠を journal から導出して表示。
    手で維持するメタデータ（milestone等）が腐る問題への答え＝記入ゼロで動く計器。
    人間は進捗を「状態」でなく「変化」で知覚する — 今週の動きを一等地に出す。"""
    feed = _load_feed("pulse")
    if not feed:
        return ""
    e = html.escape
    t = feed["total"]
    diff = t["done7"] - t["done_prev7"]
    arrow = f'▲+{diff}' if diff > 0 else (f'▼{diff}' if diff < 0 else '±0')
    rows = []
    for p in feed["projects"][:8]:   # 今週動いた順。動きゼロの羅列はしない（ダークコックピット）
        if p["done7"] + p["added7"] == 0:
            continue
        rows.append(
            f'<div class="pulserow"><span class="pulsename">[{e(p["pid"])}] {e(p["name"])}</span>'
            f'<span class="pulsenum">✅{p["done7"]} ➕{p["added7"]}</span>'
            f'{p.get("svg", "")}'
            f'<span class="hint">{p["quiet_days"]}日前</span></div>')
    quiet = [q for q in feed["dormant"]]
    quiet_html = ""
    if quiet:
        parts = [f'{e(q["pid"])} {"記録なし" if q["quiet_days"] is None else str(q["quiet_days"]) + "日"}'
                 for q in quiet[:10]]
        quiet_html = f'<div class="hint" style="margin-top:6px">😴 静か: {" ・ ".join(parts)}</div>'
    return (f'<div class="sectitle">🛰 進捗パルス — 今週 done <b>{t["done7"]}</b>（先週比 {arrow}）・'
            f'追加 {t["added7"]} <span class="hint">（journalから自動導出・記録開始 {e(feed["journal_start"])}）</span></div>'
            f'<div class="pulsecard">{"".join(rows) or "<div class=hint>今週はまだ動きがありません</div>"}'
            f'{quiet_html}</div>')


def _feed_pr_html(served: bool) -> str:
    """📣 広報室カード（F1）: 次のポスト・投稿ペース・[投稿済みにする]ボタン。"""
    feed = _load_feed("pr")
    if not feed:
        return ""
    e = html.escape
    n = feed.get("next")
    days = feed.get("days_since_last_post")
    pace = (f'最終投稿から <b>{days}日</b>' if days is not None else "投稿実績なし")
    pace_warn = ' <span style="color:var(--hi);font-weight:800">⚠ 週1ペース超過</span>' if (days or 0) > 7 else ""
    if n:
        age = f'（{n["status"]}・作成から{n["age_days"]}日）' if n.get("age_days") is not None else f'（{n["status"]}）'
        if served:
            # 👁 プレビュー=整形表示（3セクション原稿から投稿範囲を自分で選んでコピー）
            act = (f'<a class="btn" href="/pr-preview?file={e(n["file"])}" target="_blank">👁 プレビュー</a>'
                   f'<form class="act-f" method="post" action="/pr-posted">'
                   f'<input type="hidden" name="file" value="{e(n["file"])}">'
                   f'<button class="btn ok">📣 投稿済みにする</button></form>'
                   f'<form class="act-f" method="post" action="/pr-reject" '
                   f'onsubmit="return confirm(\'この記事を不採用にして、広報官に次の記事の作成を依頼します。よろしいですか？\')">'
                   f'<input type="hidden" name="file" value="{e(n["file"])}">'
                   f'<button class="btn no">🗑 不採用</button></form>')
        else:
            act = (f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" '
                   f'data-cmd="python3 feeds/pr_feed.py set-posted {e(n["file"])}">pr_feed.py set-posted …</code>')
        body = (f'<div class="apr"><div><b>次に載せる: {e(n["title"])}</b> '
                f'<span class="id">{age}</span><br>'
                f'<span class="hint">{e(n["file"])} ｜ {pace}{pace_warn}</span></div><div>{act}</div></div>')
    else:
        body = f'<div class="apr-empty">キューは空です 🎉（{pace}）</div>'
    return f'<div class="sectitle">📣 広報室 — 次のポスト</div><div class="apr-wrap">{body}</div>'


def _feed_brief_html(served: bool) -> str:
    """📰 デイリーブリーフカード（F2）: 今日の3つ＋[🌱 種にする]。読み物はリンク先で。"""
    feed = _load_feed("brief")
    if not feed or not feed.get("items"):
        return ""
    e = html.escape
    rows = []
    for it in feed["items"]:
        src = f'brief {feed.get("brief_date","")} / {it.get("source","")}'
        if served:
            act = (f'<form class="act-f" method="post" action="/seed">'
                   f'<input type="hidden" name="title" value="{e(it["title"])}">'
                   f'<input type="hidden" name="src" value="{e(src)}">'
                   f'<button class="btn">🌱 種にする</button></form>')
        else:
            act = (f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" '
                   f'data-cmd="python3 cockpit.py seed &quot;{e(it["title"])}&quot; &quot;{e(src)}&quot;">seed…</code>')
        link = f' <a href="{e(it["link"])}" target="_blank" style="color:var(--accent)">↗</a>' if it.get("link") else ""
        rows.append(
            f'<div class="apr"><div><b>{e(it["title"])}</b>{link} '
            f'<span class="id">{e(it.get("tier",""))} · {e(it.get("theme",""))}</span><br>'
            f'<span class="hint">{e(it.get("summary",""))}</span></div><div>{act}</div></div>')
    note = f'<span class="hint">（{e(feed.get("date_note",""))}）</span>' if feed.get("date_note") else ""
    return (f'<div class="sectitle">📰 今日の3つ — デイリーブリーフ {e(feed.get("brief_date",""))} {note}</div>'
            f'<div class="apr-wrap">{"".join(rows)}</div>')


def _feed_evals_html() -> str:
    """✅ 品質チップ列（F4・H4）: 各MOCの検証スイート集計＋鮮度。計測は evals_feed.py run（明示のみ）。"""
    feed = _load_feed("evals")
    if not feed or not feed.get("items"):
        return ""
    e = html.escape
    chips = []
    for it in feed["items"]:
        icon = "⏭" if it.get("skipped") else ("✅" if it.get("ok") else "❌")
        cls = "skip" if it.get("skipped") else ("ok" if it.get("ok") else "ng")
        score = f' <b>{e(it["score"])}</b>' if it.get("score") else ""
        tip = e(it.get("detail", ""))
        chips.append(f'<span class="evalchip {cls}" title="{tip}">{icon} {e(it["name"])}{score}</span>')
    fresh = f'<span class="hint">as of {e(feed["generated"])} · 再計測: <code>python3 feeds/evals_feed.py run</code></span>' \
        if feed.get("generated") else ""
    return (f'<div class="sectitle">✅ 品質 — Evals横断 {fresh}</div>'
            f'<div class="evalsbar">{"".join(chips)}</div>')


def find_tasks(state, keyword: str, group=None):
    """done-lookupプリミティブ: 全プロジェクトの全タスク（done含む）を横断検索。
    snapshot は done を載せない＝『既に済んだか』に答えられない穴を、この関数が塞ぐ。
    group 指定時はそのグループのタスクだけに絞る（後方互換＝group=None で従来通り全件）。"""
    k = keyword.lower()
    hits = []
    for p in state["projects"]:
        for t in p.get("tasks", []):
            if group is not None and (t.get("group") or None) != group:
                continue
            blob = (t.get("desc", "") + t.get("detail", "") + t.get("why", "")).lower()
            if k in blob:
                hits.append({"pid": p["id"], "id": t["id"], "status": t.get("status"),
                             "owner": t.get("owner"), "desc": t.get("desc", ""),
                             "group": t.get("group")})
    return hits


def _feed_drift_html() -> str:
    """🔄 同期係カード（ドリフト検出）: MOCカードと台帳の乖離を提案として出す。書き込みはしない。"""
    feed = _load_feed("drift")
    if not feed or not feed.get("items"):
        return ""
    e = html.escape
    rows = []
    for it in feed["items"]:
        if it["kind"] == "dangling":
            msg = f'カードが存在しないタスク <b>{e(it["task"])}</b> を参照（参照切れ）'
        else:
            msg = (f'<b>{e(it["task"])}</b> は台帳で <b>{e(str(it.get("ledger_status")))}</b> '
                   f'なのにカードは未チェック → <code>[x]</code> 化を提案')
        rows.append(f'<div class="apr"><div>[{e(it["pid"])}] {msg}<br>'
                    f'<span class="hint">カード「{e(it["card"][:60])}」</span></div></div>')
    return (f'<div class="sectitle">🔄 同期係 — カード⇄台帳の乖離 {len(feed["items"])}件 '
            f'<span class="hint">（提案のみ・確定は人間）</span></div>'
            f'<div class="apr-wrap">{"".join(rows)}</div>')


def _feed_surprises_html() -> str:
    """💡 想定外の発見（F4・H4）: flow/surprises.md の最新3件。忘れない・週次棚卸しの入口。"""
    feed = _load_feed("surprises")
    if not feed or not feed.get("items"):
        return ""
    e = html.escape
    rows = []
    for it in feed["items"]:
        tx = it["text"]
        tx = tx[:180] + "…" if len(tx) > 180 else tx
        rows.append(f'<div class="ti"><span class="hint">{e(it["date"])}</span> {e(tx)}</div>')
    return (f'<div class="sectitle">💡 最近の想定外（surprises・全{feed.get("total","?")}件）</div>'
            f'<div class="kblock" style="font-size:13px">{"".join(rows)}</div>')


def _links_html(path=None) -> str:
    """🔗 外部ツールリンク集（F3・H4）: integrations.local.toml の [links] をサイドバーに。
    ファイルが無ければ空文字＝OSSコアは沈黙（私物配線はgitignore対象のtomlに隔離）。"""
    p = Path(path) if path else (HERE / "integrations.local.toml")
    if not p.exists():
        return ""
    try:
        import tomllib
        links = tomllib.loads(p.read_text(encoding="utf-8")).get("links", {})
    except Exception:
        return ""
    if not links:
        return ""
    a = "".join(f'<a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(l)}</a>'
                for l, u in links.items())
    return f'<div class="extlinks">{a}</div>'


def _why_html(t) -> str:   # 承認カードに propose の根拠(--why)を表示（C3・HITLの判断材料）
    w = t.get("why")
    return f'<br><span class="hint">💬 {html.escape(w)}</span>' if w else ""


def render_dashboard(state, served=False, active="now", flash="") -> str:
    e = html.escape
    s = _dash_stats(state)
    sp = _sorted_projects(state)
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=3)).isoformat()

    def cur_idx(p):
        for i, ph in enumerate(p.get("phases", [])):
            if ph.get("status") != "done":
                return i
        return len(p.get("phases", []))

    def journey_mini(p):
        cur = cur_idx(p)
        return "".join(
            f'<span class="seg {"done" if i < cur else ("cur" if i == cur else "")}" title="{e(ph.get("name",""))}"></span>'
            for i, ph in enumerate(p.get("phases", [])))

    def journey_full(p):
        cur = cur_idx(p)
        out = []
        for i, ph in enumerate(p.get("phases", [])):
            mark, cls = ("✅", "done") if i < cur else (("●", "cur") if i == cur else ("○", "future"))
            here = " (you are here)" if i == cur else ""
            btn = ""
            if served and i == cur:
                btn = (f'<form class="act-f" method="post" action="/set-phase">'
                       f'<input type="hidden" name="pid" value="{p["id"]}"><input type="hidden" name="idx" value="{i}">'
                       f'<input type="hidden" name="status" value="done"><input type="hidden" name="pg" value="projects">'
                       f'<button class="btn ph">✅ Complete phase</button></form>')
            elif served and i == cur - 1:   # 直近の完了Phaseだけ「↺ todo」で1段戻せる（誤操作の即リカバリ）
                btn = (f'<form class="act-f" method="post" action="/set-phase">'
                       f'<input type="hidden" name="pid" value="{p["id"]}"><input type="hidden" name="idx" value="{i}">'
                       f'<input type="hidden" name="status" value="todo"><input type="hidden" name="pg" value="projects">'
                       f'<button class="btn" title="このPhaseを未完に戻す">↺ todo</button></form>')
            # P5: phaseにgroupが紐づいていれば、タスク由来の進捗（正直な物差し）を添える
            ptp = _phase_task_progress(p, ph)
            pt = f' <span class="hint">· {ptp[0]}/{ptp[1]} tasks</span>' if ptp else ""
            out.append(f'<div class="jstep {cls}">{mark} {e(ph.get("name",""))} — {e(ph.get("goal",""))}{pt}{here}{btn}</div>')
        out.append(f'<div class="jgoal">🏁 Goal: {e(p.get("done_def",""))}</div>')
        return "".join(out)

    def card(p):
        phs = p.get("phases", [])
        tot = len(phs) or 1
        cur = cur_idx(p)
        prog = round(min(cur, tot) / tot * 100)
        nd = _next_due(p)
        overdue = bool(nd and nd < today)
        days_over = (date.today() - date.fromisoformat(nd)).days if overdue else 0
        due = (f"🚨 {days_over}d OVERDUE · {nd}" if overdue else f"⏰ {nd}") if nd else "no due date"
        curlabel = f"{cur}/{tot} done"
        curgoal = phs[cur]["goal"] if cur < len(phs) else "(all phases done)"
        def trow(t, n):
            b = ""
            if served and t.get("status") == "todo":
                b = (f'<form class="act-f" method="post" action="/set-status">'
                     f'<input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="status" value="done">'
                     f'<input type="hidden" name="pg" value="projects"><button class="btn">Done</button></form>')
            rb = (f'<div class="hint" style="margin-left:14px">💬 {e(t["readback"]["text"])} '
                  f'<span style="opacity:.6">({e(t["readback"].get("at",""))} AI復唱)</span></div>'
                  if t.get("readback") else "")
            return (f'<div class="ti">{n}. [{t.get("status")}] {e(t["id"])}: {e(t["desc"])} '
                    f'{"🤖" if t.get("owner")=="ai" else "👤"} {b}</div>{rb}')
        # group 見出し（表示名＋件数）→ 番号付きタスク。groups[].order 順・未定義末尾・未分類は最後（§3.1）。
        tparts = []
        for g in group_tasks(p):
            tparts.append(f'<div class="tgrp">{e(g["name"])} <span class="cnt">{len(g["tasks"])}件</span></div>')
            tparts += [trow(t, i) for i, t in enumerate(g["tasks"], 1)]
        ti = "".join(tparts)
        msx = ", ".join(f'{e(m["name"])}({m.get("due","")})' for m in p.get("milestones", [])) or "none"
        deps = ", ".join(p.get("depends_on", [])) or "none"
        pv_html = f'<div class="pv">{e(p["overview"])}</div>' if p.get("overview") else ""
        dc = doc_chips(p)
        docs_html = f'<div class="docs">{dc}</div>' if dc else ""
        return (f'<div class="card{" overdue" if overdue else ""}" onclick="openModal(this)">'
                f'<div class="top"><span class="dot {p.get("priority","mid")}"></span>'
                f'<span class="nm">{e(p["name"])}</span><span class="id">{p["id"]}</span></div>'
                f'<div class="goal">🎯 {e(p.get("north_star",""))}</div>'
                f'<div class="jrow">{journey_mini(p)}<span class="jlbl">{curlabel}</span></div>'
                f'<div class="next">👉 {e(_next_action(p) or "(no next action)")}</div>'
                f'<div class="due">{due} · {prog}%</div>'
                f'<div class="cdetail">'
                f'<div class="mhead">{e(p["name"])} <span class="id">{p["id"]}</span> · {PRIO_MARK.get(p.get("priority","mid"),"")}</div>'
                f'{pv_html}'
                f'<div class="jfull">{journey_full(p)}</div>'
                f'<div class="ato">Next: {e(curgoal)} ({max(tot - cur, 0)} phase(s) left)</div>'
                f'<div class="tl"><b>Tasks</b>{ti}</div>'
                f'{docs_html}'
                f'<div class="meta">📅 {msx} · deps: {e(deps)}</div>'
                + (f'<form class="act-f" method="post" action="/set-mode" onclick="event.stopPropagation()">'
                   f'<input type="hidden" name="pid" value="{p["id"]}"><input type="hidden" name="mode" value="parked">'
                   f'<input type="hidden" name="pg" value="projects">'
                   f'<button class="btn" title="いま動かさないと決める（警報対象外になる・[▶ 再開]で戻せる）">🅿 駐機する</button></form>' if served else "")
                + '</div></div>')

    def doc_chips(p):
        chips = []
        if p.get("repo"):
            chips.append(f'<span class="docchip" title="click to copy" onclick="copyCmd(this)" data-cmd="{e(p["repo"])}">📂 {e(p["repo"])}</span>')
        for d in p.get("docs", []):
            path, label = d.get("path", ""), d.get("label", d.get("path", ""))
            chips.append(f'<span class="docchip" title="click to copy path" onclick="copyCmd(this)" data-cmd="{e(path)}">📄 {e(label)}</span>')
        return "".join(chips)

    def now_detail(p, nt, why):
        """t55: concrete-action payload for a Now card (opens in the shared modal)."""
        phase_label, dn, tot = _phase_progress(p)
        o = [f'<div class="mhead">🔥 {e(p["name"])} <span class="id">{p["id"]}</span></div>']
        if nt:
            o.append(f'<div class="nd-sec">👉 NEXT TASK</div><div class="nd-body"><b>{e(nt["id"])}</b>: {e(nt["desc"])}</div>')
            if nt.get("readback"):   # 💬 AIの復唱（read-back）: 王が一瞥して解釈ズレを止める
                o.append(f'<div class="nd-body">💬 AIの解釈: {e(nt["readback"]["text"])}</div>')
        else:
            o.append('<div class="nd-body">(no open task — add one or advance the phase)</div>')
        o.append(f'<div class="nd-sec">🔥 WHY NOW</div><div class="nd-body">{e(" / ".join(why)) or "focused"}</div>')
        o.append(f'<div class="nd-sec">📍 CURRENT PHASE</div><div class="nd-body">{e(phase_label)} ({dn}/{tot})</div>')
        o.append('<div class="nd-sec">▶ CONCRETE STEPS</div>')
        if nt and nt.get("detail"):
            o += [f'<div class="nd-step">{e(s)}</div>' for s in nt["detail"].split("\n") if s.strip()]
        else:
            o.append('<div class="nd-body nd-hint">具体手順は未記入。埋めるには: '
                     f'<code>cockpit.py set-detail {e(nt["id"]) if nt else "&lt;tid&gt;"} "手順1\\n手順2"</code></div>')
        if p.get("done_def"):
            o.append(f'<div class="nd-sec">🏁 DONE WHEN</div><div class="nd-body">{e(p["done_def"])}</div>')
        dc = doc_chips(p)
        if dc:
            o.append(f'<div class="nd-sec">🔗 DOCS &amp; REPO</div><div class="docs">{dc}</div>')
        return "".join(o)

    def nowcard(p):
        why = []
        nd = _next_due(p)
        overdue = bool(nd and nd < today)
        if overdue:
            why.append(f"🚨 {(date.today()-date.fromisoformat(nd)).days}d OVERDUE")
        elif nd and nd <= horizon:
            why.append(f"⏰ due {nd}")
        if p.get("focus_until", "") >= today and p.get("focus_until"):
            why.append(f"🔥 focus until {p['focus_until']}")
        nt = _next_task(p)
        # Nowから直接アクション（王FB: この画面で完了/承認/AIへの依頼まで完結させる）
        btns = ""
        if served and nt:
            btns += (f'<form class="act-f" method="post" action="/set-status" '
                     f'onclick="event.stopPropagation()">'
                     f'<input type="hidden" name="tid" value="{nt["id"]}">'
                     f'<input type="hidden" name="status" value="done">'
                     f'<input type="hidden" name="pg" value="now">'
                     f'<button class="btn ok">✅ 完了</button></form>')
            if not nt.get("detail"):
                btns += (f'<form class="act-f" method="post" action="/request-detail" '
                         f'onclick="event.stopPropagation()">'
                         f'<input type="hidden" name="tid" value="{nt["id"]}">'
                         f'<input type="hidden" name="pg" value="now">'
                         f'<button class="btn" title="実行手順の作成をAIの受信箱に入れる">✍️ AIに手順を依頼</button></form>')
        n_prop = sum(1 for t in p.get("tasks", []) if t.get("status") == "proposed")
        if served and n_prop:
            btns += (f'<a class="btn" href="/?pg=approve" onclick="event.stopPropagation()">'
                     f'🟡 承認待ち{n_prop}件 →</a>')
        return (f'<div class="nowcard{" overdue" if overdue else ""}" onclick="openNow(this)">'
                f'<div class="why">{" / ".join(why)}</div>'
                f'<div class="nm">{e(p["name"])} <span class="id">{p["id"]}</span><span class="info" title="具体アクションを見る">ⓘ</span></div>'
                f'<div class="act">👉 {e(_next_action(p) or "(none)")}</div>'
                f'{f"<div style=\'margin-top:8px\'>{btns}</div>" if btns else ""}'
                f'<div class="ndetail">{now_detail(p, nt, why)}</div></div>')

    # ⏳ 停滞（目的③・C1）: N日以上動いていない todo。時間メタの無い旧タスクは対象外（誤検知しない）。
    stale_rows = sorted(
        [(p, t) for p in sp for t in p.get("tasks", []) if is_stale(t)],
        key=lambda r: stale_days(r[1]) or 0, reverse=True)
    if stale_rows:
        items = "".join(
            f'<div class="apr"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>'
            f'{e(t["desc"])}</div><span class="id" style="color:var(--hi);font-weight:800">'
            f'{stale_days(t)}日 停滞</span></div>' for p, t in stale_rows[:5])
        stale_html = (f'<div class="sectitle">⏳ 停滞（{STALE_THRESHOLD_DAYS}日以上動いていない '
                      f'{len(stale_rows)}件）</div><div class="apr-wrap">{items}</div>')
    else:
        stale_html = ""

    # ⏱ タイムライン（C2・journal最新5件）: 何がいつ起きたかを見せる安心パターン
    ev = []
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines()[-5:]:
            try:
                ev.append(json.loads(line))
            except Exception:
                pass
    if ev:
        rows = "".join(
            f'<div class="ti"><b>{e(r.get("ts","")[5:16])}</b> {e(r.get("op",""))} '
            f'{e(r.get("tid",""))}{(" — " + e(r["why"])) if r.get("why") else ""}</div>'
            for r in reversed(ev))
        timeline_html = f'<div class="sectitle">⏱ タイムライン（最近の操作）</div><div class="tl">{rows}</div>'
    else:
        timeline_html = ""

    if not sp:   # empty state (first run / no projects yet)
        nows = ('<div class="nowcard" style="grid-column:1/-1;border-left-color:var(--accent)">'
                '<div class="nm">Welcome to Cockpit 👋</div>'
                '<div class="act">No projects yet. Create your first one:<br>'
                '<code>python3 cockpit.py add-project proj-1 "My first project" "The goal" high</code><br>'
                'then add a phase: <code>python3 cockpit.py add-phase proj-1 "Phase 0" "first milestone"</code></div></div>')
    else:
        # parked は due が近くても Focus に出さない（意図した眠りに警報を鳴らさない＝ダークコックピット）
        nows = "".join(nowcard(p) for p in sp if near_term(p) and not is_parked(p)) or '<div class="nowcard"><div class="act">Nothing due soon</div></div>'
    # 🅿 WIPの明示（consult v3 P2）: activeだけフルカード、parkedは1行に畳む＝「14枚の壁」を崩す。
    # 人間の並行限界（Personal Kanban: WIP 2-3）を超えた等圧表示は「全部見える＝何も見えない」。
    sp_active = [p for p in sp if not is_parked(p)]
    sp_parked = [p for p in sp if is_parked(p)]
    cards = "".join(card(p) for p in sp_active) or '<div class="apr-empty">No projects yet — run <code>add-project</code>.</div>'

    def parkedrow(p):
        open_n = len(_todos(p))
        btn = ""
        if served:
            btn = (f'<form class="act-f" method="post" action="/set-mode">'
                   f'<input type="hidden" name="pid" value="{p["id"]}"><input type="hidden" name="mode" value="active">'
                   f'<input type="hidden" name="pg" value="projects"><button class="btn">▶ 再開</button></form>')
        return (f'<div class="parkedrow"><span class="nm">🅿 {e(p["name"])}</span>'
                f'<span class="id">{p["id"]}</span><span class="hint">todo {open_n}件</span>{btn}</div>')

    parked_html = ""
    if sp_parked:
        parked_html = (f'<div class="sectitle" style="margin-top:18px">🅿 Parked — 意図して眠らせている {len(sp_parked)}件 '
                       f'<span class="hint">（警報対象外・[▶ 再開]で戻す）</span></div>'
                       f'<div class="parkedwrap">{"".join(parkedrow(p) for p in sp_parked)}</div>')

    # 🚨 逸脱ファースト（P3 ダークコックピット）: 腐った約束だけが最上段で光り、
    # [直す/捨てる]の2択に追い込む。逸脱ゼロならこのカードは存在しない＝静か＝順調。
    def devrow(d):
        btns = ""
        if served and d["kind"] == "milestone":
            btns = (f'<form class="act-f" method="post" action="/ms-defer" onclick="event.stopPropagation()">'
                    f'<input type="hidden" name="pid" value="{d["pid"]}"><input type="hidden" name="name" value="{e(d["name"])}">'
                    f'<input type="hidden" name="due" value="{d["due"]}"><input type="hidden" name="pg" value="now">'
                    f'<button class="btn" title="dueを今日+2週に引き直す">⏰ +2週に延期</button></form>'
                    f'<form class="act-f" method="post" action="/ms-drop" onclick="event.stopPropagation()">'
                    f'<input type="hidden" name="pid" value="{d["pid"]}"><input type="hidden" name="name" value="{e(d["name"])}">'
                    f'<input type="hidden" name="due" value="{d["due"]}"><input type="hidden" name="pg" value="now">'
                    f'<button class="btn" title="約束を取り下げる（履歴は残る）">🗑 取り下げ</button></form>')
        elif served:   # focus失効
            btns = (f'<form class="act-f" method="post" action="/focus-extend" onclick="event.stopPropagation()">'
                    f'<input type="hidden" name="pid" value="{d["pid"]}"><input type="hidden" name="pg" value="now">'
                    f'<button class="btn">🔥 +3日 再点火</button></form>'
                    f'<form class="act-f" method="post" action="/focus-clear" onclick="event.stopPropagation()">'
                    f'<input type="hidden" name="pid" value="{d["pid"]}"><input type="hidden" name="pg" value="now">'
                    f'<button class="btn">解除</button></form>')
        icon = "📅" if d["kind"] == "milestone" else "🔥"
        return (f'<div class="devrow"><span class="devname">{icon} [{e(d["pid"])}] {e(d["name"])}</span>'
                f'<span class="devdays">{d["days"]}日超過</span>'
                f'<span class="hint">due {e(d["due"])}</span>{btns}</div>')

    devs = _deviations(state, today)
    dev_html = ""
    if devs:
        dev_html = (f'<div class="devcard"><div class="devtitle">🚨 逸脱 — 再交渉が必要な約束 {len(devs)}件 '
                    f'<span class="hint">（直すか・捨てるか。放置は計器を腐らせる）</span></div>'
                    f'{"".join(devrow(d) for d in devs)}</div>')
    appr = [(p, t) for p in sp for t in p.get("tasks", []) if t.get("status") == "proposed"]
    if served:
        appr_items = "".join(
            f'<div class="apr"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}'
            f'{_why_html(t)}</div><div>'
            f'<form class="act-f" method="post" action="/approve"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn ok">✅ Approve</button></form>'
            f'<form class="act-f" method="post" action="/reject"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn no">🗑 Reject</button></form>'
            f'</div></div>' for p, t in appr
        ) or '<div class="apr-empty">Nothing to approve 🎉</div>'
    else:
        appr_items = "".join(
            f'<div class="apr"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}'
            f'{_why_html(t)}</div>'
            f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" data-cmd="python3 cockpit.py approve {t["id"]}">cockpit.py approve {t["id"]}</code></div>' for p, t in appr
        ) or '<div class="apr-empty">Nothing to approve 🎉</div>'

    # ✅🕓 完了の確認（done-proposed）: AIが検証済み実装を「完了確認待ち」に置いた行。作成の承認と対称の"完了側"。
    # 🤖（AI作業所有）と "✅完了確認待ち" バッジを視覚的に区別（王FB: 混同を避ける）。
    donep = [(p, t) for p in sp for t in p.get("tasks", []) if t.get("done_proposed")]

    def _dp_evidence(t):
        ev = (t.get("done_proposed") or {}).get("evidence", "")
        return f'<br><span class="hint">🔎 証跡: {e(ev)}</span>' if ev else ""
    if served:
        donep_items = "".join(
            f'<div class="apr donep"><div><span class="dpbadge">✅🕓 完了確認待ち</span> '
            f'<b>{e(p["name"])}</b> <span class="id">{p["id"]}</span> <span class="id">{e(t["id"])}</span><br>{e(t["desc"])}'
            f'{_dp_evidence(t)}</div><div>'
            f'<form class="act-f" method="post" action="/confirm-done"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn ok">✅ 完了を確認</button></form>'
            f'<form class="act-f" method="post" action="/reject-done"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn no">↩ 差し戻し</button></form>'
            f'</div></div>' for p, t in donep
        ) or '<div class="apr-empty">完了確認待ちはありません 🎉</div>'
    else:
        donep_items = "".join(
            f'<div class="apr donep"><div><span class="dpbadge">✅🕓 完了確認待ち</span> '
            f'<b>{e(p["name"])}</b> <span class="id">{p["id"]}</span> <span class="id">{e(t["id"])}</span><br>{e(t["desc"])}'
            f'{_dp_evidence(t)}</div>'
            f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" data-cmd="python3 cockpit.py confirm-done {t["id"]}">cockpit.py confirm-done {t["id"]}</code></div>' for p, t in donep
        ) or '<div class="apr-empty">完了確認待ちはありません 🎉</div>'

    # "Your tasks" lane = human's turn (owner=human todos). A separate lane from AI-proposal approvals.
    work = [(p, t) for p in sp for t in p.get("tasks", []) if t.get("owner") == "human" and t.get("status") == "todo"]
    # Group by project so a long list stays scannable (#1: too many, unstructured). Rows keep class
    # "apr work" (one per human todo); a .grp header separates each project.
    wgroups = {}
    for p, t in work:
        wgroups.setdefault(p["id"], [p, []])[1].append(t)
    word = sorted(wgroups.values(), key=lambda pt: (PRIO_ORDER.get(pt[0].get("priority", "mid"), 1), pt[0]["id"]))

    def work_row(p, t):
        if served:
            act = (f'<form class="act-f" method="post" action="/set-status"><input type="hidden" name="tid" value="{t["id"]}">'
                   f'<input type="hidden" name="status" value="done"><input type="hidden" name="pg" value="approve"><button class="btn ok">Done</button></form>')
        else:
            act = (f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" '
                   f'data-cmd="python3 cockpit.py set-status {t["id"]} done">cockpit.py set-status {t["id"]} done</code>')
        return (f'<div class="apr work"><div><span class="id">{e(t["id"])}</span> {e(t["desc"])}</div>{act}</div>')

    if word:
        work_items = "".join(
            f'<div class="grp">{PRIO_MARK.get(p.get("priority","mid"),"")} {e(p["name"])} <span class="cnt">{len(ts)}件</span></div>'
            + "".join(work_row(p, t) for t in ts)
            for p, ts in word)
    else:
        work_items = '<div class="apr-empty">No tasks pending 🎉</div>'
    msg = f"{s['proposed']} awaiting your approval." if s["proposed"] else "Nothing to approve. Nice pace ✨"
    # flash（軸1: 押下→即受領）が有れば momentum 帯に前面表示。無ければ既定文言（レイアウト不変）。
    msg_html = (f'<div class="msg flash">{e(flash)}</div>' if flash
                else f'<div class="msg">{e(msg)}</div>')

    # --- KPI page (facts derivable from state.json only) ---
    prio = {"high": 0, "mid": 0, "low": 0}
    phase_dist, done_ph, tot_ph = {}, 0, 0
    for p in state["projects"]:
        prio[p.get("priority", "mid")] = prio.get(p.get("priority", "mid"), 0) + 1
        phs = p.get("phases", [])
        ci = cur_idx(p)
        tot_ph += len(phs); done_ph += min(ci, len(phs))
        key = f"Phase{ci}" if ci < len(phs) else "All done"
        phase_dist[key] = phase_dist.get(key, 0) + 1
    overall = round(done_ph / tot_ph * 100) if tot_ph else 0
    near_n = sum(1 for p in sp if near_term(p))
    npj = s["projects"] or 1

    def kbar(name, n):
        return (f'<div class="kbar"><span class="bn">{e(name)}</span>'
                f'<span class="bt"><i style="width:{round(n / npj * 100)}%"></i></span><span class="bv">{n}</span></div>')

    def kbox(n, l):
        return f'<div class="box"><div class="n">{n}</div><div class="l">{l}</div></div>'

    kpi_top = (kbox(s["projects"], "Projects") + kbox(f"{overall}%", "Overall (phases)") + kbox(s["todo"], "Open todos")
               + kbox(s["done"], "Done") + kbox(s["proposed"], "To approve") + kbox(near_n, "Due in 3d"))
    prio_bars = kbar("🔴 High", prio["high"]) + kbar("🟡 Mid", prio["mid"]) + kbar("⚪ Low", prio["low"])
    phase_bars = "".join(kbar(k, phase_dist[k]) for k in sorted(phase_dist, key=lambda k: (k == "All done", k)))
    kpi_html = (f'<div class="sectitle">📊 Summary</div><div class="kpi">{kpi_top}</div>'
                f'<div class="sectitle">Priority distribution</div><div class="kblock">{prio_bars}</div>'
                f'<div class="sectitle">Phase distribution (where each project is now)</div><div class="kblock">{phase_bars}</div>')

    def cmd(c, desc=""):
        full = e(f"python3 cockpit.py {c}")
        tail = f" — {e(desc)}" if desc else ""
        return f'<div><code class="cmd" title="click to copy" onclick="copyCmd(this)" data-cmd="{full}">cockpit.py {e(c)}</code>{tail}</div>'
    cmds_html = "".join([
        cmd("dashboard", "rebuild this page"),
        cmd("serve [port]", "local server: 1-click buttons"),
        cmd("snapshot", "compact view (what the agent reads)"),
        cmd("now [days]", "what's hot in N days"),
        cmd("detail <pid>", "deep view of one project"),
        cmd('add-project <id> "name" "goal" high', "create a project"),
        cmd('add-phase <pid> "name" "goal"', "append a phase"),
        cmd('add <pid> "task" [prio]', "your own task"),
        cmd('propose <pid> "task"', "agent proposes (awaiting approval)"),
        cmd("approve <tid>", "proposal -> todo"),
        cmd("reject <tid>", "proposal -> dropped"),
        cmd('propose-done <tid> "evidence"', "agent: mark verified work done-proposed"),
        cmd("confirm-done <tid>", "you: confirm completion -> done"),
        cmd("reject-done <tid>", "you: send a done-proposal back (still open)"),
        cmd("set-status <tid> done|skip|dropped", "change a task"),
        cmd("set-phase <pid> <n> done", "advance the Journey"),
        cmd("set-priority <pid> high|mid|low", "re-rank"),
        cmd("focus <pid> [days]", "mark hot (unfocus to clear)"),
        cmd("diff [--advance]", "changes since the AI cursor (--advance marks read)"),
        cmd("validate", "check the ledger"),
    ])
    set_html = (
        '<div class="sectitle">⚙️ Settings</div>'
        f'<div class="setbox"><b>CLI cheatsheet</b> <span class="hint">(click any command to copy)</span><div class="cmds">{cmds_html}</div></div>'
        '<div class="setbox"><b>Theme</b><br>● Simple (active — readability first)<br>'
        '○ More themes (the data-theme base is in place; a switcher is planned)</div>'
        '<div class="setbox"><b>Display &amp; ops</b><br>focus default: 3 days · Now horizon: 3 days'
        '（CLI: <code>now [days]</code> · <code>focus &lt;pid&gt; [days]</code>）</div>'
        '<div class="setbox"><b>Data &amp; regeneration</b><br>Source of truth: <code>state.json</code> (deterministic adapter only — ADR-0006)<br>'
        'Read-only: <code>snapshot.md</code> (what the agent reads)<br>'
        'Render eval: <code>python3 eval_dashboard.py</code> (invariants)<br>'
        '1-click approve: run <code>python3 cockpit.py serve</code> (local server)</div>')

    # badge = 王を待たせている件数（承認待ち + 完了確認待ち）。どちらも王のワンクリックで前進する。
    pending_n = s["proposed"] + len(donep)
    appr_badge = f" ({pending_n})" if pending_n else ""
    # one-step Undo (server only): reverts the last approve/reject/done/phase change via the auto-backup
    undo_btn = (f'<form class="undo-f" method="post" action="/undo">'
                f'<input type="hidden" name="pg" value="{active}">'
                f'<button class="undobtn" title="直前の承認 / 不可 / Done / フェーズ変更を取り消す">↩ Undo</button></form>') if served else ""
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cockpit Dashboard</title>' + DASH_CSS + _bg_css() + _brand_css() + (_raven.RAVEN_CSS if _raven else "") + "</head>")
    body = (f'<body class="bg-d th-phoenix">{_embers_html()}{_fx_html()}<div class="wrap">'
            f'<aside class="side"><div class="brand">{_brand_html()}</div><nav class="nav">'
            f'<a class="{"active" if active=="now" else ""}" data-pg="now" href="#">🔥 Now</a>'
            f'<a class="{"active" if active=="projects" else ""}" data-pg="projects" href="#">📋 Projects</a>'
            f'<a class="{"active" if active=="approve" else ""}" data-pg="approve" href="#">🙋 Your turn{appr_badge}</a>'
            f'<a class="{"active" if active=="syllabus" else ""}" data-pg="syllabus" href="#">📚 シラバス</a>'
            f'<a class="{"active" if active=="problems" else ""}" data-pg="problems" href="#">📝 問題集</a>'
            f'<a class="{"active" if active=="settings" else ""}" data-pg="settings" href="#">⚙️ Settings</a></nav>'
            f'{_links_html()}'
            f'<button class="thbtn" onclick="toggleThGrid()">👕 テーマ: <span id="thlabel">{THEMES[0][1]}</span></button>'
            f'{_theme_tiles_html()}'
            f'<button class="bgbtn" onclick="cycleBg()">🎨 背景: <span id="bglabel">D 炎金</span></button></aside>'
            f'<main class="main"><div class="head"><div><h1><span id="greet">Good morning</span> <span class="wave">👋</span></h1>'
            f'<div class="date">{date.today()} · {s["active_n"]} active / {s["parked_n"]} parked</div></div>{undo_btn}</div>'
            f'<section class="page{" active" if active=="now" else ""}" id="pg-now"><div class="momentum">'
            f'<div><div class="big">{s["active_n"]}</div><div class="lbl">active · {s["parked_n"]} parked</div></div><div class="sep"></div>'
            f'{"<div><div class=\"lbl\" style=\"color:#c0392b;font-weight:700\">⚠ WIP " + str(s["active_n"]) + " — 同時に動かすのは3つまでが目安</div></div><div class=\"sep\"></div>" if s["active_n"] > 3 else ""}'
            f'<div><div class="big">{s["todo"]}</div><div class="lbl">todo</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["done"]}</div><div class="lbl">done</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["high"]}</div><div class="lbl">high prio</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["proposed"]}</div><div class="lbl">to approve</div></div>'
            f'{_pulse_momentum_html()}'
            f'{msg_html}</div>'
            f'{dev_html}'
            f'{_raven.render_now_card(served) if _raven else ""}'
            f'<div class="sectitle">🔥 Focus (next ~3 days)</div><div class="now">{nows}</div>'
            f'{_feed_pulse_html()}{_feed_pr_html(served)}{_feed_brief_html(served)}{_feed_drift_html()}{_feed_evals_html()}{_feed_surprises_html()}{stale_html}{timeline_html}</section>'
            f'<section class="page{" active" if active=="projects" else ""}" id="pg-projects">'
            f'<div class="sectitle">📋 Active projects (by priority)</div><div class="grid">{cards}</div>{parked_html}</section>'
            f'<section class="page{" active" if active=="approve" else ""}" id="pg-approve">'
            f'<div class="sectitle">✅ 完了の確認（AIが実装完了・確認待ち → ワンクリックで done）</div>'
            f'<div class="apr-wrap">{donep_items}</div>'
            f'<div class="sectitle">🟡 Awaiting approval (AI proposals → approve to send to the agent)</div>'
            f'<div class="apr-wrap">{appr_items}</div>'
            f'<div class="sectitle">✅ Your tasks (human work → mark done to clear)</div>'
            f'<div class="apr-wrap">{work_items}</div></section>'
            f'<section class="page{" active" if active=="syllabus" else ""}" id="pg-syllabus">'
            f'{_raven.render_syllabus() if _raven else "<div class=\'hint\'>教育係(raven)が読み込めません</div>"}</section>'
            f'<section class="page{" active" if active=="problems" else ""}" id="pg-problems">'
            f'{_raven.render_problems() if _raven else ""}</section>'
            f'<section class="page{" active" if active=="settings" else ""}" id="pg-settings">{set_html}'
            f'<details class="setbox"><summary><b>📊 KPI &amp; metrics</b> <span class="hint">(rarely needed — click to expand)</span></summary>'
            f'<div style="margin-top:14px">{kpi_html}</div></details></section>'
            f'<div id="ov" class="ov" onclick="if(event.target===this)closeModal()"><div class="modal"><button class="mx" onclick="closeModal()" title="close">×</button><div id="mbody"></div></div></div>'
            f'<div class="foot">Auto-generated from state.json (deterministic · ADR-0006). Regenerated on every change.</div>'
            f'</main></div>')
    script = ('<script>'
              'var N=document.querySelectorAll(".nav a"),P=document.querySelectorAll(".page");'
              'function go(g){N.forEach(function(x){x.classList.toggle("active",x.dataset.pg===g)});'
              'P.forEach(function(p){p.classList.toggle("active",p.id==="pg-"+g)})}'
              'N.forEach(function(a){a.onclick=function(e){e.preventDefault();go(a.dataset.pg)}});'
              'var q=new URLSearchParams(location.search).get("pg");if(q)go(q);'
              'function openModal(c){document.getElementById("mbody").innerHTML=c.querySelector(".cdetail").innerHTML;document.getElementById("ov").classList.add("open")}'
              'function openNow(c){document.getElementById("mbody").innerHTML=c.querySelector(".ndetail").innerHTML;document.getElementById("ov").classList.add("open")}'
              'function closeModal(){document.getElementById("ov").classList.remove("open")}'
              'document.addEventListener("keydown",function(e){if(e.key==="Escape")closeModal()});'
              'function copyCmd(el){var t=el.dataset.cmd,o=el.textContent;function ok(){el.textContent="✓ copied";setTimeout(function(){el.textContent=o},1000)}'
              'if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,function(){cpFb(t,ok)})}else{cpFb(t,ok)}}'
              'function cpFb(t,cb){var a=document.createElement("textarea");a.value=t;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.focus();a.select();try{document.execCommand("copy")}catch(e){}document.body.removeChild(a);cb()}'
              # 原稿など長文のコピー（base64→UTF-8復元。F1: 広報の本文コピペ）
              'function copyB64(el){var t=decodeURIComponent(escape(atob(el.dataset.b64))),o=el.textContent;'
              'function ok(){el.textContent="✓ コピーした";setTimeout(function(){el.textContent=o},1200)}'
              'if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,function(){cpFb(t,ok)})}else{cpFb(t,ok)}}'
              # 着せ替えテーマ切替（localStorage。THEMES が単一の正）
              f'var THS={json.dumps([c for c, _ in THEMES], ensure_ascii=False)},'
              f'THL={json.dumps(dict(THEMES), ensure_ascii=False)};'
              'function applyTheme(c){if(THS.indexOf(c)<0)c="th-phoenix";THS.forEach(function(x){document.body.classList.remove(x)});document.body.classList.add(c);'
              'var l=document.getElementById("thlabel");if(l)l.textContent=THL[c];'
              'document.querySelectorAll(".thtile").forEach(function(t){t.classList.toggle("sel",t.dataset.th===c)});'
              'try{localStorage.setItem("cockpit-theme",c)}catch(e){}}'
              'function toggleThGrid(){var g=document.getElementById("thgrid");if(g)g.classList.toggle("open")}'
              'var st="th-phoenix";try{st=localStorage.getItem("cockpit-theme")||"th-phoenix"}catch(e){}applyTheme(st);'
              'function cycleTheme(){var c="th-phoenix";try{c=localStorage.getItem("cockpit-theme")||"th-phoenix"}catch(e){}applyTheme(THS[(THS.indexOf(c)+1)%THS.length])}'
              # 時刻対応の挨拶（ブラウザ現地時間・#greet のテキストのみ差し替え、👋 .wave span は保持）
              'function setGreet(){var h=new Date().getHours(),g=document.getElementById("greet");if(!g)return;'
              'g.textContent=h<5?"Good evening":h<12?"Good morning":h<18?"Good afternoon":"Good evening"}setGreet();'
              'var BGS=["bg-d","bg-b","bg-none"],BGL={"bg-d":"D 炎金","bg-b":"B 紫炎","bg-none":"OFF"};'
              'function applyBg(c){document.body.classList.remove("bg-d","bg-b","bg-none");document.body.classList.add(c);'
              'var l=document.getElementById("bglabel");if(l)l.textContent=BGL[c];try{localStorage.setItem("cockpit-bg",c)}catch(e){}}'
              'var sb=null;try{sb=localStorage.getItem("cockpit-bg")}catch(e){}if(sb)applyBg(sb);'
              'function cycleBg(){var c="bg-d";try{c=localStorage.getItem("cockpit-bg")||"bg-d"}catch(e){}applyBg(BGS[(BGS.indexOf(c)+1)%BGS.length])}'
              'function fxBurst(row,type){var r=row.getBoundingClientRect(),L=document.createElement("div");L.className="fxlayer";'
              'L.style.left=r.left+"px";L.style.top=r.top+"px";L.style.width=r.width+"px";L.style.height=r.height+"px";document.body.appendChild(L);'
              'var n=type==="approve"?22:(type==="ash"?16:11);for(var i=0;i<n;i++){var s=document.createElement("i");'
              'if(type==="ash"){s.className="ash";s.style.left=(Math.random()*100)+"%";s.style.setProperty("--dx",(Math.random()*40-20)+"px");s.style.animationDelay=(Math.random()*.25)+"s"}'
              'else{var ang=Math.random()*Math.PI*2,d=42+Math.random()*92;s.className=type==="done"?"spark g":"spark";s.style.left="50%";s.style.top="50%";'
              's.style.setProperty("--tx",(Math.cos(ang)*d)+"px");s.style.setProperty("--ty",(Math.sin(ang)*d)+"px");s.style.animationDelay=(Math.random()*.1)+"s"}'
              'L.appendChild(s)}setTimeout(function(){L.remove()},1150)}'
              'function fxThenSubmit(form,type){var row=form.closest(".apr")||document.body;row.classList.add("fx-"+type);fxBurst(row,type);'
              'var d=type==="approve"?820:(type==="ash"?760:640);setTimeout(function(){form.submit()},d)}'
              'document.addEventListener("submit",function(e){var a=e.target.getAttribute("action");'
              'if(a==="/approve"){e.preventDefault();fxThenSubmit(e.target,"approve")}'
              'else if(a==="/reject"){e.preventDefault();fxThenSubmit(e.target,"ash")}'
              'else if(a==="/set-status"){e.preventDefault();fxThenSubmit(e.target,"done")}});'
              '</script></body></html>')
    return head + body + script


def main(argv):
    if not argv or argv[0] in ("snapshot", "snap"):
        # snapshot [--group <g>]: --group 指定時は1グループのミニsnapshotを print（ファイルは更新しない・§3.2）
        grp = None
        if "--group" in argv:
            i = argv.index("--group")
            grp = argv[i + 1] if i + 1 < len(argv) else None
        if grp:
            st = load_state()
            print(render_snapshot_md(make_snapshot(st, group=grp), st, group=grp)); return
        print(render_snapshot_md(emit_snapshot())); print(f"→ {SNAP_MD}"); return
    if argv[0] == "dashboard":
        failed = refresh_feeds()
        if failed:
            print(f"⚠ feed更新失敗（古いキャッシュを表示）: {', '.join(failed)}")
        emit_snapshot(); print(f"✅ dashboard generated → {DASH_HTML}"); return
    if argv[0] == "feeds":
        failed = refresh_feeds()
        print("✅ feeds refreshed" + (f"（失敗: {', '.join(failed)}）" if failed else ""))
        emit_snapshot(); return
    if argv[0] == "serve":
        import serve
        serve.run(int(argv[1]) if len(argv) > 1 else 8765); return
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "detail":
            print(detail(rest[0]))
        elif cmd == "list":
            for p in _sorted_projects(load_state()):
                print(f"## {PRIO_MARK.get(p.get('priority','mid'),'')} {p['name']} ({p['id']})")
                for t in p.get("tasks", []):
                    print(f"  [{t['status']:>8}] {t['id']}: {t['desc']}")
        elif cmd == "add-project":
            print(add_project(rest[0], rest[1], rest[2] if len(rest) > 2 else "", rest[3] if len(rest) > 3 else "mid"))
        elif cmd == "add-phase":
            print(add_phase(rest[0], rest[1], rest[2] if len(rest) > 2 else ""))
        elif cmd == "set-status":
            print(set_status(rest[0], rest[1]))
        elif cmd == "set-mode":
            print(set_mode(rest[0], rest[1]))
        elif cmd == "set-phase-groups":
            # set-phase-groups <pid> <idx> [g1,g2]  … phaseにgroupを紐づけ→進捗をタスクから導出（P5）
            print(set_phase_groups(rest[0], rest[1], rest[2] if len(rest) > 2 else ""))
        elif cmd == "readback":
            # readback <tid> "解釈 or 最初の一手を1行"  … agent: 着手の復唱（ICAO read-back・P4）
            print(readback(rest[0], rest[1]))
        elif cmd == "set-detail":
            print(set_detail(rest[0], rest[1]))
        elif cmd == "set-overview":
            print(set_overview(rest[0], rest[1]))
        elif cmd == "add-doc":
            print(add_doc(rest[0], rest[1], rest[2]))
        elif cmd == "propose":
            # propose <pid> <desc> [--why "根拠"] [--group <g>]  … 承認判断の材料を残す（HITLの質・C3）
            why = ""
            if "--why" in rest:
                i = rest.index("--why")
                why = rest[i + 1] if i + 1 < len(rest) else ""
                rest = rest[:i] + rest[i + 2:]
            grp = None
            if "--group" in rest:
                i = rest.index("--group")
                grp = rest[i + 1] if i + 1 < len(rest) else None
                rest = rest[:i] + rest[i + 2:]
            print(propose(rest[0], rest[1], why=why, group=grp))
        elif cmd == "add":
            # add <pid> <desc> [prio] [--group <g>]
            grp = None
            if "--group" in rest:
                i = rest.index("--group")
                grp = rest[i + 1] if i + 1 < len(rest) else None
                rest = rest[:i] + rest[i + 2:]
            print(add_task(rest[0], rest[1], rest[2] if len(rest) > 2 else None, group=grp))
        elif cmd == "set-group":
            # set-group <tid> <group>  |  set-group <tid> --clear
            grp = None if (len(rest) > 1 and rest[1] == "--clear") else (rest[1] if len(rest) > 1 else None)
            print(set_group(rest[0], grp))
        elif cmd == "set-owner":
            # set-owner <tid> <ai|human>
            print(set_owner(rest[0], rest[1]))
        elif cmd == "add-group":
            # add-group <pid> <id> "<name>" [order]
            print(add_group(rest[0], rest[1], rest[2], rest[3] if len(rest) > 3 else None))
        elif cmd == "group":
            # group <g>: そのグループのタスクを一覧（find の group専用ショートカット）
            g = rest[0] if rest else ""
            hits = find_tasks(load_state(), "", group=g)
            if not hits:
                print(f"（グループ '{g}' にタスクなし）")
            else:
                print(f"# グループ '{g}'（{len(hits)}件）")
                for h in hits:
                    print(f"  [{h['pid']}] {h['id']} {h['status']}/{h['owner']}: {h['desc']}")
        elif cmd == "approve":
            print(approve(rest[0]))
        elif cmd == "reject":
            print(reject(rest[0]))
        elif cmd == "propose-done":
            # propose-done <tid> ["evidence"]  … agent: 検証済みタスクを「完了確認待ち」に（status不変・HITL）
            print(propose_done(rest[0], rest[1] if len(rest) > 1 else ""))
        elif cmd == "confirm-done":
            # confirm-done <tid>  … human: 完了を確定（status=done＋マーカー消去）
            print(confirm_done(rest[0]))
        elif cmd == "reject-done":
            # reject-done <tid>  … human: 差し戻し（マーカーのみ消去・タスクは残る）
            print(reject_done(rest[0]))
        elif cmd == "now":
            print(now_view(rest[0] if rest else 3))
        elif cmd == "set-priority":
            print(set_priority(rest[0], rest[1]))
        elif cmd == "set-phase":
            print(set_phase(rest[0], rest[1], rest[2]))
        elif cmd == "focus":
            print(focus(rest[0], rest[1] if len(rest) > 1 else 3))
        elif cmd == "unfocus":
            print(unfocus(rest[0]))
        elif cmd == "seed":
            print(seed(rest[0], rest[1] if len(rest) > 1 else ""))
        elif cmd == "assign":
            print(assign(rest[0], rest[1]))
        elif cmd == "request-detail":
            print(request_detail(rest[0]))
        elif cmd == "find":
            # done-lookup: 全タスク横断（done含む）。サブエージェントが「既に済んだか」を確認する用。
            # find <kw> [--group <g>]: --group でそのグループだけに絞る（返却トークンを縮約・§4）。
            grp = None
            if "--group" in rest:
                i = rest.index("--group")
                grp = rest[i + 1] if i + 1 < len(rest) else None
                rest = rest[:i] + rest[i + 2:]
            hits = find_tasks(load_state(), rest[0] if rest else "", group=grp)
            if not hits:
                print(f"（'{rest[0] if rest else ''}' に一致するタスクなし{f' [group={grp}]' if grp else ''}）")
            else:
                for h in hits:
                    print(f"  [{h['pid']}] {h['id']} {h['status']}/{h['owner']}: {h['desc']}")
        elif cmd == "stale":
            # 停滞（N日以上動いていない todo）を一覧。目的③「漏れゼロ」の計器。
            thr = int(rest[0]) if rest else STALE_THRESHOLD_DAYS
            st = load_state()
            rows = [(p, t) for p in _sorted_projects(st) for t in p.get("tasks", []) if is_stale(t, threshold=thr)]
            if not rows:
                print(f"✅ 停滞なし（{thr}日以上動いていない todo は無し）")
            else:
                print(f"⏳ 停滞タスク（{thr}日以上・{len(rows)}件）:")
                for p, t in sorted(rows, key=lambda r: stale_days(r[1]) or 0, reverse=True):
                    print(f"  {stale_days(t)}日  [{p['id']}] {t['id']}: {t['desc']}")
        elif cmd == "diff":
            # diff [--advance]: AIカーソル以降の journal 差分を人が読める形で出力（§3.2/§4 S2）。
            #   diff            … カーソル以降のイベントを覗く（カーソルは動かさない）
            #   diff --advance  … 出力後にカーソルを最新へ進める（既読化）
            # feeds/ が無ければ機能OFF＝no-op（OSSコアは汎用のまま・state.json には触れない）。
            advance = "--advance" in rest
            if not FEEDS_DIR.exists():
                print(render_diff([], 0, 0, feeds_on=False)); return
            events, seen, total = cursor_diff(JOURNAL, CURSOR)
            print(render_diff(events, seen, total, feeds_on=True))
            if advance and total != seen:
                if write_cursor(CURSOR, total):
                    print(f"→ カーソルを最新へ（既読 {total}件・以降が次の差分）")
        elif cmd == "validate":
            errs = validate(load_state())
            print("✅ valid" if not errs else f"❌ {len(errs)} error(s):\n" + "\n".join(errs))
            sys.exit(1 if errs else 0)
        else:
            print(__doc__); sys.exit(1)
    except (KeyError, ValueError, IndexError) as exc:
        print(f"⚠ {exc}"); sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
