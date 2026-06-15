# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The `remember` skill — the agent writes one durable memory (design 59, Q3).

Per the locked design: explicit writes only — the agent calls this when it
learns a durable fact/preference/decision (guided by the skill's when_to_use,
which ports Hermes' memory norms). The profile and session come from the
dispatch-context flags (the seam built for delegation), so a memory is always
attributed to the agent that learned it and the session it was learned in.
"""

from __future__ import annotations

import frappe
from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

REMEMBER = "remember"


def remember(skill_name: str, parameters: dict) -> dict:
	"""Persist one Agent Memory row. Validation errors raise (loop A.3)."""
	memory = (parameters.get("memory") or "").strip()
	if not memory:
		raise ValueError("remember requires a 'memory' parameter — the fact to store, one sentence")
	if len(memory) > 500:
		raise ValueError("memory too long — store ONE durable fact per call, under 500 characters")

	ctx = frappe.flags.get("friday_dispatch_context") or {}
	profile = ctx.get("agent_profile") or ""
	if not profile:
		raise ValueError("remember could not determine the calling agent profile")

	session_id = ctx.get("session_id") or ""
	# Design 73 — tag the memory with the project it was learned in (if any), so
	# recall in a project room stays scoped to that project. Blank = global.
	from frappe.friday_core.llm.memory import project_for_session

	doc = frappe.get_doc(
		{
			"doctype": "Agent Memory",
			"memory": memory,
			"agent_profile": profile,
			"project": project_for_session(session_id),
			"subject": (parameters.get("subject") or "").strip(),
			"source_session": session_id,
			"status": "Active",
		}
	)
	doc.insert(ignore_permissions=True)

	return {
		"result": f"Remembered ({doc.name}): {memory}",
		"doctype": "Agent Memory",
		"record_name": doc.name,
	}


register_skill_handler(REMEMBER, remember)
