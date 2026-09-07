# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Progress + cost rollup for Projects and Tasks (design 65d).

65a defined the read-only rollup fields (Project.percent_complete /
total_tasks / completed_tasks / actual_cost_usd / actual_start_date /
actual_end_date, and Task.progress / cost_usd / duration_ms); 65b/65c render
them in the views and console. This module is what actually *fills* them.

Two derivations:

- **Task progress** — a 0/50/100 bar value from the workflow state, so the
  Gantt/Kanban/console show a sensible bar without per-task estimation. Set
  alongside the other derived fields in ``tasks/workflow.on_state_change``.

- **Project rollup** — recomputed from the project's child Tasks on every task
  transition (``_watch_transition``): task counts, %-complete, actual start/end
  dates, and **actual cost summed from the per-task cost_usd**. Written with a
  single ``frappe.db.set_value`` (no ``doc.save()``) so it fires no Task hooks
  and cannot recurse.

The honest-cost rule (design Q8): a task's ``cost_usd`` comes from the
``LLM Usage Log`` rows already recorded per turn under
``session_id = "task::<name>"``. If the operator hasn't set per-million rates
on the ``LLM Provider``, ``estimated_cost`` is ``None`` on every row, the sum is
``None``, and the field stays blank — **never a fabricated 0**.
"""

from __future__ import annotations

import frappe

# A task counts toward %-complete when it has reached a "done" terminal state.
# Blocked is deliberately NOT here — a blocked task is stuck, not complete.
COMPLETED_STATES = frozenset({"Completed", "Review", "Cancelled"})

# States that mean the project is not finished yet. While ANY child sits in one
# of these (including Blocked — stuck counts as unfinished), we don't stamp an
# actual_end_date.
NONTERMINAL_STATES = frozenset({"Pending", "Assigned", "Executing", "Blocked"})

# The 0/50/100 progress-bar value per state.
_PROGRESS = {
	"Pending": 0,
	"Assigned": 0,
	"Executing": 50,
	"Blocked": 50,
	"Review": 100,
	"Completed": 100,
	"Cancelled": 100,
}


def progress_for_state(state: str | None) -> int:
	"""Return the 0/50/100 progress-bar value for a workflow state."""
	return _PROGRESS.get(state or "", 0)


def task_cost_from_usage(task_name: str) -> float | None:
	"""Sum the recorded LLM cost for one task's turn.

	Reads the ``LLM Usage Log`` rows written per ``provider.chat()`` call under
	``session_id = "task::<name>"``. Returns the summed ``estimated_cost``, or
	``None`` when no row carried a cost (no rates configured) — never 0.
	"""
	rows = frappe.get_all(
		"LLM Usage Log",
		filters={"session_id": f"task::{task_name}"},
		fields=["estimated_cost"],
	)
	costs = [r.get("estimated_cost") for r in rows if r.get("estimated_cost") is not None]
	return sum(costs) if costs else None


def recompute_project_rollup(project_name: str | None) -> None:
	"""Recompute a project's derived rollup fields from its child Tasks.

	Idempotent and side-effect-free beyond the single Project write. No-ops when
	the project doesn't exist (e.g. a task with no project, or mid-delete).
	"""
	if not project_name or not frappe.db.exists("Agent Project", project_name):
		return

	tasks = frappe.get_all(
		"Agent Task",
		filters={"project": project_name},
		fields=["workflow_state", "cost_usd", "started_at", "completed_at"],
	)

	total = len(tasks)
	completed = sum(1 for t in tasks if t.get("workflow_state") in COMPLETED_STATES)
	percent = round(completed / total * 100, 1) if total else 0

	costs = [t.get("cost_usd") for t in tasks if t.get("cost_usd") is not None]
	actual_cost = sum(costs) if costs else None

	starts = [t.get("started_at") for t in tasks if t.get("started_at")]
	actual_start = frappe.utils.getdate(min(starts)) if starts else None

	# Only stamp an end date once NOTHING is still pending/running/blocked.
	all_done = total > 0 and not any(t.get("workflow_state") in NONTERMINAL_STATES for t in tasks)
	ends = [t.get("completed_at") for t in tasks if t.get("completed_at")]
	actual_end = frappe.utils.getdate(max(ends)) if (all_done and ends) else None

	frappe.db.set_value(
		"Agent Project",
		project_name,
		{
			"total_tasks": total,
			"completed_tasks": completed,
			"percent_complete": percent,
			"actual_cost_usd": actual_cost,
			"actual_start_date": actual_start,
			"actual_end_date": actual_end,
		},
		update_modified=False,
	)
