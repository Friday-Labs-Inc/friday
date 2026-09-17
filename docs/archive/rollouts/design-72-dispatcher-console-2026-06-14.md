# Design 72 — Dispatcher Console (Rollout)

**Date:** 2026-06-14
**Design doc:** [`72-dispatcher-console.md`](../design/72-dispatcher-console.md)
**Status:** Built end-to-end. Ready for review.

## What hurt before

When Friday was running the FLI-001 pipeline, the `guidelines` task got stuck in `Executing` for 7+ minutes. The operator (you) had no way to see what was happening. Behind the scenes:

1. The agent skill called a tool that tried to INSERT a duplicate `Project` row.
2. Postgres rejected it with `UniqueViolation`.
3. That **poisoned the database transaction** — every later SQL statement got `InFailedSqlTransaction`.
4. The runner's own error handler tried to update the task → crashed itself.
5. Task sat in `Executing` forever, no Issue raised, no War Room post, nothing in the logs that anyone was watching.

We *only* found it because we manually scrolled through `friday.tasks.runner.log` and saw the cascading Postgres errors.

This is the kind of incident an observability tool exists to prevent. Friday had a beautiful **outcomes** view (Project Console) and zero **mechanics** view.

## What changed

A new admin page at `/desk/dispatcher-console` with two tabs:

### Pulse — operational health at a glance

Six cells, 2x3 grid, refreshes every 2 seconds:

| Cell | Tells you |
|---|---|
| **Scheduler** | When the scheduler last ticked. Red if >5 min stale (the same signal the Project Console health strip uses). |
| **Reconciler** | When the reconciler last swept + what it found. "tick: assigned_orphans=0, executing_stale=0, transient_blocked=1, randompack_events=0" — you see every sweep, not silence. |
| **Active Leases** | How many tasks are currently `Executing`, and the oldest unrefreshed heartbeat. Red if a heartbeat is >5 min stale (the runner is dead). |
| **Dispatchable** | How many `Pending` tasks are sitting in the queue + the oldest one's age. |
| **RQ Queues** | Depth of the `default` and `friday` job queues. |
| **Workers** | Which Agent Profiles are Active. |

### Lifecycle Trace — what happened to one task

Pick a task from the dropdown. The page shows every framework event that touched it, in time order:

- `workflow.state_change` (with the **trigger source**: `manual_save`, `dispatcher_claim`, `reconciler_reset`, `runner_complete`, `runner_block`, `runner_error`, `user_desk`)
- `workflow.executing_token_released` — when the runner's claim was given up
- `dispatcher.claim_attempt` — when the dispatcher picked it up
- `dispatcher.skip` — when the dispatcher saw it but couldn't claim (no profile match / concurrency cap / parent task not done / etc.)
- `reconciler.tick` — every reconciler sweep
- `reconciler.action` — every re-pend / runner_lost / re-enqueue
- `runner.start`, `runner.complete`, `runner.block`, `runner.error`
- `llm.call_summary` — one row per LLM API call (provider, model, tokens, cost)
- `warroom.post` — every War Room post (succeeded OR silently rolled back)
- `issue.raised` — every Failure / Dependency-Wait Issue

Each row shows the wall-clock time, the event type, the trigger source, and a one-line summary. Color-coded so state changes (blue), skip events (amber), errors (red), and completes (green) stand out.

For live tasks (`Pending`, `Assigned`, `Executing`), the page auto-tails as new events land. For terminal tasks, it snapshots.

A summary panel at the top shows: current state, profile, retry count, blocked reason, total cost (USD), duration (ms) — pulled from `Task Completion Summary` (the permanent compact audit row written on every terminal transition).

## How the data plane works

A new `Dispatcher Event` DocType is the typed event log. Every framework write site calls `friday_core.observability.emit()` to record what happened. The helper:

