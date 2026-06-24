# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Task runner — executes assigned Tasks inside Docker sandboxes.

Executes a Task as a background RQ job enqueued by the workflow hook
(``tasks.workflow.on_state_change``) when the task enters ``Assigned``.
Transitions task state through Executing → Review (success) or
Executing → Blocked (failure).

Registration
------------
Call ``register_task_runner()`` once during Frappe app initialisation
(e.g. from ``after_migrate`` or via a startup hook) to wire up the
real-time subscription.  The runner persists across requests as part
of the Frappe worker process.

Architecture note
-----------------
This is the async counterpart to the synchronous skill dispatcher in
``friday_core.agent_runner.dispatcher``.  Both share the same sandbox
runner (``friday_core.sandbox.runner``) but differ in lifecycle:
- Chat flow: synchronous, in-process, per-message.
- Task flow: event-driven, cron-dispatched, persistent.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.agent_runner.exceptions import TurnInterrupted
from frappe.friday_core.issues.raise_issue import raise_failure_issue
from frappe.friday_core.observability import emit
from frappe.utils import now_datetime

# Lazy import to avoid circular dependency with the warroom module.
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


_logger = frappe.logger("friday.tasks.runner")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_task_runner() -> None:
	"""
	Subscribe to ``agent_task.assigned`` real-time events.

	**Currently a no-op.** ``frappe.realtime.on(...)`` does not exist —
	Frappe's realtime layer is publish-only on the server side (via
	``frappe.publish_realtime``); subscriptions live in browser clients
	over socket.io. Trying to call it crashes ``after_migrate`` and
	breaks every site migrate. This stub exists so the ``after_migrate``
	hook entry in ``hooks.py`` doesn't fail.

	The real handler ``on_agent_task_assigned()`` is now triggered by
	``tasks.workflow.on_state_change``: when a Task transitions into
	``Assigned`` it enqueues that handler as an RQ job on the ``default``
	queue (decision 2026-06-13). This stub therefore stays a no-op — it
	exists only so the ``after_migrate`` hook entry in ``hooks.py`` does
	not fail. No realtime subscription is needed or possible server-side.
	"""
	# Intentional no-op. See docstring above for the real fix.
	pass


def on_agent_task_assigned(message: dict) -> None:
	"""
	Execute a task that has just been assigned.

	Runs as an RQ background job enqueued by ``tasks.workflow.on_state_change``
	when a Task transitions into ``Assigned`` (on the ``default`` queue, after
	the assigning transaction commits).

	Args:
		message: Dict with keys ``task_name``, ``assigned_to_profile``,
		          ``workflow_state``.
	"""
	task_name = message.get("task_name")
	profile_name = message.get("assigned_to_profile")

	if not task_name or not profile_name:
		_logger.error("Malformed agent_task.assigned message: %s", message)
		return

	try:
		_run_task(task_name, profile_name)
	except Exception as exc:
		# An unexpected crash in the runner itself — NOT a skill-level failure
		# (those land in _block_task via SandboxResult.status). Auto-raise a
		# Failure Issue and surface it (D6).
		#
		# Design 72 — also fix the resilience gap that stranded FLI-001's
		# guidelines task: a Postgres UniqueViolation poisons the surrounding
		# transaction, and the error handler below then crashes on
		# InFailedSqlTransaction when it tries DB writes. Roll back FIRST so the
		# transaction is usable; then record the failure and emit a trace event.
		try:
			frappe.db.rollback()
		except Exception:
			_logger.exception("rollback failed before issue raise (will continue)")
		_logger.exception("Task runner crashed for task %s on profile %s", task_name, profile_name)
		issue_name = _raise_failure_issue(task_name, "error")
		emit(
			"runner.error",
			task=task_name,
			agent_profile=profile_name,
			trigger_source="runner_loop_exception",
			summary=f"runner crashed: {type(exc).__name__}: {str(exc)[:200]}",
			payload={"exc_type": type(exc).__name__, "issue": issue_name},
		)
		_post_warroom(task_name, "error", {"profile": profile_name, "issue": issue_name})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _post_warroom(task_name: str, event: str, details: dict | None = None) -> None:
	"""
	Post a status update to the Raven War Room channel.

	Never raises — degrades gracefully on any error.

	Args:
		task_name: Task document name.
		event: One of ``executing``, ``completed``, ``blocked``,
		       ``error``, ``oom``, ``timeout``.
		details: Optional extra data.
	"""
	warroom = _get_warroom()
	if warroom is None:
		return
	try:
		# Savepoint: see workflow._post_warroom_update — a failed post must
		# not abort the surrounding Postgres transaction.
		frappe.db.savepoint("friday_warroom")
		warroom.post_task_update(task_name, event, details)
	except Exception:
		frappe.db.rollback(save_point="friday_warroom")


