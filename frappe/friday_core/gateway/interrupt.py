# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The interrupt flag — a tiny cross-process signal to stop a running turn.

PLAIN ENGLISH
=============

A conversational turn runs inside a worker process. The operator's `/stop`
arrives in a *different* process (the Raven hook / web request). They can't call
each other directly, so they talk through one Redis key per session:

    friday:interrupt:{session_id}

`/stop` sets the key (`request_interrupt`); the running turn's ReAct loop checks
it once per iteration (`is_interrupt_requested`) and, if set, stops cleanly. The
key carries a short TTL so a `/stop` that lands when nothing is running never
wedges a future turn — and `run_turn` also clears it once at entry (Design 83,
Q3) so only a flag set *during* the current turn is ever honored. The session
lock guarantees one turn per session at a time, which is what makes
clear-at-entry sufficient (no Hermes-style generation counter needed).

This is the cooperative half of the interrupt port (Design 83, Q2). It lands at
ReAct iteration boundaries, not mid-LLM-call — Friday's provider call is one
blocking request, so the soonest a turn can notice is after the current call
returns. A hard kill (`send_stop_job_command`) is a named follow-up.
"""

from __future__ import annotations

import frappe

# One Redis key per session. Matches the session-lock keyspace convention.
_INTERRUPT_PREFIX = "friday:interrupt:"

# TTL backstop: a flag nobody consumes self-expires, so a stray `/stop` can never
# silently kill a turn that starts minutes later. Generous enough to outlive one
# in-flight LLM call (the worst-case latency before the loop checks it).
_INTERRUPT_TTL_SECONDS = 120


def _key(session_id: str) -> str:
	return f"{_INTERRUPT_PREFIX}{session_id}"


def request_interrupt(session_id: str) -> None:
	"""Ask the running turn for this session to stop (set by `/stop`)."""
	frappe.cache().set_value(_key(session_id), "1", expires_in_sec=_INTERRUPT_TTL_SECONDS)


def is_interrupt_requested(session_id: str) -> bool:
	"""True when an interrupt is pending for this session.

	Best-effort: a cache hiccup degrades to "no interrupt" rather than breaking
	the turn — same posture as the heartbeat/compression/usage callsites. The
	turn keeps running; the operator can `/stop` again.
	"""
	try:
		return bool(frappe.cache().get_value(_key(session_id)))
	except Exception:
		return False


def clear_interrupt(session_id: str) -> None:
	"""Drop the flag — called at turn entry (Q3) and once an interrupt is honored.

	Best-effort: a cache failure here must never break the turn.
	"""
	try:
		frappe.cache().delete_value(_key(session_id))
	except Exception:
		pass
