# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Agent report-back (design 62, Q3).

When a Task reaches a terminal state and it knows the conversation that
asked for it (``originating_session``), the agent that did the work
writes ONE outbound Chat Message back to that session. The human who
said "@Friday plan the pipeline" gets a direct "done" in their own
channel — not just a line in the shared War Room.

Independently-dispatched pipeline tasks with no originating session
(e.g. RandomPack projects, whose report-back is the backend write-back)
write nothing here — the War Room post remains their only signal.

Never raises: a report-back failure must not break the task pipeline
(the War Room / connector-bridge defensiveness pattern).
"""

from __future__ import annotations

import frappe

# States at which we tell the requester something final happened. Executing /
# Assigned / Pending are in-flight and produce no chat reply (the War Room
# ticker covers progress).
TERMINAL_STATES = frozenset({"Completed", "Review", "Blocked", "Cancelled"})

_logger = frappe.logger("friday.tasks.report_back")

# report_back runs INSIDE the caller's task-save transaction (it is invoked from
# the Task terminal-state handler). On Postgres a failed Chat Message insert aborts
# that whole tx — so swallowing the Python error is not enough: the task's own save
# would then fail with InFailedSqlTransaction. This savepoint scopes the failure so
# we can roll back JUST the insert and hand the caller a clean tx.
_SAVEPOINT = "friday_report_back"


def report_back(task, state: str) -> None:
	"""Write one outbound Chat Message to the task's originating session.

	No-op when the state is non-terminal or the task has no origin.
	"""
	if state not in TERMINAL_STATES:
		return

	session_id = (task.get("originating_session") or "").strip()
	if not session_id:
		return  # not born from a conversation — War Room post is the only signal

	frappe.db.savepoint(_SAVEPOINT)
	try:
		platform = (task.get("originating_platform") or "").strip() or "cli"
		profile = (task.get("assigned_to_profile") or "").strip() or "Friday"
		content = _compose_reply(task, state, profile)

		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"session_id": session_id,
				"platform": platform,
				"direction": "outbound",
				"sender_id": profile,
				"agent_profile": profile,
				"content": content,
				"timestamp": frappe.utils.now_datetime(),
				"processed": 1,
			}
		).insert(ignore_permissions=True)

		# Nudge any live surface subscribed to this session. Global broadcast
		# is intentional and matches the gateway's chat.outbound publish: the
		# payload carries session_id and surfaces filter to their own sessions
		# client-side. There is no per-session Frappe "room" to scope to.
		frappe.publish_realtime(  # nosemgrep: frappe-realtime-pick-room
			event="chat.outbound",
			message={"session_id": session_id, "platform": platform},
			after_commit=True,
		)
	except Exception:
		# Roll back to the savepoint FIRST — this un-aborts the caller's tx so its
		# own task.save() (and the log_error below) still commit. Then record it.
		frappe.db.rollback(save_point=_SAVEPOINT)
		_logger.exception("report_back failed for task %s", getattr(task, "name", "?"))
		frappe.log_error(title=f"friday.report_back failed: {getattr(task, 'name', '?')}")


def _compose_reply(task, state: str, profile: str) -> str:
	"""Compose the human-facing reply, authored by the agent profile."""
	title = task.get("title") or task.name
	summary = _result_summary(task)

	if state in ("Completed", "Review"):
		head = f'✅ {profile} finished "{title}" ({task.name})'
		return f"{head}:\n{summary}" if summary else head
	if state == "Blocked":
		head = f"⚠️ {profile} couldn't finish \"{title}\" ({task.name}) — it's blocked and needs attention."
		return f"{head}\n{summary}" if summary else head
	# Cancelled
	return f'🛑 "{title}" ({task.name}) was cancelled.'


def _result_summary(task) -> str:
	"""Pull the human-readable summary out of the task's result envelope."""
	raw = task.get("result")
	if not raw:
		return ""
	import json

	data = raw if isinstance(raw, dict) else {}
	if isinstance(raw, str):
		try:
			data = json.loads(raw)
		except (TypeError, ValueError):
			return str(raw)[:1000]
	return str(data.get("summary") or "")[:2000]