def _raise_failure_issue(
	task_name: str,
	error_type: str,
	details: "str | None" = None,
	execution_log: "str | None" = None,
) -> "str | None":
	"""File an Agent-raised Failure Issue for a failed task (doc 53 D6).

	Best-effort and never raises — mirrors `_post_warroom`'s defensiveness. A
	hiccup in the issue-raising path must not mask the original task failure.
	Returns the new Issue name, or None if it could not be raised.
	"""
	try:
		return raise_failure_issue(
			task_name,
			error_type=error_type,
			details=details,
			execution_log=execution_log,
		)
	except Exception:
		_logger.exception("Could not raise a Failure Issue for task %s", task_name)
		return None


def _claim_task(task_name: str) -> str | None:
	"""
	Design 61, Q5 — idempotent claim-and-set lease.

	Atomically transition Assigned → Executing AND stamp an executing_token.
	A duplicate trigger (the reconciler re-fires a lost enqueue, or a stuck
	queue belatedly drains the original) sees a non-empty token and exits
	cleanly. This is what makes the at-least-once-trigger / exactly-once-
	effect contract honest — without it, the reconciler would risk double-
	executing the same task and writing duplicate deliverables.

	Returns the token if we won the claim, None if someone else got there
	first. The UPDATE itself is the lock; we do not pre-read the row.
	"""
	token = frappe.generate_hash(length=16)
	# COALESCE collapses NULL/'' so an empty-string token left over from an
	# older row (pre-migration) does not falsely lock the task.
	frappe.db.sql(
		"""
		UPDATE `tabTask`
		SET workflow_state = 'Executing',
		    executing_token = %s,
		    started_at = COALESCE(started_at, NOW()),
		    last_heartbeat_at = NOW()
		WHERE name = %s
		  AND workflow_state = 'Assigned'
		  AND COALESCE(executing_token, '') = ''
		""",
		(token, task_name),
	)
	# frappe.db.sql returns a list of rows for SELECT; for UPDATE the affected
	# row count comes via the underlying cursor. The simple, portable test:
	# re-read the token. If it matches, we won.
	current = frappe.db.get_value("Task", task_name, "executing_token")
	return token if current == token else None


def _elapsed_ms(started_at) -> int:
	"""Milliseconds from ``started_at`` to now (design 65d duration_ms)."""
	delta = now_datetime() - started_at
	return int(delta.total_seconds() * 1000)


def _heartbeat(task_name: str) -> None:
	"""
	Refresh ``last_heartbeat_at`` so the reconciler knows this runner is alive.

	Called periodically during long agentic turns and at every skill boundary
	for mechanical runs. Failures are swallowed: a missed heartbeat costs at
	most one reconciler grace window, but a crash inside the heartbeat must
	never break the actual work.
	"""
	try:
		frappe.db.set_value("Task", task_name, "last_heartbeat_at", now_datetime(), update_modified=False)
	except Exception:
		_logger.warning("heartbeat update failed for %s", task_name)


