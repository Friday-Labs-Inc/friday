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
from friday.friday_core.agent_runner.dispatcher import register_skill_handler

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

	# Design 80 — which store: facts about the USER vs the agent's own notes.
	memory_type = (parameters.get("memory_type") or "general").strip()
	if memory_type not in ("general", "user_profile"):
		memory_type = "general"

	session_id = ctx.get("session_id") or ""
	# Design 73 — tag the memory with the project it was learned in (if any), so
	# recall in a project room stays scoped to that project. Blank = global.
	# Design 95 — scope="global" stores the memory UNTAGGED so it is recallable
	# on every future project: for cross-project lessons (craft, conventions,
	# taste), never for one client's private facts.
	from friday.friday_core.llm.memory import project_for_session

	scope = (parameters.get("scope") or "project").strip().lower()
	project = None if scope == "global" else project_for_session(session_id)

	doc = frappe.get_doc(
		{
			"doctype": "Agent Memory",
			"memory": memory,
			"agent_profile": profile,
			"project": project,
			"subject": (parameters.get("subject") or "").strip(),
			"memory_type": memory_type,
			"source_session": session_id,
			"status": "Active",
		}
	)
	doc.insert(ignore_permissions=True)

	# Design 80 step 2b-2 — embed the new memory (async, after commit) so semantic
	# recall can find it. Best-effort; no embedding just means keyword+recency.
	from friday.friday_core.llm.embed import enqueue_embed

	enqueue_embed(doc.name)

	return {
		"result": f"Remembered ({doc.name}): {memory}",
		"doctype": "Agent Memory",
		"record_name": doc.name,
	}


register_skill_handler(REMEMBER, remember)
