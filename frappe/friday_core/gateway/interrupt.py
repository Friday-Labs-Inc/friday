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


# ---------------------------------------------------------------------------
# Cascade to delegated work (Design 85)
# ---------------------------------------------------------------------------

# The non-terminal Task states — a task in any of these is "active" and worth
# stopping. Matches `skills/handlers_delegate._ACTIVE_STATES`.
_ACTIVE_STATES = ("Pending", "Assigned", "Executing", "Blocked")


def collect_active_subtree(session_id: str) -> list[str]:
	"""Active Task names delegated under this session (descendants included).

	Roots are tasks this session spawned (`Task.originating_session`); descendants
	follow `Task.parent_task`. Only `_ACTIVE_STATES` tasks are collected — a
	finished task has nothing to stop. No schema change: both links already exist
	(`handlers_delegate.py:132,138`).
	"""
	roots = frappe.get_all(
		"Task",
		filters={"originating_session": session_id, "workflow_state": ("in", _ACTIVE_STATES)},
		pluck="name",
	)
	seen: list[str] = []
	frontier = list(roots)
	while frontier:
		name = frontier.pop()
		if name in seen:
			continue
		seen.append(name)
		children = frappe.get_all(
			"Task",
			filters={"parent_task": name, "workflow_state": ("in", _ACTIVE_STATES)},
			pluck="name",
		)
		frontier.extend(children)
	return seen


def cascade_interrupt(session_id: str) -> int:
	"""Stop every active delegated task under this session. Returns the count.

	For each node: set the cooperative interrupt flag on its `task::{name}`
	session (a running turn honors it at its next ReAct boundary, then the Task
	path marks it Cancelled). A node that is NOT currently executing has no turn
	to interrupt, so it is cancelled directly here so it never starts.
	"""
	names = collect_active_subtree(session_id)
	for name in names:
		request_interrupt(f"task::{name}")
		if frappe.db.get_value("Task", name, "workflow_state") != "Executing":
			_cancel_task(name)
	return len(names)


def _cancel_task(task_name: str) -> None:
	"""Mark a not-yet-running task Cancelled/interrupted. Best-effort, per task.

	Direct `set_value` (no workflow hook) keeps the cascade robust — one task's
	failure can't abort the rest, and it can't poison the surrounding txn.
	"""
	try:
		frappe.db.set_value(
			"Task",
			task_name,
			{"workflow_state": "Cancelled", "blocked_reason": "interrupted"},
			update_modified=False,
		)
	except Exception:
		frappe.logger("friday.interrupt").warning(
			f"cascade cancel failed for {task_name!r}", exc_info=True
		)
