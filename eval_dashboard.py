#!/usr/bin/env python3
"""Invariant eval for dashboard.html (catches rendering bugs). Verification-first: measure the UI too.
Re-render -> write out -> check invariants. Exit 1 on any failure.
Checks are structural (CSS classes / counts derived from data), so they survive i18n and any dataset."""
import re
import sys
from pathlib import Path

from cockpit import load_state, _sorted_projects, render_dashboard, near_term

HERE = Path(__file__).resolve().parent
state = load_state()
H = render_dashboard(state)
(HERE / "dashboard.html").write_text(H, encoding="utf-8")  # keep fresh


def done_cnt(p):
    n = 0
    for ph in p.get("phases", []):
        if ph.get("status") == "done":
            n += 1
        else:
            break
    return n


projs = state["projects"]
n = len(projs)
total_done = sum(done_cnt(p) for p in projs)
total_phases = sum(len(p.get("phases", [])) for p in projs)
label_y = sum(len(p.get("phases", [])) or 1 for p in projs)   # card label uses (len or 1)
with_cur = sum(1 for p in projs if done_cnt(p) < len(p.get("phases", [])))
human_todo = sum(1 for p in projs for t in p.get("tasks", []) if t.get("owner") == "human" and t.get("status") == "todo")
card_n = H.count('class="card"')
openmodal_n = H.count('onclick="openModal(this)"')

seg_done = len(re.findall(r'class="seg done"', H))
seg_cur = len(re.findall(r'class="seg cur"', H))
seg_all = len(re.findall(r'class="seg', H))
labs = re.findall(r"(\d+)/(\d+) done", H)
now_n = len(re.findall(r'class="nowcard"', H))
near_n = max(sum(1 for p in _sorted_projects(state) if near_term(p)), 1)

checks = [
    ("project cards == projects", card_n == n, f"{card_n} vs {n}"),
    ("modal overlay present", 'id="ov"' in H, ""),
    ("openModal wired == projects", openmodal_n == n, f"{openmodal_n} vs {n}"),
    ("seg total == total phases", seg_all == total_phases, f"{seg_all} vs {total_phases}"),
    ("seg.done == done phases (=filled=label)", seg_done == total_done, f"{seg_done} vs {total_done}"),
    ("seg.cur == active projects", seg_cur == with_cur, f"{seg_cur} vs {with_cur}"),
    ("jstep.cur (you-are-here) == active projects", H.count('class="jstep cur"') == with_cur, f"{H.count('class=\"jstep cur\"')} vs {with_cur}"),
    ("jgoal (🏁) == projects", H.count('class="jgoal"') == n, f"{H.count('class=\"jgoal\"')} vs {n}"),
    ("label X sum == done phases", sum(int(a) for a, b in labs) == total_done, f"{sum(int(a) for a, b in labs)} vs {total_done}"),
    ("label Y sum == phases(or 1)", sum(int(b) for a, b in labs) == label_y, f"{sum(int(b) for a, b in labs)} vs {label_y}"),
    ("label count == projects", len(labs) == n, f"{len(labs)} vs {n}"),
    ("now count == near_term count", now_n == near_n, f"{now_n} vs {near_n}"),
    ("every project name appears", all(p["name"] in H for p in projs), ""),
    ("no template leftovers", "None" not in re.findall(r">(None)<", H), ""),
    ("menu: data-pg links == 5", H.count('data-pg="') == 5, H.count('data-pg="')),
    ("menu: page sections == 5", H.count('class="page') == 5, H.count('class="page')),
    ("menu: tab-switch JS present", "classList.toggle" in H, ""),
    ("your-tasks lane == human todos", H.count('class="apr work"') == human_todo, f"{H.count('class=\"apr work\"')} vs {human_todo}"),
]

print("=== Dashboard invariant eval ===")
fails = 0
for name, ok, got in checks:
    print(f"  {'✅' if ok else '❌'} {name}" + (f"   [{got}]" if (not ok and got) else ""))
    fails += 0 if ok else 1
print(f"\n{'🎉 all ' + str(len(checks)) + ' checks PASS' if not fails else '❌ ' + str(fails) + ' FAIL'}")
sys.exit(1 if fails else 0)
