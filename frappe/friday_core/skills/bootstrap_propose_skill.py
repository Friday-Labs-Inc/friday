# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-command provisioning for the `propose_skill_change` skill (design 79 Slice 2).

Same pattern as bootstrap_memory: a "Skill Proposer" role with exactly what the
skill needs (create+read on Skill Proposal), the Skill row, and profile wiring.
Idempotent.

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_propose_skill.provision
"""

from __future__ import annotations

import json

import frappe

PROPOSER_ROLE = "Skill Proposer"

_SKILL = {
	"skill_name": "propose_skill_change",
	"description": (
		"Propose a change to the skill library for a human to review — a new "
		"skill, an update to an existing one, or an added reference. This does "
		"NOT change anything itself; it records a Pending proposal a human "
		"approves. Use it in a self-improvement review when you learn a reusable "
		"how-to lesson."
	),
	"when_to_use": (
		"Use when a reusable, durable how-to lesson emerged that a future session "
		"would benefit from: the user corrected your approach/workflow/format, a "
		"non-trivial technique or fix worked, or a skill you used was wrong or "
		"missing a step. Prefer proposing an UPDATE to the most relevant existing "
		"skill over a brand-new one.\n\n"
		"Do NOT propose for: environment/setup failures (missing binaries, "
		"unconfigured credentials), negative claims about tools ('X is broken'), "
		"transient errors that resolved, or one-off task narratives. These harden "
		"into bad standing rules. One proposal per call. You never apply the "
		"change yourself — a human reviews and applies it."
	),
	"parameters_schema": {
		"type": "object",
		"properties": {
			"title": {
				"type": "string",
				"description": "Short name for the proposed change.",
			},
			"proposal_type": {
				"type": "string",
				"enum": ["new_skill", "update_skill", "add_reference"],
				"description": "new_skill | update_skill | add_reference. Default new_skill.",
			},
			"target_skill": {
				"type": "string",
				"description": "For update/add: the existing skill this concerns. Blank for a new skill.",
			},
			"rationale": {
				"type": "string",
				"description": "Why this is worth doing — what you learned that future sessions need.",
			},
			"proposed_content": {
				"type": "string",
				"description": "The proposed skill text / change, for a human to review and apply.",
			},
		},
		"required": ["title"],
	},
	"required_doctypes": [{"target_doctype": "Skill Proposal", "operation": "create"}],
}

_ROLE_PERMS = {"Skill Proposal": {"create": 1, "read": 1}}


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, perms, the Skill row, and profile wiring. Idempotent."""
	if not frappe.db.exists("Role", PROPOSER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": PROPOSER_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		if not frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": PROPOSER_ROLE}):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": target_doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": PROPOSER_ROLE,
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
	if PROPOSER_ROLE not in {row.role for row in (profile.assigned_roles or [])}:
		profile.append("assigned_roles", {"role": PROPOSER_ROLE})
	if skill_name not in {row.skill for row in (profile.permitted_skills or [])}:
		profile.append("permitted_skills", {"skill": skill_name})
	profile.save(ignore_permissions=True)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {"role": PROPOSER_ROLE, "skill": skill_name, "profile": profile_name}
	print(f"✓ propose_skill_change provisioned: {summary}")
	return summary
