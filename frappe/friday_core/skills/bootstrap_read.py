# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
One-command provisioning for the generic governed read tools (design 66a).

Run once per site:

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_read.provision

Idempotent — re-runs safely add nothing.

Unlike per-DocType skills (``get-brand-brief``, ``remember``), the read tools
do NOT carry a fixed ``required_doctypes`` set: they read whatever the
caller asks, gated by ``frappe.has_permission`` against the agent's User.
That's deliberate — one tool covers every DocType the agent already has
read access to, which is the Friday-beats-Hermes axis of this design.

The skills are granted to the default ``Friday`` profile by default; pass
a different ``profile_name`` to wire another profile.
"""

from __future__ import annotations

import frappe

READ_ROLE = "Friday Reader"

_SKILLS: dict[str, dict] = {
	"read-record": {
		"description": (
			"Fetch ONE record by its DocType and name (e.g. a work-item "
			"Task TASK-42, Project PRJ-7, Issue ISS-3). Returns the record's "
			"fields. Use this whenever someone asks 'what does X say' or "
			"'show me record X' or 'fetch the saved Y' — instead of "
			"answering from memory or improvising."
		),
		"when_to_use": (
			"Call this BEFORE answering any question about a specific saved "
			"record. If the operator says 'what does TASK-42 say' or 'pull "
			"up TASK-42', call read-record with the doctype + name. If you "
			"do not have read access, the response carries a structured "
			"error and you must report that honestly — never invent the "
			"record's contents."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"doctype": {
					"type": "string",
					"description": "The Frappe DocType, e.g. 'Task', 'Project', 'Issue'.",
				},
				"name": {
					"type": "string",
					"description": "The record's primary key, e.g. 'TASK-42'.",
				},
			},
			"required": ["doctype", "name"],
		},
		# No required_doctypes here — see module docstring. Permission check
		# happens at call time against whatever doctype the caller passes.
		"required_doctypes": [],
	},
	"list-records": {
		"description": (
			"List rows of one DocType (e.g. 'all Task rows for "
			"project PRJ-7', 'all open Tasks on PRJ-7'). Supports filters as "
			"a dict of field → value (or [operator, value] tuples). Capped "
			"at 100 rows. Use this whenever someone asks 'what are the X "
			"for Y' — instead of guessing or fabricating."
		),
		"when_to_use": (
			"Call this whenever the operator asks about a SET of records "
			"('which Issues are open on PRJ-7', 'what tasks "
			"are pending on PRJ-7'). Filter precisely. If your read access "
			"is denied, the response carries a denied flag and you must "
			"report that honestly — never invent the list."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"doctype": {
					"type": "string",
					"description": "The Frappe DocType to list, e.g. 'Task'.",
				},
				"filters": {
					"type": "object",
					"description": "Field → value dict. Example: {'project': 'PRJ-0001'}.",
				},
				"limit": {
					"type": "integer",
					"description": "Maximum rows to return (capped at 100).",
				},
			},
			"required": ["doctype"],
		},
		"required_doctypes": [],
	},
}


def ensure_definitions() -> None:
	"""Role + Skill rows only (no profile wiring) — the after_migrate path
	(bootstrap_registry), so definition edits reach existing sites."""
	_ensure_role()
	for skill_name in _SKILLS:
		_ensure_skill_row(skill_name)


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, skill rows, profile wiring. Idempotent."""
	ensure_definitions()
	_wire_profile(profile_name)

	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	# Manual commit: same idiom as the other bootstraps (run via bench
	# execute, no request lifecycle to commit for us).
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {"role": READ_ROLE, "skills": sorted(_SKILLS.keys()), "profile": profile_name}
	print(f"✓ Read tools provisioned: {summary}")
	return summary


def _ensure_role() -> None:
	"""Create the Friday Reader role (idempotent).

	We deliberately do NOT grant per-DocType Custom DocPerm rows here:
	read-record and list-records call frappe.has_permission at runtime, so
	the AGENT'S existing roles (Brand Agent, Memory Agent, etc.) gate the
	read. This role exists so a profile that only needs read can be set up
	without bundling any write rights.
	"""
	if not frappe.db.exists("Role", READ_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": READ_ROLE}).insert(ignore_permissions=True)


def _ensure_skill_row(skill_name: str) -> None:
	spec = _SKILLS[skill_name]
	import json

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
	# Active EXPLICITLY — the create-only Draft default is the #179 class.
	doc.status = "Active"
	doc.save(ignore_permissions=True)


def _wire_profile(profile_name: str) -> None:
	"""Grant the role + permit the two skills on the target Agent Profile."""
	if not frappe.db.exists("Agent Profile", profile_name):
		print(f"! Agent Profile {profile_name!r} not found; skipping wiring")
		return

	profile = frappe.get_doc("Agent Profile", profile_name)

	# Grant the Friday Reader role (via the profile's user if it has one).
	user_id = profile.get("frappe_user")
	if user_id and frappe.db.exists("User", user_id):
		user = frappe.get_doc("User", user_id)
		have_roles = {r.role for r in user.roles or []}
		if READ_ROLE not in have_roles:
			user.append("roles", {"role": READ_ROLE})
			user.save(ignore_permissions=True)

	# Permit the skills explicitly on the profile.
	have_skills = {row.skill for row in profile.get("permitted_skills") or []}
	added = False
	for skill_name in _SKILLS:
		if skill_name in have_skills:
			continue
		profile.append("permitted_skills", {"skill": skill_name})
		added = True
	if added:
		profile.save(ignore_permissions=True)
