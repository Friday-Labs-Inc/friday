# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Brand-skill handlers — Friday's first business skills (design 56, LOCKED).

PLAIN ENGLISH
=============
Two small, auditable functions behind the dispatcher chokepoint:

  - `get_brand_brief`        READ:  hand the agent a Brand Brief's content.
  - `create_brand_direction` WRITE: persist ONE agent-generated direction.

Per locked Q3, these handlers contain NO intelligence: the model generates
the creative content inside the governed ReAct loop (usage-logged,
reasoning-scrubbed) and calls these with finished content as arguments.
The handlers only validate and persist.

Validation failures `raise ValueError` — the dispatcher catches, logs, and
feeds the error text back to the model so it can correct itself (loop A.3),
the same contract `create_note` uses. Inserts use `ignore_permissions=True`
because the permission decision already happened at the dispatch gate
(matrix.check → Permission Decision Log) — the handler is system machinery
executing an already-authorised action.
"""

from __future__ import annotations

import json

import frappe

from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

GET_BRAND_BRIEF = "get-brand-brief"
CREATE_BRAND_DIRECTION = "create-brand-direction"

# The brief fields the reader hands to the model — content only, no
# system/audit fields.
_BRIEF_CONTENT_FIELDS = (
	"business_name",
	"industry",
	"what_they_do",
	"target_audience",
	"brand_personality",
	"competitors",
	"color_preferences",
	"inspirations",
	"notes",
	"status",
)


def get_brand_brief(skill_name: str, parameters: dict) -> dict:
	"""Return a Brand Brief's content so the agent can generate from it.

	Parameters:
	  - `brief` (str, required): the Brand Brief ID, e.g. "BB-0001".
	"""
	brief_name = (parameters.get("brief") or "").strip()
	if not brief_name:
		raise ValueError("get-brand-brief requires a 'brief' parameter (the Brand Brief ID, e.g. 'BB-0001')")
	if not frappe.db.exists("Brand Brief", brief_name):
		raise ValueError(f"Brand Brief {brief_name!r} not found — check the ID in Desk")

	doc = frappe.get_doc("Brand Brief", brief_name)
	out = {field: (doc.get(field) or "") for field in _BRIEF_CONTENT_FIELDS}
	out["brief"] = brief_name
	out["result"] = f"Brand Brief {brief_name} ({doc.business_name}) loaded"
	return out


def create_brand_direction(skill_name: str, parameters: dict) -> dict:
	"""Persist ONE brand direction the agent generated (called once per direction).

	Parameters (required): `brief`, `direction_name`, `concept_story`.
	Optional: `personality_keywords`, `color_palette` (list of
	{hex, name, role} — stored as JSON), `typography`, `logo_concept`,
	`tagline_options`.
	"""
	brief_name = (parameters.get("brief") or "").strip()
	direction_name = (parameters.get("direction_name") or "").strip()
	concept_story = (parameters.get("concept_story") or "").strip()

	if not brief_name:
		raise ValueError("create-brand-direction requires a 'brief' parameter (the Brand Brief ID)")
	if not direction_name:
		raise ValueError("create-brand-direction requires a 'direction_name' parameter")
	if not concept_story:
		raise ValueError("create-brand-direction requires a 'concept_story' parameter")
	if not frappe.db.exists("Brand Brief", brief_name):
		raise ValueError(f"Brand Brief {brief_name!r} not found — check the ID")

	# The model passes the palette as a list of objects; the field stores
	# JSON text. Accept either shape (a JSON string passes through).
	palette = parameters.get("color_palette")
	if palette is not None and not isinstance(palette, str):
		palette = json.dumps(palette)

	doc = frappe.get_doc(
		{
			"doctype": "Brand Direction",
			"brief": brief_name,
			"direction_name": direction_name,
			"concept_story": concept_story,
			"personality_keywords": parameters.get("personality_keywords") or "",
			"color_palette": palette,
			"typography": parameters.get("typography") or "",
			"logo_concept": parameters.get("logo_concept") or "",
			"tagline_options": parameters.get("tagline_options") or "",
			"status": "Proposed",
		}
	)
	doc.insert(ignore_permissions=True)

	# The brief now has at least one direction — reflect that in its status
	# so the team's list view shows progress at a glance.
	frappe.db.set_value("Brand Brief", brief_name, "status", "Directions Generated", update_modified=False)

	return {
		"result": f"Brand Direction '{direction_name}' created as {doc.name} for {brief_name}",
		"direction": doc.name,
		"doctype": "Brand Direction",
		"record_name": doc.name,
	}


# Registered at import time; the dispatcher imports this module at its
# bottom, so registration happens exactly once per process.
register_skill_handler(GET_BRAND_BRIEF, get_brand_brief)
register_skill_handler(CREATE_BRAND_DIRECTION, create_brand_direction)
