# Design 61 — The Durable, Observable Task Pipeline

**Status:** LOCKED 2026-06-13 (Q4 = dedicated `friday` queue with auto-fallback;
Q3 = strict thresholds; all other Qs as recommended). Implementation lands as
**three PRs**: 61a (reconciler + fail-loud + state-machine fix), 61b (liveness
+ health), 61c (RandomPack durability — stuck-`Received` reconcile + idempotent
`handle_project_created`).

## Why this exists — the plain English

On 2026-06-12 a user planned a project pipeline, and the tasks sat at
**Pending for four hours**. The scheduler was on; workers were up; agent
profiles were configured; LLM keys worked. The assistant watching it
declared "everything operating in harmony" — *twice* — while the loop was
dead. The user, not an internals expert, had to push back: *"what meant
its not working all settings seems fine."* See the Legion validation
transcript for the full incident arc.

What broke was not five unrelated bugs. It was that **Friday's autonomous
loop has no liveness, no self-healing, and no voice**. A single dropped
signal stranded a task forever; nothing told anyone — not the operator,
not the dashboard, not even the AI watching it. That is the disease.
Design 60 shipped the *shape* of the command center (events → tasks →
agents → write-back); this design makes that shape **actually run and
prove it's running**.

## The principle that drives every Q below

> **State is the source of truth; the scheduler is the heartbeat;
> events are only an optimization.**

Today the *message* (`frappe.enqueue` to a worker) is load-bearing — lose
it, lose the task. We flip that: a periodic **reconciler** drives tasks
forward purely from their DB state on every tick. Events make it fast;
the reconciler makes it correct. A lost enqueue heals automatically on
the next tick instead of stranding a task forever.

## Compare with Hermes — what it does, what we deliberately do beyond

Hermes runs an agent **in-process and synchronously** (`run_agent.py`,
`batch_runner.py`): when a run fails, the process returns or throws.
Failure is visible *by construction*; Hermes never has "a task stranded
for 4 hours" because it has no persisted, decoupled task to strand.

Friday went **beyond** Hermes deliberately — persistent `Task` rows, a
cron dispatcher, background workers, dependencies, human gates — because
a governed, team-visible, durable command center is the whole point.
**But it inherited a distributed-systems duty Hermes never had, and
implemented it as if it were still the easy in-process case.** This
design closes that gap. Per the hermes-floor-not-ceiling rule
([[feedback_hermes-floor-not-ceiling]]) the surpass-Hermes axis is named
explicitly: **durability + observability of the autonomous loop**.

## What's already in this branch

`fix/task-pipeline-trigger` (uncommitted, off `origin/main b6ce59a`)
already contains the minimal correctness fixes from the Legion incident:

- single trigger chokepoint at `workflow.on_state_change` → `frappe.enqueue`
  on `default` queue (replaces the dead `publish_realtime`),
- dispatcher actually transitions `Pending` → `Assigned` (the bug the
  Legion report missed; the state change is what fires the hook),
- safe `.get("agent_role_profile")` (Bug 1),
- scan window 100 + budget 5 (Bug 4 starvation),
- updated tests, all green: 15/15 dispatcher + 15/15 workflow,
- rollout doc in the same PR.

**That branch is Phase 0 of this design** and gets folded into 61a's PR.
Nothing about it is throwaway; it's the minimum bar for "the loop runs at
all." 61a builds the durability layer on top.

---

## Q1 — Reconciler: the heartbeat that replaces event load-bearing

*Recommendation:* a single cron job
`friday_core.tasks.reconciler.tick` running **every 60 seconds** (same
cadence as the dispatcher) that scans tasks by state and drives them
forward purely from DB facts:

