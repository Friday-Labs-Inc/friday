# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# --- the Agent Settings singleton: canonical identity ----------------------
#
# Agent Settings is a regular (non-``issingle``) DocType that holds exactly ONE
# row of global defaults. There is a subtle trap here, so this is the single
# source of truth that every reader/writer must use:
#
#   * Frappe FORBIDS naming a record the same as its DocType, so the row can
#     NOT be named "Agent Settings". The DocType autonames on its hidden
#     ``__default`` field, and the singleton row is named ``"__default"``.
#   * Worse, ``frappe.db.exists("Agent Settings", "Agent Settings")`` returns a
#     FALSE POSITIVE — Frappe short-circuits ``exists(dt, dn)`` when ``dt == dn``
#     ("a single always exists") and never touches the database. So guarding on
#     that form silently lies, and reading the row as "Agent Settings" raises
#     DoesNotExistError.
#
# Always address the row by ``SETTINGS_NAME`` (= "__default"). Use
# ``get_agent_settings()`` to read it (it self-heals a missing row).
SETTINGS_DOCTYPE = "Agent Settings"
SETTINGS_NAME = "__default"


class AgentSettings(Document):
	pass


def ensure_agent_settings() -> None:
	"""Create the Agent Settings singleton row if it doesn't exist. Idempotent.

	Uses the dict-filter form of ``exists`` (NOT ``exists(dt, dn)``, which
	false-positives when name == doctype) and creates the row under
	``SETTINGS_NAME`` by setting the ``__default`` autoname field.
	"""
	if frappe.db.exists(SETTINGS_DOCTYPE, {"name": SETTINGS_NAME}):
		return
	try:
		frappe.get_doc({"doctype": SETTINGS_DOCTYPE, "__default": SETTINGS_NAME}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	except frappe.exceptions.DuplicateEntryError:
		# Lost a race with a concurrent migrate — the row exists now.
		frappe.db.rollback()


def get_agent_settings() -> "AgentSettings":
	"""Return the Agent Settings singleton, creating it if absent."""
	ensure_agent_settings()
	return frappe.get_cached_doc(SETTINGS_DOCTYPE, SETTINGS_NAME)
