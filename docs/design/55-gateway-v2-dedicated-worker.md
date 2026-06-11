# Design 55 — Gateway v2: the dedicated Friday worker

**Status: LOCKED 2026-06-10 — all six decisions (Q1–Q6) accepted as recommended ("lock all").**

## What this is, in plain English

Today, an agent turn runs **inside whatever process received the message** —
the CLI process (sync) or a *shared* background worker (async, on Frappe's
`default` queue, which also runs emails, notifications, and every other
background job on the site).

Gateway v2 gives Friday its **own dedicated worker process** — `bench worker
--queue friday` — that does nothing but run agent turns. Surfaces stay thin
(they only write a `Chat Message` row); the dedicated worker is the one place
agent work executes.

This is the Frappe-native equivalent of Hermes' always-running gateway daemon
(`gateway/run.py`, 18.7k lines) — except process supervision, queuing,
retry, delivery, and config are all things Frappe already ships, so the
gateway stays a few hundred lines.

## Why a dedicated worker (the three real reasons)

1. **Capacity isolation.** Agent turns are LONG (LLM calls 5–100s; the retry
   budget alone can reach ~97s; sandbox runs add more). On the shared
   `default` queue, one chatty session starves the site's own background jobs
   — and vice versa. A dedicated queue means agent load and site load can't
   hurt each other.
2. **Independent scaling.** Concurrency = number of friday workers. One in
   dev; N under supervisor in production. Per-session ordering is already
   guaranteed by the Redis session lock, so N workers safely run N
   *different* sessions in parallel.
3. **Independent policy.** Our own timeout (10 min vs default 5), our own
   monitoring, and one obvious place to look when something hangs.

## How we leverage Frappe's machinery (the answer to "what does Frappe give us")

| Need | Hermes built it as | Friday LEVERAGES |
|---|---|---|
| Always-on gateway process | `gateway/run.py` daemon (18.7k lines) | **RQ worker**: `bench worker --queue friday` (Procfile line; supervisor in prod) |
| Job queue + retry plumbing | hand-rolled asyncio loops | **`frappe.enqueue(queue="friday")`** — durable Redis-backed jobs |
| Queue definition + timeout | config.py | **`common_site_config.json` → `"workers": {"friday": {"timeout": 600}}`** (read natively by `get_queues_timeout`) |
| Real-time push to UIs | `delivery.py` + stream consumer | **`frappe.publish_realtime("chat.outbound", …, after_commit=True)`** → Frappe's socketio node server → Desk/Raven/web clients |
| Session state | in-memory `SessionStore` (1.3k lines) | **Chat Message rows** (durable, auditable) + **`frappe.cache().lock()`** per-session Redis lock |
| Crash recovery | `shutdown_forensics.py` | **scheduler sweeper** (`recovery.py`): re-enqueues orphan `processed=0` rows, idempotent, retry-capped |
| Process restarts / memory | `memory_monitor.py`, `restart.py` | **bench/supervisor** owns process lifecycle — not our code |
| Per-platform config | YAML | **Chat Platform DocType** (`dispatch_mode` field) |

## The message flow (v2)

```
surface (CLI / Raven / Telegram webhook / A2A)
   │  writes ONE inbound Chat Message row          ← unchanged contract
   ▼
after_insert hook (handle_inbound) — now a THIN ROUTER only
   │
   ├── platform dispatch_mode = "async"  → frappe.enqueue(queue="friday")
   │                                        ▼
   │                              DEDICATED FRIDAY WORKER
   │                              _run_pipeline (lock → batch →
   │                              run_turn → outbound row →
   │                              publish_realtime → mark processed)
   │
   └── dispatch_mode = "sync" (CLI/tests) → same pipeline, inline
                                            (fallback path — see Q1)
```

The pipeline function itself **does not change** — same locking, same audit
rows, same error-row guarantees. v2 changes *where it executes*.

## Decisions to lock (Q-by-Q)

**Q1 — Does the CLI go through the worker too, or stay inline?**
*Recommendation:* CLI enqueues to the friday queue like everything else
(single execution path = single thing to reason about), **with an automatic
inline fallback** when no friday worker is alive (RQ exposes worker counts) —
so `friday chat` still works in a bare dev shell, with a logged warning.
Surfaces never know the difference; they read the outbound row / realtime
event either way.

**Q2 — Queue name, timeout, worker count?**
*Recommendation:* queue `friday`, timeout **600s** (the engine's worst case:
LLM retries + sandbox + approval writes), **1 worker in the dev Procfile**
(`worker_friday:` line), N via supervisor in production. Configured in
`common_site_config.json`, no code constant.

**Q3 — Two messages hit the same session while it's busy: what happens?**
Today: the second waits 30s for the session lock, then gets "(session is
busy)". *Recommendation:* in worker mode, **requeue once with a 15s delay**
before giving the busy message — bursts feel queued, not rejected. (True
burst-batching — joining messages into one turn — stays a stub until the
first bursty surface lands, per design 47.)

**Q4 — Realtime targeting: global event or per-user rooms?**
*Recommendation:* keep the single `chat.outbound` event with
`session_id`/`platform` in the payload for v0.1 (CLI ignores it; the first
UI subscriber filters by session). Move to per-user rooms
(`publish_realtime(user=…)`) when Raven lands and sessions map to users.

**Q5 — Outbound delivery to push platforms (Telegram sendMessage etc.)?**
*Recommendation:* defer. Design note only: delivery becomes a *small
separate job* per outbound row (Hermes `delivery.py` equivalent) enqueued by
the pipeline — built with the first webhook surface, not before.

**Q6 — Stamp the RQ job id onto the Chat Message row?**
*Recommendation:* yes — one optional Data field (`job_id`) written at
enqueue time. Cost: one column. Benefit: row → queue job traceability when
debugging ("which worker ran this turn?").

## What changes on disk (when approved)

- `gateway/service.py` — `handle_inbound` enqueues to `queue="friday"`;
  inline fallback per Q1; requeue-on-busy per Q3. Pipeline body unchanged.
- `common_site_config.json` (bench-level, not in repo) — `workers.friday`.
- `Procfile` (bench-level) — `worker_friday: bench worker --queue friday`.
- `chat_message.json` — `job_id` field (Q6).
- `recovery.py` — sweeper re-enqueues to the friday queue.
- Tests first (per workflow): router enqueues to the right queue; fallback
  fires when no worker; requeue-then-busy ordering; job_id stamped.

## What this deliberately does NOT do

- No streaming (`stream_consumer.py`) — nothing to stream to yet; revisit
  with the first real-time UI surface.
- No pairing / channel directory / mirror — platform-specific, land with
  their platforms.
- No new daemon code — the "dedicated worker" IS a stock RQ worker; we add
  zero process-management code.

## Hermes faithfulness statement

The gateway remains Friday's **one deliberate architecture override** of
Hermes (design 47): durable rows instead of in-memory sessions, Frappe's
queue/realtime/scheduler instead of a hand-built daemon. v2 doesn't change
that stance — it completes it, by giving the row-driven gateway the same
*operational* property Hermes' daemon had: dedicated, always-on, scalable
execution capacity.
