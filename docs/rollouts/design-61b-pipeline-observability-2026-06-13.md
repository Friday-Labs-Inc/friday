# Design 61b — Pipeline Health: the autonomous loop now has a voice (2026-06-13)

## The one-sentence version

Before today the only way to tell whether Friday's autonomous loop was alive
was to plan a project and wait — for four hours, as Legion proved. This PR
gives the operator (and the AI watching them work) a single colour-coded
answer: **`ok` / `degraded` / `down`**, refreshed every minute, derived from
the same data the reconciler acts on.

## What landed

**`friday_core/health/pipeline_health.py`** — a whitelisted method that
returns one structured dict:

```python
{
  "verdict": "ok" | "degraded" | "down",
  "scheduler_tick_age_seconds": 30,
  "workers": {
    "default": {"present": True, "inflight": 0},
    "friday":  {"present": True, "inflight": 0},
  },
  "tasks_by_state": {"Pending": 3, "Assigned": 0, "Executing": 2, "Blocked": 0, "Review": 1, "Completed": 482, "Cancelled": 0},
  "stuck": {"assigned_orphaned": 0, "executing_stale": 0, "transient_blocked_pending_retry": 0},
  "randompack": {"events_received_pending": 0, "events_failed_retriable": 0},
  "open_issues": 0,
  "thresholds": { ... },
}
```

The verdict is the headline. **Strict thresholds** (Q3 LOCKED):
- `down` if no scheduler tick in 5 min OR `friday` worker absent OR any
  stuck.* > 0 (the reconciler is healing it, but the operator should know).
- `degraded` if pending Tasks > 10 OR open Friday Issues > 5.
- `ok` otherwise.

**Fail-loud envelope.** If the health check itself errors (DB blip, Redis
down, whatever), the response is `{"verdict": "down", "error": "..."}`
— never silently `ok`. The disease this design treats is reassurance
without evidence; the health endpoint refuses to be the place that
disease re-enters.

**`friday_core/health/after_migrate.py`** — runs every migrate, idempotent
+ atomic, to register the `friday` queue in `common_site_config.json` so
a fresh clone of the repo cannot lose the runner trigger to an
"unknown queue" error. This kills the second-most-common silent-failure
mode on bring-up. The Procfile registration of
`bench worker --queue friday` is the one remaining manual step in the
runbook (we can't safely modify the bench-level Procfile from inside the
app), and the health endpoint reports a missing worker as `down` within
60s — so a forgotten Procfile line is loud, not silent.

**Agentic-loop heartbeat.** `run_turn` now accepts an optional
`heartbeat` callback. The task runner passes a closure that refreshes
`last_heartbeat_at` on every ReAct iteration. Combined with the
mechanical heartbeat at every skill boundary (landed in 61a), this means
a genuinely-running agentic turn — even one that takes 10 minutes
through 30 LLM round-trips — can NEVER be killed by the executing-stale
sweep. Only truly silent workers trip it.

## Why we know it works

**70/70 green** headless across the touched and adjacent surface:

- **8 new `test_pipeline_health`** — verdict matrix (ok / down-on-missing-
  worker / down-on-no-tick / degraded-on-pending / degraded-on-issues),
  stuck-block numbers, RandomPack-block numbers, fail-loud envelope.
- **4 new `test_health_after_migrate`** — adds `friday` when absent,
  preserves other workers, idempotent on second run, skips silently
  when config file missing (test/sandbox benches).
- 12 reconciler · 15 dispatcher · 15 workflow · 20 command-center ·
  **16 react_loop** (confirms the heartbeat parameter didn't break the
  ReAct loop) · all green.

`test_chat_flow` failures are pre-existing site-bound errors
(`object is not bound`) — they need `bench run-tests`, not headless;
unaffected by this PR.

## What's still open

- **The Pipeline Health Desk page.** The endpoint is whitelisted and the
  data is real — but rendering it as an auto-refreshing Frappe Page with
  traffic-light colours lands separately so the visual polish doesn't
  block the data layer. Operators can hit the method directly today via
  `/api/method/friday.friday_core.health.pipeline_health.pipeline_health`
  (returns the same dict).
- **The 5-min auto-fallback from `friday` → `default` queue** for the case
  where a registered queue's worker stays absent. The endpoint *reports*
  the absent worker (verdict `down`); the automatic re-routing lands in a
  follow-up so we can decide the runbook story first (is "degrade
  silently" actually what we want, or does an operator alert beat it?).
- Toolbox / 62 report-back / 63 providers / 64 wizard / 65 project console
  — separate designs.

## Test plan

- [ ] `bench migrate` on a fresh clone → `common_site_config.json` gains
  `workers.friday = {"timeout": 600}` automatically.
- [ ] `curl /api/method/friday.friday_core.health.pipeline_health.pipeline_health`
  → returns the dict above with `verdict: "ok"` when everything is up.
- [ ] Stop the `friday` worker → within 60s the verdict goes `down` with
  `workers.friday.present = False`.
- [ ] Restart the worker → verdict returns to `ok`.
- [ ] Stop the scheduler → verdict goes `down` with
  `scheduler_tick_age_seconds > 300`.
- [ ] Send a 5-minute agentic task → heartbeat lands per ReAct iteration;
  the executing-stale sweep never blocks it.
