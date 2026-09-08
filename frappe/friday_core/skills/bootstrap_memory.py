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
		"('PRJ-0007 shipped on the 14th'), a standing instruction."
	),
	"when_to_use": (
		"Save proactively — do not wait to be asked. Save when: the user corrects "
		"you or says 'remember this'; the user reveals a preference, habit, role, "
		"or personal detail; a durable decision or standing instruction is made; "
		"or you learn a convention/fact useful in future sessions.\n\n"
		"Set memory_type: 'user_profile' for facts about the USER (their role, "
		"preferences, working style, pet peeves); 'general' for your own notes "
		"(decisions, client facts, conventions). Priority: user corrections and "
		"preferences first.\n\n"
		"One fact per call. Set 'subject' to the client or record ID it concerns "
		"(e.g. 'PRJ-0007') for filtering in Desk. Do NOT store conversation "
		"minutiae, one-off task chatter, things already in your memory, or "
		"anything temporary."
	),
	"parameters_schema": {
		"type": "object",
		"properties": {
			"memory": {
				"type": "string",
				"description": "The fact to remember — ONE sentence, under 500 characters.",
			},
			"memory_type": {
				"type": "string",
				"enum": ["general", "user_profile"],
				"description": (
					"'user_profile' = a fact about the user (role, preferences, style, "
					"pet peeves). 'general' = your own notes (decisions, conventions, "
					"learnings). Defaults to 'general'."
				),
			},
			"subject": {
				"type": "string",
				"description": "Optional grouping tag: a client name or record ID like 'PRJ-0007'.",
			},
			"scope": {
				"type": "string",
				"enum": ["project", "global"],
				"description": (
					"'project' (default) ties the memory to the current project — "
					"recalled only there. 'global' makes it recallable on EVERY future "
					"project — use for cross-project lessons (craft, conventions, "
					"taste), never for one client's private facts."
				),
			},
		},
		"required": ["memory"],
	},
	"required_doctypes": [{"target_doctype": "Agent Memory", "operation": "create"}],
}

# read: lets @-reference gating + future recall queries pass for this role too.
_ROLE_PERMS = {"Agent Memory": {"create": 1, "read": 1}}


def ensure_memory_role() -> None:
	"""Ensure the Memory Agent role + its Agent Memory perms exist. Idempotent
	and safe from after_migrate (no prints, no manual commit). Split out of
	provision() so DOMAIN provisioners can grant the role to their profiles:
	the loader's permission-matrix filter DROPS an allow-listed `remember`
	unless the profile holds create-on-Agent-Memory (design 95 finding — the
	CD apprentice had remember in permitted_skills but never saw the tool)."""
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


def ensure_memory_skill() -> None:
	"""UPSERT the remember Skill row from _SKILL — after_migrate entry.

	Finding #19 (design 95 deploy verify): schema edits to _SKILL (e.g. the
	scope param) never reached existing sites, because provision() is CLI-only
	and nothing on the migrate path refreshed the row — the deployed skill
	definition silently drifted from the code. This runs on every migrate so
	the row always matches _SKILL, like every other provisioned artifact.
	"""
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


def ensure_memory_provisioned() -> None:
	"""after_migrate entry: role + perms + the Skill row, failure-isolated.
	Profile wiring stays in provision() (CLI) and the domain provisioners —
	granting is an operator/domain decision, the definitions are not."""
	try:
		ensure_memory_role()
		ensure_memory_skill()
	except Exception:
		frappe.log_error(title="bootstrap_memory: ensure_memory_provisioned failed")


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, perms, the Skill row, and profile wiring. Idempotent."""
	ensure_memory_role()
	ensure_memory_skill()
	skill_name = _SKILL["skill_name"]

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
