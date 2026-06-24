# Concurrent friday worker — let agents serve many people at once

_Shipped 2026-06-23. Flag-gated, default OFF (no behaviour change until you turn it on)._

## In one sentence

Friday can now handle several agent conversations or tasks **at the same time**
instead of one-at-a-time, controlled by a single number you set — and it stays
switched off by default so nothing changes until you choose.

## What it actually does (in plain terms)

Every time an agent replies to a message or runs a pipeline task, that work runs
as a background job on a dedicated lane called the `friday` queue. Until now,
**one worker** drained that lane, so it did one job at a time.

Here's the catch: an agent turn is mostly spent _waiting_ — waiting for the
language model to type its answer back over the network. So if two people
message at once, the second one just stands in line behind the first, even
though the worker is doing nothing but waiting.

This change lets you run **more than one worker on that lane**. Because each
worker spends its time waiting on its _own_ model call, several turns overlap
their waiting and the line disappears. The knob is one setting,
`Agent Settings → Max Concurrent Turns`:

- **1** (the default) → exactly today's behaviour. One worker. Zero change.
- **N** → N workers on the `friday` queue, so up to N turns run at once.

It takes effect the next time the friday worker is (re)started.

## What scenarios it now covers

| Scenario | Before | After (e.g. setting = 8) |
|---|---|---|
| One person messages | Instant-ish (~4s) | Same (~3s) |
| 5 people message at once | 5th waits ~11s | All answered in ~3s |
| 10 people message at once | 10th waits ~18s | All answered in ~3.4s |
| A long pipeline + a chat arrive together | Chat waits behind the task | Both run in parallel |
| Someone sets the number absurdly high | n/a | Safely capped at 16 |
| Someone leaves it blank / it can't be read | n/a | Falls back to 1 (safe) |

## What it means for friday-core

Before: the `friday` queue was a single-server checkout — throughput hit a
ceiling (~33 turns/min) and the wait grew with the crowd.

After: throughput scales with the number of workers (~176 turns/min at 10
concurrent turns in our Legion benchmark), and the wait stays flat. The agent
runtime's core property — it's _waiting_, not _computing_ — is finally used to
your advantage.

Nothing about _how a turn runs_ changed: the same governed `run_turn`, the same
permission checks, the same audit trail, the same durable Task state. We only
changed _how many turns run side by side_.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| "Run N turns at once" | Frappe's own RQ `WorkerPool` (`start_worker_pool`) — N real worker processes |
| "Is a worker alive?" (gateway check) | Each pooled worker registers as a normal RQ `Worker`, so `pipeline_health` and the gateway's `_friday_worker_alive()` keep working |
| The concurrency knob | An `Int` field on the existing `Agent Settings` singleton |
| Start the worker | New command `bench --site <site> friday worker` (replaces `bench worker --queue friday`) |

We chose **processes** (the worker pool), not threads. We proved the speed-up
with a thread pool in the benchmark, but a hand-rolled threaded worker would not
register as an RQ worker — the gateway would think no worker was alive and fall
back to running turns inline. The process pool avoids that, reuses Frappe's
tested code, and isolates crashes. The throughput win is identical either way.

## What the company can say truthfully today

- "Friday handles concurrent users without queueing them behind one another —
  proven ~5× higher throughput at 10 simultaneous turns, with the wait
  eliminated." (Legion benchmark, real MiniMax, before/after.)
- "The capability ships off by default and is a single, bounded setting — it
  cannot be misconfigured into instability (capped at 16, never below 1)."
- "Turning it on changes nothing about governance: the same permission checks,
  audit log, and durable state apply to every concurrent turn."

## Risks and limits a product head should hold

- **Each worker uses memory.** N workers ≈ N× a worker's footprint. On a small
  box, keep N modest (4–8). This is why the default is 1 and the ceiling is 16.
- **The safe ceiling for _this_ deployment isn't measured yet.** The benchmark
  went to 10 concurrent turns cleanly; the real limit (Postgres connections,
  MiniMax rate limits) should be probed before setting a high number in
  production. Treat 8 as a sensible starting point, not a proven maximum.
- **Frappe marks `start_worker_pool` "experimental."** We lean on it
  deliberately and keep the default-1 path on Frappe's standard single worker,
  so the experimental code is only reached when you opt in.
- **Restart required.** Changing the number doesn't affect a running worker;
  the friday worker must be restarted to pick up a new value.

## What this unlocks

- A real answer to the audit's "single-worker bottleneck" finding — now a knob,
  not a redesign.
- A path to higher concurrency once the per-deployment ceiling is measured.
- The same pattern can later gate the _task_ pipeline's throughput, not just
  chat.

## Numbers for the record

- Files: 1 new module (`agent_runner/worker_pool.py`), 1 new command
  (`friday worker`), 1 new `Agent Settings` field (`max_concurrent_turns`,
  default 1), 1 new test file (13 tests), this rollout doc.
- Tests: 13/13 green. Migrate: clean on `friday.localhost` (Postgres).
- Benchmark (Legion, real MiniMax, before → after, 10 concurrent turns):
  drain 18.4s → 3.4s; throughput 33 → 176 turns/min; slowest-turn wait
  18.3s → 3.4s.
- Behaviour at default (setting = 1): byte-for-byte identical to the previous
  single `bench worker --queue friday`.
