# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Provisioning for the `session_search` skill (Design 89). Idempotent; runs on
every migrate. Creates the Skill row (read-only, low risk, no role gate, and
**no `required_doctypes`**) and wires it onto a profile.

WHY NO `Chat Message: read` DOCTYPE GATE (the fix for the organic-load bug):
A `required_doctypes=[Chat Message: read]` gate would drop the skill from every
agent's menu unless a role grants `Chat Message: read` — and that grant is
DOCTYPE-level, so it would ALSO unlock the generic `read-record`/`list-records`
skills on Chat Message, letting an agent read OTHER agents' messages. The
session_search handler instead hard-scopes to the caller's own `agent_profile`
(read from dispatch context, not an LLM parameter — unspoofable), so it needs no
broad doctype grant. Dropping the gate is both the fix AND the more secure choice,
and matches D89's "no special privilege" intent.
"""

from __future__ import annotations

import json

import frappe

_SKILL_NAME = "session_search"

_SKILL = {
	"description": (
		"THE tool for searching your own past conversations / chat history / earlier "
		"messages by full text. Returns the best-matching past messages (content + "
		"session + timestamp), scoped to your own messages."
	),
	"when_to_use": (
		"Use this WHENEVER you're asked to search, look through, recall, or find "
		"anything from past conversations, chat history, earlier messages, or what "
		"was said/decided before — e.g. 'search our past conversations for X', "
		"'what did we decide about Y', 'have I seen this before', 'find where the "
		"user mentioned Z'. This is the ONLY correct tool for conversation/message "
		"history — do NOT reach for generic record-listing tools (like list-records) "
		"for transcript searches; they cannot search message text. Pass a 'query' "
		"(keywords) and an optional 'limit'. You can only search YOUR OWN messages."
	),
	"schema": {
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Keywords to search your past messages for."},
			"limit": {"type": "integer", "description": "Max results (default 10, cap 50)."},
		},
		"required": ["query"],
	},
	# No required_doctypes — see the module docstring. The handler's own-profile
	# scoping is the boundary; a Chat Message read gate would both break the menu
	# and leak cross-agent reads via generic read skills.
	"docs": [],
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
			from friday.friday_core.skills.loader import invalidate_for_profile

			invalidate_for_profile(profile_name)

	return {"skill": _SKILL_NAME, "profile": profile_name}
