# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The steer inbox — inject mid-turn guidance into a running turn (Design 84).

PLAIN ENGLISH
=============

Steer is interrupt's gentle sibling. Where `/stop` (Design 83) halts a running
turn, `/steer <text>` *nudges* it: "use the staging DB", "keep it under 200
words". The agent reads the nudge on its next think/act cycle and adapts —
without restarting.

Same cross-process channel as interrupt: one Redis key per session,

    friday:steer:{session_id}

holding the pending guidance text (not just a flag). `/steer` pushes into it
(`push_steer`, coalescing multiple nudges with newlines, as Hermes does); the
running turn's ReAct loop drains it at each boundary (`drain_steer` = read +
clear) and appends it to the conversation so the model sees it on the next call.
`run_turn` also clears the slot at entry (Design 84, Q4) so a stale steer never
leaks into a later turn — the session lock guarantees one turn per session, which
is what makes clear-at-entry sufficient.

This is the cooperative half, like interrupt: it lands at ReAct iteration
boundaries, not mid-LLM-call.
"""

from __future__ import annotations

import frappe

# One Redis key per session, sibling to the interrupt flag's keyspace.
_STEER_PREFIX = "friday:steer:"

# TTL backstop: a steer nobody consumes self-expires, so a stray `/steer` can't
# silently ride into a turn that starts minutes later.
_STEER_TTL_SECONDS = 120


def _key(session_id: str) -> str:
	return f"{_STEER_PREFIX}{session_id}"


def push_steer(session_id: str, text: str) -> bool:
	"""Add a nudge for the running turn. Coalesces with any pending text.

	Returns False (and stores nothing) for empty text — mirrors Hermes'
	`steer()` ignoring empty strings. Multiple nudges before a drain concatenate
	with newlines.
	"""
	cleaned = (text or "").strip()
	if not cleaned:
		return False
	existing = frappe.cache().get_value(_key(session_id))
	combined = f"{existing}\n{cleaned}" if existing else cleaned
	frappe.cache().set_value(_key(session_id), combined, expires_in_sec=_STEER_TTL_SECONDS)
	return True


def drain_steer(session_id: str) -> str | None:
	"""Return the pending steer text and clear the slot. None when empty.

	Best-effort: a cache hiccup degrades to "no steer" rather than breaking the
	turn (same posture as the interrupt reads, Design 83).
	"""
	try:
		val = frappe.cache().get_value(_key(session_id))
		if val:
			frappe.cache().delete_value(_key(session_id))
			return val
		return None
	except Exception:
		return None


def clear_steer(session_id: str) -> None:
	"""Drop any pending steer — called once at turn entry (Q4). Best-effort."""
	try:
		frappe.cache().delete_value(_key(session_id))
	except Exception:
		pass
