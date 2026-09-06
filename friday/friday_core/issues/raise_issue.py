# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Raising Issues from the agent system — the "agent issue tracker" (doc 53 §5).

PLAIN ENGLISH
=============
When an agent's Task goes wrong, the system files an Issue about it — the same
way a human teammate would raise a ticket — so a supervisor can see the holdup
without reading logs. Two triggers:

  1. FAILURE (D6) — the task errored / ran out of memory / timed out / was
     denied. Called from `tasks/runner.py`'s failure handlers.
  2. DEPENDENCY-WAIT (D5) — the task can't run yet because another task it
     `depends_on` isn't finished. The task is parked and an Issue records
     *what* it's waiting on.

Both create an `Issue` row with ``source = "Agent-raised"``. Ordinary work
tickets people file by hand are ``source = "Human-raised"`` — same tracker,
told apart by the `source` field.

These functions are deliberately small and side-effect-light (build a dict,
insert it) so they unit-test without a database — see
`tests/test_issue_tracker.py`. The real behaviour (a real Issue on a real
failed Task) is exercised by the bench e2e tests.
"""

from __future__ import annotations

import frappe

# The Task DocType these Issues point at — renamed from "Agent Task" to "Agent Task"
# in Phase B (doc 53 §7). Kept as a single constant for the dependency lookups
# below; the Link `options` live in issue.json (related_task, waiting_on).
TASK_DOCTYPE = "Agent Task"

# A dependency stops blocking once it reaches one of these terminal states.
# Ported from ERPNext Task.validate_status, which refuses to complete a task
# while a dependency is neither Completed nor Cancelled.
_SETTLED_STATES = ("Completed", "Cancelled")


def unfinished_dependencies(task) -> list[str]:
	"""Return the names of this task's `depends_on` tasks that aren't settled.

	A task is "blocked" when any task it depends on is still in flight (not
	Completed or Cancelled). The caller parks the task and raises a
	`Dependency-Wait` Issue for each blocker.

	`task` is a Task document (or anything with a `depends_on` child list whose
	rows have a `.task` name). Returns an empty list when nothing blocks it.
	"""
	blocked: list[str] = []
	for row in getattr(task, "depends_on", None) or []:
		if not row.task:
			continue
		status = frappe.db.get_value(TASK_DOCTYPE, row.task, "status")
		if status not in _SETTLED_STATES:
			blocked.append(row.task)
	return blocked


def raise_failure_issue(
	task_name: str,
	*,
	error_type: str | None = None,
	details: str | None = None,
	execution_log: str | None = None,
) -> str:
	"""File an Agent-raised ``Failure`` Issue for a task that errored (D6).

	Returns the new Issue's name. ``ignore_permissions=True`` because the
	system is recording its *own* failure — there is no user role for "may
	file the agent's issue", and denying the write would hide the very thing
	it is trying to surface (same reasoning as the audit logs).
	"""
	subject = f"Task {task_name} failed"
	if error_type:
		subject += f": {error_type}"

	issue = frappe.get_doc(
		{
			"doctype": "Agent Issue",
			"source": "Agent-raised",
			"reason": "Failure",
			"status": "Open",
			"subject": subject,
			"description": details or "",
			"related_task": task_name,
			"execution_log": execution_log,
		}
	)
	issue.insert(ignore_permissions=True)

	# Design 72 — record the Issue raise as a trace event so the Lifecycle Trace
	# shows the link from a runner.error event to the Issue ticket without the
	# operator hunting through Issue list.
	try:
		from friday.friday_core.observability import emit

		emit(
			"issue.raised",
			task=task_name,
			trigger_source="failure",
			summary=f"Issue raised: {subject}",
			payload={"issue": issue.name, "error_type": error_type},
		)
	except Exception:
		pass

	return issue.name


def raise_dependency_wait_issue(task_name: str, blocking_task: str) -> str:
	"""File an Agent-raised ``Dependency-Wait`` Issue: a task is blocked (D5).

	Returns the new Issue's name. Raising the Issue is the *record*; parking
	the task and avoiding duplicate Issues per (task, blocker) is the caller's
	job (the runner), kept out of here so this stays a pure builder.
	"""
	issue = frappe.get_doc(
		{
			"doctype": "Agent Issue",
			"source": "Agent-raised",
			"reason": "Dependency-Wait",
			"status": "Open",
			"subject": f"Task {task_name} is waiting on {blocking_task}",
			"description": f"{task_name} depends on {blocking_task}, which is not yet completed.",
			"related_task": task_name,
			"waiting_on": blocking_task,
		}
	)
	issue.insert(ignore_permissions=True)

	try:
		from friday.friday_core.observability import emit

		emit(
			"issue.raised",
			task=task_name,
			trigger_source="dependency_wait",
			summary=f"Issue raised: Dependency-Wait on {blocking_task}",
			payload={"issue": issue.name, "waiting_on": blocking_task},
		)
	except Exception:
		pass

	return issue.name
