# Pipeline health: measure the scheduler tick correctly — 2026-06-14

## One sentence

Pipeline health reported **down** even though the scheduler was perfectly
healthy, because it measured scheduler liveness from the wrong place — this
points it at the signal Frappe actually updates on every tick.

## What was wrong

The Desk's **Verify & Finish** step (and the live console health strip) read
`pipeline_health()`. Its verdict goes `down` if the scheduler hasn't "ticked"
in 5 minutes. To find the last tick, it looked at the newest **Scheduled Job
Log** row.

The catch: Frappe only writes a Scheduled Job Log row for job types that have
`create_log = 1`. **Most** scheduled jobs — including the every-minute ones like
the reconciler and dispatcher — run with `create_log = 0` and write **no log
row**; they only stamp `last_execution` on their Scheduled Job Type.

So the log is sparse. On a live bench we saw the reconciler firing every ~50
seconds (`last_execution` fresh) while the newest Scheduled Job Log row was ~19
minutes old. Health read the 19-minute figure, decided the scheduler was dead,
and forced `down` — blocking the setup wizard's "Verify & complete" for no real
reason.

## The fix

Measure the tick from `max(Scheduled Job Type.last_execution)` across enabled
(`stopped = 0`) job types. Frappe stamps `last_execution` on **every** fire,
logged or not, so this is the true "is the scheduler alive?" signal.

Two implementation details worth noting:

- We use a `Max(last_execution)` aggregate via the query builder. `Max` ignores
  job types that have never run (NULL `last_execution`).
- We deliberately do **not** filter with `("is", "set")`. Frappe compiles that
  to `last_execution != ''`, and **Postgres rejects comparing a timestamp
  column to an empty string** (MariaDB quietly tolerates it). This is the same
  MariaDB-vs-Postgres trap that bit the Number Card and the patch ordering
  earlier today — the aggregate sidesteps it entirely.

This is a sibling of the earlier 61b fix that stopped using `get_jobs()` for
worker presence (it missed idle workers). Same lesson: measure health from the
signal Frappe actually maintains, not a convenient-looking proxy.

## Why the tests didn't catch it

Every existing pipeline-health test **mocks `_scheduler_tick_age` away** and
feeds the verdict a number directly — so the function's real query was never
exercised. The new test is real-DB: it asserts `_scheduler_tick_age()` agrees
with `max(Scheduled Job Type.last_execution)`, which would fail against the old
Scheduled-Job-Log implementation. (Mocks aren't acceptance — re-prove on the
real bench.)

## Verification (local bench, Postgres)

- Real verdict before: `down`, `scheduler_tick_age_seconds: 1153` (while the
  reconciler's `last_execution` was 49s old).
- Real verdict after: **`ok`**, `scheduler_tick_age_seconds: 155`, both workers
  present, no stuck tasks.
- `test_pipeline_health` — 9 tests green (8 existing + 1 new real-DB tick test).
- `bench migrate` clean (exit 0); health still `ok` post-migrate.

## Comparison with Hermes

Not a port. Hermes (a single Python process) has no Frappe scheduler / Scheduled
Job Type model; this is a Frappe-platform health probe specific to Friday's
durable pipeline.
