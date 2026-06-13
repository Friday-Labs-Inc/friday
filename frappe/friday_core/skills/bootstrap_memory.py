# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-command provisioning for the memory skill (design 59).

Same pattern as the other bootstraps: a "Memory Agent" role with exactly what
memory needs (create+read on Agent Memory), the `remember` Skill row, and the
profile wiring. Idempotent.

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_memory.provision
"""

from __future__ import annotations

import json

import frappe

MEMORY_ROLE = "Memory Agent"

_SKILL = {
	"skill_name": "remember",
	"description": (
		"Store ONE durable fact, preference, or decision in your persistent "
		"memory so you know it in every future conversation. Examples: a "
		"client's taste ('Loop Coffee hates serif fonts'), a decision "
		"('BB-0001 shortlisted Midnight Roast'), a standing instruction."
	),
	"when_to_use": (
		"Use when you learn something durable that future conversations need: "
		"client preferences, decisions made, standing facts. Also use when the "
		"user explicitly says 'remember ...'. Do NOT store conversation "
		"minutiae, things already in your memory context, or anything "
		"temporary. One fact per call; set 'subject' to the client or record "
		"ID it concerns (e.g. 'BB-0001') so the team can filter it in Desk."
	),
	"parameters_schema": {
		"type": "object",
		"properties": {
			"memory": {
				"type": "string",
				"description": "The fact to remember — ONE sentence, under 500 characters.",
			},
			"subject": {
				"type": "string",
				"description": "Optional grouping tag: a client name or record ID like 'BB-0001'.",
			},
		},
		"required": ["memory"],
	},
	"required_doctypes": [{"target_doctype": "Agent Memory", "operation": "create"}],
}

# read: lets @-reference gating + future recall queries pass for this role too.
_ROLE_PERMS = {"Agent Memory": {"create": 1, "read": 1}}


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, perms, the Skill row, and profile wiring. Idempotent."""
	if not frappe.db.exists("Role", MEMORY_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": MEMORY_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		if not frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": MEMORY_ROLE}):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": target_doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": MEMORY_ROLE,
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
		frappe.throw(
			frappe._("Agent Profile {0} not found — run `bench friday setup` first.").format(profile_name)
		)
	profile = frappe.get_doc("Agent Profile", profile_name)
	if MEMORY_ROLE not in {row.role for row in (profile.assigned_roles or [])}:
		profile.append("assigned_roles", {"role": MEMORY_ROLE})
	if skill_name not in {row.skill for row in (profile.permitted_skills or [])}:
		profile.append("permitted_skills", {"skill": skill_name})
	profile.save(ignore_permissions=True)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	# Manual commit is required: provision() runs via `bench execute` (no
	# request lifecycle to commit for us) and must persist before returning.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {"role": MEMORY_ROLE, "skill": skill_name, "profile": profile_name}
	print(f"✓ Memory provisioned: {summary}")
	return summary
