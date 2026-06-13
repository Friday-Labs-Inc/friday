# Design 61a — the autonomous task pipeline now runs, and heals itself when it doesn't (2026-06-13)

## The one-sentence version

Before today the agent loop was *event load-bearing* — one lost message stranded
a task forever, and a customer pipeline sat dead for four hours while the AI
watching it declared "everything operating in harmony." This PR makes the
pipeline run, then layers on a watchdog that drives stuck tasks forward purely
from DB state so a single dropped signal can never silently strand work again.

## Two layers in one PR

**Phase 0 — make it run** (the original `fix/task-pipeline-trigger` branch,
folded in here). Five surgical fixes in `tasks/`:

- `workflow.on_state_change` enqueues the runner (the dead `publish_realtime`
  only reached browser clients, so backend workers never got the signal),
- the dispatcher transitions Pending → Assigned (not just sets a profile);
  the state change is what fires the hook — the decisive bug the original
  bug report missed,
- safe `.get("agent_role_profile")` so a missing optional field no longer
  silently kills the dispatcher tick with AttributeError,
- the dispatcher scans 100 candidates but caps dispatch at 5 per tick, so
  parked tasks (unmet deps, On-Hold projects) cannot starve ready ones,
- docstrings updated to the resolved trigger decision.

**Durability layer — heal the seams** (Design 61 proper, Q1+Q5+Q7+Q4):

- A new **`tasks/reconciler.py`** wired into the 60-second cron. Four sweeps,
  each isolated so one failure cannot kill the others:
  - **Assigned orphans** — a task Assigned > 30s with no in-flight job means
    the original enqueue was lost. Re-enqueue (idempotent on the runner side
    via the lease, below).
  - **Executing stale** — Executing > 15 min with no fresh heartbeat AND no
    in-flight job means the runner died mid-execution. Block with reason
    `runner_lost`, file a Failure Issue (visible to humans), post to the War
    Room. Long-but-healthy agentic turns keep heartbeating so this cannot
    kill them.
  - **Transient blocked retry** — Blocked with `oom`/`timeout`/`runner_lost`,
    under retry budget (3), > 5 min old → re-Pend cleanly. Semantic blocks
    (`dependency_failed`, `no_profile_for_skills:*`) need a human and are
    NOT retried.
  - **RandomPack events** (Q7a) — `Received` events > 60s old or `Failed`
    events > 5 min old (still under retry budget) re-enqueue
    `process_event`. The receiver acks 200 the moment it persists; if the
    `friday` worker was down at that moment the event sat forever. Not any
    more.

- A new **idempotent claim-and-set lease** in the runner (Q5). Atomically
  transitions Assigned → Executing AND stamps a 16-hex `executing_token`. A
  duplicate trigger (the reconciler re-fires a lost enqueue belatedly) sees
  the token and exits cleanly. At-least-once-trigger / exactly-once-effect —
  no double-execution of the same task.

- A periodic **heartbeat** during real work (`_heartbeat` at every skill
  boundary for mechanical; called explicitly during agentic runs in 61b).
  The reconciler reads `last_heartbeat_at`, not `started_at`, so the
  executing-stale sweep distinguishes "genuinely running" from "runner
  died."

- **Q4 — canonical queue is `friday`.** Phase 0 used `default` as the
  minimum viable choice; this PR moves the runner enqueue to `friday` to
  match what the already-merged RandomPack code uses
  (`surfaces/randompack.py:95`, `randompack_client.py:91`), and to
  isolate minutes-long agent work from Frappe's housekeeping queue.
  The auto-fallback to `default` after 5 min of missing worker, and the
  bench setup script, land in 61b.

- **Q7b — `handle_project_created` is observably idempotent.** The
  underlying `instantiate_pipeline` already deduped per-task, but a replay
  silently returned "0 tasks created" looking like a successful plan. Now
  it logs explicitly as a no-op replay in the War Room.

## Why we know it works

`test_task_dispatcher.py` (15 tests) + `test_task_workflow.py` (15 tests) +
**new** `test_task_reconciler.py` (12 tests) + the surface and command-center
suites (45 tests) — **87/87 green** headless. New coverage explicitly hits:

- the reconciler re-enqueues Assigned-orphans and uses the in-flight job set
  to avoid double-firing,
- executing-stale Block path raises the Issue and posts to the War Room,
- transient-Blocked retry respects the 3-attempt cap and resets the lease,
- RandomPack `Received`/`Failed` events re-enqueue under their grace windows,
- one phase failing does NOT abort the rest of the tick (the heartbeat is
  partial-tolerant by design).

## What you would have seen

You create a project. Friday plans it into Tasks. The War Room shows the tasks
sitting at **Pending** forever — hours, not seconds — even though the scheduler,
the workers, and the agent profiles are all configured correctly. Nothing in the
Error Log explains why. It just… stops.

