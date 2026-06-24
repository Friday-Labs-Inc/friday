# Gateway — queue phase (stop dropping busy-session messages)

_Shipped 2026-06-23. First phase of the interrupt/steer/queue port. Fixes a live
data-loss bug; no schema change. Queue-by-default (your decision)._

## In one sentence

A second message sent while an agent is still answering the first is now
**queued and answered in order** instead of being thrown away with a "session
busy" reply.

## What it actually does (plain terms)

Each conversation is serialized by a per-session lock so one turn runs at a time.
Before this change, if a message arrived while the lock was held, the gateway —
after one short requeue — wrote a "session is busy, try again" reply and **marked
the message processed (i.e. discarded it)**. The user's message was gone.

Now, when the lock is busy, the gateway simply **leaves the message unprocessed
and returns**. The turn that holds the lock, the moment it finishes, pulls the
oldest queued message for that session and runs it (FIFO). The existing orphan
sweeper (`gateway/recovery.py`, every minute) is the backstop if a drain is ever
missed. Nothing is interrupted; nothing is lost.

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| 2nd message while turn 1 runs | "busy" reply, message discarded | Queued; answered after turn 1 |
| Burst of N messages | Most discarded | Drained in order, one per completed turn |
| Drain missed (rare race / worker crash) | n/a | Orphan sweeper re-runs it within ~5 min |
| Same row enqueued twice (drain + sweeper + concurrent workers) | risk of duplicate reply | **Double-dispatch guard**: re-checks `processed` after acquiring the lock and skips |
| Sync/CLI (no worker) | unchanged | Serialized in-process; sweeper covers async |

## What it means for friday-core

This removes a real data-loss path on the gateway hot path, and it composes
correctly with the concurrent-worker pool shipped earlier today: the post-lock
`processed` re-check ensures that even if two workers grab jobs for the same row,
only one runs the turn — no duplicate replies. The running turn is never
interrupted (queue-by-default); explicit interrupt/steer are later phases.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| "Queue" | the inbound `Chat Message` row left `processed=0` — no new field |
| FIFO drain | `_drain_next_in_session` enqueues the oldest unprocessed inbound for the session after the lock releases |
| Backstop | the existing `gateway/recovery.py` orphan sweeper (processed=0, async, >5 min) |
| Dedup | post-lock `processed` re-check + the per-session Redis lock |

## Risks and limits a product head should hold

- **No "queued" acknowledgement.** The user sees silence until their message is
  answered (it just works), not a "you're in the queue" note. A transient ack
  could be added later; omitted to keep this minimal.
- **A session stuck busy >~15 min** (3 sweeper retries) still ends in a
  system-error reply — the safety valve for a genuinely wedged session.
- **Interrupt and steer are not in this phase** — a new message never cancels
  the running turn. Those are the next two phases (interrupt cancels the RQ job;
  steer needs a Redis steer-inbox polled in `run_turn`).

## What this unlocks

- Phases B (interrupt via RQ job cancel) and C (steer via Redis inbox) build on
  this queue.

## Numbers for the record

- Files: `gateway/service.py` (busy path → queue; post-lock dedup guard;
  `_drain_next_in_session`), `tests/test_gateway_v2.py` (busy-queues, drain ×3,
  double-dispatch guard).
- Tests: test_gateway_v2 11/11 (3 new behaviours + no regression). No schema
  change → no migration. Reuses the existing orphan sweeper as the backstop.
