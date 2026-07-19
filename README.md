# 🛰 Cockpit

**A deterministic HITL sync layer between you and your coding agent.**
Keep yourself and your AI agent (e.g. Claude Code) looking at the *same* project state — without
drift, without burning tokens, and without letting the agent silently change the truth.

No dependencies. If Python runs, this runs.

![evals](https://github.com/ryota9/cockpit/actions/workflows/ci.yml/badge.svg)

![Cockpit demo](demo.gif)

---

## What is it (30 seconds)

You juggle several projects, and you also hand work to an AI coding agent. Cockpit is a tiny
project tracker with one twist:

> **The human and the agent share one ledger. The agent can only *propose*; the human *approves*.**

- **You** look at a dashboard, approve proposals, mark your work done.
- **The agent** reads a small *snapshot* to understand status, and proposes new tasks.
- The ledger (the source of truth) is **one JSON file**. Everything else is generated from it.

No server required (optional), no database, no login.

## Why this shape

Working with an AI agent creates three recurring problems. Cockpit answers each with one choice:

| Problem | Answer |
| --- | --- |
| **Drift** — the agent's view diverges from how you track things | One ledger: `state.json`. Both sides resolve to it. |
| **Token waste** — re-reading full state every time is expensive | The agent reads only a compact `snapshot.md`. |
| **Agent overreach** — it marks things done / invents tasks | The agent can only **propose**; humans **approve** (HITL gate). |

And the underlying rule: **canonical state is written by deterministic code, never by an LLM.**
The agent lives at the edges (reads the snapshot, proposes); plain Python writes the truth.
See [DESIGN.md](DESIGN.md) for the reasoning.

## The files

```
cockpit.py          # the tool (read/write the ledger via commands)
serve.py            # optional: a tiny local server for 1-click approval in the browser
eval.py             # self-test: drift=0, HITL gate, token reduction
eval_dashboard.py   # self-test: invariants on the generated HTML
eval_h1.py          # self-test: time metadata, journal, stale detection, backward compat
eval_theme.py       # self-test: the 4 dashboard themes (verification-first)
eval_donepropose.py     # self-test: the "done" HITL gate (propose/confirm/reject)
eval_aicursor.py        # self-test: the agent journal cursor (diff / --advance)
eval_intent.py          # self-test: readback (intent capture before starting a task)
eval_mode.py            # self-test: set-mode (focus / parked / normal)
eval_grouping.py        # self-test: groups, ownership, cross-project find
eval_phasegroup.py      # self-test: phase progress derived from task groups
eval_deviations.py      # self-test: stale milestones / expired focus get surfaced
eval_phase_feedback.py  # self-test: phase-advance guardrails
state.example.json  # sample data (copied to state.json on first run)
DESIGN.md           # why it works this way

# generated / gitignored (created on first run):
state.json          # ★ the source of truth
snapshot.md         # what the agent reads (compact, read-only)
dashboard.html      # what you look at
events.jsonl        # append-only journal (what happened, when)
```

Remember one thing: **`state.json` is the truth; `snapshot.md` and `dashboard.html` are outputs.**
Editing the outputs does nothing — change state through the commands below.

## Requirements

- Python 3.8+ (`python3 --version`). That's it — **no external packages**.

## Quick start

```bash
git clone <repo> && cd cockpit

python3 cockpit.py dashboard     # first run copies state.example.json -> state.json, builds dashboard.html
open dashboard.html              # macOS (use `start` on Windows, `xdg-open` on Linux)

python3 cockpit.py snapshot      # the compact, agent-facing view
python3 cockpit.py now           # what's hot in the next ~3 days
```

The dashboard's left menu switches between **Now / Projects / Your turn / KPI / Settings**.

## Concepts

- **Project** — one effort. Has an `id`, `name`, a goal (`north_star`), priority, etc.
- **Phase (the Journey bar)** — a project's path: `✅ done → ● you-are-here → ○ future → 🏁 goal`.
  The point is to see *where you are and where the finish line is* at a glance.
- **Task** with a **status**:

  | status | meaning | who sets it |
  | --- | --- | --- |
  | `todo` | to do | human |
  | `done` | finished | human |
  | `skip` | no longer needed | human |
  | `dropped` | cancelled | human |
  | `proposed` | **the agent's proposal (awaiting approval)** | agent only |

- **owner** — `human` (👤) or `ai` (🤖). An approved `owner=ai` todo becomes the **agent's inbox**.
- **priority** — `high` 🔴 / `mid` 🟡 / `low` ⚪.
- **focus** — flag a project "hot" for a few days even if nothing is due.

## The approval loop (the heart of it)

Three lanes, all projections of `owner × status` — think **outbox ↔ inbox**:

```
🟡 Awaiting approval  (proposed)            -> you approve
✅ Your tasks         (human + todo)        -> you do
🤖 Ready for the agent (ai + todo)          -> the agent does
```

1. **Agent proposes:** `python3 cockpit.py propose proj-rag "implement hybrid search"` → `proposed`.
2. **You approve:** `python3 cockpit.py approve t8` (or the [✅ Approve] button) → becomes an `ai` todo.
3. **It reaches the agent:** the task now shows under **"Ready for the agent"** in `snapshot.md`.

The agent can never promote its own work — your approval is the GO signal.

## Command reference

```bash
# view
python3 cockpit.py snapshot                 # compact view (writes snapshot.md)
python3 cockpit.py dashboard                # human HTML (writes dashboard.html)
python3 cockpit.py now [days]               # what's hot in the next N days (default 3)
python3 cockpit.py detail proj-rag          # deep view of one project
python3 cockpit.py list                     # all tasks

# create
python3 cockpit.py add-project proj-1 "My project" "The goal" high
python3 cockpit.py add-phase   proj-1 "Phase 0" "first milestone"
python3 cockpit.py add         proj-1 "my own task" mid     # your task (owner human, todo)

# human confirms (HITL)
python3 cockpit.py approve t8                # proposal -> todo
python3 cockpit.py reject  t8                # proposal -> dropped
python3 cockpit.py set-status  t8 done       # todo | done | skip | dropped
python3 cockpit.py set-priority proj-1 high
python3 cockpit.py set-phase    proj-1 1 done   # advance the Journey (0-based)
python3 cockpit.py focus proj-1 5            # hot for 5 days  (unfocus to clear)

# agent proposes (only)
python3 cockpit.py propose proj-1 "a task it suggests"
python3 cockpit.py propose proj-1 "a task" --why "evidence for the human's decision"

# time & delegation
python3 cockpit.py stale [days]              # todos untouched for N+ days (default 7)
python3 cockpit.py seed "an idea" [source]   # 1-click idea capture -> seedbed project
python3 cockpit.py assign proj-1 "work"      # put a task straight in the agent's inbox
python3 cockpit.py request-detail t8         # ask the agent to write the how-to for a task
python3 cockpit.py readback t8 "how I'm reading this / my first move"  # agent: read-back before starting

# completion (its own HITL gate — an agent's "done" is a claim, not a fact)
python3 cockpit.py propose-done t8 "evidence"  # agent: mark verified-and-ready-to-confirm (status unchanged)
python3 cockpit.py confirm-done t8             # human: confirm -> status=done
python3 cockpit.py reject-done  t8             # human: send back (task stays, marker cleared)

# grouping & ownership (cross-project slices)
python3 cockpit.py add-group proj-1 g1 "Group name" [order]
python3 cockpit.py set-group  t8 g1          # set-group t8 --clear to unset
python3 cockpit.py set-owner  t8 ai          # ai | human
python3 cockpit.py group g1                  # list every task in a group (any project)
python3 cockpit.py find "keyword" [--group g1]   # search all tasks, including done (dedup check)
python3 cockpit.py set-phase-groups proj-1 1 g1,g2   # link a phase to groups: progress derives from their tasks

# agent journal
python3 cockpit.py diff              # what happened since the agent last looked (cursor untouched)
python3 cockpit.py diff --advance    # same, then mark it read

# housekeeping
python3 cockpit.py set-mode proj-1 focus     # focus | parked | normal
python3 cockpit.py validate                  # check the ledger for errors
```

Every mutation stamps `created` / `status_changed` and appends one line to `events.jsonl`
(an append-only journal), so the dashboard can show a timeline and flag silently-stalled tasks.
Old tasks without timestamps are treated as "unknown" — never false-flagged.

## Optional: 1-click approval in the browser

```bash
python3 cockpit.py serve            # http://127.0.0.1:8765  (Ctrl+C to stop)
```

Open `http://127.0.0.1:8765` and the cards get **[✅ Approve] [🗑 Reject] [Done] [✅ Complete phase]**
buttons. Clicking updates `state.json` and regenerates the page — so approval reaches the agent's
inbox immediately. Standard library only; binds `127.0.0.1` (local only). Without the server, just
open `dashboard.html` (the buttons become copy-paste commands — nothing breaks).

## Themes

The dashboard ships with four skins — cycle them with the **👕 テーマ** button in the sidebar
(the choice is saved in `localStorage`; it never touches `state.json`, because a UI preference
is not project state):

| Theme | Mood | Particles |
| --- | --- | --- |
| 🔥 Phoenix (default) | dark, flame-gold | rising embers |
| 🛰 Satellite | deep-space navy × cyan | drifting stars |
| 🐋 Orca | black & white × ice blue | rising bubbles |
| 🏔 Wind (mountain) | light, mist & fresh green | floating leaves |

## Wiring your agent

Tell your agent (in its instructions/system file):

- Read **`snapshot.md`** for project state — not the whole `state.json` (saves tokens).
- To add/change a task, **propose only**: `python3 cockpit.py propose <pid> "<desc>"`.
- A human confirms with `approve` / `set-status`. After approval the task shows under
  **"Ready for the agent"** in the snapshot — that's the inbox.

## Data model (`state.json`)

```jsonc
{
  "projects": [{
    "id": "proj-rag",
    "name": "RAG quality loop",
    "north_star": "Build a loop that measures and improves RAG answer quality",
    "priority": "high",                 // high | mid | low
    "repo": "rag/",
    "depends_on": [],
    "done_def": "A score-over-time chart is demoable",   // 🏁
    "phases":   [{ "name": "Phase 0 eval loop", "goal": "...", "status": "done" }],
    "milestones": [{ "name": "demo", "due": "2026-07-15", "status": "todo" }],
    "tasks": [{ "id": "t1", "desc": "...", "status": "todo", "owner": "human" }]
  }]
}
```

> Edit via commands, not by hand — hand-editing is error-prone and defeats the deterministic design.

## Tests

```bash
python3 eval.py                 # drift=0 round-trip, HITL gate, token reduction
python3 eval_dashboard.py       # invariants on the rendered HTML
python3 eval_h1.py              # time metadata, journal, stale detection, backward compat
python3 eval_theme.py           # the 4 themes: default, determinism, switcher, palettes
python3 eval_donepropose.py     # propose-done / confirm-done / reject-done HITL gate
python3 eval_aicursor.py        # diff / --advance: the agent-facing journal cursor
python3 eval_intent.py          # readback: intent capture before an agent starts a task
python3 eval_mode.py            # set-mode: focus / parked / normal
python3 eval_grouping.py        # groups, ownership (ai|human), cross-project find
python3 eval_phasegroup.py      # set-phase-groups: phase progress derived from task groups
python3 eval_deviations.py      # stale milestones / expired focus surfaced, not silently dropped
python3 eval_phase_feedback.py  # phase-advance guardrails
```

Both run in CI on every push (`.github/workflows/ci.yml`). See [DESIGN.md](DESIGN.md) for what
each eval proves and why the checks are structural.

## FAQ

- **Is my data sent anywhere?** No. Everything is local files. The optional server binds `127.0.0.1` only.
- **Does it work without an AI agent?** Yes — it's a fine lightweight project tracker on its own.
- **Multiple users / concurrent edits?** Single-user by design; swap the store for SQLite behind the
  same deterministic API if you need it.

## License

[MIT](LICENSE) © 2026 Ryota Asai