def _run_task(task_name: str, profile_name: str) -> None:
	"""
	Load a task, execute its required skills, and update the task state.

	Args:
		task_name: ``Task`` document name.
		profile_name: ``Agent Profile`` name to execute the task under.
	"""
	# Q5 — claim the task atomically. If someone else already did, exit cleanly.
	token = _claim_task(task_name)
	if not token:
		_logger.info(
			"runner: task %s already claimed (duplicate trigger from reconciler?) — exiting",
			task_name,
		)
		return

	task = frappe.get_doc("Task", task_name)

	# Design 60, Q2 — agentic tasks run a REAL governed turn instead of the
	# mechanical skill sequence. Milestones never reach here (the dispatcher
	# filters them), but guard anyway.
	if (task.get("execution_mode") or "mechanical") == "agentic":
		_run_task_agentic(task, profile_name)
		return
	if task.get("execution_mode") == "milestone":
		return

	# Record start time for duration calculation.
	started_at = now_datetime()

	# Transition to Executing was already done atomically by _claim_task; we
	# only refresh the timestamp fields the doc-level save needs to see.
	task.started_at = started_at
	task.save(ignore_permissions=True)
	frappe.db.commit()

	# Post "executing" to War Room.
	skills = [row.skill for row in task.required_skills if row.skill]
	_post_warroom(task_name, "executing", {"profile": profile_name, "skills": skills})

	# Execute each required skill in sequence.
	results = []

	for skill_name in skills:
		# Heartbeat at every skill boundary so the reconciler's executing-stale
		# sweep does not block a long but healthy task. Cheap update — no save.
		_heartbeat(task_name)
		result = _execute_skill_in_sandbox(skill_name, task, profile_name)
		results.append(result)

		if result.status != "success":
			_block_task(task, results)
			return

	# All skills succeeded — transition to Review.
	task.result = frappe.as_json(_build_result_envelope(results, "success"))
	_task_transition(task, "Review")
	task.save(ignore_permissions=True)
	frappe.db.commit()

	# Post "completed" to War Room.
	import datetime

	duration_ms = int((datetime.datetime.utcnow() - started_at).total_seconds() * 1000)
	_post_warroom(
		task_name,
		"completed",
		{"duration_ms": duration_ms, "profile": profile_name},
	)


def _execute_skill_in_sandbox(skill_name: str, task: "Task", profile_name: str) -> "SandboxResult":
	"""
	Execute one skill from a task's required_skills in a Docker sandbox.

	Uses the warm container pool (via ``sandbox.runner``) with credentials
	resolved from ``skill_name + profile_name``.

	Args:
		skill_name: Name of the skill to execute.
		task: The ``Task`` document.
		profile_name: The executing ``Agent Profile`` name.

	Returns:
		``SandboxResult`` dataclass from sandbox.runner.
	"""
	from frappe.friday_core.sandbox import credentials as sandbox_creds
	from frappe.friday_core.sandbox import runner as sandbox_runner

	parameters = _parse_task_parameters(task, skill_name)
	creds = sandbox_creds.resolve_credentials(profile_name, skill_name)

	execution_id = f"{task.name}:{skill_name}"
	token = sandbox_creds.generate_scoped_token(profile_name, execution_id)

	return sandbox_runner.execute(
		skill_name=skill_name,
		parameters=parameters,
		agent_profile=profile_name,
		api_key=token,
		credentials=creds,
	)


def _parse_task_parameters(task: "Task", skill_name: str) -> dict:
	"""
	Extract parameters for ``skill_name`` from the task document.

	Phase 1: uses the task's ``description`` field as a plain-text hint
	passed to the sandbox entrypoint.  Phase 1.5 will support structured
	parameters stored in a child table.

	Args:
		task: The ``Task`` document.
		skill_name: Name of the skill whose parameters are needed.

	Returns:
		Dict of parameters to pass to the skill handler.
	"""
	# Phase 1 — unstructured description as parameters.
	# The skill handler decides how to parse it.
	return {"description": task.description or ""}


def _block_task(task: "Task", results: list) -> None:
	"""
	Mark a task as blocked after a skill execution failure.

	Args:
		task: The ``Task`` document.
		results: List of ``SandboxResult`` from executed skills.
	"""
	task.result = frappe.as_json(_build_result_envelope(results, "failed"))
	_task_transition(task, "Blocked")
	task.save(ignore_permissions=True)
	frappe.db.commit()

	# D6 — a blocked task auto-raises a Failure Issue, so a supervisor sees the
	# holdup as a ticket without reading logs.
	failed = results[-1] if results else None
	issue_name = _raise_failure_issue(
		task.name,
		error_type=(failed.status if failed else "failed"),
		details=frappe.as_json(failed.result) if (failed and failed.result) else None,
	)

	# Post "blocked" to War Room, referencing the Issue. Design 62 — name the
	# agent that hit the block so the War Room shows who needs help, not a
	# faceless task.
	_post_warroom(
		task.name,
		"blocked",
		{
			"error_message": results[-1].result if results else None,
			"issue": issue_name,
			"profile": task.get("assigned_to_profile"),
		},
	)


