# Design notes

Cockpit is a deterministic middle layer that keeps **you** and **your coding agent** looking
at the same project state — without drift, without burning tokens, and without letting the
agent silently change the truth.

This document explains the *why*. The decisions below are the interesting part; the code is small.

---

## The problem

Working across many projects *with* an AI coding agent creates three recurring failures:

1. **Drift** — the agent's idea of "what's done / what's next" diverges from how you actually track it.
2. **Token waste** — re-reading the full project state every time the agent needs context is expensive.
3. **Agent overreach** — the agent marks things "done", invents tasks, or mutates state you never approved.

Cockpit answers each with one design choice.

---

## Core model

- **One source of truth: `state.json`.** Both human and agent resolve to the same file.
- **The agent reads a projection, not the whole thing: `snapshot.md`.** A compact, read-only
  slice (active tasks, current phase, what's awaiting approval). Cheap to read every session.
- **Three lanes**, all *projections of `owner × status`* (no extra state is introduced):

  | Lane | Filter | Who acts |
  | --- | --- | --- |
  | 🟡 Awaiting approval | `status == proposed` | human **approves** |
  | ✅ Your tasks | `owner == human && status == todo` | human **does** |
  | 🤖 Ready for the agent | `owner == ai && status == todo` | agent **does** |

  Approval is the join: the agent `propose`s → it lands in *Awaiting approval* → you `approve`
  → it becomes an `owner=ai` todo → it appears in the agent's snapshot inbox. The loop is closed.

---

## ADR-0006 — The canonical state is written by deterministic code, never by an LLM

The LLM lives at the **edges** (it reads the snapshot; it `propose`s). The **center** — every
mutation of `state.json` — goes through plain, deterministic Python (`cockpit.py`).

Why:

- **Predictability.** State transitions are auditable and reproducible. No prompt can corrupt the truth.
- **Safety / HITL gate.** Roles are separated by API: the agent can only create `proposed` tasks;
  only a human can `approve` / `set-status` / `set-phase`. The agent cannot promote its own work.
- **Testability.** Because the core is deterministic, it can be verified with code (see below),
  not vibes.

A useful tell: the agent is a *consumer at the edges*, not the writer of record.

---

## Verification-first

The core was measured **before** any UI was built. Three evals ship with the repo:

- **`eval.py`**
  - **Round-trip integrity (drift = 0):** mutate state → project to snapshot → reconstruct →
    compare against ground truth. Any mismatch is a bug.
  - **HITL gate:** a `proposed` task must stay out of the agent's open tasks until approved.
  - **Token reduction:** full-state read vs snapshot read (char count as a proxy; the *ratio* is the point).
- **`eval_dashboard.py`** — invariants on the generated HTML (e.g. the progress bar's filled
  segments equal the phases-done label; menu wiring is intact). Checks are structural (CSS
  classes and counts derived from data), so they survive translation and any dataset.

Run them: `python eval.py` and `python eval_dashboard.py`. CI runs both on every push.

> Note: the dashboard eval once passed *too easily* because of a tuple-unpacking bug in the
> checker itself — the judge always returned true. The fix (and the lesson) is why the checks
> are now structural and the eval is itself reviewed: **a check you haven't verified isn't a check.**

---

## Non-goals (for now)

- **Multi-user / concurrent writes.** Single-user, file-based by design. If you need concurrency,
  swap the store for SQLite behind the same deterministic API.
- **A full web app.** The dashboard is read-mostly; the optional local server adds 1-click approval.
  Project/task *authoring* stays in the CLI.
- **Auth / remote hosting.** The server binds `127.0.0.1` — local only, on purpose.

---

## Wiring an agent to it

Tell your agent (e.g. in its system/instructions file):

- To understand project state, **read `snapshot.md`** — not the whole `state.json` (saves tokens).
- To add or change a task, **propose only**: `python cockpit.py propose <pid> "<desc>"`.
  A human confirms with `approve` / `set-status` (the HITL gate).
- After approval, the task appears under **"Ready for the agent"** in the snapshot — that's the inbox.

That is the entire contract: the agent reads a thin file and proposes; the human approves;
deterministic code keeps the books.
