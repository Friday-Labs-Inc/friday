# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-command provisioning for the delegate-task skill (design 57).

Same pattern as `bootstrap_brand`: an "Agent Delegator" role with exactly the
permissions delegation needs (create/read/write on Task — the handler creates
the row, then updates result/state), the Skill row with its model-facing
schema, and the profile wiring. Idempotent.

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_delegate.provision
"""

from __future__ import annotations

import json

import frappe

DELEGATOR_ROLE = "Agent Delegator"

_SKILL = {
	"skill_name": "delegate-task",
	"description": (
		"Delegate a self-contained subtask to another agent and receive its "
		"summary back. Creates an audited Task record, runs the specialist "
		"agent in an isolated session, and returns its concise summary so you "
		"can compose the final answer."
	),
	"when_to_use": (
		"Use when a piece of work benefits from a specialist profile or a "
		"clean separate context (research, drafting, a multi-step subtask). "
		"Give complete, self-contained instructions — the specialist cannot "
		"see this conversation. Do NOT delegate trivial steps you can do "
		"directly, and do not delegate while you are completing a delegated "
		"task yourself."
	),
	"parameters_schema": {
		"type": "object",
		"properties": {
			"title": {"type": "string", "description": "Short name for the subtask, e.g. 'Draft taglines for Loop Coffee'."},
			"instructions": {"type": "string", "description": "Complete, self-contained instructions for the specialist — include all context it needs; it cannot see this conversation."},
			"profile": {"type": "string", "description": "The specialist Agent Profile to use, e.g. 'Copywriter'. Omit to auto-match by required_skills."},
			"required_skills": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Skill names the specialist must be permitted to use (for auto-matching when no profile is named).",
			},
		},
		"required": ["title", "instructions"],
	},
	"required_doctypes": [{"target_doctype": "Task", "operation": "create"}],
}

_ROLE_PERMS = {"Task": {"create": 1, "read": 1, "write": 1}}


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, perms, the Skill row, and profile wiring. Idempotent."""
	if not frappe.db.exists("Role", DELEGATOR_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": DELEGATOR_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		if not frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": DELEGATOR_ROLE}):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": target_doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": DELEGATOR_ROLE,
					"permlevel": 0,
					**ptypes,
				}
			).insert(ignore_permissions=True)

	skill_name = _SKILL["skill_name"]
	if frappe.db.exists("Skill", skill_name):
		skill = frappe.get_doc("Skill", skill_name)
	else:
		skill = frappe.new_doc("Skill")
		skill.skill_name = skill_name
	skill.description = _SKILL["description"]
	skill.when_to_use = _SKILL["when_to_use"]
	skill.parameters_schema = json.dumps(_SKILL["parameters_schema"])
	skill.risk_level = "low"
	skill.requires_approval = 0
	skill.status = "Active"
	skill.required_doctypes = []
	for req in _SKILL["required_doctypes"]:
		skill.append("required_doctypes", req)
	skill.save(ignore_permissions=True)

	if not frappe.db.exists("Agent Profile", profile_name):
		frappe.throw(f"Agent Profile {profile_name!r} not found — run `bench friday setup` first.")
	profile = frappe.get_doc("Agent Profile", profile_name)
	if DELEGATOR_ROLE not in {row.role for row in (profile.assigned_roles or [])}:
		profile.append("assigned_roles", {"role": DELEGATOR_ROLE})
	if skill_name not in {row.skill for row in (profile.permitted_skills or [])}:
		profile.append("permitted_skills", {"skill": skill_name})
	profile.save(ignore_permissions=True)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	frappe.db.commit()

	summary = {"role": DELEGATOR_ROLE, "skill": skill_name, "profile": profile_name}
	print(f"✓ Delegation provisioned: {summary}")
	return summary
