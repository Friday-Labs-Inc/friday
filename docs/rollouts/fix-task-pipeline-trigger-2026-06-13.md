# Fix — the autonomous task pipeline now actually runs (2026-06-13)

## The one-sentence version

Tasks the dispatcher assigned to an agent were getting stuck and never ran;
three bugs in the dispatcher (plus one in the trigger wiring) meant the
"agent picks up a task and does it" loop — the heart of the Design 60 command
center — was broken end to end. This fix makes the loop run.

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

## Still open (not in this fix)

- **Live end-to-end proof.** Run a project on a bench with workers + scheduler
  up and watch one task complete. The autonomous path wasn't exercised before
  the Design 60 merge; it should be now.
- **`get-brand-direction` skill.** The agent can *save* Brand Direction records
  but has no skill to *read* them back in chat, so it regenerates them. A small
  feature gap — tracked separately.
- **Duplicate-project detection** in the `plan-project` skill (the bench made
  three near-identical "Legion Coffee" projects). Separate cleanup.
- **SQL-level readiness filter.** The scan/budget split fixes the starvation
  symptom; pushing the "is ready" check into the query (or a `next_retry_at`
  column) would be the cleaner long-term shape if the parked backlog grows large.
