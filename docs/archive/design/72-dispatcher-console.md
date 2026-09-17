# Design 72 — Dispatcher Console

**Status:** Locked 2026-06-14. All Qs decided. Implementing next.

## The pain

The Project Console shows **outcomes** — projects, tasks, percent complete, last state. It does **not** show the runtime mechanics that produce those outcomes. When something goes wrong — or even when it goes right — the framework's behaviour is invisible:

- **Reconciler** ticks every minute, silently. No record of when it last ran, what it found (transient blocked / stale executing / orphans), or what it acted on. We only see the side effects (a task suddenly Pended again).
- **Dispatcher** claims tasks via `FOR UPDATE SKIP LOCKED`, silently. No record of what was eligible, why some eligible tasks were skipped (no profile match? all profiles at concurrency cap? role gate? depth gate?), or what was claimed.
- **Workflow hook** fires on every state change, silently. No record of *who* triggered it (manual save / RQ runner / reconciler reset / dispatcher claim / user from Desk) or which side effects ran versus silently rolled back via savepoint.
- **Active leases** — silent. Who holds which `executing_token`, how stale is the `last_heartbeat_at`, how long has the task been Executing.
- **Per-task lifecycle** — fragmented. `last_heartbeat_at`, `retry_count`, `blocked_reason`, log files, Comments, workflow_state changes — all in different places. No single trace to follow one task end-to-end.

The most acute symptom — caught live on the FLI-001 E2E run today (2026-06-14): the `guidelines` task stayed in `Executing` for **7+ minutes** with no visible signal of what was happening. The runner had actually crashed on a `psycopg2.UniqueViolation` (the agent kept trying to insert a duplicate `backend_ref=FLI-001` Project) and the runner's error handler crashed *itself* on `InFailedSqlTransaction` because it tried DB writes without a `frappe.db.rollback()`. Neither failure surfaced in the Project Console — the task just sat there. With the console proposed here, the lifecycle trace would have shown: `Executing started → LLM call → tool call insert_project → Postgres unique_violation → error handler crashed → no state transition`. The operator could have intervened in 30 seconds instead of 7 minutes.

## Goal

Two complementary views in one console:

1. **Pulse** — top-of-page operational heartbeat. *Is the framework healthy and what is it doing right now?* (Live counters for scheduler, reconciler, queue depths, leases, dispatchable count.)
2. **Lifecycle Trace** — per-task forensic timeline. *What actually happened to this one task end-to-end?* (Every state transition, every system action, every LLM call, every War Room post — with the exact trigger source.)

## Non-goals

- **Not a replacement for Project Console** — outcomes view stays separate and unchanged.
- **Not a metrics dashboard** — no charts, no histograms, no Grafana parity. Timeseries belongs elsewhere.
- **Not user-facing** — System Manager / operator console. Not for clients viewing project status.
- **Not an LLM observability tool** — call summaries are in scope (model / tokens / cost / classified reason), but full prompt/response replay belongs in Agent Run drilldown (Design 70 territory).

## Hermes comparison

Hermes has an `Agent Run` doctype with a structured trace timeline per turn (events for tool calls, LLM round trips, classifier verdicts). It does NOT have any equivalent of the dispatcher / reconciler / pulse views — Hermes is in-process, one turn per request, no scheduled-job topology to observe.

