# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Task workflow state-machine hook for Task documents.

Registered as ``doc_events["Task"]["on_update"]`` in ``hooks.py``.

Responsibilities
----------------
1. Derive ``dispatchable`` from the current ``workflow_state``.
   dispatchable = True when workflow_state ∈ {Pending, Assigned}.
2. Record ``started_at`` when entering the Executing state.
3. Record ``completed_at`` when entering Completed or Cancelled.
4. Clear ``assigned_to_profile`` when entering Cancelled.
5. Emit ``agent_task.assigned`` on Frappe Redis pub/sub when
   transitioning Pending → Assigned so the task runner can pick it up
   outside the save transaction (avoids holding a DB lock while the
   worker runs).
6. Post a War Room update to the Raven FRIDAY_WAR_ROOM channel on
   every state transition (graceful degradation if Raven is not installed).
"""

import frappe

# Lazy import to avoid circular imports — warroom itself doesn't import tasks.
_warroom = None

def _get_warroom():
	global _warroom
	if _warroom is None:
		try:
			from frappe.friday_core import warroom
			_warroom = warroom
		except Exception:
			_warroom = None
	return _warroom


# States that make a task available for the dispatcher to claim.
DISPATCHABLE_STATES = frozenset({"Pending", "Assigned"})


def on_state_change(doc: "Task", method: str) -> None:
	"""
	Recompute dispatchable; record timestamps; emit Redis event.

	Called by Frappe's doc_events system after every save of an
	Task document.  Runs inside the same transaction as the
	save, so all DB writes are atomic with it.

	Args:
		doc: The saved Task document.
		method: The Frappe hook method name (``"on_update"``).
	"""
	# 1. dispatchable is a derived field — always recompute from live state.
	doc.dispatchable = doc.workflow_state in DISPATCHABLE_STATES

	# Only act on actual workflow state transitions, not unrelated field saves.
	if doc.has_value_changed("workflow_state"):
		_watch_transition(doc)

	# Persist the derived/side-effect fields WITHOUT doc.save(): this function
	# runs ON on_update, so save() here re-fires on_update → this function →
	# save() → RecursionError. db_set writes the columns directly and fires no
	# document hooks (the Frappe idiom for persisting from inside a hook).
	doc.db_set(
		{
			"dispatchable": 1 if doc.dispatchable else 0,
			"started_at": doc.started_at,
			"completed_at": doc.completed_at,
			"assigned_to_profile": doc.assigned_to_profile,
		},
		update_modified=False,
	)


def _watch_transition(doc: "Task") -> None:
	"""
	Handle side-effects that depend on the specific state transition.

	Runs inside the save transaction — keep DB writes minimal.
	Long-running work (Docker execution) happens in the runner, which
	picks up the ``agent_task.assigned`` pub/sub event.
	"""
	state = doc.workflow_state

	# --- timestamps -------------------------------------------------------
	if state == "Executing" and doc.started_at is None:
		doc.started_at = frappe.utils.now_datetime()

	if state in ("Completed", "Cancelled") and doc.completed_at is None:
		doc.completed_at = frappe.utils.now_datetime()

	# --- clear assignment on cancellation ---------------------------------
	if state == "Cancelled" and doc.assigned_to_profile:
		doc.assigned_to_profile = None

	# --- War Room post ----------------------------------------------------
	_post_warroom_update(doc, state)

	# --- RandomPack write-back (design 60, Q5) ------------------------------
	# The bridge no-ops for tasks/projects without backend refs and never
	# raises — a write-back outage cannot break a task save.
	from frappe.friday_core.integrations.randompack_bridge import on_task_transition

	on_task_transition(doc, state)

	# --- emit Redis pub/sub for task runner -------------------------------
	# Only emit when we are moving INTO Assigned AND the profile actually
	# changed (avoids duplicate events on re-save without assignment change).
	if state == "Assigned" and doc.has_value_changed("assigned_to_profile"):
		_emit_assigned_event(doc.name, doc.assigned_to_profile)


def _post_warroom_update(doc: "Task", state: str) -> None:
	"""
	Post a status update to the Raven War Room channel.

	Args:
		doc: The Task document.
		state: The new workflow_state.
	"""
	warroom = _get_warroom()
	if warroom is None:
		return

	try:
		# Savepoint so a failed statement inside the post (e.g. Raven not
		# installed on this site) rolls back WITHOUT aborting the whole
		# transaction — on Postgres a bare `except: pass` is NOT graceful:
		# every later statement would fail with InFailedSqlTransaction.
		frappe.db.savepoint("friday_warroom")
		details = {"profile": doc.assigned_to_profile} if doc.assigned_to_profile else None
		warroom.post_task_update(doc.name, state.lower(), details)
	except Exception:
		# Never block the task pipeline — degrade gracefully.
		frappe.db.rollback(save_point="friday_warroom")


def _emit_assigned_event(task_name: str, assigned_to_profile: str) -> None:
	"""
	Publish an ``agent_task.assigned`` real-time event.

	The task runner subscribes to this event and resumes a warm container
	to execute the task.  Publishing happens after the save transaction
	commits via ``doctype=True`` so it is outside the DB write path.

	Args:
		task_name: Task document name (e.g. ``AT-000042``).
		assigned_to_profile: The agent profile assigned to the task.
	"""
	message = {
		"task_name": task_name,
		"assigned_to_profile": assigned_to_profile,
		"workflow_state": "Assigned",
	}
	frappe.publish_realtime(
		event="agent_task.assigned",
		message=message,
		doctype="Task",
		after_commit=True,
	)