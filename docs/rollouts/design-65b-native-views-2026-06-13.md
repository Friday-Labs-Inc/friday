# Design 65b — Native project views (2026-06-13)

## The one-sentence version

Turn the new Project/Task fields into the ERPNext-style views the user asked
for — a **Task Pipeline Kanban**, a **Gantt timeline**, **dashboard charts**,
**number-card tiles**, and a **Projects Workspace** — all built from Frappe's
own rendering, not hand-written UI.

## Why this is PR #2 of four

65a laid the data model. 65b makes it *visible* using the platform we forked:
Frappe already renders Kanban, Gantt, charts, number cards and workspaces — we
only declare *what* to show. (65c adds the bespoke live console; 65d wires the
cost/progress rollup.)

## What this PR ships

### 1. `workflow_state` becomes a Select (the enabling change)

Frappe's Kanban can only column on a **Select** field, and `workflow_state` was
a free-text `Data` field. This PR converts it to a Select over the canonical
state set — `Pending / Assigned / Executing / Review / Completed / Blocked /
Cancelled`. Verified safe: every code path (dispatcher, runner, reconciler,
workflow hook) writes only those seven values; a repo-wide scan found no other.
The conversion is also a **hardening** — a task can no longer be saved into a
state outside the machine. A test (`test_workflow_state_is_select_with_canonical_options`)
pins the field options to the shared `TASK_STATES` list so the Kanban columns
and the field can never drift apart.

### 2. The Task Pipeline Kanban

A "Task Pipeline" Kanban Board on Task, columned on `workflow_state`, one column
per state with a colour indicator (Executing=blue, Completed=green, Blocked=red,
…). This is the literal *"I want to see task executions"* — cards slide across
columns as the pipeline runs them.

### 3. The Gantt timeline

`task_calendar.js` registers `frappe.views.calendar["Task"]` with
`exp_start_date` → `exp_end_date` and `gantt: true`. Gantt is **not** automatic
in Frappe — two date fields are necessary but not sufficient; this file names
which fields are the bar's start/end and turns the view on (the same pattern
core uses for ToDo/Event). Bars are coloured by the task's `color` and show
`progress`.

### 4. Number cards + dashboard charts

- Cards: **Active Projects**, **Tasks Executing**, **Tasks Blocked**, **Open
  Issues** — the at-a-glance "busy / stuck" tiles.
- Charts: **Tasks by State** (group-by bar) and **Tasks Completed** per day
  (timeseries line).

### 5. The "Projects" Workspace

A public Workspace that lays the four cards in a row, the two charts below, and
shortcuts to the Project list and the Task Pipeline Kanban — plus a sidebar
links card (Project, Task, Issue). This is the ERPNext-style "project dashboard"
landing page, the answer to *"I can't even see projects and their plans."*

### How it's provisioned

One idempotent `after_migrate` provisioner,
`friday_core/console/provision_console.py`. Every artifact is created only if
absent (`frappe.db.exists`) and each is attempted in its own try/except, so one
failure is logged loudly and skipped, never aborting the rest (same failure-
isolation contract as 65a's identity backfill). The artifacts are plain public
DB records (`is_standard=0`) — Frappe won't try to reconcile them against
on-disk fixture JSON.

## Compare with Hermes

Hermes hand-rolls every dashboard panel in React and has **no Kanban, no Gantt,
no project concept** — its unit is a flat session list. Friday gets all of these
from the forked platform by declaring config. Per `feedback_hermes-floor-not-ceiling`
the surpass axis (a real project plane + a live push-driven console) is 65c;
65b delivers the structured-PM parity Hermes never had.

## Why we know it works

9 unit tests in `friday/friday_core/tests/test_console_views.py`: card/chart/
kanban/workspace creation, idempotency, failure isolation, the
Kanban-columns ↔ Task-state coupling, and that the Workspace `content` blob
references only cards/charts that exist as child rows. The full pipeline suite
(dispatcher/workflow/reconciler — 61 tests total) stays green after the Select
conversion, with zero assertion changes.

## What's NOT in this PR

- The bespoke **live console Desk Page** with realtime push (65c) — the
  Workspace will gain a shortcut to it then.
- The rollup that *fills* the number cards' underlying fields like
  `percent_complete`/cost (65d). The state/count cards work today off live data;
  cost renders blank until 65d.

## Operator note

After merging: `bench --site <site> migrate` (creates the views) then
`bench build --app frappe` once + hard-refresh (loads `task_calendar.js` so the
Gantt button appears). No manual setup.
