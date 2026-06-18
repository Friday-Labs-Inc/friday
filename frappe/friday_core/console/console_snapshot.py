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

	# Merge legacy Project tiles with Design 75 Brand Brief tiles in the
	# unscoped view. When the user has scoped to a specific Project, briefs
	# stay out (they're a separate work-item plane, not nested under a Project).
	projects = _projects(project)
	if not project:
		projects = projects + _brand_brief_tiles()

	return {
		"generated_at": frappe.utils.now(),
		"health": pipeline_health(),
		"projects": projects,
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


def _brand_brief_tiles() -> list[dict]:
	"""Render Brand Briefs the metadata engine has touched (Design 75) as
	project tiles, so the new pipeline shows up in the console alongside the
	legacy Project view. Only briefs with at least one engine Task are listed;
	tiles are ordered by most-recent task activity so today's work surfaces
	at the top. The JS uses ``kind="brand_brief"`` to route a click to the
	Brand Brief form instead of trying to scope tasks by project.
	"""
	# Single Task query: get every engine Task on a Brand Brief, aggregate in
	# Python. This both filters out briefs the engine never touched (no noise)
	# and gives us the per-brief "last activity" timestamp for ordering.
	tasks = frappe.get_all(
		"Task",
		filters={"work_item_doctype": "Brand Brief"},
		fields=["work_item_name", "workflow_state", "modified"],
	)
	if not tasks:
		return []

	rollup: dict[str, dict] = {}  # brief -> {total, completed, last_activity}
	for t in tasks:
		brief = t.work_item_name
		if not brief:
			continue
		row = rollup.setdefault(brief, {"total": 0, "completed": 0, "last_activity": t.modified})
		row["total"] += 1
		if t.workflow_state == "Completed":
			row["completed"] += 1
		if t.modified and (not row["last_activity"] or t.modified > row["last_activity"]):
			row["last_activity"] = t.modified

	# Most-recently-active first; cap at the same limit as legacy Projects.
	brief_names = sorted(rollup, key=lambda n: rollup[n]["last_activity"], reverse=True)[:PROJECTS_LIMIT]
	briefs = {
		b.name: b
		for b in frappe.get_all(
			"Brand Brief",
			filters={"name": ["in", brief_names]},
			fields=["name", "business_name", "workflow_state"],
		)
	}

	tiles: list[dict] = []
	for brief_name in brief_names:
		b = briefs.get(brief_name)
		if not b:
			continue
		row = rollup[brief_name]
		total, completed = row["total"], row["completed"]
		pct = int(round(completed / total * 100)) if total else 0
		tiles.append(
			{
				"name": b.name,
				"project_name": b.business_name or b.name,
				"status": "Completed" if b.workflow_state == "Delivered" else "Open",
				"priority": "",
				"percent_complete": pct,
				"total_tasks": total,
				"completed_tasks": completed,
				"actual_cost_usd": 0,
				"kind": "brand_brief",
			}
		)
	return tiles


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
