# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
One-command provisioning for the brand skills (design 56).

PLAIN ENGLISH
=============
Creates everything an Agent Profile needs to generate brand directions, all
idempotent (safe to run twice):

  1. A "Brand Agent" Role with exactly the Frappe permissions the skills
     need: READ on Brand Brief, CREATE on Brand Direction. Deny-by-default
     stays intact — the role grants nothing else.
  2. The two Skill rows (`get-brand-brief`, `create-brand-direction`) with
     their parameter schemas, model-facing descriptions, and
     `required_doctypes` rows — which is what the permission matrix checks
     against the profile's roles.
  3. Wires the target Agent Profile: assigns the role + permits both skills.

Run it once per site:

    bench --site friday.localhost execute \\
        frappe.friday_core.skills.bootstrap_brand.provision

(Default profile "Friday"; pass --args "['Other Profile']" to target another.)
"""

from __future__ import annotations

import json

import frappe

BRAND_ROLE = "Brand Agent"

# Skill definitions — name → (description, when_to_use, schema, required docs).
# The description/when_to_use text is what the model reads when deciding
# whether and how to call the skill; written for the model, not for humans.
_SKILLS: dict[str, dict] = {
	"get-brand-brief": {
		"description": (
			"Read a client's Brand Brief (the branding questionnaire) by its ID "
			"and return its content: business name, industry, audience, "
			"personality, competitors, color preferences, inspirations, notes."
		),
		"when_to_use": (
			"Call this FIRST whenever the user asks for brand work on a brief "
			"(e.g. 'generate brand directions for BB-0001'). You need the "
			"brief's content before generating anything."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"brief": {
					"type": "string",
					"description": "The Brand Brief ID, e.g. 'BB-0001'.",
				},
			},
			"required": ["brief"],
		},
		"required_doctypes": [{"target_doctype": "Brand Brief", "operation": "read"}],
	},
	"create-brand-direction": {
		"description": (
			"Save ONE complete brand direction you have generated for a Brand "
			"Brief. Call once per direction (a typical request wants 3 distinct "
			"directions, so 3 calls). Each direction needs a short evocative "
			"name, a concept story explaining why it fits the brief, and "
			"ideally a color palette, typography suggestion, designer-ready "
			"logo concept description, and tagline options."
		),
		"when_to_use": (
			"After reading the brief with get-brand-brief and generating a "
			"direction's full content yourself, call this to persist it. "
			"Make the directions genuinely DISTINCT from each other in mood "
			"and visual language."
		),
		"parameters_schema": {
			"type": "object",
			"properties": {
				"brief": {"type": "string", "description": "The Brand Brief ID this direction belongs to."},
				"direction_name": {
					"type": "string",
					"description": "Short evocative name, e.g. 'Midnight Atelier'.",
				},
				"concept_story": {
					"type": "string",
					"description": "The narrative: what this direction says about the brand and why it fits the brief.",
				},
				"personality_keywords": {
					"type": "string",
					"description": "3-5 comma-separated personality words.",
				},
				"color_palette": {
					"type": "array",
					"description": "3-6 colors with roles.",
					"items": {
						"type": "object",
						"properties": {
							"hex": {"type": "string", "description": "e.g. '#1A1A2E'"},
							"name": {"type": "string", "description": "e.g. 'Ink Navy'"},
							"role": {
								"type": "string",
								"description": "primary / secondary / accent / background",
							},
						},
					},
				},
				"typography": {
					"type": "string",
					"description": "Heading + body font suggestion with a one-line rationale.",
				},
				"logo_concept": {
					"type": "string",
					"description": "Designer-ready description of the logo: imagery, construction, mood.",
				},
				"tagline_options": {"type": "string", "description": "2-3 tagline options, one per line."},
			},
			"required": ["brief", "direction_name", "concept_story"],
		},
		"required_doctypes": [{"target_doctype": "Brand Direction", "operation": "create"}],
	},
}

# Frappe permissions the Brand Agent role needs, per target DocType.
_ROLE_PERMS: dict[str, dict] = {
	"Brand Brief": {"read": 1, "write": 1},  # write: the handler flips brief status
	"Brand Direction": {"create": 1, "read": 1},
}


def ensure_definitions() -> None:
	"""Role + perms + Skill rows only (no profile wiring) — the after_migrate
	path (bootstrap_registry), so definition edits reach existing sites."""
	_ensure_role_and_perms()
	for skill_name in _SKILLS:
		_ensure_skill_row(skill_name)


def provision(profile_name: str = "Friday") -> dict:
	"""Provision role, permissions, skill rows, and profile wiring. Idempotent."""
	ensure_definitions()
	_wire_profile(profile_name)

	# The loader caches per-profile skill lists; new permissions must show up
	# on the very next turn.
	from frappe.friday_core.skills.loader import invalidate_for_profile

	invalidate_for_profile(profile_name)
	# Manual commit is required: provision() runs via `bench execute` (no
	# request lifecycle to commit for us) and must persist before returning.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	summary = {
		"role": BRAND_ROLE,
		"skills": sorted(_SKILLS.keys()),
		"profile": profile_name,
	}
	print(f"✓ Brand skills provisioned: {summary}")
	return summary


def _ensure_role_and_perms() -> None:
	"""Create the Brand Agent role + its Custom DocPerm rows (idempotent)."""
	if not frappe.db.exists("Role", BRAND_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": BRAND_ROLE}).insert(ignore_permissions=True)

	for target_doctype, ptypes in _ROLE_PERMS.items():
		if frappe.db.exists("Custom DocPerm", {"parent": target_doctype, "role": BRAND_ROLE}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": target_doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": BRAND_ROLE,
				"permlevel": 0,
				**ptypes,
			}
		).insert(ignore_permissions=True)


def _ensure_skill_row(skill_name: str) -> None:
	"""Create or refresh one Skill row from `_SKILLS` (idempotent)."""
	spec = _SKILLS[skill_name]
	if frappe.db.exists("Skill", skill_name):
		skill = frappe.get_doc("Skill", skill_name)
	else:
		skill = frappe.new_doc("Skill")
		skill.skill_name = skill_name

	skill.description = spec["description"]
	skill.when_to_use = spec["when_to_use"]
	skill.parameters_schema = json.dumps(spec["parameters_schema"])
	skill.risk_level = "low"
	skill.requires_approval = 0
	skill.status = "Active"
	skill.required_doctypes = []
	for req in spec["required_doctypes"]:
		skill.append("required_doctypes", req)
	skill.save(ignore_permissions=True)


def _wire_profile(profile_name: str) -> None:
	"""Assign the role + permit both skills on the profile (append-if-missing)."""
	if not frappe.db.exists("Agent Profile", profile_name):
		frappe.throw(
			frappe._("Agent Profile {0} not found — run `bench friday setup` first.").format(profile_name)
		)
	profile = frappe.get_doc("Agent Profile", profile_name)

	existing_roles = {row.role for row in (profile.assigned_roles or [])}
	if BRAND_ROLE not in existing_roles:
		profile.append("assigned_roles", {"role": BRAND_ROLE})

	existing_skills = {row.skill for row in (profile.permitted_skills or [])}
	for skill_name in _SKILLS:
		if skill_name not in existing_skills:
			profile.append("permitted_skills", {"skill": skill_name})

	profile.save(ignore_permissions=True)
