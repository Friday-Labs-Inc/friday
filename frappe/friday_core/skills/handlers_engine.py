# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Generic engine skills (Design 75 Phase 1.1) — domain-agnostic.

`get-phase-outputs` lets an agent read what the EARLIER phases of the same
work-item produced. The metadata engine runs each phase as its own Task; each
agent's reply is stored in that Task's `result`. A later phase (e.g. a gate
prep that summarises prior work for the client, or a build-out that needs the
chosen direction's detail) needs to SEE those earlier outputs — otherwise it
only has the original brief and writes thin, generic copy.

This is a *generic* primitive: it knows nothing about brands. Any future domain
(data-centre ops, research) gets the same "read my earlier phases" capability
for free. The handler recovers the current work-item from the executing Task
(the dispatch context carries `session_id = "task::<task_name>"`), so the model
can call it with no arguments; it may also pass `work_item` explicitly.
"""

from __future__ import annotations

import json

import frappe
from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

GET_PHASE_OUTPUTS = "get-phase-outputs"


def get_phase_outputs(skill_name: str, parameters: dict) -> dict:
	"""Return the completed earlier phases of the current (or named) work-item.

	Contract (dispatcher): returns a dict whose `result` string is what the
	model sees. Never raises for recoverable conditions — an empty/contextless
	call returns a helpful message, not an exception.
	"""
	params = parameters or {}
	work_item_doctype = params.get("work_item_doctype")
	work_item_name = params.get("work_item") or params.get("work_item_name")

	# When the model didn't name a work-item, recover it from the executing Task.
	if not work_item_name:
		ctx = frappe.flags.get("friday_dispatch_context") or {}
		session = ctx.get("session_id") or ""
		if session.startswith("task::"):
			task_name = session.removeprefix("task::")
			row = frappe.db.get_value(
				"Task", task_name, ["work_item_doctype", "work_item_name"], as_dict=True
			)
			if row:
				work_item_doctype = work_item_doctype or row.work_item_doctype
				work_item_name = work_item_name or row.work_item_name

	if not work_item_name:
		return {
			"result": (
				"No work item in context. This skill reads the earlier phases of a "
				"pipeline work item — call it from within a pipeline task, or pass "
				"`work_item` (e.g. the brief id)."
			)
		}

	filters = {"work_item_name": work_item_name, "workflow_state": "Completed"}
	if work_item_doctype:
		filters["work_item_doctype"] = work_item_doctype
	rows = frappe.get_all(
		"Task",
		filters=filters,
		fields=["phase_key", "assigned_to_profile", "result"],
		order_by="creation asc",
	)

	chunks = []
	for r in rows:
		body = _summary_text(r.get("result"))
		if not body:
			continue
		phase = r.get("phase_key") or "(phase)"
		by = r.get("assigned_to_profile") or "agent"
		chunks.append(f"### {phase} — by {by}\n{body}")

	if not chunks:
		return {"result": f"No completed earlier phases for {work_item_name} yet."}

	header = f"Outputs from the earlier completed phases of {work_item_name}:"
	return {"result": header + "\n\n" + "\n\n".join(chunks)}


def _summary_text(result) -> str:
	"""Pull the agent's human-readable output from a Task.result JSON blob.

	Task.result is JSON like {"status": "success", "summary": "<the reply>"}.
	Be tolerant: accept a dict, a JSON string, or a bare string.
	"""
	if not result:
		return ""
	data = result
	if isinstance(result, str):
		try:
			data = json.loads(result)
		except (ValueError, TypeError):
			return result.strip()
	if isinstance(data, dict):
		return str(data.get("summary") or data.get("result") or data).strip()
	return str(data).strip()


register_skill_handler(GET_PHASE_OUTPUTS, get_phase_outputs)
