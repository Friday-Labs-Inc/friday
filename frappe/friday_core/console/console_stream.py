# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Live activity stream for the Project Console (design 65c, Q6).

The console page shows what is happening *right now*. Rather than poll a REST
endpoint every few seconds (Hermes' approach — 5s `setInterval`), we PUSH each
Task transition to the Desk over Frappe's realtime layer the instant it happens.

``publish_activity(task, state)`` is called from the same
``tasks/workflow._watch_transition`` seam that already posts to the War Room
and writes the report-back — one more sink, fail-soft. It emits a single
``frappe:project_activity`` event with no room/user/doctype args, which Frappe
resolves to the site-wide ``"all"`` room: **every System User Desk client
(operators and agents alike) receives it with no client-side subscription**
(see ``frappe/realtime.py::get_site_room`` and ``realtime/handlers.js`` —
System Users are auto-joined to ``"all"`` on connect).

Why this is the surpass-Hermes axis
------------------------------------
Hermes' dashboard polls a flat list of *sessions*. Friday pushes a *project-
scoped* feed of governed task transitions, each carrying the agent that did the
work (65a identity) and the project it belongs to. Push, not poll; a project
plane, not a session list. Per ``feedback_hermes-floor-not-ceiling``.

Never raises
------------
A realtime hiccup must not break a task save. Every failure is swallowed with a
warning log — the 30s ``console_snapshot`` poll on the page is the correctness
backstop if a frame is ever dropped (same "state is truth" principle as the
Design 61 reconciler).
"""

from __future__ import annotations

import frappe

ACTIVITY_EVENT = "frappe:project_activity"

# States in which a task is no longer actively running — used by the page to
# style the feed row (a finish vs. an in-flight update).
TERMINAL_STATES = frozenset({"Review", "Completed", "Blocked", "Cancelled"})

_logger = frappe.logger("friday.console")


def publish_activity(task, state: str) -> None:
	"""Push one Task transition to every Desk console client. Never raises.

	Args:
		task: the Task document (doc-like with name/title/assigned_to_profile/project).
		state: the new ``workflow_state``.
	"""
	try:
		payload = {
			"task": task.get("name"),
			"title": task.get("title"),
			"state": state,
			"profile": task.get("assigned_to_profile"),
			"project": task.get("project"),
			"is_terminal": state in TERMINAL_STATES,
			"ts": frappe.utils.now(),
		}
		# No room/user/doctype args -> site room "all" -> all System User Desk
		# clients. after_commit is irrelevant here (no DB write) but the runner
		# calls this mid-transaction, so leave the default (immediate) — the
		# page tolerates an event that slightly precedes commit because its 30s
		# snapshot reconciles from committed state anyway.
		frappe.publish_realtime(ACTIVITY_EVENT, payload)
	except Exception:
		_logger.warning("console_stream: failed to publish activity for %s", task.get("name"))