def _build_result_envelope(results: list, status: str) -> dict:
	"""
	Build the JSON result envelope written to ``Task.result``.

	Args:
		results: List of ``SandboxResult`` from skill executions.
		status: Overall status string (``"success"`` or ``"failed"``).

	Returns:
		Envelope dict with ``status``, ``skills``, ``started_at``, etc.
	"""
	return {
		"status": status,
		"skills": [
			{
				"skill": r.skill,
				"status": r.status,
				"result": r.result,
				"logs": r.logs,
				"duration_ms": r.duration_ms,
			}
			for r in results
		],
		"completed_at": frappe.utils.now_datetime(),
	}


def _run_task_agentic(task: "Task", profile_name: str) -> None:
	"""Run one queued task as a real governed agent turn (design 60, Q2).

	Same isolation contract as delegation (design 57): a fresh
	`task::<name>` session, the task framing as the only context, the
	profile's own permissions gating every skill call, the summary stored
	as the result envelope. State transitions fire the workflow hook, which
	carries War Room posts and backend write-back.
	"""
	from frappe.friday_core.agent_runner.runner import run_turn
	from frappe.friday_core.tasks.rollup import task_cost_from_usage

	started_at = now_datetime()
	frappe.flags.dispatcher_event_source = "runner_start"
	try:
		task.workflow_state = "Executing"
		task.assigned_to_profile = profile_name
		task.started_at = started_at
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.dispatcher_event_source = None
	frappe.db.commit()

	emit(
		"runner.start",
		task=task.name,
		project=task.get("project"),
		agent_profile=profile_name,
		trigger_source="runner_loop",
		summary=f"{task.name}: agentic turn started on {profile_name}",
	)

	framing = (
		f"You are completing a queued pipeline task ({task.name}): {task.title}\n\n"
		f"Instructions:\n{task.description or ''}\n\n"
		"Tool discipline: call each tool AT MOST ONCE unless a tool result "
		"tells you otherwise. Once you have what you need, STOP calling tools "
		"and write your final answer as a normal reply.\n\n"
		"When finished, reply with a clear, concise summary of the outcome — "
		"including the names of any records you created. Your reply is stored "
		"as the task result for human review."
	)
	# Design 61b — pass a per-iteration heartbeat so a long agentic ReAct loop
	# (real LLM calls + tool dispatches) keeps last_heartbeat_at fresh and the
	# reconciler's executing-stale sweep does NOT block it as runner_lost.
	task_name = task.name
	try:
		summary = run_turn(
			profile_name=profile_name,
			session_id=f"task::{task.name}",
			inbound_content=framing,
			heartbeat=lambda: _heartbeat(task_name),
		)
	except TurnInterrupted:
		# Design 85 (Q3) — this delegated child was cascaded a `/stop`. It did NOT
		# finish, so it must NOT be marked Completed. Roll back any partial txn,
		# mark it Cancelled with an "interrupted" reason, and stop.
		try:
			frappe.db.rollback()
		except Exception:
			_logger.exception("rollback failed before _run_task_agentic interrupt save")
		# Design 83b — if the operator `/stop force`d this task, the kill path
		# already set ForceKilled + audit fields; don't downgrade it to Cancelled.
		if frappe.db.get_value("Task", task.name, "force_killed_by"):
			return
		task.result = frappe.as_json({"status": "interrupted"})
		task.workflow_state = "Cancelled"
		task.blocked_reason = "interrupted"
		task.duration_ms = _elapsed_ms(started_at)
		frappe.flags.dispatcher_event_source = "runner_interrupt"
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.dispatcher_event_source = None
		frappe.db.commit()
		emit(
			"runner.interrupt",
			task=task.name,
			project=task.get("project"),
			agent_profile=profile_name,
			trigger_source="runner_interrupt",
			summary=f"{task.name}: cancelled (operator interrupt)",
		)
		return
	except Exception as exc:
		# Design 72 — roll back any poisoned transaction BEFORE we try to write
		# the failure state (the FLI-001 guidelines bug: UniqueViolation from a
		# skill insert poisoned the txn, and the error handler then crashed on
		# InFailedSqlTransaction because it tried to save the Task without
		# rolling back first). Rollback is harmless when the txn is healthy.
		# The in-memory `task` doc is unaffected by DB rollback — only the
		# pending DB writes are reverted — so we keep using it directly.
		try:
			frappe.db.rollback()
		except Exception:
			_logger.exception("rollback failed before _run_task_agentic error save")

		issue = _raise_failure_issue(task.name, type(exc).__name__, str(exc)[:300])
		task.result = frappe.as_json({"status": "error", "error_type": type(exc).__name__})
		task.workflow_state = "Blocked"
		# Record the classified reason (e.g. "timeout", "rate_limit") an LLMError
		# carries, so the reconciler can auto-retry transient transport failures
		# instead of stranding the task. None for unclassified errors — those stay
		# Blocked for a human (a non-transient reason is never auto-retried).
		task.blocked_reason = getattr(exc, "reason", None)
		# Design 65d — capture whatever LLM spend accrued before the failure
		# (honest blank if no rates configured), so a blocked task still shows
		# its cost.
		task.cost_usd = task_cost_from_usage(task.name)
		task.duration_ms = _elapsed_ms(started_at)
		frappe.flags.dispatcher_event_source = "runner_error"
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.dispatcher_event_source = None
		frappe.db.commit()
		emit(
			"runner.block",
			task=task.name,
			project=task.get("project"),
			agent_profile=profile_name,
			trigger_source="runner_error",
			summary=f"{task.name}: blocked ({type(exc).__name__}: {str(exc)[:200]})",
			payload={
				"exc_type": type(exc).__name__,
				"blocked_reason": task.blocked_reason,
				"issue": issue,
				"duration_ms": task.duration_ms,
			},
		)
		_post_warroom(task.name, "blocked", {"profile": profile_name, "issue": issue})
		return

	# Design 83b — if the operator `/stop force`d this task while it was finishing,
	# the kill path already set ForceKilled; don't override it with Completed.
	if frappe.db.get_value("Task", task.name, "force_killed_by"):
		return
	task.result = frappe.as_json({"status": "success", "summary": summary})
	task.workflow_state = "Completed"
	task.completed_at = now_datetime()
	# Design 65d — attach the real cost + duration of this turn. cost_usd is the
	# summed LLM Usage Log for this task's session, or None when no rates are set
	# (never a fabricated 0). The project rollup (workflow hook) sums these.
	task.cost_usd = task_cost_from_usage(task.name)
	task.duration_ms = _elapsed_ms(started_at)
	frappe.flags.dispatcher_event_source = "runner_complete"
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.dispatcher_event_source = None
	frappe.db.commit()
	emit(
		"runner.complete",
		task=task.name,
		project=task.get("project"),
		agent_profile=profile_name,
		trigger_source="runner_loop",
		summary=f"{task.name}: completed in {task.duration_ms}ms",
		payload={
			"duration_ms": task.duration_ms,
			"cost_usd": task.cost_usd,
		},
	)


def _task_transition(task: "Task", target_state: str) -> None:
	"""
	Transition an Task to a new workflow state.

	Calls the Frappe Workflow action if the workflow document defines
	a valid transition.  Silently no-ops if no workflow is configured
	or if the transition is not defined — this allows the runner to work
	both with and without a Frappe Workflow on the DocType.

	Args:
		task: The ``Task`` document.
		target_state: The target state name string.
	"""
	try:
		if hasattr(task, "transition") and callable(task.transition):
			task.transition(target_state)
	except Exception:
		# Workflow not configured or transition not allowed — set directly.
		task.workflow_state = target_state
