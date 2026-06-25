# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Provisioning for the `session_search` skill (Design 89). Idempotent; runs on
every migrate. Creates the Skill row (read-only, low risk, no role gate — an
agent searching its OWN transcripts needs no special privilege) and grants the
agent's existing skill set Chat Message READ, then wires it onto a profile.
"""

from __future__ import annotations

import json

import frappe

_SKILL_NAME = "session_search"

_SKILL = {
	"description": (
		"Search your own past conversations (Chat Message history) by full text. "
		"Returns the best-matching past messages with their session + timestamp."
	),
	"when_to_use": (
		"Call this when you need to recall something from an earlier conversation — "
		"'what did we decide about X', 'have I seen this error before', 'remind me "
		"what the user asked last week'. Pass a 'query' (keywords) and an optional "
		"'limit'. You can only search YOUR OWN messages."
	),
	"schema": {
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Keywords to search your past messages for."},
			"limit": {"type": "integer", "description": "Max results (default 10, cap 50)."},
		},
		"required": ["query"],
	},
	"docs": [{"target_doctype": "Chat Message", "operation": "read"}],
}


def provision(profile_name: str = "Friday") -> dict:
	"""Upsert the Skill row + wire it onto `profile_name`. Idempotent."""
	skill = (
		frappe.get_doc("Skill", _SKILL_NAME)
		if frappe.db.exists("Skill", _SKILL_NAME)
		else frappe.new_doc("Skill")
	)
	skill.skill_name = _SKILL_NAME
	skill.description = _SKILL["description"]
	skill.when_to_use = _SKILL["when_to_use"]
	skill.parameters_schema = json.dumps(_SKILL["schema"])
	skill.risk_level = "low"
	skill.requires_approval = 0
	skill.status = "Active"
	skill.required_doctypes = []
	for req in _SKILL["docs"]:
		if frappe.db.exists("DocType", req["target_doctype"]):
			skill.append("required_doctypes", req)
	skill.save(ignore_permissions=True)

	if frappe.db.exists("Agent Profile", profile_name):
		profile = frappe.get_doc("Agent Profile", profile_name)
		if _SKILL_NAME not in {s.skill for s in (profile.permitted_skills or [])}:
			profile.append("permitted_skills", {"skill": _SKILL_NAME})
			profile.save(ignore_permissions=True)
			from frappe.friday_core.skills.loader import invalidate_for_profile

			invalidate_for_profile(profile_name)

	return {"skill": _SKILL_NAME, "profile": profile_name}
