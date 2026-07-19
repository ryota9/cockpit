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

---

## 教育係（edu/）— コーディング学習ゲートのCockpit常設化（2026-07-12・設計）

**発案**: 王。RRFの穴埋め→説明ゲート→Phoenix記録、という今日の学習の流れを常設の仕組みに。会社の学習ゲート哲学(feedback_knowledge_hollowing)の実装。

**教育係 ≠ Phoenix（兄弟・配線でつながる）**:
- 教育係🐣 = 前向き。問題を出す/採点/解説（パーソナルトレーナー）。1問ごと・Cockpit UI・速い。
- Phoenix🐥🔥 = 後ろ向き。記録/スキルマップ/分析（カルテ・成績表）。1日ごと・Notion・重い。
- 連携: 教育係はPhoenixのstrategy.md(スキルマップ)を読んで何を出すか決め、正解→Phoenixの学習ログへ手渡す。＝王の原則「実行と判定の分離」。

**ADR-0006を守る置き場所**（Cockpitはブローカー、eduが所有＝pr_feed方式）:
```
cockpit/edu/  tutor.md（教育係の人格・基準）/ syllabus.json（項目＋学習済みフラグ・王承認制）
              problems/（生成問題・提出・解説 1問1ファイル）/ edu.py（決定論ブローカー→claude -p）
```
正本 state.json にLLMは触れない。edu.py が edu 内の状態を所有し、結果（習得フラグ）だけを扱う。

**フロー**: Nowに今日の問題 → 提出ボタン `/edu-submit`（serve.py・即時 claude -p 採点）→ 解説ページ（pr-preview方式）→ 正解=Phoenix記録＋syllabus学習済み／不正解=同type別問題＋どこが違うか解説。

**4決定（王・2026-07-12）**: ①採点=即時 ②シラバス=教育係草案→王承認 ③採点=LLM＋解説 ④Phoenix=正解時に学習ログ1行自動追記。

**Phase**: 1=MVP(tutor/edu.py/シラバスタブ/Now今日の問題/提出→採点→解説/学習済みフラグ)。2=不正解の自動差し替え・問題集タブ・Phoenix本連携。
