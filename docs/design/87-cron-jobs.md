# Design 87 — Scheduled agent runs / cron jobs (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — Q1–Q6 all answered as the recommended path.
Tests-first, then code. Gateway-adjacent gap (ports ledger row #7) and the first
real **consumer of the delivery router** (Design 86). Scoped to **Slice 1** below.

## Plain English

Friday can run an agent when a human messages it. It cannot yet run an agent **on
a schedule** — "every weekday at 9am, summarise yesterday's completed tasks and
post it to #ops". That's cron jobs: a stored schedule + a prompt + a delivery
target, fired by a tick, with the output delivered somewhere (a channel, or a
file when there's no channel). Hermes has this (`cron/jobs.py`,
`cron/scheduler.py`, `tools/cronjob_tools.py`); Friday's `*/1` ticks are
infra-only today.

## What the source says (grounded, both sides)

**Hermes** — job record carries `schedule` (once / interval / cron), `prompt`,
`deliver` target, `repeat {times, completed}`, `enabled`, `next_run_at`,
`last_run_at/status`, `origin`, `profile` (`cron/jobs.py:653`). A 60s ticker
(`scheduler.py`) finds due jobs (`next_run_at <= now AND enabled`), **advances
`next_run_at` BEFORE running** (at-most-once safety, `jobs.py:964`), runs the
agent in a `cron_{id}` session, delivers via the job's target, then
`mark_job_run` (bumps `completed`, removes the job at its repeat limit). Cron
expressions are parsed by **`croniter`**. A `[SILENT]` reply suppresses delivery.

**Friday substrate** — `croniter 6.0.0` is available (Frappe's own scheduler uses
it). The `*/1` tick pattern is established (`tasks/dispatcher.py`,
`reconciler.py`): register in `hooks.py scheduler_events`, select due rows, act
with a per-tick budget. The proven way to run a no-human agent turn is a **Task**:
create it assigned to a profile → `tasks/workflow.py:233` emits `agent_task.assigned`
→ the runner runs it (durable, heartbeat'd, reconciler-rescued, marks itself
Completed with the reply as `result`). Output delivery is exactly what the new
`DeliveryRouter.deliver(content, targets, job_id, …)` does (Design 86): `"local"`
→ a private File, `"raven:CH"` → an outbound row.

## Slice 1 scope (this design)

A **Desk-managed** cron feature: a `Cron Job` doctype, a `*/1` tick that spawns a
Task per due job, and delivery of the result. The **agent-facing cron skill**
(an agent scheduling its own jobs) is **Slice 2**, deferred — Slice 1 is a
complete, usable feature on its own (an operator creates jobs in Desk).

## Why a Q-by-Q lock

The execution model, schedule formats, at-most-once safety, delivery timing, and
repeat-lifecycle each have a real choice. Six questions.

---

## Q1 — How does a scheduled run execute?

**Option A — spawn a Task, reuse the durable run path (recommended).** The `*/1`
tick creates a `Task` (assigned to the job's `agent_profile`, `description` = the
job's prompt, a new `cron_job` Link back to the job). The existing machinery runs
it: `agent_task.assigned` → runner → heartbeat → marks Completed with the reply
as `result`; the reconciler rescues a stalled run. Delivery happens on completion
(Q4). Maximum reuse; inherits Friday's durability/observability for free.

**Option B — a dedicated direct-run RQ job.** The tick enqueues a job that calls
`run_turn` in a `cron::{id}` session and delivers inline. Self-contained, but
re-implements durability (no reconciler rescue, no heartbeat, no Task audit row).
Rejected — Friday's whole ethos is the durable Task pipeline.

**Recommendation: A.** Cron runs ARE Tasks, tagged with a `cron_job` link.

---

## Q2 — Which schedule formats?

**Option A — cron + interval + once (recommended).** A `schedule_kind`
(Select: `cron` / `interval` / `once`) + `schedule_expr`:
- `cron` → a 5-field expression, `next_run` via `croniter(expr, base).get_next()`.
- `interval` → "every N minutes", `next_run = last_run + N min`.
- `once` → an ISO datetime; fires once then disables.

Covers recurring + one-shot with ~a dozen lines each. Faithful to Hermes' three
kinds; `croniter` does the hard part.

**Option B — cron expressions only.** Simpler, but no "remind me once at 3pm" and
no friendly intervals. Rejected — once/interval are nearly free and commonly
wanted.

**Recommendation: A.** All three kinds, `croniter` for `cron`.

---

## Q3 — At-most-once safety

**Option A — advance `next_run_at` BEFORE spawning the Task (recommended).** In
the tick, compute and persist the next `next_run_at` first, then create the Task.
If the worker dies between the two, the job simply skips that run rather than
double-firing on the next tick. This is Hermes' critical pattern (`jobs.py:964`).
Pair it with a per-tick budget (like the dispatcher's 5) and `FOR UPDATE SKIP
LOCKED`-style claiming so two workers never grab the same job.

**Recommendation: A.** Advance-then-spawn; faithful at-most-once.

---

## Q4 — When/how is output delivered?

**Option A — deliver on Task completion via a hook (recommended).** A handler on
Task → Completed: if `task.cron_job` is set, parse the job's `deliver` target and
call `DeliveryRouter.deliver(task.result, [target], job_id=cron_job, job_name=…)`,
then update the Cron Job bookkeeping (Q5). Default target `"local"` → a private
File (a no-channel job still produces durable output). A `[SILENT]` reply
suppresses delivery (faithful to Hermes) but still records the run.

**Option B — the tick polls finished cron-Tasks and delivers.** Adds a second
scan + a "delivered" flag. More moving parts than a completion hook. Rejected.

**Recommendation: A.** Deliver in the Task-completion handler; `[SILENT]` skips.

---

## Q5 — Repeat limit + lifecycle

Hermes **deletes** a job when its repeat limit is reached. Frappe rows are an
audit surface and shouldn't silently vanish.

**Option A — disable, don't delete (recommended).** `repeat_times` (0 = forever,
1 = once, N = N times) + a read-only `completed` counter. On each run bump
`completed`; when `completed >= repeat_times` (and not forever), set
`enabled=0, state="Completed"`. The row stays for history; an operator can resume
or remove it. Disclosed divergence from Hermes' delete.

**Recommendation: A.** Disable + mark Completed; keep the row.

---

## Q6 — Scope of this slice

**Option A — Slice 1 = doctype + tick + delivery, Desk-managed (recommended).**
Ship the `Cron Job` doctype, the `*/1` tick, the completion-delivery hook, the
`croniter` next-run logic, and `after_migrate` (the doctype + a `Friday Cron
Manager` role to gate who may create jobs). An operator creates/pauses/removes
jobs in Desk. Complete and testable without any agent-facing surface.

**Slice 2 (deferred)** — a `manage-cron-jobs` skill so an agent can schedule its
own recurring work (create/list/pause/resume/remove/trigger), permission-gated.
Bigger blast radius (agent self-scheduling); lands once Slice 1 is proven.

**Recommendation: A.** Slice 1 now; the skill is its own design/PR.

---

## Summary of what lands once Q1–Q6 are answered (recommended path)

- **`Cron Job` doctype** (`module: Friday Core`, `autoname field:job_name`):
  `job_name`, `enabled`, `agent_profile` (Link), `prompt` (Long Text),
  `schedule_kind` (Select cron/interval/once), `schedule_expr` (Data),
  `deliver` (Data, default `"local"`), `repeat_times` (Int, 0=forever),
  `completed` (Int, read-only), `state` (Select Scheduled/Paused/Completed/Error),
  `next_run_at` / `last_run_at` (Datetime, read-only), `last_status` /
  `last_error` (read-only), `last_task` (Link Task, read-only).
- **`Task.cron_job`** (Link Cron Job) — the only new Task field; the completion
  hook reads `deliver` from the linked job.
- **`cron/scheduler.py`** (new under friday_core): `tick()` (advance-then-spawn,
  per-tick budget), `compute_next_run(kind, expr, base)` (croniter/interval/once),
  registered at `hooks.py scheduler_events["cron"]["*/1 * * * *"]`.
- **Completion delivery** — extend the Task-completion path: `if task.cron_job`,
  deliver `result` via `DeliveryRouter` + update the Cron Job (Q4/Q5).
- **`cron/after_migrate.py`** — ensure the `Friday Cron Manager` role.
- **No** agent skill (Slice 2).

**Tests-first:**
1. `compute_next_run`: cron `"*/5 * * * *"` → +5 min via croniter; interval `"30"`
   → +30 min; once ISO → that time, then None. (Q2)
2. `tick` advances `next_run_at` BEFORE creating the Task (a crash after advance
   does not double-fire). (Q3)
3. `tick` spawns ONE Task per due job, assigned to `agent_profile`, linked via
   `cron_job`, only for `enabled` jobs whose `next_run_at <= now`. (Q1)
4. Completion hook delivers `task.result` to the job's `deliver` target via the
   router and bumps `completed`; `[SILENT]` result records the run but skips
   delivery. (Q4)
5. Repeat limit: a job with `repeat_times=1` flips to `enabled=0, state=Completed`
   after one run; `repeat_times=0` keeps running. (Q5)
6. Default `deliver="local"` with no channel → a private File is written. (Q4)

Nothing is built until Q1–Q6 are confirmed.
