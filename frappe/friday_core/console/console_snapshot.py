# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The Project Console snapshot endpoint (design 65c, Q6 — poll fallback + seed).

The console is realtime-PUSH first (``console_stream``). This whitelisted
endpoint is the other half: it seeds the page on open and is re-polled every
30s as a correctness backstop, so a dropped realtime frame self-heals on the
next poll (the same "state is the source of truth" principle as the Design 61
reconciler — the push is the optimization, the snapshot is the truth).

One call returns everything the three console zones need:
  - ``health``         — the Pipeline Health verdict (reused verbatim from 61b;
                          the header status strip).
  - ``projects``       — per-project rollup cards (status, %-complete, counts).
  - ``active_tasks``   — what is in flight right now (Assigned / Executing).
  - ``recent_activity``— the latest terminal transitions (the seed for the feed
                          before any live event arrives).

Pass ``project`` to scope every section to one project (the per-project view).

Fail-loud envelope
------------------
If any data path errors, we log loudly and return an envelope with an ``error``
string and a ``down`` health verdict — never a silent empty "all good" page.
Mirrors ``pipeline_health``'s contract.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.console.console_stream import TERMINAL_STATES
from frappe.friday_core.health.pipeline_health import pipeline_health

ACTIVE_STATES = ("Assigned", "Executing")
RECENT_LIMIT = 20
PROJECTS_LIMIT = 50


@frappe.whitelist()
def console_snapshot(project: str | None = None) -> dict:
	"""Return the full console snapshot. Optionally scoped to one ``project``.

	Whitelisted; permission is the same low bar as ``pipeline_health`` — any
	authenticated Desk user. No PII, just operational state.
	"""
	try:
		return _build(project)
	except Exception as exc:
		frappe.log_error(title="friday.console console_snapshot failed")
		return {
			"generated_at": frappe.utils.now(),
			"error": f"{type(exc).__name__}: {str(exc)[:300]}",
			"health": {"verdict": "down", "error": "snapshot failed"},
			"projects": [],
			"active_tasks": [],
			"recent_activity": [],
		}


def _build(project: str | None) -> dict:
	task_filter = {"project": project} if project else {}

	return {
		"generated_at": frappe.utils.now(),
		"health": pipeline_health(),
		"projects": _projects(project),
		"active_tasks": _active_tasks(task_filter),
		"recent_activity": _recent_activity(task_filter),
	}


def _projects(project: str | None) -> list[dict]:
	filters = {"name": project} if project else {}
	return frappe.get_all(
		"Project",
		filters=filters,
		fields=[
			"name",
			"project_name",
			"status",
			"priority",
			"percent_complete",
			"total_tasks",
			"completed_tasks",
			"actual_cost_usd",
		],
		order_by="modified desc",
		limit=PROJECTS_LIMIT,
	)


def _active_tasks(task_filter: dict) -> list[dict]:
	return frappe.get_all(
		"Task",
		filters={**task_filter, "workflow_state": ["in", list(ACTIVE_STATES)]},
		fields=["name", "title", "project", "assigned_to_profile", "workflow_state", "started_at"],
		order_by="started_at asc",
	)


def _recent_activity(task_filter: dict) -> list[dict]:
	return frappe.get_all(
		"Task",
		filters={**task_filter, "workflow_state": ["in", list(TERMINAL_STATES)]},
		fields=[
			"name",
			"title",
			"project",
			"assigned_to_profile",
			"workflow_state",
			"modified",
			"duration_ms",
		],
		order_by="modified desc",
		limit=RECENT_LIMIT,
	)