- **Borrow:** the structured event-log pattern (typed `DispatchEvent` doctype with `event_type`, `payload`, `task`, `agent_profile`, `trigger_source` — mirrors Hermes's `AgentRunEvent` shape).
- **Surpass ([[hermes-floor-not-ceiling]]):** Pulse, Dispatch Queue, Active Leases, Reconciler Trace — these are net-new Friday features driven by our multi-worker queue/scheduler topology. Hermes wouldn't make sense of them. Friday needs them because the framework is durable + observable across worker lifetimes ([[unified-gateway-service]]).

## Locked Qs

### Q1 — Scope?
**Locked 2026-06-14: Both Pulse and Lifecycle Trace, as tabs of one console.** Pulse answers "is the system healthy now"; Lifecycle Trace answers "what happened to this one task." Both modes are needed; neither alone closes the observability gap.

### Q2 — Where does the console live in the Desk UX?
**Locked 2026-06-14: New top-level Desk page** at `/desk/dispatcher-console`, sibling of Project Console, listed under "Pages" in the Friday workspace shortcuts. The console is framework-level, not project-level — it shows what the runtime is doing across all projects. Project Console's purpose (per-project status) stays clean.

### Q3 — Unit of Lifecycle Trace?
**Locked 2026-06-14: Task as anchor, Agent Run drillable.** Pick a task in the trace tab — that's the primary unit (it's what blocks / cancels / completes in your FLI-001 run). An "Agent Runs" sub-section lists each ReAct turn against that task, and the operator can drill into one for LLM round trips and tool calls when they want LLM-level detail. Project view deferred to a future design layer; cross-task analysis isn't the immediate gap.

### Q4 — Trace data source?
**Locked 2026-06-14: New `Dispatcher Event` doctype.** A typed event log written by dispatcher / reconciler / runner / workflow hook / LLM provider / War Room publisher / issue raiser via one `emit(event_type, **fields)` helper. Single source of truth, queryable, indexable, with `trigger_source` as a first-class field on every event. Adds 1 doctype + ~7 write sites + a 30-day retention sweep. Scraping existing surfaces was rejected because the most-needed events (reconciler skip reasons, dispatcher skip reasons, savepoint rollbacks, classifier verdicts) are not recorded anywhere today — scraping only rearranges known data without closing the gap.

### Q5 — Live updates mechanism?
**Locked 2026-06-14: 2-second polling.** The page hits one JSON endpoint every 2 s; server returns Pulse cells + new trace events since the page's last seen cursor. Predictable, no socketio plumbing, the console keeps working even if Frappe's realtime layer is broken — an observability tool must not depend on the same fragile machinery it exists to observe. The Raven `VITE_SOCKET_PORT=9000` vs `9005` incident from earlier today is fresh evidence this matters. 2 s is human-perceptible-live without thrashing the server.

### Q6 — Retention of `Dispatcher Event`?
**Locked 2026-06-14: 30-day raw window + permanent `Task Completion Summary`.** Raw `Dispatcher Event` rows are auto-purged by a daily scheduler job after 30 days. On every terminal task transition (Completed / Cancelled / Blocked-non-transient), the workflow hook writes one compact `Task Completion Summary` row capturing: final state, total event count, total LLM cost, total duration, blocked_reason if any, terminating Issue if any, list of agent profiles that touched the task. Summary table grows only with project/task count — bounded forever. Gives operational depth for recent debugging plus permanent audit trail for long-tail forensics.

### Q7 — Pulse panel contents?
**Locked 2026-06-14: Ship all 6 cells in v1.** 2×3 grid, top-to-bottom broad → narrow (system tick → mid-layer reconciler/leases/queue → workers):

| # | Cell | Headline | Detail |
|---|---|---|---|
| 1 | **Scheduler** | last tick (relative + absolute) | red if >5 min stale |
| 2 | **Reconciler** | last sweep | last action summary ("re-pended 1 / cancelled 0 / no-op 4") |
| 3 | **Active Leases** | count | stalest heartbeat age (red if >5 min) |
| 4 | **Dispatchable** | count | oldest age in queue |
| 5 | **RQ Queues** | `default` depth + `friday` depth | worker count per queue |
| 6 | **Workers** | `up` / `down` per Agent Profile | matches the "friday worker: up" line already in Project Console |

Each cell ~3 lines: headline number, age, last action. Each is a single query or single Redis check — cheap enough that the 2-second polling endpoint (Q5) computes all 6 fresh each tick. Removing any one creates a visible blind spot.

### Q8 — Lifecycle Trace event types?
**Locked 2026-06-14: Ship all 13 event types in v1.**

