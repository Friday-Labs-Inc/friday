# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Domain Bundle lookups for the engine (Design 75).

A Domain Bundle is the record that says "this work-item DocType is governed by
this Frappe Workflow." The engine asks three questions, all answered here:

  - Is this DocType governed at all? (active_bundle_for)
  - Which Workflow drives it?       (workflow_for)
  - Which field holds the state?    (state_field_for)

These are thin, read-only helpers on purpose — the bundle is just data, and the
engine should never reach past it into domain specifics.
"""

from __future__ import annotations

import frappe


def active_bundle_for(doctype: str) -> str | None:
	"""Name of the single active Domain Bundle governing `doctype`, or None.

	The Domain Bundle controller enforces at-most-one-active per DocType, so this
	is unambiguous when it returns a value.
	"""
	return frappe.db.get_value(
		"Domain Bundle", {"domain_doctype": doctype, "is_active": 1}, "name"
	)


def workflow_for(doctype: str) -> str | None:
	"""The Frappe Workflow name that drives `doctype`'s pipeline, or None if the
	DocType isn't governed (or its bundle has no workflow wired yet)."""
	name = active_bundle_for(doctype)
	if not name:
		return None
	return frappe.db.get_value("Domain Bundle", name, "workflow_name")


def state_field_for(workflow: str) -> str:
	"""The fieldname on the work-item that holds its workflow state. Frappe lets a
	Workflow name this field; it defaults to `workflow_state`."""
	return frappe.db.get_value("Workflow", workflow, "workflow_state_field") or "workflow_state"
