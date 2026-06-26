#!/usr/bin/env python3
"""Verification-first eval for the core (measure before building UI):
  (1) Round-trip integrity (drift=0): State change -> Snapshot -> read back, zero mismatch.
  (2) HITL gate: a proposed task stays out of open_tasks until a human approves.
  (3) Token reduction: full-state read vs snapshot read (char count ~ proxy; the ratio is the point).
Data-agnostic: works on any state.json (picks tasks dynamically), so CI can run it on the example."""
from __future__ import annotations
import copy
import json
import sys

from cockpit import load_state, make_snapshot


def gt_open(state):    # ground truth: ids of status==todo tasks
    return {t["id"] for p in state["projects"] for t in p.get("tasks", []) if t.get("status") == "todo"}

def snap_open(snap):   # ids reconstructed from the snapshot's open_tasks
    return {e.split(":")[0] for p in snap["projects"] for e in p["open_tasks"]}

def snap_proposed(snap):
    return {e.split(":")[0] for p in snap["projects"] for e in p["proposed"]}

def set_status(state, tid, status):
    for p in state["projects"]:
        for t in p.get("tasks", []):
            if t["id"] == tid:
                t["status"] = status
    return state

def add_task(state, pid, tid, desc, status):
    for p in state["projects"]:
        if p["id"] == pid:
            p.setdefault("tasks", []).append({"id": tid, "desc": desc, "status": status, "owner": "ai"})
    return state

def drift(state):
    """Symmetric difference between todo-ids (truth) and open-ids reconstructed from the snapshot."""
    return len(gt_open(state) ^ snap_open(make_snapshot(state)))


def main():
    base = load_state()
    todos = [t["id"] for p in base["projects"] for t in p.get("tasks", []) if t.get("status") == "todo"]
    pid = base["projects"][0]["id"] if base["projects"] else None

    print("=== (1) Round-trip integrity + (2) HITL gate (drift=0 passes) ===")
    total = 0
    d = drift(copy.deepcopy(base)); total += d; print(f"  S0 baseline               drift={d}")
    if todos:
        s = set_status(copy.deepcopy(base), todos[0], "done"); d = drift(s); total += d
        print(f"  S1 human: {todos[0]} todo->done   drift={d}")
    if len(todos) > 1:
        s = set_status(copy.deepcopy(base), todos[1], "skip"); d = drift(s); total += d
        print(f"  S2 human: {todos[1]} todo->skip   drift={d}")

    gate_ok = appr_ok = True
    if pid:
        s = add_task(copy.deepcopy(base), pid, "t_eval", "weekly review automation", "proposed")
        snap = make_snapshot(s)
        gate_ok = ("t_eval" in snap_proposed(snap)) and ("t_eval" not in snap_open(snap)) and ("t_eval" not in gt_open(s))
        d = drift(s); total += d
        print(f"  S3 agent: proposes t_eval drift={d} / HITL gate={'OK (kept out of open)' if gate_ok else 'NG'}")
        s = set_status(s, "t_eval", "todo"); snap = make_snapshot(s)
        appr_ok = "t_eval" in snap_open(snap); d = drift(s); total += d
        print(f"  S4 human: approve->todo   drift={d} / shows after approve={'OK' if appr_ok else 'NG'}")

    ok = (total == 0 and gate_ok and appr_ok)
    print(f"  --- total drift={total} -> {'✅ consistent (drift=0), HITL gate OK' if ok else '❌ inconsistent'}")

    print("\n=== (3) Token reduction (char count ~ proxy; ratio is the point) ===")
    full = json.dumps(base, ensure_ascii=False)
    snap = json.dumps(make_snapshot(base), ensure_ascii=False)
    fr, sr = len(full), max(len(snap), 1)
    print(f"  full state read : {fr:>6} chars")
    print(f"  snapshot read   : {sr:>6} chars")
    print(f"  reduction       : {round((1 - sr / fr) * 100)}%  (~{round(fr / sr, 1)}x)" if fr else "  (empty state)")
    ok = ok and sr <= fr
    print(f"\nVerdict: {'✅ core hypothesis holds (drift=0, gate OK, fewer tokens)' if ok else '❌ needs review'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
