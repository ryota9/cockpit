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
  validate                          # check the canonical state for errors
"""
from __future__ import annotations
import html
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
EXAMPLE = HERE / "state.example.json"
BAK = HERE / "state.json.bak"
SNAP_MD = HERE / "snapshot.md"
DASH_HTML = HERE / "dashboard.html"

HUMAN_STATUS = {"todo", "done", "skip", "dropped"}
ALL_STATUS = HUMAN_STATUS | {"proposed"}
PRIO_ORDER = {"high": 0, "mid": 1, "low": 2}
PRIO_MARK = {"high": "🔴 High", "mid": "🟡 Mid", "low": "⚪ Low"}


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
    dues = [m["due"] for m in p.get("milestones", []) if m.get("status") != "done" and m.get("due")]
    dues += [t["due"] for t in p.get("tasks", []) if t.get("status") == "todo" and t.get("due")]
    return min(dues) if dues else None


def _todos(p):
    return [t for t in p.get("tasks", []) if t.get("status") == "todo"]


def _next_action(p):
    ts = sorted(_todos(p), key=lambda t: (PRIO_ORDER.get(t.get("priority", "mid"), 1), t.get("due") or "9999"))
    return f'{ts[0]["id"]}: {ts[0]["desc"]}' if ts else None


def _sorted_projects(state):
    return sorted(state["projects"],
                  key=lambda p: (PRIO_ORDER.get(p.get("priority", "mid"), 1), _next_due(p) or "9999"))


# --- Snapshot (the thin layer the agent reads) ---
def snapshot_project(p):
    phase, dn, tot = _phase_progress(p)
    return {
        "id": p["id"], "name": p["name"], "goal": p.get("north_star", ""),
        "priority": p.get("priority", "mid"),
        "phase": phase, "phase_progress": f"{dn}/{tot}" if tot else "—",
        "next_due": _next_due(p), "next_action": _next_action(p),
        "open_tasks": [f'{t["id"]}: {t["desc"]}' for t in _todos(p)],
        "proposed": [f'{t["id"]}: {t["desc"]}' for t in p.get("tasks", []) if t.get("status") == "proposed"],
    }


def make_snapshot(state):
    return {"generated": str(date.today()), "projects": [snapshot_project(p) for p in _sorted_projects(state)]}


def render_snapshot_md(snap, state=None) -> str:
    out = [f"# Cockpit Snapshot ({snap['generated']} · read-only · by priority)",
           "> The agent reads this. Deep info: `detail <pid>`. Changes: agent proposes -> human approves.", ""]
    ai_todos = [(p["id"], t) for p in (state or {}).get("projects", [])
                for t in p.get("tasks", []) if t.get("owner") == "ai" and t.get("status") == "todo"]
    if ai_todos:
        out.append("## 🤖 Ready for the agent (approved, owner=ai todos = my inbox)")
        out += [f"- [{pid}] {t['id']}: {t['desc']}" for pid, t in ai_todos]
        out.append("")
    for p in snap["projects"]:
        due = f" | due {p['next_due']}" if p["next_due"] else ""
        out.append(f"## {PRIO_MARK.get(p['priority'],'')} {p['name']} ({p['id']}){due}")
        out.append(f"- Goal: {p['goal']}")
        out.append(f"- phase({p['phase_progress']}): {p['phase']}")
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
    state = load_state(); _, t = _find_task(state, tid)
    if not t:
        raise KeyError(f"task {tid} not found")
    t["status"] = status; save_state(state); emit_snapshot(state)
    return f"✅ {tid} → {status}"


def propose(pid, desc):
    state = load_state()
    proj = _find_project(state, pid)
    if not proj:
        raise KeyError(f"project {pid} not found")
    tid = _next_id(state)
    proj.setdefault("tasks", []).append({"id": tid, "desc": desc, "status": "proposed", "owner": "ai"})
    save_state(state); emit_snapshot(state)
    return f"🟡 proposed {tid} (awaiting approval): {desc}"


def add_task(pid, desc, prio=None):   # human: add your own task (agent-uninvolved = owner human todo)
    state = load_state()
    proj = _find_project(state, pid)
    if not proj:
        raise KeyError(f"project {pid} not found")
    tid = _next_id(state)
    t = {"id": tid, "desc": desc, "status": "todo", "owner": "human"}
    if prio in PRIO_ORDER:
        t["priority"] = prio
    proj.setdefault("tasks", []).append(t)
    save_state(state); emit_snapshot(state)
    return f"✅ added {tid} (your task · todo): {desc}"


def approve(tid):
    state = load_state(); _, t = _find_task(state, tid)
    if not t or t.get("status") != "proposed":
        raise ValueError(f"{tid} is not proposed")
    t["status"] = "todo"; save_state(state); emit_snapshot(state)
    return f"✅ approved {tid} → todo"


def reject(tid):
    state = load_state(); _, t = _find_task(state, tid)
    if not t or t.get("status") != "proposed":
        raise ValueError(f"{tid} is not proposed")
    t["status"] = "dropped"; save_state(state); emit_snapshot(state)
    return f"🗑 rejected {tid} → dropped"


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
    return f"🔥 {pid} focused (until {until})"


def unfocus(pid):
    state = load_state()
    p = _find_project(state, pid)
    if p and p.pop("focus_until", None) is not None:
        save_state(state); emit_snapshot(state)
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
    ":root{--bg:#eef2f8;--surface:#fff;--ink:#1f2d3d;--muted:#64748b;--line:#dde5ee;--accent:#2563eb;--accent2:#60a5fa;--hi:#e11d48;--mid:#d97706;--low:#94a3b8;--radius:16px;--shadow:0 6px 20px rgba(31,45,61,.08)}"
    "body{margin:0;font-family:'Hiragino Sans','Yu Gothic UI','Noto Sans JP',system-ui,sans-serif;color:var(--ink);background:var(--bg)}"
    ".wrap{display:grid;grid-template-columns:210px 1fr;min-height:100vh}"
    ".side{padding:18px 14px;border-right:1px solid var(--line);background:#ffffffaa}.brand{font-weight:800;font-size:20px;margin:4px 8px 18px}"
    ".nav a{display:block;padding:10px 12px;border-radius:12px;color:var(--ink);text-decoration:none;font-size:14px;margin-bottom:4px;opacity:.85}.nav a.active{background:#2563eb26;color:var(--accent);font-weight:700}"
    ".main{padding:20px 26px}.head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}.head h1{font-size:22px;margin:0}.date{color:var(--muted);font-size:13px}"
    ".momentum{display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:linear-gradient(90deg,#eef4ff,#fff);border:1px solid var(--line);border-radius:14px;padding:12px 18px;margin-bottom:22px}"
    ".momentum .big{font-size:22px;font-weight:800;color:var(--accent)}.momentum .lbl{font-size:12px;color:var(--muted)}.momentum .sep{width:1px;height:30px;background:var(--line)}.momentum .msg{margin-left:auto;font-weight:700}"
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
    ".ato{background:#2563eb0d;border-radius:8px;padding:7px 10px;margin:6px 0;font-size:12px}.tl{margin:8px 0}.tl b{font-size:12px;color:var(--muted)}.ti{padding:3px 0}.meta{font-size:11px;color:var(--muted);margin-top:8px;border-top:1px dashed var(--line);padding-top:8px}.apr-wrap{margin-bottom:24px}.apr{display:flex;justify-content:space-between;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--mid);border-radius:12px;padding:11px 14px;margin-bottom:8px;font-size:13px}.apr code{background:#0f1f33;color:#d6e6ff;padding:5px 9px;border-radius:6px;font-size:12px;white-space:nowrap}.apr-empty{color:var(--muted);font-size:13px}.apr.work{border-left-color:var(--accent)}.page{display:none}.page.active{display:block}.kpi{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;margin-bottom:22px}.kpi .box{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow)}.kpi .n{font-size:26px;font-weight:800;color:var(--accent)}.kpi .l{font-size:12px;color:var(--muted)}.kblock{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px;box-shadow:var(--shadow)}.kbar{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}.kbar .bn{width:96px;color:var(--muted)}.kbar .bt{flex:1;height:14px;background:var(--line);border-radius:7px;overflow:hidden}.kbar .bt i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2))}.kbar .bv{width:40px;text-align:right;font-weight:700}.setbox{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:var(--shadow);font-size:13px;line-height:1.8}.setbox code{background:#2563eb12;color:var(--accent);padding:2px 6px;border-radius:5px;font-size:12px}.act-f{display:inline}.btn{cursor:pointer;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:5px 11px;font-size:12px;font-weight:700;margin-right:6px}.btn:hover{filter:brightness(.97)}.btn.ok{background:var(--accent);color:#fff;border-color:var(--accent)}.btn.no{color:var(--hi);border-color:#f3c9d2}.btn.ph{background:var(--accent2);color:#fff;border-color:var(--accent2);font-size:11px;padding:3px 9px;margin-left:10px}.ov{position:fixed;inset:0;background:rgba(15,23,42,.45);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);display:none;align-items:flex-start;justify-content:center;padding:48px 20px;z-index:50;overflow:auto}.ov.open{display:flex}.modal{background:var(--surface);border-radius:18px;max-width:720px;width:100%;padding:26px 30px;box-shadow:0 24px 70px rgba(0,0,0,.3);position:relative;animation:pop .14s ease-out}@keyframes pop{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}.modal .mhead{font-size:20px;font-weight:800;margin:0 0 14px;padding-right:30px}.modal .jstep{font-size:14px;padding:6px 0 6px 12px}.modal .jgoal{font-size:14px}.modal .ti{padding:5px 0;font-size:14px}.modal .ato{font-size:13px}.modal .tl b{font-size:13px}.modal .meta{font-size:12px}.mx{position:absolute;top:12px;right:16px;border:none;background:transparent;font-size:26px;line-height:1;cursor:pointer;color:var(--muted)}.mx:hover{color:var(--ink)}.hint{color:var(--muted);font-size:11px;font-weight:400}.cmds{margin-top:8px}.cmds div{margin:6px 0;font-size:12px;color:var(--muted)}.cmds code{background:#0f1f33;color:#d6e6ff;padding:3px 7px;border-radius:5px;font-size:12px}.cmd{cursor:pointer}.cmd:hover{filter:brightness(1.25)}</style>"
)


def _dash_stats(state):
    tk = [t for p in state["projects"] for t in p.get("tasks", [])]
    return {"projects": len(state["projects"]),
            "todo": sum(t.get("status") == "todo" for t in tk),
            "done": sum(t.get("status") == "done" for t in tk),
            "high": sum(p.get("priority") == "high" for p in state["projects"]),
            "proposed": sum(t.get("status") == "proposed" for t in tk)}


def render_dashboard(state, served=False, active="now") -> str:
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
            out.append(f'<div class="jstep {cls}">{mark} {e(ph.get("name",""))} — {e(ph.get("goal",""))}{here}{btn}</div>')
        out.append(f'<div class="jgoal">🏁 Goal: {e(p.get("done_def",""))}</div>')
        return "".join(out)

    def card(p):
        phs = p.get("phases", [])
        tot = len(phs) or 1
        cur = cur_idx(p)
        prog = round(min(cur, tot) / tot * 100)
        nd = _next_due(p)
        due = f"⏰ {nd}" if nd else "no due date"
        curlabel = f"{cur}/{tot} done"
        curgoal = phs[cur]["goal"] if cur < len(phs) else "(all phases done)"
        def trow(t):
            b = ""
            if served and t.get("status") == "todo":
                b = (f'<form class="act-f" method="post" action="/set-status">'
                     f'<input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="status" value="done">'
                     f'<input type="hidden" name="pg" value="projects"><button class="btn">Done</button></form>')
            return (f'<div class="ti">[{t.get("status")}] {e(t["id"])}: {e(t["desc"])} '
                    f'{"🤖" if t.get("owner")=="ai" else "👤"} {b}</div>')
        ti = "".join(trow(t) for t in p.get("tasks", []))
        msx = ", ".join(f'{e(m["name"])}({m.get("due","")})' for m in p.get("milestones", [])) or "none"
        deps = ", ".join(p.get("depends_on", [])) or "none"
        return (f'<div class="card" onclick="openModal(this)">'
                f'<div class="top"><span class="dot {p.get("priority","mid")}"></span>'
                f'<span class="nm">{e(p["name"])}</span><span class="id">{p["id"]}</span></div>'
                f'<div class="goal">🎯 {e(p.get("north_star",""))}</div>'
                f'<div class="jrow">{journey_mini(p)}<span class="jlbl">{curlabel}</span></div>'
                f'<div class="next">👉 {e(_next_action(p) or "(no next action)")}</div>'
                f'<div class="due">{due} · {prog}%</div>'
                f'<div class="cdetail">'
                f'<div class="mhead">{e(p["name"])} <span class="id">{p["id"]}</span> · {PRIO_MARK.get(p.get("priority","mid"),"")}</div>'
                f'<div class="jfull">{journey_full(p)}</div>'
                f'<div class="ato">Next: {e(curgoal)} ({max(tot - cur, 0)} phase(s) left)</div>'
                f'<div class="tl"><b>Tasks</b>{ti}</div>'
                f'<div class="meta">📅 {msx} · 🔗 {e(p.get("repo","—"))} · deps: {e(deps)}</div></div></div>')

    def nowcard(p):
        why = []
        nd = _next_due(p)
        if nd and nd <= horizon:
            why.append(f"⏰ due {nd}")
        if p.get("focus_until", "") >= today and p.get("focus_until"):
            why.append(f"🔥 focus until {p['focus_until']}")
        return (f'<div class="nowcard"><div class="why">{" / ".join(why)}</div>'
                f'<div class="nm">{e(p["name"])} <span class="id">{p["id"]}</span></div>'
                f'<div class="act">👉 {e(_next_action(p) or "(none)")}</div></div>')

    if not sp:   # empty state (first run / no projects yet)
        nows = ('<div class="nowcard" style="grid-column:1/-1;border-left-color:var(--accent)">'
                '<div class="nm">Welcome to Cockpit 👋</div>'
                '<div class="act">No projects yet. Create your first one:<br>'
                '<code>python3 cockpit.py add-project proj-1 "My first project" "The goal" high</code><br>'
                'then add a phase: <code>python3 cockpit.py add-phase proj-1 "Phase 0" "first milestone"</code></div></div>')
    else:
        nows = "".join(nowcard(p) for p in sp if near_term(p)) or '<div class="nowcard"><div class="act">Nothing due soon</div></div>'
    cards = "".join(card(p) for p in sp) or '<div class="apr-empty">No projects yet — run <code>add-project</code>.</div>'
    appr = [(p, t) for p in sp for t in p.get("tasks", []) if t.get("status") == "proposed"]
    if served:
        appr_items = "".join(
            f'<div class="apr"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}</div><div>'
            f'<form class="act-f" method="post" action="/approve"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn ok">✅ Approve</button></form>'
            f'<form class="act-f" method="post" action="/reject"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="pg" value="approve"><button class="btn no">🗑 Reject</button></form>'
            f'</div></div>' for p, t in appr
        ) or '<div class="apr-empty">Nothing to approve 🎉</div>'
    else:
        appr_items = "".join(
            f'<div class="apr"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}</div>'
            f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" data-cmd="python3 cockpit.py approve {t["id"]}">cockpit.py approve {t["id"]}</code></div>' for p, t in appr
        ) or '<div class="apr-empty">Nothing to approve 🎉</div>'

    # "Your tasks" lane = human's turn (owner=human todos). A separate lane from AI-proposal approvals.
    work = [(p, t) for p in sp for t in p.get("tasks", []) if t.get("owner") == "human" and t.get("status") == "todo"]
    work.sort(key=lambda pt: (PRIO_ORDER.get(pt[1].get("priority") or pt[0].get("priority", "mid"), 1), pt[1].get("due") or "9999"))
    if served:
        work_items = "".join(
            f'<div class="apr work"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}</div>'
            f'<form class="act-f" method="post" action="/set-status"><input type="hidden" name="tid" value="{t["id"]}"><input type="hidden" name="status" value="done"><input type="hidden" name="pg" value="approve"><button class="btn ok">Done</button></form>'
            f'</div>' for p, t in work
        ) or '<div class="apr-empty">No tasks pending 🎉</div>'
    else:
        work_items = "".join(
            f'<div class="apr work"><div><b>{e(p["name"])}</b> <span class="id">{p["id"]}</span><br>{e(t["desc"])}</div>'
            f'<code class="cmd" title="click to copy" onclick="copyCmd(this)" data-cmd="python3 cockpit.py set-status {t["id"]} done">cockpit.py set-status {t["id"]} done</code></div>' for p, t in work
        ) or '<div class="apr-empty">No tasks pending 🎉</div>'
    msg = f"{s['proposed']} awaiting your approval." if s["proposed"] else "Nothing to approve. Nice pace ✨"

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
        cmd("set-status <tid> done|skip|dropped", "change a task"),
        cmd("set-phase <pid> <n> done", "advance the Journey"),
        cmd("set-priority <pid> high|mid|low", "re-rank"),
        cmd("focus <pid> [days]", "mark hot (unfocus to clear)"),
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

    appr_badge = f" ({s['proposed']})" if s["proposed"] else ""   # badge = approvals only (the thing blocking the agent)
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cockpit Dashboard</title>' + DASH_CSS + "</head>")
    body = (f'<body><div class="wrap">'
            f'<aside class="side"><div class="brand">🛰 Cockpit</div><nav class="nav">'
            f'<a class="{"active" if active=="now" else ""}" data-pg="now" href="#">🔥 Now</a>'
            f'<a class="{"active" if active=="projects" else ""}" data-pg="projects" href="#">📋 Projects</a>'
            f'<a class="{"active" if active=="approve" else ""}" data-pg="approve" href="#">🙋 Your turn{appr_badge}</a>'
            f'<a class="{"active" if active=="kpi" else ""}" data-pg="kpi" href="#">📊 KPI</a>'
            f'<a class="{"active" if active=="settings" else ""}" data-pg="settings" href="#">⚙️ Settings</a></nav></aside>'
            f'<main class="main"><div class="head"><div><h1>Good morning 👋</h1>'
            f'<div class="date">{date.today()} · {s["projects"]} projects active</div></div></div>'
            f'<section class="page{" active" if active=="now" else ""}" id="pg-now"><div class="momentum">'
            f'<div><div class="big">{s["projects"]}</div><div class="lbl">projects</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["todo"]}</div><div class="lbl">todo</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["done"]}</div><div class="lbl">done</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["high"]}</div><div class="lbl">high prio</div></div><div class="sep"></div>'
            f'<div><div class="big">{s["proposed"]}</div><div class="lbl">to approve</div></div>'
            f'<div class="msg">{e(msg)}</div></div>'
            f'<div class="sectitle">🔥 Focus (next ~3 days)</div><div class="now">{nows}</div></section>'
            f'<section class="page{" active" if active=="projects" else ""}" id="pg-projects">'
            f'<div class="sectitle">📋 All projects (by priority)</div><div class="grid">{cards}</div></section>'
            f'<section class="page{" active" if active=="approve" else ""}" id="pg-approve">'
            f'<div class="sectitle">🟡 Awaiting approval (AI proposals → approve to send to the agent)</div>'
            f'<div class="apr-wrap">{appr_items}</div>'
            f'<div class="sectitle">✅ Your tasks (human work → mark done to clear)</div>'
            f'<div class="apr-wrap">{work_items}</div></section>'
            f'<section class="page{" active" if active=="kpi" else ""}" id="pg-kpi">{kpi_html}</section>'
            f'<section class="page{" active" if active=="settings" else ""}" id="pg-settings">{set_html}</section>'
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
              'function closeModal(){document.getElementById("ov").classList.remove("open")}'
              'document.addEventListener("keydown",function(e){if(e.key==="Escape")closeModal()});'
              'function copyCmd(el){var t=el.dataset.cmd,o=el.textContent;function ok(){el.textContent="✓ copied";setTimeout(function(){el.textContent=o},1000)}'
              'if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,function(){cpFb(t,ok)})}else{cpFb(t,ok)}}'
              'function cpFb(t,cb){var a=document.createElement("textarea");a.value=t;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.focus();a.select();try{document.execCommand("copy")}catch(e){}document.body.removeChild(a);cb()}'
              '</script></body></html>')
    return head + body + script


def main(argv):
    if not argv or argv[0] in ("snapshot", "snap"):
        print(render_snapshot_md(emit_snapshot())); print(f"→ {SNAP_MD}"); return
    if argv[0] == "dashboard":
        emit_snapshot(); print(f"✅ dashboard generated → {DASH_HTML}"); return
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
        elif cmd == "propose":
            print(propose(rest[0], rest[1]))
        elif cmd == "add":
            print(add_task(rest[0], rest[1], rest[2] if len(rest) > 2 else None))
        elif cmd == "approve":
            print(approve(rest[0]))
        elif cmd == "reject":
            print(reject(rest[0]))
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
