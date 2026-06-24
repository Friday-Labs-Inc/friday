# 83b — `/stop force` — hard-kill a stuck agent turn

> **Status:** SHIPPED 2026-06-24 — with **three corrections applied during
> implementation** (the original proposal's Q4/Q5/Q8 were technically wrong; the
> schema it scaffolded was kept). See **§ Corrections** below.
> **Closes:** `docs/ports/hermes-port-ledger.md` §5 row #1 + Tier A #1
> (the last missing piece of the gateway session manager).
>
> ## Corrections (vs the original locked proposal)
>
> The proposal's *schema* (the `ForceKilled` state + 3 audit fields + patch +
> console wiring) was sound and kept. Three *behavioral* decisions were wrong and
> were corrected — verified against real source before any code:
>
> 1. **Q4 — kill primitive.** Proposal: `get_job(job_id).cancel()`. **Wrong** —
>    `Job.cancel()` only dequeues a *not-yet-started* job; it cannot stop a
>    *running* one (verified: rq 2.6.1). Corrected to
>    **`rq.command.send_stop_job_command`** (SIGTERMs the worker horse) — the true
>    analogue of Hermes `gateway/run.py:15292`.
> 2. **Q5 — finding the job.** Proposal: filter RQ jobs by
>    `kwargs.message.session_id`. **Wrong** — Friday's job is
>    `run_pipeline_for_row(row_name=…, lock_retry=…)`; no such kwarg exists.
>    Corrected to **`Chat Message.job_id`** (the chat turn) **+ the Design 85
>    cascade subtree** (delegated task jobs `task:{name}`).
> 3. **Q8 — reconciler.** Proposal: change the stale-Executing auto-heal to write
>    `ForceKilled`. **Regressive** — that path is the `runner_lost` → re-Pend →
>    retry-×3 safety net (Design 61a). **Reverted** — the reconciler is untouched;
>    `ForceKilled` is **operator-initiated only**.
>
> **Plain English.** Today an operator who needs to stop a stuck
> agent turn has two bad choices: wait (if the agent is mid-LLM
> call, that's the provider's streaming budget, up to ~120 s) or
> kill the whole friday worker (which cascades through honcho and
> tears down web, socketio, and all queues — the FLI-001 7-minute
> outage precedent). `/stop force` adds a third option: cancel
> the in-flight RQ job by id, mark the Task as a new first-class
> `ForceKilled` terminal state, sweep the orphaned sandbox within
> 60 s, and write one Dispatcher Event audit row. Operator-tier
> role only, single command, no confirmation prompt.

---

## Authority

Per `docs/design/42-phase-one-authority-contract.md` and the standing
"doc 42 wins on conflict" rule, this design supersedes any prior
description of `/stop force` behaviour in the port ledger or
gateway-command-surface memory notes. The doc-by-doc authority chain
for this slice: `42` → this doc → `49` (deviation audit) → port
ledger → other design docs.

---

## Decisions (Q-by-Q)

### Q1 — Single command vs confirmation prompt?
**Decision: single command (`/stop force`). No confirmation.**

Rationale: every other operator-tier slash command is single-command
+ role-gated (`/stop`, `/steer`, `/approve`, `/deny`, `/status`).
Adding `confirm` would break the pattern for no real win — the
`Friday Operator` role gate IS the confirmation. The action is
destructive to the in-flight job but the state is recoverable: the
Task row survives, the Dispatcher Event audit row exists, and the
reconciler sweeps any orphans. In an incident, an extra "confirm"
prompt adds friction at exactly the wrong moment. Accountability
lives in the audit row, not in a confirm-prompt dance.

### Q2 — Surgical `<task-id>` vs session-wide?
**Decision: session-wide. No `<task-id>` argument.**

Rationale: aligns with the existing `/stop` cascade (Design 85) —
which already reaches the whole delegated subtree via
`Task.parent_task` — and with Hermes' session-level cancel intent
(`hermes/gateway/run.py:15292` `send_stop_job_command` operates on
a session, not a single task). Operators don't track Task IDs at
chat time; they track sessions. One implementation path = simpler
code, fewer edge cases to test. If a future driver asks for
surgical kill, add `/stop force <task-id>` as a follow-up slice.

### Q3 — New `Task.workflow_state` value or reuse `Blocked`?
**Decision: new value — `ForceKilled`. Plus 3 new Task fields.**

Rationale: a "force-killed" task and a "blocked on dependency" task
are operationally different things and need to be visually
separated in the Kanban and queryable in reports without joining
the Dispatcher Event table. The principle "every state change is
reconstructable from logs" (Design 04 + 42 §8) is met by the
Dispatcher Event audit; the Task state is the **headline** view,
not the audit — keep it clear, not blurred. Migration cost is
small (the `Task.workflow_state` Select is **not** a Frappe
Workflow, per the standing rule "never attach a Frappe Workflow to
the Task DocType" — Design 75 §5; adding an 8th value means one
line in the `TASK_STATES` constant, three test pinning updates,
and one idempotent migration patch).