| Found state | Condition | Action |
|---|---|---|
| `Pending` | dispatchable, deps Completed, project not On Hold | (the existing dispatcher handles — leave it) |
| `Assigned` | `assigned_to_profile` set AND no in-flight job for `<task_name>` AND `assigned_at` > 30s ago | re-enqueue `runner.on_agent_task_assigned` (the original enqueue was lost) |
| `Executing` | `started_at` > **15 minutes** ago AND no in-flight job AND no fresh `last_heartbeat_at` | mark `Blocked` with reason `"runner_lost"`, raise a Failure Issue (D6), War Room post |
| `Blocked(transient)` | `blocked_reason ∈ {oom,timeout,runner_lost}` AND `blocked_at` > 5 minutes ago AND `retry_count` < 3 | transition back to `Pending` (the dispatcher will pick it up again) |
| `Cancelled` / `Completed` / `Review` | terminal | skip |

Two new fields on Task: `assigned_at` (Datetime), `last_heartbeat_at`
(Datetime), `blocked_reason` (Data), `retry_count` (Int, default 0).
The "in-flight job" check uses Frappe's `frappe.utils.background_jobs.get_jobs()`
filtered by `job_name = f"task:{task.name}"` (we set this explicitly when
enqueuing) — see Q4.

**Why a single reconciler and not a "fix-it" per state:** one chokepoint,
one place to look, one test surface. The dispatcher stays exactly what
it is (drives `Pending → Assigned`); the reconciler covers every other
seam where a task could be stuck.

**Edge cases explicitly covered:**
- Scheduler down (the Legion `bench serve` trap): the *liveness view*
  (Q5) reports it; the reconciler can't fix it because it itself doesn't
  run, but Q5's check page flags it loudly.
- Worker down: tasks pile in `Assigned`; the reconciler re-enqueues, but
  the new enqueue also fails to consume — Q5's worker-presence check
  flags it within 60s.
- DB row locked: `FOR UPDATE SKIP LOCKED` everywhere (already used in the
  dispatcher); the reconciler uses the same idiom.
- Concurrent reconciler runs: cron job is single-instance per bench;
  the SQL claim pattern protects against accidental parallel ticks.
- "Permanently stuck" tasks (`retry_count >= 3`): stay Blocked with a
  visible reason and an Issue — humans decide.

## Q2 — Fail-loud: delete every `except: pass`

*Recommendation:* a codebase sweep against this rule:

> Any exception that crosses a `tasks/` or `surfaces/randompack` boundary
> must produce: (a) a `frappe.log_error` entry with the task or event
> ref, (b) a Friday `Issue` (the tracker exists), and (c) a War Room
> post. Three signals — DB, ticket, chat — none silent.

The current code has the right *aspirations* but inconsistent practice.
Confirmed offenders (read 2026-06-13):
- `surfaces/randompack.py:248` — `_warroom`'s broad `except` is correct
  (visibility must never break processing) → **keep**, but log the
  swallowed exception type at WARN level.
- `integrations/randompack_bridge.py:83` — bridge `except` swallows
  silently → **add log + Issue**, keep "never raise into save."
- `tasks/dispatcher.py:_load_permitted_skills` — the fixed `.get()` is
  already the right pattern; ensure the existing `except Exception` for
  the role-profile fetch logs.
- `tasks/runner.py:on_agent_task_assigned` — already logs + raises Issue
  on crash → **keep, this is the model**.

The rule is: `except:` is fine; **silent** `except:` is not. Either log
*and* raise an Issue, or re-raise.

**Edge cases:**
- A failure in the fail-loud machinery itself (e.g. Raven down when
  posting the War Room signal): `_warroom` already savepoint-guards and
  degrades — that pattern stays.
- Storm: 100 tasks fail at once → 100 War Room posts. Rate-limit by
  bucketing identical Issue titles within a 60s window; one summary
  post when the bucket flushes. Disclosed simplification: no exponential
  bucket, just a window — proportionate to single-tenant.

## Q3 — Liveness/health: a real signal the operator and the AI can read

*Recommendation:* one whitelisted method
`friday_core.health.pipeline_health()` returning a dict, plus a Desk
page that renders it. Fields:

