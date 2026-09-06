# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
DEFERRED: per-session batching. Today this module is a no-op stub.

PLAIN ENGLISH
=============

When the first bursty surface lands (Telegram users double-tapping, A2A
agents sending three messages in a flurry, etc.) Friday will collect
near-simultaneous inbound messages for the same session and feed them
to the agent as a single batch instead of N separate runs.

That's not in v0.1. The CLI never bursts; we don't have webhooks yet.
But the SEAM is here so the day this becomes real, only this file
changes — every gateway caller already routes through `flush_batch()`.

The full design (idle window per platform, max batch size, signature
change to `messages: list`, mid-run behavior) lives in
`docs/design/47-gateway-design-decisions.md` §4 Q4-C.

TODAY'S BEHAVIOR
================

`flush_batch(session_id, inbound_row)` returns the inbound row's content
as a single-element list. That's it. No queue, no timer, no waiting.
The gateway treats the result as "the batch to feed the agent." Because
v0.1 always has one message per batch, the agent's existing
`run_turn(profile, session, content: str)` signature still works — we
just unwrap the single-element list before calling.

WHEN THIS ACTIVATES
===================

The slice that ships the first bursty surface (likely Slice 7 with
Telegram, or Slice 8 with A2A). At that point:

  - Replace this body with a real Redis-backed per-session queue.
  - Implement the idle-window timer per `Chat Platform.batch_idle_ms`.
  - Cap at 5 messages per batch (hardcoded for v1; configurable later).
  - Change `agent_runner.run_turn` to accept `messages: list[str]`
    (signature change documented in §4 Q4-C; backwards compatibility
    via wrapping a single string).
  - Implement "buffer for next batch" semantics if a new inbound
    arrives mid-agent-run.

Until then: this file is intentionally a thin pass-through.
"""

from __future__ import annotations


def flush_batch(session_id: str, inbound_content: str) -> list[str]:
	"""Return a list of inbound contents to feed the agent for this turn.

	v0.1: always a single-element list. No queueing, no waiting.

	The function exists so future gateway code never grows a special-case
	"batched-or-not" branch. When the real queue lands, this function's
	body changes; its callers don't.
	"""
	return [inbound_content]