New fields on `Task`:

| Field | Type | Purpose |
|---|---|---|
| `force_killed_by` | Link → User | Operator accountability |
| `force_killed_at` | Datetime | When (correlate with Dispatcher Event + LLM Usage Log) |
| `force_kill_reason` | Small Text | `"operator /stop force mid-skill-execution"` OR `"reconciler sweep — orphaned heartbeat >300s"` |

Disclosed divergence from Hermes: Hermes just kills the job and
leaves the task in whatever state. Friday makes `ForceKilled` a
first-class terminal state because operators need it visible in
the Kanban and queryable in reports.

### Q4 — RQ cancel primitive?
**Decision: `frappe.utils.background_jobs.get_job(job_id).cancel()`**

Rationale: this is the Frappe-canonical RQ cancel primitive; it's
what `send_stop_job_command` (`hermes/gateway/run.py:15292`) maps
to in a row-based, RQ-backed world. The `rq_job_id` field already
exists on inbound `Chat Message` rows per Design 83
(`gateway/service.py:118`); we read it from there. Idempotent — if
the job is already finished or cancelled, the call is a no-op and
the chat reply reports "already done."

### Q5 — How do we know which jobs to cancel (per session)?
**Decision: filter RQ registry by `session_id` derived from the
most recent inbound `Chat Message` for the channel.**

Rationale: Hermes indexes its own in-process session map by session
key. Friday's session identity lives on `Chat Message.session_id`
(plain Data, per `docs/design/05-module-design.md` AS BUILT note).
The cancel loop reads the channel's most recent inbound row,
extracts `session_id`, then queries
`frappe.utils.background_jobs.get_jobs(queue="friday")` filtered
to those whose `kwargs.message.session_id` matches. **No new
state.** The lookup is read-only.

### Q6 — Chat reply routing — channel or DM?
**Decision: reply to the same channel where the operator typed.**

Rationale: the audit belongs where the operator and other viewers
can see it. A DM would split the audit story from the action. The
chat reply IS the operator-visible acknowledgement — it should land
where the action was taken.

### Q7 — Does `ForceKilled` count for billing/cost rollup?
**Decision: yes.**

Rationale: the LLM Usage Log (Design 65d's source of truth for
actual spend) records whatever tokens were burned before the kill.
A force-killed task that burned tokens before being killed is real
spend and should appear in the project rollup exactly like a
Completed task that burned tokens. Hiding it would understate
cost.

### Q8 — Reconciliation on a force-killed Task?
**Decision: the reconciler's existing `Executing`-with-stale-heartbeat
sweep writes `ForceKilled` instead of `Blocked`, populates the 3
fields, and lets the dispatcher's "claim only `Pending`" rule
prevent re-claim (per `tasks/dispatcher.py:175` — verified).**

Rationale: the existing reconciler already detects the
"stuck-in-Executing" condition (Design 61a). The change is one
branch: write `ForceKilled` + populate the 3 fields + set
`force_kill_reason="reconciler sweep — orphaned heartbeat >300s"`.
No new sweep logic — just a different terminal-state choice for
the same condition.

### Q9 — Sandbox cleanup?
**Decision: add `force_killed_at < now - 60s` predicate to
`sandbox/pool.py:cleanup_stale()`.**

