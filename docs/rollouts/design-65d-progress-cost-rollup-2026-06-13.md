# Design 65d — Progress & cost rollup (2026-06-13)

## The one-sentence version

Fill the numbers: every task now carries a progress bar and its real LLM cost,
and every project rolls those up into %-complete, task counts, dates, and total
spend — so the views and console from 65b/65c show live, honest figures.

## Why this is PR #4 of four — the finale of Design 65

65a defined the rollup fields (read-only), 65b/65c render them. They've been
showing blanks/zeros because nothing computed them yet. 65d is the wiring that
makes them real. With this, Design 65 is complete: an ERPNext-grade project
module + a live console, fully populated.

## What this PR ships

### 1. Task `progress` (the bar)

A 0/50/100 value derived from `workflow_state` — Pending/Assigned = 0,
Executing/Blocked = 50, Review/Completed/Cancelled = 100. Set alongside the
other derived fields in `tasks/workflow.on_state_change` (same `db_set`, no
extra save). Drives the Gantt bars and console progress.

### 2. Task `cost_usd` + `duration_ms` (honest cost)

When an agentic task finishes (or fails), the runner attaches:
- `cost_usd` = the summed `estimated_cost` from the `LLM Usage Log` rows already
  recorded per model call under `session_id = "task::<name>"`.
- `duration_ms` = wall-clock of the turn.

**The honest-cost rule:** `estimated_cost` is only a number when the operator
has set `input_cost_per_million` / `output_cost_per_million` on the `LLM
Provider`. If they haven't, every row's cost is `None`, the sum is `None`, and
`cost_usd` stays **blank — never a fabricated 0** (the console renders "—").
Captured on the failure path too, so a blocked task still shows what it spent.

### 3. Project rollup (`tasks/rollup.recompute_project_rollup`)

On every child-task transition, the parent project's derived fields are
recomputed from its tasks in one pass:
- `total_tasks`, `completed_tasks` (done = Completed/Review/Cancelled),
  `percent_complete`.
- `actual_start_date` = earliest task start.
- `actual_end_date` = latest completion, **only once nothing is still
  Pending/Assigned/Executing/Blocked** (a stuck task means the project isn't
  done, so no end date is stamped).
- `actual_cost_usd` = sum of child `cost_usd` (None if all blank — never 0).

Written with a single `frappe.db.set_value` on the Project (fires no Task hooks
→ no recursion), inside a savepoint so a rollup hiccup can never break the task
save and can't poison the Postgres transaction. The numbers are derived, so
they self-heal on the next transition if a recompute is ever skipped.

## Compare with Hermes

Hermes gates its token analytics off by default because its counts are
unreliable, and only ever aggregates — there's no per-run cost in the UI.
Friday attributes **real, governed cost per task** (from the same usage ledger
the agent already writes) and rolls it to the project, surfaced in the console
and number cards. Accurate-by-construction, and honest when rates aren't set.
Per `feedback_hermes-floor-not-ceiling`.

## Why we know it works

13 unit tests in `frappe/friday_core/tests/test_rollup.py`: the progress map;
the cost sum (real, all-None → None, no-rows → None); and the project rollup
math — counts, %-complete, the "end-date only when all done" rule (incl. a
Blocked task suppressing it), cost summation, and the no-op guards. The full
pipeline suite (workflow/dispatcher/reconciler — 55 tests) stays green with the
rollup wired into the transition seam.

## What's NOT in this PR

- `estimated_cost_usd` on Project (a *planned* budget) — left for the operator;
  65d only computes *actual* cost.
- A backfill of historical projects/tasks — rollup fields populate going
  forward, on the next transition of each task. A one-shot recompute script can
  be added if a site wants its existing rows filled immediately.

## Operator note

To see real cost figures, set **Input/Output Cost per Million** on each **LLM
Provider**. Without them, progress/counts/dates are still live; cost shows "—".
No migration needed beyond the usual `bench migrate`.
