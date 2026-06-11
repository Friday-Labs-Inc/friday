# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The `delegate-task` skill — one agent hands work to another (design 57, LOCKED).

PLAIN ENGLISH
=============
Port of Hermes `tools/delegate_tool.py` onto Friday's Task objects. The parent
agent calls this with a title + instructions; we create a durable Task row
(the audit record of who delegated what to whom), run the child agent's own
governed ReAct turn in an ISOLATED session, store its summary on the Task,
and hand that summary back to the parent — which composes the final answer.

Hermes-faithful isolation (Q3): the child sees ONLY the task framing, never
the parent's conversation; the parent sees ONLY the summary. Both sessions
are independently audited.

Locked decisions enforced here: every delegation is a Task row (Q1);
synchronous wait (Q2); depth cap 1 — children cannot delegate (Q4);
named profile wins, else capability auto-match via the existing task
dispatcher's matcher (Q5).
"""

from __future__ import annotations

import re

import frappe

from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

DELEGATE_TASK = "delegate-task"

# Ports Hermes delegate_tool's child instruction ("When finished, provide a
# clear, concise summary of: ... relayed to the parent agent as a summary").
_CHILD_FRAMING = (
	"You are completing a delegated task ({task_name}): {title}\n\n"
	"Instructions:\n{instructions}\n\n"
	"When finished, reply with a clear, concise summary of the outcome — "
	"including the names of any records you created or changed. Your reply "
	"goes back to the delegating agent, not to a human."
)


def delegate_task(skill_name: str, parameters: dict) -> dict:
	"""Create a Task row, run the child agent, return its summary.

	Parameters: `title` + `instructions` (required); `profile` (optional —
	the specialist Agent Profile); `required_skills` (optional list — used
	to auto-match a profile when none is named).
	"""
	ctx = frappe.flags.get("friday_dispatch_context") or {}
	parent_session = ctx.get("session_id") or ""
	parent_profile = ctx.get("agent_profile") or ""

	# Q4 — depth cap 1: a child (running in a task:: session) may not delegate.
	if parent_session.startswith("task::"):
		raise ValueError(
			"delegation depth limit reached — you are already completing a "
			"delegated task; do the work directly instead of delegating again"
		)

	title = (parameters.get("title") or "").strip()
	instructions = (parameters.get("instructions") or "").strip()
	if not title:
		raise ValueError("delegate-task requires a 'title' parameter")
	if not instructions:
		raise ValueError("delegate-task requires an 'instructions' parameter")

	required_skills = _normalise_skill_list(parameters.get("required_skills"))
	child_profile = _resolve_child_profile(
		(parameters.get("profile") or "").strip() or None, required_skills
	)

	# Q1 — the durable audit record, created BEFORE the child runs. State
	# "Executing" (not "Assigned") so the mechanical task machinery does not
	# also pick it up — this handler owns the execution.
	task = frappe.get_doc(
		{
			"doctype": "Task",
			"title": title,
			"description": (
				f"{instructions}\n\n[delegated by {parent_profile!r} "
				f"from session {parent_session!r}]"
			),
			"assigned_to_profile": child_profile,
			"required_skills": [{"skill": s} for s in required_skills],
			"workflow_state": "Executing",
			"started_at": frappe.utils.now_datetime(),
		}
	)
	task.insert(ignore_permissions=True)

	# Q2/Q3 — run the child inline, in an isolated session, through the SAME
	# governed loop as any other turn (its skill calls dispatch under its own
	# profile's permissions). Lazy import: the dispatcher imports this module
	# at its bottom, so a top-level runner import would be circular.
	from frappe.friday_core.agent_runner.runner import run_turn

	child_session = f"task::{task.name}"
	framing = _CHILD_FRAMING.format(task_name=task.name, title=title, instructions=instructions)

	try:
		summary = run_turn(
			profile_name=child_profile,
			session_id=child_session,
			inbound_content=framing,
		)
	except Exception as exc:  # noqa: BLE001 — child failure must not crash the parent turn
		task.result = frappe.as_json({"status": "error", "error_type": type(exc).__name__})
		task.workflow_state = "Blocked"
		task.save(ignore_permissions=True)
		# Type name only (redaction policy) — actionable enough for the model.
		raise ValueError(
			f"delegated task {task.name} failed ({type(exc).__name__}) — "
			f"the task is Blocked; try different instructions or another profile"
		) from exc

	# Task.result is a JSON column (Postgres validates it) — store an envelope
	# like the mechanical runner does, never raw text.
	task.result = frappe.as_json({"status": "success", "summary": summary})
	task.workflow_state = "Completed"
	task.completed_at = frappe.utils.now_datetime()
	task.save(ignore_permissions=True)

	return {
		"result": f"Task {task.name} completed by {child_profile!r}. Summary:\n{summary}",
		"task": task.name,
		"assigned_profile": child_profile,
		"doctype": "Task",
		"record_name": task.name,
	}


def _normalise_skill_list(raw) -> list[str]:
	"""Accept a list of skill names, or a comma/newline string from the model."""
	if not raw:
		return []
	if isinstance(raw, str):
		return [s.strip() for s in re.split(r"[,\n]", raw) if s.strip()]
	return [str(s).strip() for s in raw if str(s).strip()]


def _resolve_child_profile(named: str | None, required_skills: list[str]) -> str:
	"""Q5 — named profile wins; else first Active profile covering the skills."""
	if named:
		if not frappe.db.exists("Agent Profile", named):
			raise ValueError(f"Agent Profile {named!r} not found — name an existing profile or omit it")
		if frappe.db.get_value("Agent Profile", named, "status") != "Active":
			raise ValueError(f"Agent Profile {named!r} is not Active")
		return named

	# Reuse the orchestrator's existing exact-subset matcher rather than
	# duplicating it (it only reads `.required_skills` rows off the doc).
	from frappe.friday_core.tasks.dispatcher import _match_profiles

	probe = frappe._dict(
		required_skills=[frappe._dict(skill=s) for s in required_skills]
	)
	matches = _match_profiles(probe)
	if not matches:
		raise ValueError(
			f"no Active Agent Profile permits all of {required_skills!r} — "
			f"name a 'profile' explicitly or adjust required_skills"
		)
	return matches[0]


register_skill_handler(DELEGATE_TASK, delegate_task)
