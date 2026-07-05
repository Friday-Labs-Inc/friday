# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
One-command provisioning for the deliverable-as-File tools (design 66b).

Run once per site (idempotent):

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_files.provision

Grants the agent the right to write Files (and read attached ones) by
adding the standard ``System Manager`` or a tighter custom role to the
profile's User; v0.1 grants a dedicated ``Friday File Author`` role with
create on File and read on Project + Task. Per-DocType perms gate the
actual attach calls at runtime.
"""

from __future__ import annotations

import json

import frappe

FILE_ROLE = "Friday File Author"

_SKILLS: dict[str, dict] = {
	"attach-deliverable": {
		"description": (
			"Save a deliverable as a real Frappe File attached to a "
			"Project (or Task). The file becomes visible in the Desk "
			"attachment sidebar of that Project immediately. Use this "
			"to save naming options, brand-direction copy, refinement "
			"notes, or any finished content the operator or client "
			"should retrieve. Default private."
		),
		"when_to_use": (
			"Call this whenever you have generated FINISHED CONTENT "
			"someone needs to receive (a deliverable, not a draft you "
			"are still iterating). Pass project_name (e.g. PRJ-1) or "
			"task_name, a file_name with extension, and the content "
			"(text or bytes). Do NOT use this for ephemeral notes — "
			"those go in the project notes or memory."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"project_name": {
					"type": "string",
					"description": "The Project ID to attach the file to (mutually exclusive with task_name).",
				},
				"task_name": {
					"type": "string",
					"description": "The Task ID to attach the file to (mutually exclusive with project_name).",
				},
				"file_name": {
					"type": "string",
					"description": "The filename as it will appear in the sidebar, e.g. 'naming_options_v1.txt'.",
				},
				"content": {
					"type": "string",
					"description": "The deliverable's text content (UTF-8). For binary content use base64 in a later iteration.",
				},
				"is_private": {
					"type": "boolean",
					"description": "Default true (v0.1 stance). Public requires explicit opt-in.",
				},
				"description": {
					"type": "string",
					"description": "Short human description, logged in the response.",
				},
			},
			"required": ["file_name", "content"],
		},
		"required_doctypes": [{"target_doctype": "File", "operation": "create"}],
	},
	"list-project-files": {
		"description": (
			"List the Frappe Files attached to a Project — the same set "
			"the Desk attachment sidebar shows. Use this to see what "
			"deliverables exist on a project before answering 'what do "
			"we have on PRJ-7' or before deciding to attach a duplicate."
		),
		"when_to_use": (
			"Call this whenever the operator asks 'what deliverables / "
			"files / outputs do we have on project X'. Also call this "
			"BEFORE attaching a deliverable if you suspect a similar "
			"file may already be there, to avoid duplicates."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"project_name": {
					"type": "string",
					"description": "The Project ID, e.g. 'PRJ-1'.",
				},
				"limit": {
					"type": "integer",
					"description": "Maximum rows to return (capped at 200).",
				},
			},
			"required": ["project_name"],
		},
		"required_doctypes": [],
	},
	"get-project-file": {
		"description": (
			"Read the text content of ONE Frappe File attached to a "
			"Project. Use this to inspect a previously saved deliverable "
			"(e.g. for refinement, for inclusion in a write-back to a "
			"backend). Cross-project access is refused."
		),
		"when_to_use": (
			"Call this when you need the bytes of a specific file you "
			"saw in list-project-files. NEVER assume the contents — "
			"always fetch them. If you cannot read it, say so plainly."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"project_name": {
					"type": "string",
					"description": "The Project ID the file belongs to.",
				},
				"file_name": {
					"type": "string",
					"description": "The File document name (e.g. 'f-abc'), as returned by list-project-files.",
				},
			},
			"required": ["project_name", "file_name"],
		},
		"required_doctypes": [],
	},
}

_ROLE_PERMS: dict[str, dict] = {
	"File": {"create": 1, "read": 1, "write": 1},
	"Project": {"read": 1, "write": 1},  # write needed for has_permission on attach
	"Task": {"read": 1, "write": 1},
}


def ensure_definitions() -> None:
	"""Role + perms + Skill rows only (no profile wiring) — the after_migrate
	path (bootstrap_registry), so definition edits reach existing sites."""
	_ensure_role_and_perms()
	for skill_name in _SKILLS:
		_ensure_skill_row(skill_name)


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, skill rows, profile wiring. Idempotent."""
	ensure_definitions()
	_wire_profile(profile_name)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {"role": FILE_ROLE, "skills": sorted(_SKILLS.keys()), "profile": profile_name}
	print(f"✓ File tools provisioned: {summary}")
	return summary


def _ensure_role_and_perms() -> None:
	if not frappe.db.exists("Role", FILE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": FILE_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		if frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": FILE_ROLE}):
			continue
		perm_row = {
			"doctype": "Custom DocPerm",
			"parent": target_doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": FILE_ROLE,
			"permlevel": 0,
		}
		perm_row.update(ptypes)
		frappe.get_doc(perm_row).insert(ignore_permissions=True)


def _ensure_skill_row(skill_name: str) -> None:
	spec = _SKILLS[skill_name]
	schema_json = json.dumps(spec["parameters_schema"])
	if frappe.db.exists("Skill", skill_name):
		doc = frappe.get_doc("Skill", skill_name)
	else:
		doc = frappe.new_doc("Skill")
		doc.skill_name = skill_name
	doc.description = spec["description"]
	doc.when_to_use = spec["when_to_use"]
	doc.parameters_schema = schema_json
	doc.risk_level = "low"
	doc.requires_approval = 0
	# Active EXPLICITLY: the original create-only default left these rows Draft,
	# which the loader hard-excludes — the E2E #179 finding. Forcing the full
	# definition on every run kills that class.
	doc.status = "Active"
	doc.save(ignore_permissions=True)


def _wire_profile(profile_name: str) -> None:
	if not frappe.db.exists("Agent Profile", profile_name):
		print(f"! Agent Profile {profile_name!r} not found; skipping wiring")
		return

	profile = frappe.get_doc("Agent Profile", profile_name)

	user_id = profile.get("frappe_user")
	if user_id and frappe.db.exists("User", user_id):
		user = frappe.get_doc("User", user_id)
		have_roles = {r.role for r in user.roles or []}
		if FILE_ROLE not in have_roles:
			user.append("roles", {"role": FILE_ROLE})
			user.save(ignore_permissions=True)

	have_skills = {row.skill for row in profile.get("permitted_skills") or []}
	added = False
	for skill_name in _SKILLS:
		if skill_name in have_skills:
			continue
		profile.append("permitted_skills", {"skill": skill_name})
		added = True
	if added:
		profile.save(ignore_permissions=True)
