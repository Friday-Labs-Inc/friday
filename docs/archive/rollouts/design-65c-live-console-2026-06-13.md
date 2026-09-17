# Design 65c — The live Project Console (2026-06-13)

## The one-sentence version

A dedicated Desk page that shows, **live and pushed in real time**, what every
project and agent is doing right now — the direct answer to *"I have no clue
what's really happening in a project; I want a dedicated console page like
Hermes' dashboard."*

## Why this is PR #3 of four

65a gave the data model, 65b gave the structured views (Kanban/Gantt/cards).
65c is the **signature surpass-Hermes moment**: a single command-center page
with a live activity feed. (65d wires the cost/progress rollup that fills the
numbers.)

## What this PR ships

### 1. The Project Console page — `page/project_console/`

A standard Desk page (`project-console`, gated to System Manager + Agent
Supervisor) with three zones:

- **Health strip** — the Pipeline Health verdict (🟢 ok / 🟡 degraded /
  🔴 down) plus live state counts and the `friday` worker presence. The "is the
  loop alive?" line the 4-hour-stall incident proved we need, now visible at a
  glance. Reuses `pipeline_health()` verbatim (61b).
- **Project lane** — a card per project: status badge, a %-complete bar, and
  task counts. Click a card to scope the whole console to that project; click
  the scope chip to clear it. Below it, an **In Flight** list of the tasks
  currently Assigned/Executing, each naming its agent.
- **Live activity feed** — a reverse-chron stream of agent task transitions,
  each row leading with the agent (65a identity), the task, and the new state,
  with a terminal icon (✅ ⛔ 📝 🚫) and time-ago.

Pure Frappe-native vanilla JS + CSS that follows the Desk theme — no React, no
build step. The page JS is served from disk at request time.

### 2. The realtime push — `console/console_stream.py`

`publish_activity(task, state)` is called from the same
`tasks/workflow._watch_transition` seam that already posts to the War Room. It
emits one `frappe:project_activity` event with no room args, which Frappe
resolves to the site-wide `"all"` room — **every System User Desk client
receives it with no client-side subscription** (operators and, since 65a, the
agent users too). Never raises: a realtime hiccup cannot break a task save.

### 3. The snapshot endpoint — `console/console_snapshot.py`

A whitelisted `console_snapshot(project=None)` that returns all three zones'
data in one call: the health verdict, project rollups, in-flight tasks, and
recent terminal activity. The page calls it on open (to seed) and every 30s (a
correctness backstop). If a realtime frame is ever dropped, the next poll heals
it — **state is the source of truth, the push is the optimization** (the Design
61 reconciler principle, applied to the UI). Fail-loud: any data-path error
returns an `error` envelope with a `down` verdict, never a silent empty page.

### 4. A Workspace shortcut

65b's "Projects" Workspace gains a green **Project Console** shortcut as its
first tile, so the console is one click from the Desk landing.

## Compare with Hermes

Hermes' dashboard **polls** a flat list of *sessions* every 5 seconds and has no
project concept, no per-agent identity in the feed, and no liveness verdict.
Friday **pushes** a *project-scoped* feed of *governed* transitions, each
carrying the agent and project, fronted by a real health verdict — and falls
back to a 30s reconciling poll for correctness. Push not poll; a project plane
not a session list; governed identity not a string. Per
`feedback_hermes-floor-not-ceiling`, this is the named surpass axis for 65.

## Why we know it works

- `console_stream`: 3 tests — site-wide emit shape (no room args → `"all"`),
  terminal-state flag, never-raises on publish failure.
- `console_snapshot`: 4 tests — all zones returned, per-project scoping on every
  query, the in-flight state filter, and the fail-loud envelope.
- Wiring: the full `test_task_workflow` suite stays green with `publish_activity`
  added to the transition seam.

The page JS/CSS are exercised live (no unit harness for Desk JS); the data
contracts they consume are fully covered above.

## What's NOT in this PR

- The cost/progress **rollup** that fills `percent_complete` and the cost fields
  (65d). The console renders whatever those fields currently hold; the bars and
  counts are live, cost shows blank until 65d.
- Per-project realtime *rooms* — v1 broadcasts site-wide and the client filters
  by the active project. Fine for single-tenant; room-scoping is a later
  optimization if event volume ever warrants it.

## Operator note

After merging: `bench --site <site> migrate` (registers the Page + adds the
Workspace shortcut). No `bench build` needed — Desk page JS/CSS are read from
disk at request time. Open **Projects → Project Console**, or go to
`/app/project-console`.