```python
{
  "scheduler_last_tick_at": "2026-06-13 14:32:01",   # via Scheduled Job Log
  "dispatcher_last_tick_at": "2026-06-13 14:32:01",
  "reconciler_last_tick_at": "2026-06-13 14:32:01",
  "workers": {                                        # via get_queues()
    "default": {"present": True, "depth": 0},
    "friday":  {"present": False, "depth": 12},      # ← the bench-serve trap
  },
  "tasks_by_state": {"Pending": 3, "Assigned": 0,
                     "Executing": 2, "Blocked": 0,
                     "Review": 1, "Completed": 482},
  "stuck": {                                          # what the reconciler will act on
    "assigned_orphaned": 0,
    "executing_stale": 0,
    "transient_blocked_pending_retry": 0,
  },
  "randompack": {                                     # 61c
    "events_received_pending": 0,
    "events_failed_retriable": 0,
  },
  "raven": {"installed": True, "war_room_channel_id": "CH-..."},
  "issues_open_friday": 2,
  "verdict": "ok" | "degraded" | "down",              # derived
}
```

`verdict` is computed:
- `down` if no scheduler tick in 5 min, or `friday` queue worker absent,
  or `stuck.*` non-zero for > 2 ticks.
- `degraded` if any `*_pending` > 10 or `issues_open_friday` > 5.
- `ok` otherwise.

**The Desk page** (`Pipeline Health`) renders this with traffic-light
colours and a "last refreshed" timestamp. Auto-refresh every 30s. The
operator opening this page gets the same answer as the AI calling
`pipeline_health()` — **no more "all settings seem fine."**

**Edge cases:**
- The health check itself fails to run (DB down, etc.): the page shows
  a red banner "health check failed" with the exception — fail-loud
  even about fail-loud.
- A reconciler that just started has no `*_last_tick_at` yet: shows
  "never (waiting for first tick)" not "down".

## Q4 — The canonical queue: `friday` (named) or `default` (stock)?

*Recommendation:* **`friday` queue, but with the Procfile/config
contract made part of the bench setup, NOT optional, NOT silent.**

Reasoning:
- Stock `default` queue is what every Frappe bench has; using it
  guarantees the loop runs on any clone with no extra setup. This is
  what `fix/task-pipeline-trigger` did, and what Phase 0 ships with.
- BUT Friday's task runner can take **minutes** per task (agentic
  runs, sandbox executions, LLM round-trips). Putting that on `default`
  means it competes with email sends, link-count updates, Frappe's own
  housekeeping — and one slow task blocks unrelated Frappe jobs.
- Dedicated `friday` queue isolates agent work, lets us tune its
  timeout (600s in the RandomPack client; same for the runner), and
  matches what `surfaces/randompack.py:95` and
  `integrations/randompack_client.py:91` already do (those enqueues
  *already* target `friday`).

So the decision is **`friday`**, made *robust*:
1. `common_site_config.json` registers it (script in 61b's PR adds it
   idempotently to existing benches).
2. `Procfile` adds the worker line.
3. `health.pipeline_health()` (Q3) reports `friday` worker presence;
   `verdict = down` when missing — so a forgotten setup step is a red
   banner within 60s, not silent stalls.
4. `RUNBOOK-LEGION.md` updated with the one-time setup step.
5. **Fallback:** if `friday` queue worker is absent for > 5 minutes,
   the reconciler logs a CRITICAL Issue *and* the dispatcher
   automatically routes new enqueues to `default` until the worker
   returns. (Disclosed graceful-degrade; the goal is the loop never
   stops moving, but the user knows.)

**This reverses one decision from `fix/task-pipeline-trigger`** (which
chose `default`). That branch was the correct *minimum*; this is the
correct *target*. The reversal is named here so it's not a silent drift.

## Q5 — Idempotent claim/lease for the runner

*Recommendation:* before the runner does any work, it
**check-and-sets** `executing_token` on the Task row:

```python
token = frappe.generate_hash(length=16)
claimed = frappe.db.sql(
    """
    UPDATE `tabTask`
    SET workflow_state='Executing', executing_token=%s,
        started_at=now(), last_heartbeat_at=now()
    WHERE name=%s AND workflow_state='Assigned'
      AND (executing_token IS NULL OR executing_token='')
    """,
    (token, task_name),
)
if not claimed: return   # someone else got it
```

