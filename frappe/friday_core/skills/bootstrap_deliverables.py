# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
One-command provisioning for the deliverable-sharing skill (Design 73, use-case #5).

Grants a tight ``Friday Deliverable Sharer`` role (read File + Project, create
Raven Message), the ``share-deliverables`` Skill row, and wires both onto a
profile. Idempotent. Raven must be installed (this is a chat-surface feature).

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_deliverables.provision
"""

from __future__ import annotations

import json

import frappe

SHARER_ROLE = "Friday Deliverable Sharer"

_SKILL_NAME = "share-deliverables"
_SKILL = {
	"description": (
		"Post the project's finished deliverable files (the assembled package — "
		"the deliverable-* Files on the Project) into THIS project's chat channel, "
		"as real downloadable attachments. The files come from the project of the "
		"current channel."
	),
	"when_to_use": (
		"Call this when someone in a project's channel asks you to share, send, "
		"post, or hand over the project's deliverables / files / final package. "
		"Do NOT describe or guess filenames — call this and the real files appear "
		"in the channel. If there are none, it will say so."
	),
	"schema": {"type": "object", "properties": {}, "required": []},
	"docs": [
		{"target_doctype": "File", "operation": "read"},
		{"target_doctype": "Project", "operation": "read"},
		{"target_doctype": "Raven Message", "operation": "create"},
	],
}

_ROLE_PERMS = {
	"File": {"read": 1},
	"Project": {"read": 1},
	"Raven Message": {"create": 1, "read": 1},
}


def ensure_definitions() -> None:
	"""Role + perms + the Skill row only (no profile wiring) — the
	after_migrate path (bootstrap_registry), so definition edits reach
	existing sites."""
	if not frappe.db.exists("Role", SHARER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": SHARER_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		# Skip a doctype that isn't installed (e.g. Raven absent) rather than crash.
		if not frappe.db.exists("DocType", target_doctype):
			continue
		if frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": SHARER_ROLE}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": target_doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": SHARER_ROLE,
				"permlevel": 0,
				**ptypes,
			}
		).insert(ignore_permissions=True)

	if frappe.db.exists("Skill", _SKILL_NAME):
		skill = frappe.get_doc("Skill", _SKILL_NAME)
	else:
		skill = frappe.new_doc("Skill")
		skill.skill_name = _SKILL_NAME
	skill.description = _SKILL["description"]
	skill.when_to_use = _SKILL["when_to_use"]
	skill.parameters_schema = json.dumps(_SKILL["schema"])
	skill.risk_level = "low"
	skill.requires_approval = 0
	skill.status = "Active"
	skill.required_doctypes = []
	for req in _SKILL["docs"]:
		# Only declare a required doctype that actually exists on this site.
		if frappe.db.exists("DocType", req["target_doctype"]):
			skill.append("required_doctypes", req)
	skill.save(ignore_permissions=True)


def provision(profile_name: str = "Friday") -> dict:
	"""Provision the role, the Skill row, and profile wiring. Idempotent."""
	ensure_definitions()

	if not frappe.db.exists("Agent Profile", profile_name):
		frappe.throw(
			frappe._("Agent Profile {0} not found — run `bench friday setup` first.").format(profile_name)
		)
	profile = frappe.get_doc("Agent Profile", profile_name)
	if SHARER_ROLE not in {row.role for row in (profile.assigned_roles or [])}:
		profile.append("assigned_roles", {"role": SHARER_ROLE})
	if _SKILL_NAME not in {row.skill for row in (profile.permitted_skills or [])}:
		profile.append("permitted_skills", {"skill": _SKILL_NAME})
	profile.save(ignore_permissions=True)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	# Manual commit: provision() runs via `bench execute` (no request lifecycle).
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {"role": SHARER_ROLE, "skill": _SKILL_NAME, "profile": profile_name}
	print(f"✓ Deliverable sharing provisioned: {summary}")
	return summary