## Why it was stuck (the chain of failures)

A task has to travel: **Pending → Assigned → Executing → Review/Completed**.
A cron job (`dispatcher.tick`, every 60s) does the first hop; a background
runner does the rest. Four things broke that journey:

1. **The dispatcher crashed silently on every tick.** When it tried to match a
   task to an agent, it read `profile.agent_role_profile` as a plain attribute.
   That field isn't a guaranteed column on Agent Profile, so Python raised
   `AttributeError`. Because the crash happened deep inside a scheduler job, it
   was swallowed with no Error Log — the only symptom was tasks never moving.

2. **The dispatcher never actually changed the task's state.** It set the
   agent profile and saved, but left `workflow_state` at **Pending**. The
   state-machine hook only reacts to a *state change*, so it never fired. The
   task now had an agent attached but was still officially Pending — limbo.
   (This bug was not in the original report; reading the state machine surfaced
   it. With our chosen trigger it was the decisive blocker.)

3. **The runner was never told to start.** The dispatcher announced the
   assignment with `publish_realtime` — but that channel only reaches *browser*
   windows, never a backend worker. The runner's own code even documented this
   ("currently a no-op… dormant"). So the start signal went into the void.

4. **Old blocked tasks crowded out new ready ones.** The dispatcher fetched
   only 5 tasks per tick. If 5 older tasks were parked (waiting on dependencies,
   or in an On-Hold project), the tick burned its whole look at tasks it
   couldn't run and never reached the ready ones behind them. Permanent
   starvation.

## What we changed

The fix is built around one decision (locked 2026-06-13): **there is a single
place that starts the runner — the state-machine hook.**

- **One trigger, done right.** `workflow.on_state_change` now `frappe.enqueue`s
  the runner as a real background (RQ) job on the **`default`** queue when a
  task enters **Assigned**, deferred until the save commits. This replaces the
  dead `publish_realtime`. One chokepoint means it fires for *any* path into
  Assigned (the dispatcher today, manual reassignment tomorrow) and can't
  double-fire. *(fixes #3, and the wrong-queue variant)*

- **The dispatcher now transitions the state.** It sets the profile **and**
  moves the task to **Assigned** in one save — which is exactly what fires the
  hook above. *(fixes #2)*

- **Safe field access.** `profile.get("agent_role_profile")` instead of the
  attribute read, so a missing field returns `None` instead of crashing the
  tick. *(fixes #1)*

- **Scan wide, spend a budget.** The tick now scans up to 100 candidates but
  still hands off at most 5 ready tasks, so parked tasks can never block ready
  ones. *(fixes #4)*

## How we know it works

`test_task_dispatcher.py` (15 tests) and `test_task_workflow.py` (15 tests)
pass headless. New/changed coverage:

- the dispatcher moves a matched task to **Assigned** (not just sets a profile);
- the dispatcher does **not** emit the trigger itself (no double-run);
- the hook **enqueues the runner** on the `default` queue on Pending→Assigned,
  and **not** when the profile is unchanged;
- a starvation regression: 10 parked tasks ahead of 3 ready ones — all 3 ready
  ones still get dispatched; and the per-tick budget caps at 5.

> Note: these are fast, mocked unit tests. The full live loop (a real task
> flowing Pending → Completed on a worker) still needs a verification pass on a
> bench with `bench worker` + `bench schedule` running — see "Still open".

## Still open (lands in 61b / 61c / other designs)

- **Pipeline Health page + bench setup script** (61b). The whitelisted
  `pipeline_health()` method, the Desk page that renders it (auto-refresh
  30s, strict thresholds per Q3), and the `Procfile` +
  `common_site_config.json` registration of the `friday` queue with the
  auto-fallback to `default` after 5 min of missing worker (Q4 fallback).
  These make the durability layer *visible* — verdicts: `ok` / `degraded` /
  `down`, with the worker-absent check killing the "bench serve trap" for
  good.
- **Agentic-run heartbeat** (61b). Mechanical runs heartbeat at every skill
  boundary here; agentic runs need an explicit periodic heartbeat during
  the ReAct loop (every 30s). Trivial wiring, but lands with the rest of
  the observability layer.
- **`get-brand-direction` read skill / generic governed-DocType read tool**
  — separate design (the toolbox), tracked in
  `project_v02-gap-and-vision`.
- **Live end-to-end proof on a real bench** — run a project end-to-end with
  workers + scheduler up and watch it complete. The autonomous path wasn't
  exercised before the Design 60 merge; the live proof for the durability
  guarantees (kill a worker mid-execution, replay a `project.created`
  event three times) is on the runbook.