Rationale: most containers exit on their own when the RQ worker
drops the job (the worker sends SIGTERM via RQ's lifecycle), but
stragglers exist. The 60-second grace window is defensive — it
covers the case where the worker died before cleanup ran. The
predicate is a strict subset of the existing
`created_at < now - 300s` sweep, so it can't regress the broader
sweep.

### Q10 — Dispatcher Event payload?
**Decision: one event type, `gateway.force_kill`, with the
following payload.**

```python
{
    "session_id": str,                    # the channel's session
    "operator": str,                      # User.name of the operator
    "jobs_cancelled": int,                # count
    "jobs_already_done": int,             # count of no-op cancels
    "tasks_now_forcekilled": list[str],   # Task names
    "request_id": str,                    # correlation id (already on the inbound row)
    "channel_id": str,                    # for the chat reply
}
```

Rationale: enough to reconstruct what happened without joining
other tables. The Lifecycle Trace tab in the Dispatcher Console
(Design 72) renders one row per event.

### Q11 — Migration sequence?
**Decision: post_model_sync patch.**

Rationale: per `project_design-68-agent-role-contract.md` §"PATCHES.TXT
GOTCHA," a patch that **populates a newly-added field** goes in
`[post_model_sync]`. Ours only ADDS fields and a Select option — no
row writes, so the patch is naturally idempotent and safe to leave
in place on roll-back. File: `patches/v1_0/add_task_forcekill_fields.py`.

### Q12 — Order in `frappe/patches.txt`?
**Decision: append at the end of `[post_model_sync]`.**

Rationale: the patch is additive and idempotent; ordering at the
end keeps the migration history clean. No prior patches depend on
this; no future patches depend on it (it's a leaf).

### Q13 — Tests / coverage?
**Decision: ≥85% line coverage on new and modified files.**

Rationale: matches the project's quality bar for the gateway
(`docs/design/11-agent-validation-checklist.md` Slice 9 §"Coverage
target" — critical modules ≥85%). The test files listed in the
proposal §5 cover happy path + every disclosed divergence path
(idempotency, refused-for-non-Operator, sandbox cleanup, etc.).

### Q14 — Live verification?
**Decision: live manual test on Legion before merging, per the
proposal §8 success criteria.**

Rationale: this is the same verification gate as every recent
gateway slice (Designs 82–86 all went through Legion E2E before
merge). The `Friday Operator` role is seeded by
`gateway/after_migrate.py` (per Design 82), so on Legion the
Administrator account is granted it (per
`project_ec2-deployment-2026-06-18.md`); on AWS same.

---

## Implementation surface (file-by-file)

| Path | Change |
|---|---|
| `friday_core/gateway/commands.py` | Add `_handle_stop_force` parallel to `_handle_stop` |
| `friday_core/gateway/interrupt.py` | Add `force_kill_session(session_id, operator) -> dict` |
| `friday_core/gateway/service.py` | Route `/stop force` through the slash dispatcher (D82 hook already in place) |
| `friday_core/observability/emit.py` | Add `gateway.force_kill` event type with Q10 payload |
| `friday_core/tasks/reconciler.py` | Replace the `Executing → Blocked` branch with `Executing → ForceKilled` for the heartbeat-stale path; populate the 3 new fields |
| `friday_core/sandbox/pool.py` | Add `force_killed_at < now - 60s` predicate to `cleanup_stale()` |
| `friday_core/doctype/task/task.json` | Add 3 new fields; add `ForceKilled` to `workflow_state` options |
| `friday_core/constants.py` (or wherever `TASK_STATES` lives) | Add `FORCE_KILLED = "ForceKilled"` |
| `friday_core/patches/v1_0/add_task_forcekill_fields.py` | NEW migration — idempotent, no row writes |
| `frappe/patches.txt` | Register the patch in `[post_model_sync]` |

## Tests

| Path | Tests |
|---|---|
| `friday_core/tests/test_stop_force.py` | NEW — 8 tests per proposal §5 |
| `friday_core/tests/test_reconciler_forcekill.py` | NEW — reconciler marks stale-Executing tasks ForceKilled |
| `friday_core/tests/test_sandbox_pool.py` | EXTEND — `force_killed_at < now - 60s` predicate |
| `friday_core/tests/test_task_constants.py` (or pin wherever TASK_STATES is) | UPDATE — add the 8th state |

## Docs (per `feedback_high-school-readable-docs.md` — same PR)

| Path | Change |
|---|---|
| `docs/rollouts/design-83b-stop-force-2026-06-24.md` | NEW — rollout narrative (9 required sections) |
| `docs/ports/hermes-port-ledger.md` | UPDATE — move §5 row #1 from open-gaps to faithful-ports; cite `hermes/gateway/run.py:15292` + the disclosed Frappe adaptation |
| `docs/project/IMPLEMENTATION_LOG.md` | UPDATE — append dated entry |

---

## Standing rule reaffirmations

- **Migrate gate before push** (`feedback_migrate-gate-before-pr.md`):
  `bench --site friday.localhost migrate` must pass clean before any
  PR.
- **Two-layer docs in same PR** (`feedback_high-school-readable-docs.md`):
  in-code plain-English docstrings + committed rollout narrative.
- **1:1 Hermes port discipline** (`feedback_true-1to1-ports.md`):
  read the actual Hermes source (`gateway/run.py:15292`
  `send_stop_job_command`); classify the disclosed divergences
  (`frappe-adaptation`: RQ cancel primitive + DocType state + 3
  fields; `improvement`: first-class terminal state with
  queryable discriminator; `simplification`: none).
- **Hermes floor, not ceiling** (`feedback_hermes-floor-not-ceiling.md`):
  the `ForceKilled` state is the deliberate surpass — Hermes
  doesn't have a queryable kill signal; we do.

---

## Definition of done

- [ ] All 14 questions above answered (done — this doc)
- [ ] Code lands in a single PR on `feat/design-83b-stop-force`
- [ ] All 14 file changes land in the same PR
- [ ] `bench --site friday.localhost migrate` passes clean (gate)
- [ ] All tests green per proposal §5 + this doc §Tests
- [ ] Live Legion verification per proposal §8 (operator kills a
      long-running `run_turn`; observes all 4 effects)
- [ ] Rollout doc committed with all 9 required sections
- [ ] Ports ledger updated; `/stop force` row moved to faithful-ports
- [ ] IMPLEMENTATION_LOG entry appended
- [ ] Conventional commit message: `feat(gateway): /stop force —
      hard-kill an in-flight turn (Design 83b)`

---

*This design is locked. Implementation may begin.*