The runner periodically updates `last_heartbeat_at` during long
operations (every 30s during agentic turns; every skill boundary for
mechanical). The reconciler's "executing_stale" check looks at
`last_heartbeat_at`, not `started_at`, so genuinely-running long tasks
are not killed.

**Why this matters:** with the Q1 reconciler re-enqueuing lost-message
tasks, we move from "at-most-once-and-hope" to **at-least-once with
idempotent execution** — i.e. exactly-once effect, the only durable
shape that actually works. Without this, a re-enqueued task could
run twice and double-write deliverables. This is a *correctness* fix,
not a perf tweak.

**Edge cases:**
- Heartbeat update fails (DB blip): the runner catches and continues
  the work — a missed heartbeat just means the reconciler might
  declare the task stale early. Add a one-tick (60s) grace before the
  "executing_stale" check fires. (Better: use NOW() in the SQL so a
  successful re-heartbeat is monotonic.)
- Token collision: 16 hex chars = 64 bits; collision negligible.

## Q6 — Readiness preflight: visible `blocked_reason` instead of silent Pending

*Recommendation:* `tasks.dispatcher._match_profiles` already returns
empty when no profile matches. Today the task silently stays Pending.
Change: when no eligible profile is found, write a structured
`blocked_reason` to the Task — e.g.
`no_profile_for_skills:create-brand-direction,get-brand-brief` — and
keep the row in Pending. The Desk Task list (Q9) and the Pipeline Health
(Q3) surface tasks with `blocked_reason` set. Additional preflight
reasons:

- `profile_has_no_llm_provider` (the Legion trap)
- `provider_disabled`
- `skill_not_installed`
- `dependency_failed` (an upstream task is Blocked)

The reconciler clears `blocked_reason` once the underlying condition
changes (e.g. an LLM provider gets assigned). This is the user-facing
half of fail-loud: **agents don't fail silently, and tasks don't sit
silently** — every parked row carries a reason a human can read in one
glance.

## Q7 — RandomPack durability (folds in 60a/60b robustness gaps found 2026-06-13)

Two production gaps in the already-merged RandomPack flow, found while
auditing for the contract conformance:

**(a) Stuck `RandomPack Event` reconcile.** Receiver acks 200, inserts
the event row as `Received`, then enqueues `process_event` on the
`friday` queue. If the queue worker is down (the central failure mode
this design addresses), the event sits `Received` forever — backend
sees `Delivered` but Friday never processed it.

*Recommendation:* the same Q1 reconciler also sweeps:
- `RandomPack Event` in `Received` with `creation` > 60s ago → re-enqueue
  `process_event`.
- `RandomPack Event` in `Failed` with `creation` > 5 min ago AND
  `retry_count` < 3 → re-enqueue (need to add `retry_count` to the
  DocType).

Idempotency: `process_event` already short-circuits on
`status == "Processed"` (`surfaces/randompack.py:138`), so re-enqueue
of a succeeded row is a no-op.

**(b) Non-idempotent `handle_project_created`.** Today
`handle_project_created` reuses an existing Project row (good), but
then unconditionally calls `instantiate_pipeline(project, ref, brief)`
— so a replay of `project.created` creates a **second full set of
9 tasks** under the same project. **This matches the three near-identical
"Legion Coffee" projects observed in the bench database.**

*Recommendation:* guard pipeline instantiation:

```python
existing = frappe.db.count("Task",
    {"project": project, "backend_ref": ("like", "stage_%")})
if existing == 0:
    tasks = instantiate_pipeline(project, ref, brief)
```

Apply the same idempotency rule to every other state-mutating handler:
`handle_refinement_requested` is already keyed by `f"refinement_r{round_n}"`
in `backend_ref` — verify uniqueness with a guard.

**This unblocks the contract's replay/test semantics.** Until 61c lands,
a replayed `project.created` is unsafe.

## Q8 — Scope boundary

In scope for Design 61:
- the reconciler, fail-loud, liveness/health, the canonical-queue
  decision + fallback, idempotent runner lease, blocked-reason
  preflight, RandomPack durability;
- folding in `fix/task-pipeline-trigger` (Phase 0) into 61a's PR;
- updating the rollout doc the fix branch already drafted to cover the
  full Design 61 story.