- Wraps every write in `frappe.db.savepoint("dispatcher_emit")`.
- Rolls back the savepoint on any failure (mirrors the proven `_post_warroom` pattern in `tasks/workflow.py`).
- **Never raises.** A bug in emit cannot poison the surrounding transaction or break production code.
- Returns `None` on failure; callers ignore the return value.

The doctype is **append-only** — System Manager has read-only access, no create/edit/delete from the UI. All writes go through `emit()`.

Retention: a daily scheduler job (`purge_old_events`) deletes rows older than 30 days in 1000-row batches. On every terminal state transition, the workflow hook writes a permanent compact `Task Completion Summary` row (one per task, upserted) so the audit trail survives the purge.

## Write sites instrumented

| Module | Events emitted |
|---|---|
| `tasks/workflow.py` | `workflow.state_change` (every transition, with trigger source), `workflow.executing_token_released`, `warroom.post` (succeeded / silently_rolled_back_savepoint) |
| `tasks/dispatcher.py` | `dispatcher.claim_attempt` (won), `dispatcher.skip` (5 reasons: no_profile_match, milestone_not_dispatchable, parent_pending, project_on_hold, stale_assigned_profile) — deduped per (task, reason) within 60s |
| `tasks/reconciler.py` | `reconciler.tick` (per-cycle with phase action counts), `reconciler.action` (re_enqueue_assigned_orphan, runner_lost, re_pend_transient) |
| `tasks/runner.py` | `runner.start`, `runner.complete`, `runner.block` (per-attempt), `runner.error` (top-level crash) — **plus the resilience fix** for the FLI-001 case below |
| `llm/usage.py` | `llm.call_summary` after every `LLM Usage Log` write (provider, model, tokens, cost) |
| `issues/raise_issue.py` | `issue.raised` for both Failure and Dependency-Wait Issues |

## Bonus fix: runner resilience (the FLI-001 root cause)

The agentic runner's error handlers now call `frappe.db.rollback()` **before** any subsequent DB writes. Previously a `UniqueViolation` from a skill insert would poison the transaction and the error handler would crash on `InFailedSqlTransaction` instead of recording the failure cleanly. Two paths fixed:

1. `on_agent_task_assigned` top-level except — rolls back, then raises Issue + emits `runner.error`.
2. `_run_task_agentic` except — rolls back, re-fetches the task doc, then saves the Blocked state cleanly.

This means the next time a skill bug crashes the txn, the task transitions cleanly to `Blocked` with a structured `blocked_reason`, an Issue is filed, the War Room is posted, and the Lifecycle Trace shows exactly what happened.

## Where it lives in the UX

- New top-level Desk page: `/desk/dispatcher-console`
- Shortcut tile in the **Friday** workspace (red — admin/observability color)
- New "Observability" card in the workspace listing `Dispatcher Event` + `Task Completion Summary` for direct doctype browsing

## What does NOT ship in v0.1 (deferred to v0.2)

- Reconciler Trace tab (richer per-tick view)
- Event Bus tab (cross-task workflow hook stream)
- Agent Run drilldown (open one turn's LLM round-trips)
- Filtering UI (by project / profile / blocked_reason / time window)

## Migrations & gates

- `bench migrate` passes clean (gate per [[migrate-gate-before-pr]]).
- 42 tests across emit / workflow / reconciler pass with zero regressions.
- Smoke test confirms events flow end-to-end from a real Task save → `Dispatcher Event` rows → live Pulse + Lifecycle Trace render.

## Hermes parity

- **Borrowed pattern:** Hermes's `AgentRunEvent` typed-event-log shape (event_type + trigger_source + structured payload) — Friday's `Dispatcher Event` mirrors it verbatim.
- **Surpass-Hermes per [[hermes-floor-not-ceiling]]:** Pulse + Dispatch Queue + Active Leases + Reconciler Trace are net-new Friday features. Hermes is in-process; it has no multi-worker / scheduled-job topology to observe. These views are driven by Friday's durable [[unified-gateway-service]] architecture.
