# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday gateway — the single chokepoint every message flows through.

PLAIN ENGLISH
=============

Every message in Friday — from any surface, to any agent, returning to any
surface — flows through ONE function: `gateway.service.handle_inbound`.

That function is registered via Frappe's `doc_events` so it fires whenever
ANY surface (CLI, Telegram, Slack, Raven, A2A — present and future)
writes an inbound Chat Message row. The gateway then:

  1. Decides sync vs async based on `Chat Platform.dispatch_mode`.
  2. Acquires a per-session Redis lock so concurrent inbound for the
     same session don't trample each other.
  3. (Future: dedup the message, join a batch — both stubbed today.)
  4. Runs the permission check (Slice 2).
  5. Loads the agent's tool menu (Slice 3).
  6. Calls the agent runner (Slice 4 stub; Slice 5 LLM).
  7. Writes the outbound Chat Message row.
  8. Fires `publish_realtime("chat.outbound", ...)` so future async
     subscribers can attach without any gateway changes.
  9. Marks the inbound row as processed.
 10. Releases the session lock.

THE ONE RULE
============

**No surface ever imports `agent_runner` directly.** If you're an adapter
author and you think you need to, you're violating the chokepoint pattern.
Write your inbound row and let the gateway do its job.

MODULES
=======

  - `service.py`  — the chokepoint hook (`handle_inbound`).
  - `batching.py` — DEFERRED batching. Stub today; real queue + timer
                    when the first bursty surface ships.
  - `recovery.py` — the orphan sweeper (Q5 half-step). Runs every
                    minute via Frappe's scheduler.

REFERENCED DOCS
===============

- `docs/design/47-gateway-design-decisions.md` — the contract.
- `docs/design/10-agent-execution-guide.md` §Slice 4 — the original spec.
- `feedback-unified-gateway-service` (project memory) — why ONE chokepoint.
- `feedback-single-tenant-not-saas` (project memory) — sizing constraints.
- `feedback-compare-with-hermes` (project memory) — Hermes equivalents in the design doc.
"""
