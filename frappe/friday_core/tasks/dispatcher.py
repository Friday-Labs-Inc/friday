# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Task dispatcher — cron-scheduled task claim and profile assignment.

Registered as ``scheduler_events["cron"]["*/1 * * * *"]`` in ``hooks.py``.

One dispatcher cycle (``tick()``) runs every 60 seconds and:

1. Atomically fetches up to 5 dispatchable, unclaimed ``Pending`` tasks
   using ``SELECT … FOR UPDATE SKIP LOCKED`` so concurrent dispatcher
   instances never double-claim a row.
2. For each task, matches required skills against active Agent Profiles.
3. Assigns the first eligible profile, transitions the task to ``Assigned``,
   and emits an ``agent_task.assigned`` pub/sub event.
4. Logs a warning if a task has no eligible profile (it stays Pending and
   will be retried on the next tick).
"""

import frappe
from frappe.utils import now_datetime


_logger = frappe.logger("friday.tasks.dispatcher")


def tick() -> None:
	"""
	One dispatcher cycle — claim and dispatch up to 5 tasks.

	Safe to call concurrently from multiple scheduler workers;
	``FOR UPDATE SKIP LOCKED`` ensures tasks are claimed exactly once.
	"""
	tasks = _fetch_dispatchable_tasks(limit=5)
	for task_doc in tasks:
		_claim_and_dispatch(task_doc)


def _fetch_dispatchable_tasks(limit: int = 5) -> list["Task"]:
	"""
	Fetch tasks that are dispatchable, unclaimed, and in Pending state.

	Uses ``FOR UPDATE SKIP LOCKED`` so concurrent dispatcher instances
	skip already-locked rows instead of waiting. Ordered by strict
	priority: urgent > high > normal > low, then FIFO by creation time.

	Args:
		limit: Maximum number of tasks to claim in one cycle.

	Returns:
		List of ``Task`` documents (already locked for update).
	"""
	# Frappe's ORM doesn't support FOR UPDATE SKIP LOCKED directly,
	# so we use raw SQL.  The query selects the document names; we then
	# load each document individually so Frappe tracks the row lock.
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabTask`
		WHERE dispatchable = 1
		  AND assigned_to_profile IS NULL
		  AND workflow_state = 'Pending'
		ORDER BY
		  CASE priority
		    WHEN 'urgent' THEN 1
		    WHEN 'high'   THEN 2
		    WHEN 'normal' THEN 3
		    WHEN 'low'    THEN 4
		    ELSE 5
		  END,
		  creation ASC
		LIMIT %(limit)s
		FOR UPDATE SKIP LOCKED
		""",
		{"limit": limit},
		as_dict=True,
	)

	return [frappe.get_doc("Task", row.name) for row in rows]


def _claim_and_dispatch(task_doc: "Task") -> None:
	"""
	Match an eligible profile, atomically assign the task, and emit event.

	Args:
		task_doc: The claimed ``Task`` document (row-locked).
	"""
	eligible = _match_profiles(task_doc)

	if not eligible:
		_logger.warning(
			"No eligible profile for task %s (required_skills=%s)",
			task_doc.name,
			[trow.skill for trow in task_doc.required_skills],
		)
		return

	chosen_profile = eligible[0]

	task_doc.assigned_to_profile = chosen_profile
	task_doc.save(ignore_permissions=True)

	# Publish outside the save transaction via after_commit so the
	# runner picks it up after the DB commit.
	frappe.publish_realtime(
		event="agent_task.assigned",
		message={
			"task_name": task_doc.name,
			"assigned_to_profile": chosen_profile,
			"workflow_state": "Assigned",
		},
		doctype="Task",
		after_commit=True,
	)


def _match_profiles(task_doc: "Task") -> list[str]:
	"""
	Return Agent Profile names whose permitted skills cover all required skills.

	Phase 1 uses exact subset matching: every skill listed in
	``task_doc.required_skills`` must be explicitly permitted by the
	profile.  Profiles with no required skills can handle any task.

	Args:
		task_doc: The ``Task`` document.

	Returns:
		List of matching ``Agent Profile`` names, in creation order.
	"""
	required = {row.skill for row in task_doc.required_skills if row.skill}

	if not required:
		# No required skills — any active profile can take it.
		return [p.name for p in frappe.get_all(
			"Agent Profile",
			filters={"status": "Active"},
			order="creation ASC",
		)]

	active = frappe.get_all(
		"Agent Profile",
		filters={"status": "Active"},
		order="creation ASC",
	)

	matched = []
	for profile_row in active:
		permitted = _load_permitted_skills(profile_row.name)
		if required.issubset(permitted):
			matched.append(profile_row.name)

	return matched


def _load_permitted_skills(profile_name: str) -> set[str]:
	"""
	Return the set of skill names the profile can execute.

	Checks the profile's explicit ``permitted_skills`` table first,
	then falls back to the ``agent_role_profile`` linked on the profile.

	Args:
		profile_name: Name of the ``Agent Profile`` document.

	Returns:
		Frozenset of skill names.
	"""
	profile = frappe.get_doc("Agent Profile", profile_name)

	skills = {row.skill for row in profile.permitted_skills if row.skill}

	if not skills and profile.agent_role_profile:
		try:
			role_profile = frappe.get_doc(
				"Agent Role Profile", profile.agent_role_profile
			)
			skills |= {
				row.skill
				for row in role_profile.get("assigned_roles", [])
				if row.skill
			}
		except Exception:
			# Role profile may not exist or have no assigned_roles — ignore.
			pass

	return skills