Explicitly OUT of scope (deliberate, disclosed):
- the toolbox / read-tool / MCP — that's a separate design;
- agents reporting back to Raven / multi-agent War Room — design 62;
- the project console page — design 65;
- provider parity, model discovery, setup wizard — designs 63 + 64.

This is the foundation. Nothing else functions reliably without it,
and trying to bundle it loses test discipline.

## What lands on disk — three PRs

**61a — durability core**
- Folds in `fix/task-pipeline-trigger` (the existing fix, rebased onto a
  Phase-0 commit).
- New: `tasks/reconciler.py` with the Q1 sweep, registered in
  `hooks.scheduler_events["cron"]["* * * * *"]`.
- New fields on Task: `assigned_at`, `last_heartbeat_at`,
  `executing_token`, `blocked_reason`, `retry_count`.
- Patches: existing pending rows get `assigned_at = modified`.
- Runner: claim-and-set lease (Q5) + periodic heartbeat.
- Fail-loud sweep (Q2) of `tasks/`, `surfaces/randompack.py`,
  `integrations/randompack_bridge.py`.
- Tests: stuck-Assigned reconcile, stuck-Executing reconcile,
  Blocked-transient retry, lease idempotency, fail-loud emits
  Issue + log + War Room.
- Rollout doc: `docs/rollouts/design-61a-durable-pipeline.md`.

**61b — liveness + observability**
- New: `friday_core/health/` with `pipeline_health()` whitelisted method.
- New Desk page: "Pipeline Health" rendering the dict, auto-refresh 30s.
- `Procfile` + `common_site_config.json` migration: register `friday`
  queue (Q4); idempotent.
- `RUNBOOK-LEGION.md` updated with the queue setup step.
- Tests: health snapshot under each verdict (ok/degraded/down),
  worker-absent detection.
- Rollout doc: `docs/rollouts/design-61b-pipeline-observability.md`.

**61c — RandomPack durability**
- New: `RandomPack Event.retry_count` field + patch.
- `surfaces/randompack.handle_project_created` made idempotent (Q7b).
- Reconciler extended with the RandomPack sweep (Q7a).
- Tests: replay of `project.created` doesn't double-plan; stuck-Received
  event re-enqueues; retry budget caps.
- Rollout doc: `docs/rollouts/design-61c-randompack-durability.md`.

## How we'll know it works — live proof (not just unit tests)

For 61a: a deliberately-killed worker mid-execution → restart worker →
the reconciler recovers the orphan within 90s; the task completes; the
operator sees one "runner recovered" Issue and one War Room post.

For 61b: stop the `friday` worker → within 60s the Pipeline Health page
goes red with `friday queue: missing worker`; a banner Issue is filed.
Restart the worker → green within 60s, Issue auto-resolves.

For 61c: replay `project.created` three times via the contract's
`outbox.emit(...)` test path → exactly 9 tasks created (not 27); the
3rd attempt is a clean no-op.

## Risks called out

- The reconciler is itself a single point of failure: if its cron job
  fails to schedule, we lose the heartbeat. Mitigation: `pipeline_health`
  reports `reconciler_last_tick_at`, and `verdict=down` if stale.
- Re-enqueuing on lost messages risks duplicate execution; mitigated by
  the Q5 lease. Tests must include the duplicate-enqueue race
  explicitly — not just the "happy reconcile" path.
- The fail-loud sweep (Q2) might generate Issue noise during initial
  bedding-in; the bucket-and-summary rule (Q2 edge cases) bounds this.
- Changing the queue from `default` (Phase 0) to `friday` (target)
  introduces one config migration; the migration is idempotent and
  the runbook covers it.

## Locks needed

Q1 reconciler tick interval (60s) · Q2 the fail-loud rule + the 60s
storm window · Q3 the verdict thresholds · Q4 the `friday`-queue
decision (and the `default` fallback) · Q5 the lease shape · Q6 the
preflight reason taxonomy · Q7a the Received-event reconcile cadence
(60s) and retry budget (3) · Q7b the pipeline-idempotency guard ·
Q8 the scope boundary.
