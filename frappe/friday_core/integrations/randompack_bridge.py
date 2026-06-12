# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The state bridge — Friday Task transitions → RandomPack write-back (design 60, Q5).

One module owns the mapping; it is called from the Task workflow hook on
every transition and NEVER raises (the client already never raises; this
adds a belt-and-braces guard so a mapping bug can't break a save).

  Executing                → update_task_progress(in_progress)
  Completed                → update_task_progress(completed, progress=100)
                             + the result summary as a project note
  Completed gate-prep task → request_gate_open (signal-only; humans own it)
  Blocked                  → Pending Review + note (the locked needs-human
                             shape; the Issue lands in the War Room)
  Cancelled                → terminal note

Write-back only fires for tasks that carry a backend phase slug
(`Task.backend_ref`) under a project linked to the backend
(`Project.backend_ref`) — purely internal tasks stay internal.
"""

from __future__ import annotations

import json

import frappe

from frappe.friday_core.integrations import randompack_client as client

# gate-prep phase slug → the gate it prepares.
_GATE_PREP = {"gate1_prep": "gate1", "gate2_prep": "gate2"}

_STATUS_MAP = {
	"Executing": "in_progress",
	"Completed": "completed",
	"Cancelled": "cancelled",
}


def on_task_transition(task, state: str) -> None:
	"""Mirror one Friday Task transition to the backend. Never raises."""
	try:
		phase = task.get("backend_ref")
		if not phase or not task.get("project"):
			return
		project_ref = frappe.db.get_value("Project", task.project, "backend_ref")
		if not project_ref:
			return

		task_ref = f"{project_ref}:{phase}"

		if state == "Blocked":
			client.signal_pending_review(
				task_ref,
				issue_name="see FRIDAY_WAR_ROOM",
				summary=f"{task.title} is blocked and needs a human decision.",
			)
			return

		status = _STATUS_MAP.get(state)
		if not status:
			return

		client.update_task_progress(
			task_ref,
			status=status,
			progress=100 if state == "Completed" else None,
		)

		if state == "Completed":
			summary = _result_summary(task)
			if summary:
				client.post_project_note(
					project_ref, note=f"[{phase}] completed:\n{summary[:2000]}", task_ref=task_ref
				)
			gate = _GATE_PREP.get(phase)
			if gate:
				client.request_gate_open(
					project_ref, gate=gate, summary=f"{task.title} is ready for client review."
				)
	except Exception:  # noqa: BLE001 — write-back must never break a task save
		frappe.log_error(title="friday.randompack bridge failed")


def _result_summary(task) -> str:
	raw = task.get("result")
	if not raw:
		return ""
	data = raw if isinstance(raw, dict) else {}
	if isinstance(raw, str):
		try:
			data = json.loads(raw)
		except (TypeError, ValueError):
			return str(raw)
	return str(data.get("summary") or "")
