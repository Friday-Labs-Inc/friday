# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Provisioning for the `manage-cron-jobs` skill (Design 87, Slice 2).

Creates the Skill row, grants the existing ``Friday Cron Manager`` role create/
read/write/delete on ``Cron Job``, and wires both onto a profile. Idempotent;
safe to call on every migrate. The role itself is ensured by
``cron/after_migrate.ensure_cron_role`` (Slice 1).
"""

from __future__ import annotations

import json

import frappe

CRON_MANAGER_ROLE = "Friday Cron Manager"
_SKILL_NAME = "manage-cron-jobs"

_SKILL = {
	"description": (
		"Schedule, list, pause, resume, remove, or trigger your own recurring "
		"agent runs (Cron Jobs). One 'action' parameter drives it. A job runs the "
		"given prompt on a schedule and delivers the result to a channel or a file."
	),
	"when_to_use": (
		"Call this when asked to do something on a schedule or repeatedly — "
		"'every morning', 'each Monday', 'in an hour', 'every 30 minutes'. Use "
		"action=create with a prompt + schedule_expression. Use action=list to see "
		"your jobs; pause/resume/remove/trigger to manage one by name. You can only "
		"manage your OWN jobs."
	),
	"schema": {
		"type": "object",
		"properties": {
			"action": {
				"type": "string",
				"enum": ["create", "list", "pause", "resume", "remove", "trigger"],
			},
			"prompt": {"type": "string", "description": "create: the instruction to run each fire."},
			"schedule_kind": {"type": "string", "enum": ["cron", "interval", "once"]},
			"schedule_expression": {
				"type": "string",
				"description": "cron: '0 9 * * *'; interval: '30' (minutes); once: ISO datetime.",
			},
			"deliver": {"type": "string", "description": "Optional. 'local', 'raven:<channel>', or 'origin'."},
			"repeat_times": {"type": "integer", "description": "0 = forever, 1 = once, N = N times."},
			"name": {"type": "string", "description": "Job name (required for pause/resume/remove/trigger)."},
		},
		"required": ["action"],
	},
	"docs": [{"target_doctype": "Cron Job", "operation": "create"}],
}


def provision(profile_name: str = "Friday") -> dict:
	"""Provision the Skill row + role perms + profile wiring. Idempotent."""
	if not frappe.db.exists("Role", CRON_MANAGER_ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": CRON_MANAGER_ROLE, "desk_access": 1}
		).insert(ignore_permissions=True)

	# Grant the role full management of Cron Job rows.
	if frappe.db.exists("DocType", "Cron Job") and not frappe.db.exists(
		"Custom DocPerm", {"parent": "Cron Job", "role": CRON_MANAGER_ROLE}
	):
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Cron Job",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": CRON_MANAGER_ROLE,
				"permlevel": 0,
				"read": 1,
				"create": 1,
				"write": 1,
				"delete": 1,
			}
		).insert(ignore_permissions=True)

	skill = frappe.get_doc("Skill", _SKILL_NAME) if frappe.db.exists("Skill", _SKILL_NAME) else frappe.new_doc("Skill")
	skill.skill_name = _SKILL_NAME
	skill.description = _SKILL["description"]
	skill.when_to_use = _SKILL["when_to_use"]
	skill.parameters_schema = json.dumps(_SKILL["schema"])
	skill.risk_level = "medium"
	skill.requires_approval = 0  # first-party-trusted (feedback_v01-skills-first-party-trust)
	skill.role_gate = CRON_MANAGER_ROLE
	skill.status = "Active"
	skill.required_doctypes = []
	for req in _SKILL["docs"]:
		if frappe.db.exists("DocType", req["target_doctype"]):
			skill.append("required_doctypes", req)
	skill.save(ignore_permissions=True)

	# Wire onto the profile (role + permitted skill), if it exists.
	if frappe.db.exists("Agent Profile", profile_name):
		profile = frappe.get_doc("Agent Profile", profile_name)
		if CRON_MANAGER_ROLE not in {r.role for r in (profile.assigned_roles or [])}:
			profile.append("assigned_roles", {"role": CRON_MANAGER_ROLE})
		if _SKILL_NAME not in {s.skill for s in (profile.permitted_skills or [])}:
			profile.append("permitted_skills", {"skill": _SKILL_NAME})
		profile.save(ignore_permissions=True)
		from frappe.friday_core.skills.loader import invalidate_for_profile

		invalidate_for_profile(profile_name)

	return {"role": CRON_MANAGER_ROLE, "skill": _SKILL_NAME, "profile": profile_name}