| Source | Event types |
|---|---|
| **workflow hook** | `workflow.state_change` (with `trigger_source`: `manual_save \| dispatcher_claim \| reconciler_reset \| runner_complete \| runner_block \| runner_error \| user_desk`) · `workflow.dispatchable_changed` · `workflow.executing_token_set` · `workflow.executing_token_released` |
| **dispatcher** | `dispatcher.claim_attempt` (`won \| lost_duplicate`) · `dispatcher.skip` (`no_profile_match \| concurrency_cap \| role_gate \| depth_gate \| parent_pending \| stale_assigned_profile`) |
| **reconciler** | `reconciler.tick` (counts: transient_blocked / stale_executing / orphans) · `reconciler.action` (per-action: re-pend / cancel / no-op + target task) |
| **runner** | `runner.start` · `runner.complete` · `runner.block` · `runner.error` · `runner.heartbeat` (sampled once per 30 s) |
| **llm provider** | `llm.call_summary` (model / latency_ms / prompt_tokens / completion_tokens / cost_usd / classified_reason if failed) |
| **warroom publisher** | `warroom.post` (`succeeded \| silently_rolled_back_savepoint`) |
| **issues** | `issue.raised` (link to Issue doc) |

Gaps in observability are worse than no observability (silence reads as "it worked"). Deferring any source means retro-instrumenting later when a real incident exposes the blind spot. The FLI-001 `guidelines` invisible-crash becomes traceable as: `runner.start → llm.call_summary → runner.error (UniqueViolation) → warroom.post (silently_rolled_back_savepoint)` — every step visible.

### Q9 — Auth: who sees the Dispatcher Console?
**Locked 2026-06-14: System Manager only.** This is admin/operator territory. Showing dispatcher skip reasons, active leases, and stuck-task counts to non-admins is a privacy leak (surfaces internal queue health and which clients have problems). Project Console stays open to its existing audience; Dispatcher Console is gated.

### Q10 — Dispatch Queue "why not claimed" reasons?
**Locked 2026-06-14: Instrument dispatcher to emit `dispatcher.skip` per skipped task as part of v0.1.** The current `_fetch_dispatchable_tasks` / `_attempt_claim` paths silently exclude tasks; the Dispatch Queue panel needs the reason to be useful. Skip reasons:

