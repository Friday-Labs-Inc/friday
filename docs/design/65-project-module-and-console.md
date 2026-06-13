# Design 65 — The ERPNext-grade Project Module + Live Console

**Status:** LOCKED 2026-06-13. Three forking decisions answered by the user:
Q1 = **visual + structural port, agent-adapted** (not full ERPNext billing/
timesheet machinery); Q5 = **native Frappe views + one bespoke live console
page** (not a from-scratch SPA, not Workspace-only); Q4 = **each Agent Profile
links to a system Frappe User** (no login). All other Qs as recommended below.

Implementation lands as **four PRs**: 65a (data model — fields + agent-User
provisioning), 65b (native views — Gantt/Kanban/Dashboard/Workspace), 65c (the
live Project Console Desk Page + realtime activity stream), 65d (cost/progress
rollup + number cards). Tests-first per
[[feedback_workflow-design-lock-before-roo-code]].

## Why this exists — the plain English

On 2026-06-13 the user ran their first real project on Legion and said two
things that name this design exactly:

> *"the project module is completely useless — what I was expecting [is]
> ERPNext full project feat just without ERPNext. I can't even see project
> and their plans, task executions."*

> *"I have no clue what's really happening in [the] project. I want [a]
> dedicated console page to see — in Hermes there['s a] dashboard which
> serves the same purpose."*

Today the `Project` DocType has four fields (name, description, status,
backend_ref) and **zero UI** — no Gantt, no Kanban, no dashboard, no console,
nothing. A user who plans a 10-day RandomPack pipeline into a dozen Tasks
across several agents has no single screen that shows the plan, the progress,
who is doing what, or what just happened. The pipeline got durable + observable
in Design 61, agents got tools + report-back in 66/62 — but all of that
liveness is currently only visible as a Raven chat firehose. **This design
gives the project a face.**

## The principle that drives every Q below

> **The project DocType is the plan; native Frappe views render the plan;
> the console page renders the *pulse*. Structure is ERPNext-grade; the live
> command-center is the surpass-Hermes axis.**

Two distinct jobs, deliberately not merged:
- **Structured PM** (what's planned, what depends on what, %-complete, the
  Gantt) → Frappe's *built-in* Gantt/Kanban/List/Dashboard. We add fields, not
  UI code. This is the ERPNext parity the user asked for, for almost free.
- **The live console** (what is happening *right now* — which agent is mid-turn,
  what just completed, the health strip) → one bespoke Desk Page driven by
  `frappe.realtime` push.

## Compare with Hermes — what it does, what we deliberately do beyond

Hermes' dashboard (`hermes_cli/web_server.py` + `web/` React SPA) is the named
reference. What it actually is:

- A FastAPI app serving a compiled React 19 SPA, SQLite-backed
  (`~/.hermes/hermes.db`, `sessions` + `messages` tables).
- Its core view is a **Sessions** list: reverse-chronological feed of runs with
  `LIVE` pulse badges, expandable message threads, source icons, token counts.
- Analytics (tokens/cost, gated off by default because it undercounts), Logs,
  Cron, Skills, Plugins, Config, Keys.
- **It polls** — 5s for the live sessions view, 10s for the sidebar status
  strip. No WebSocket for monitoring (WS exists only for the embedded chat PTY).
- **It has no timeline, no Gantt, no project concept at all** — Hermes has no
  persisted multi-task project; a "session" is the unit. It is a *single-agent
  run monitor*, not a *project command center*.

Per [[feedback_hermes-floor-not-ceiling]] the surpass-Hermes axes are named:

1. **A real project plane.** Hermes has sessions; Friday has Projects → Tasks →
   dependencies → agents. We render the *plan and its execution*, not a flat
   run list. Gantt + Kanban + dependency graph have no Hermes equivalent.
2. **Push, not poll.** Frappe ships `frappe.realtime` (socket.io). The console
   subscribes to live events emitted from the workflow hook — no 5s `setInterval`.
   A light periodic reconcile-poll is the fallback, not the primary path.
3. **Accurate cost, surfaced per task.** Hermes hides analytics because its
   counts are off and only aggregates. Friday reads execution telemetry off the
   `Task.result` envelope and rolls it up per-project, per-agent, per-task.
4. **Governed identity.** Each agent is a first-class Frappe User (Q4) — native
   assignment, avatars, @-mentions, ToDo, Gantt resource rows — something a
   pixel-drawn Hermes badge can't be.

Grounding stays proportionate: single-tenant ([[feedback_single-tenant-not-saas]]),
explained at framework altitude ([[feedback_framework-altitude.md]]), and the
ERPNext *coupling* stays out ([[feedback_erpnext-free-core]]) — we adapt the
patterns, we do not depend on the `erpnext` app.

## Prior art in-repo

- `health/pipeline_health.py` → `pipeline_health()` already returns a structured
  verdict (ok/degraded/down), per-state task counts, worker presence, stuck
  counters, open issues. **This is the console's header status strip data
  source — already built.**
- `warroom/publisher.py` posts agent-as-speaker events to Raven on every
  transition. The console's activity feed is the *same events*, rendered in Desk
  instead of (as well as) chat.
- `tasks/report_back.py` already uses `frappe.publish_realtime` — the realtime
  plumbing exists; we add a project-scoped event channel.
- Design 66b `attach_deliverable` already attaches finished files to Project via
  the Frappe File layer — the console's "Deliverables" panel reads those.

---

## Q1 — ERPNext port scope *(LOCKED: visual + structural, agent-adapted)*

We port the *patterns* ERPNext made canonical for project management and
**reinterpret each for agent execution**, dropping the human/billing apparatus:

| ERPNext concept | Friday adaptation | Dropped |
|---|---|---|
| `% Completed` (by task weight) | `percent_complete` derived from Task states | — |
| `expected_start/end_date` | planned dates (from RandomPack phase plan, editable) | — |
| `actual_start/end_date` | derived from first `started_at` / last `completed_at` | — |
| Project cost (estimated/actual) | **LLM token + USD spend** rolled up from runs | customer billing, sales |
| Task `expected_time` / `actual_time` | execution **duration** (ms → hrs) | human timesheets |
| Resource / assignee | **Agent Profile** (now a Frappe User, Q4) | employee, HR |
| Gantt / Kanban / dashboard | Frappe native views on the DocTypes | — |
| Project Template / Type | *deferred* — RandomPack pipeline IS the template | Project Template DocType |
| Activity Type / Activity Cost | not ported | the whole costing-by-activity model |

We do **not** add: Timesheet, Activity Cost, Sales/Billing, Customer, Project
Template DocType, Project Type. If a future business surface needs human
timesheets, that's its own design.

## Q2 — New `Project` fields *(recommended)*

Added to `doctype/project/project.json` (all optional; existing rows migrate
clean with NULLs):

| field | type | source |
|---|---|---|
| `percent_complete` | Percent, read_only | derived (Q8) |
| `expected_start_date` | Date | RandomPack plan / human |
| `expected_end_date` | Date | RandomPack plan / human |
| `actual_start_date` | Date, read_only | min(Task.started_at) |
| `actual_end_date` | Date, read_only | max(Task.completed_at) when all terminal |
| `priority` | Select (Low/Medium/High/Urgent), default Medium | human |
| `estimated_cost_usd` | Currency, read_only | rolled up (Q8) |
| `actual_cost_usd` | Currency, read_only | rolled up (Q8) |
| `total_tasks` | Int, read_only | count |
| `completed_tasks` | Int, read_only | count |
| `project_lead_profile` | Link → Agent Profile | the commander/orchestrator |

`status` Select extended with no new values (Open/In Progress/Completed/
Cancelled/On Hold already cover it).

## Q3 — New `Task` fields *(recommended)*

Gantt is impossible without a date range; these are the minimum:

| field | type | source |
|---|---|---|
| `exp_start_date` | Date | plan / derived from deps |
| `exp_end_date` | Date | plan / derived from deps |
| `progress` | Percent, read_only | 0/50/100 by state (Pending/Executing/terminal) |
| `color` | Color | per agent profile, for Gantt/Kanban bars |
| `is_milestone` | Check, read_only | mirrors `execution_mode == "milestone"` |
| `duration_ms` | Int, read_only | from result envelope on completion |
| `cost_usd` | Currency, read_only | from result envelope (Q8) |

No change to the workflow-state machine — these are *display/rollup* fields,
written by the same hooks that already fire (`tasks/workflow.on_state_change`,
`tasks/runner`).

## Q4 — Agent identity: link Agent Profile → Frappe User *(LOCKED)*

Each `Agent Profile` gets a `frappe_user` field (Link → User) — the name
already referenced by the 66a/66b bootstraps (`bootstrap_read.py`,
`bootstrap_files.py` both call `profile.get("frappe_user")`), so 65a finally
provisions the field they were written to expect. An idempotent provisioner
(`agent_identity.py`, run in `after_migrate` + on Agent Profile `after_insert`)
creates a **system User** per profile:

- email `agent+<profile-slug>@friday.local`, `enabled=1`, **`user_type =
  "System User"` but login disabled** — `new_password` never set, no API key,
  not in any login flow. Governed: an agent-User *cannot authenticate*; it
  exists only as an assignable/mentionable identity.
- `full_name = profile_name`, a generated avatar (Frappe's letter avatar),
  roles mirrored from the profile's `assigned_roles`.
- The provisioner is fail-loud (logs + Issue on failure) and idempotent
  (re-running never duplicates).

This unlocks, for free: native **assignment** (`_assign`), **@-mentions** in
Comments, **ToDo** rows, avatars in every Desk list, and **Gantt resource
swimlanes** keyed on the assignee User. The "only one agent in the War Room"
complaint is structurally answered — every agent is now a real, visible actor
in Desk, not a string.

*Security note* per [[feedback_v01-skills-first-party-trust]]: these are
first-party trusted identities on a single-tenant site. The CRITICAL bar is
that they **cannot log in** (no credential path) — verified by a test asserting
`frappe.auth` rejects them. Robustness of the provisioner = HIGH.

## Q5 — Console architecture: native views + one bespoke page *(LOCKED)*

**Structured PM = native Frappe, zero custom UI code:**
- **Gantt**: Task list view → Gantt, using `exp_start_date`/`exp_end_date`,
  grouped by `project`, colored by `color`, resource = assignee User.
- **Kanban**: Task Kanban board keyed on `workflow_state` columns.
- **Dashboard**: a Project Dashboard (`dashboard/`) with charts + number cards.
- **Workspace**: a "Projects" Workspace (`workspace/projects.json`) as the Desk
  landing — shortcuts to Project list, Task Kanban, Gantt, the Console page,
  number cards (Active Projects, Tasks Executing, Blocked, Open Issues).

**Live command-center = one bespoke Desk Page** (`page/project_console/`):
the `.json` + `.js` + (optional) `.py` triplet Frappe expects. Vanilla JS +
Frappe's UI primitives (no React build step — stays inside Frappe's asset
pipeline). It is the *only* hand-written UI surface.

## Q6 — Live data: realtime push, poll as fallback *(recommended)*

- **Push (primary):** a new `warroom/console_stream.py` emits
  `frappe.publish_realtime("friday:project_activity", payload, room=...)` on
  every Task transition (called from the same `_watch_transition` seam that
  already posts to War Room — one more sink, fail-soft). The console page does
  `frappe.realtime.on("friday:project_activity", ...)` and prepends to the live
  feed. Per-project rooms so a project view only hears its own events.
- **Poll (fallback + initial load):** on page open and every 30s, the page
  calls a single whitelisted `console_snapshot(project=None)` that returns the
  same shape as `pipeline_health()` plus the active-task list. This catches any
  dropped realtime frame (same "state is truth" principle as Design 61's
  reconciler) and seeds the view before the first event arrives.

No 5s polling like Hermes — realtime carries the live load; the 30s poll is a
correctness backstop, not the primary path.

## Q7 — What the Console page shows (information architecture) *(recommended)*

Single Desk Page, three zones:

1. **Header status strip** — drawn from `pipeline_health()`: verdict pill
   (🟢 ok / 🟡 degraded / 🔴 down), counts (Pending / Executing / Blocked /
   Completed today), `friday` worker presence, open Issues. This is the
   "is the machine alive" line the 4-hour-stall incident proved we need.
2. **Project lane (left/main)** — a selector + per-project card: %-complete
   ring, task state tally, the agents on it (avatars), deliverable count
   (Design 66b files), a mini dependency/Gantt strip. Click → native Gantt.
3. **Live activity feed (right)** — reverse-chron stream of agent-as-speaker
   events (`🤖 Copywriter — [TASK-42] completed · 1.8s`), pushed in realtime,
   each row linking to the Task. This is the Hermes "Sessions LIVE feed"
   equivalent, but project-scoped and push-driven.

## Q8 — Progress + cost rollup *(recommended)*

- **`percent_complete`**: `completed_tasks / total_tasks * 100`, where a Task
  counts complete in {Completed, Review, Cancelled}. Recomputed on any child
  Task transition via a hook on Task `on_update` that touches its `project`
  (db_set, no recursive save — same idiom as `tasks/workflow`).
- **Cost**: the agentic runner's `run_turn` result envelope is the source. If
  per-turn token/USD telemetry is **not yet captured** there, 65d adds a
  `usage` block to the envelope (input/output tokens, est. USD from the LLM
  Provider's price) — this is a *named sub-dependency*, flagged here so it's not
  silently skipped. Task `cost_usd` ← envelope; Project `actual_cost_usd` ←
  Σ child tasks. No fabrication: if usage is absent, cost renders "—", never 0.

## Q9 — Native view configuration details *(recommended)*

- Task `.json`: add `"gantt"` and `"kanban"` to allowed view modes; set
  `kanban` default columns from `workflow_state`; `gantt` date fields
  `exp_start_date`/`exp_end_date`.
- Ship a **Kanban Board** fixture (`workflow_state` columns) and a **Dashboard
  Chart** fixture (Tasks by state, Tasks completed/day) + **Number Cards** so
  they exist on fresh installs, not just hand-built per site.
- Permissions: Project Console page + Workspace gated to System Manager +
  Agent Supervisor (same as Project DocType today).

## Q10 — Implementation phasing

| PR | Scope | Verify |
|---|---|---|
| **65a** | Project + Task new fields; `agent_identity.py` provisioner + Agent Profile `user` link; after_migrate wiring | `bench migrate` clean; provisioner idempotent (re-run → no dupes); agent-User cannot auth (test); existing pipeline tests still green |
| **65b** | Native views: Gantt/Kanban view config, Kanban Board + Dashboard + Number Card fixtures, "Projects" Workspace | Open Task Kanban/Gantt in Desk live; Workspace renders; number cards populate |
| **65c** | `page/project_console/` Desk Page + `console_stream.py` realtime emit + `console_snapshot()` endpoint | Console page loads; transition a task → event appears live in feed without refresh; snapshot poll seeds view |
| **65d** | Progress rollup hook (Project %-complete) + cost telemetry in run_turn envelope + cost rollup + cost number cards | Complete a task → project %-complete updates; cost rolls up or renders "—" (never fabricated 0) |

Each PR carries its own tests-first suite + a `docs/rollouts/design-65X-*.md`
narrative in the same PR ([[feedback_high-school-readable-docs]]).

## What's explicitly NOT in Design 65

- OAuth provider login (63b-OAuth) — separate slice.
- MCP / outside-world tools (Design 67).
- Setup wizard (Design 64).
- Project Template DocType, Timesheets, billing (Q1 dropped).
- A React/Vite build — the console is Frappe-native vanilla JS by Q5.