- `no_profile_match` — no Agent Profile has all required skills for this task
- `concurrency_cap` — all matching profiles at `max_concurrent_tasks`
- `role_gate` — task requires a role no available profile has (Design 68)
- `depth_gate` — delegation depth exceeded (Design 69)
- `parent_pending` — parent task not yet Completed (Design 69)
- `stale_assigned_profile` — `assigned_to_profile` non-null but task is `Pending` (follow-up to PR #111, addresses dispatcher gap from FLI-001)

Each emit is dedup-windowed per (task, reason) within 60 s to avoid table thrash on a busy dispatcher tick. Additive instrumentation — no change to claim logic itself.

### Q11 — v0.1 ship boundary?
**Locked 2026-06-14: Slice as below.**

**Ships in v0.1 (one PR):**
- `Dispatcher Event` DocType (System Manager read; `permitted_to_create = 0` outside the emit helper)
- `Task Completion Summary` DocType (one row per terminal task)
- `friday_core/observability/emit.py` — single `emit(event_type, **fields)` helper, savepoint-guarded, never raises
- Write-site instrumentation: `tasks/dispatcher.py`, `tasks/reconciler.py`, `tasks/runner.py`, `tasks/workflow.py`, `llm/provider.py`, `warroom/publisher.py`, `issues/raise_issue.py`
- Dispatcher skip-reason emission (Q10) + 60 s dedup window
- Daily retention sweep (batch DELETE in 1000-row chunks) + terminal-state Task Completion Summary writer
- `/desk/dispatcher-console` page — two tabs (Pulse, Lifecycle Trace), Q7 all 6 cells, Q14 auto-tail, 2 s polling endpoint, System Manager auth
- Tests: each write site, savepoint rollback safety, retention sweep, 60 s dedup, polling endpoint, page renders for empty / FLI-001 / running task
- `docs/rollouts/design-72-dispatcher-console-2026-06-14.md`

**v0.2 follow-ups (later PRs):**
- Reconciler Trace tab (richer per-tick view)
- Event Bus tab (cross-task workflow hook stream)
- Agent Run drilldown for `llm.call_summary` rows (full prompt/response replay)
- Filtering UI (by project / profile / blocked_reason / time window)

This boundary respects [[workflow-design-lock-before-roo-code]] — one tight slice per PR, [[migrate-gate-before-pr]] runs clean locally before push, all code paths tested before merge.

### Q12 — Hermes parity verdict?
**Locked 2026-06-14: Pattern borrowed, structure surpasses.**

- **Borrowed:** Hermes's `AgentRunEvent` typed-event-log pattern (one event row per durable thing-that-happened, with `event_type` + `trigger_source` + structured payload). Friday's `Dispatcher Event` mirrors the shape verbatim.
- **Surpass per [[hermes-floor-not-ceiling]]:** Pulse + Dispatch Queue + Active Leases + Reconciler Trace are net-new Friday features — Hermes is in-process and has no multi-worker / scheduled-job topology to observe. These are not "improvements" to a Hermes pattern; they're new surface driven by Friday's [[unified-gateway-service]] + durable runtime design.
- **Disclosed deviation:** none at this layer.

The rollout doc will call this out as a Friday-only feature with the Hermes pattern as foundation.

### Q13 — Layout style for Pulse?
**Locked 2026-06-14: 2×3 grid of cards.** Each cell needs 3 lines (headline number / age / last action) to be informative. A horizontal strip squeezes them into single lines and loses the "what was the last action" detail. Grid mirrors the card pattern already in Project Console for project tiles — consistent UX language.

### Q14 — Tail mode for Lifecycle Trace?
**Locked 2026-06-14: Auto-tail when the task is in a live state (`Executing`, `Pending`, `Assigned`); snapshot otherwise.** The whole point of the console is to *watch the framework work* — a snapshot view of an actively-running task misses the moment the operator opens the page to investigate. Hybrid rule keeps the table small: completed/cancelled tasks freeze at page-load, live tasks auto-extend via the 2 s polling cursor.

## What ships in v0.1

(Assuming all open Qs lock to the recommendations above.)

- `friday_core/doctype/dispatcher_event/` — new DocType (`event_type`, `task`, `agent_profile`, `trigger_source`, `payload_json`, `created_at`, plus indexed columns for the common queries).
- `friday_core/doctype/task_completion_summary/` — new DocType written once per task on terminal state (Completed / Cancelled / Blocked-non-transient).
- `friday_core/observability/emit.py` — single typed `emit(event_type, **fields)` helper used by every write site.
- Write site additions: `tasks/dispatcher.py`, `tasks/reconciler.py`, `tasks/runner.py`, `tasks/workflow.py`, `llm/provider.py`, `warroom/publisher.py`, `issues/raise_issue.py`.
- Dispatcher skip-reason instrumentation in `tasks/dispatcher.py`.
- `friday_core/console/dispatcher_console.py` — page handler + data API methods (Pulse cells, Lifecycle Trace fetch).
- Page UI in `friday_core/page/dispatcher_console/` — two-tab layout, Pulse grid, Lifecycle Trace picker + timeline.
- Retention scheduler: daily job purges `Dispatcher Event` rows older than 30 days; writes `Task Completion Summary` on terminal state transitions.
- `friday_core/patches/v1_0/add_dispatcher_event.py` if any seed is needed (probably not).
- Tests: doctype schema, each write site, retention purge, page rendering, polling endpoint.
- `docs/rollouts/design-72-dispatcher-console-2026-06-14.md` — rollout narrative.

## What does NOT ship in v0.1

- Reconciler Trace tab, Event Bus tab, Agent Run drilldown — v0.2.
- Filtering UI — v0.2.
- Socketio live push — never (decision Q5b).
- Charts / histograms / timeseries — out of scope (non-goal).
- Cross-site Pulse — single-site only (Friday is single-tenant per [[single-tenant-not-saas]]).
