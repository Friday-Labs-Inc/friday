# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Rename the agent-namespaced tracker DocTypes to their generic names (doc 53 §7, D1).

    Agent Project      -> Project
    Agent Task         -> Task
    Agent Task Skill   -> Task Skill   (child table)

WHY pre_model_sync
==================
`frappe.rename_doc("DocType", ...)` renames the underlying table (e.g.
`tabAgent Task` -> `tabTask`) and rewrites the DocType record. This MUST run
*before* the model sync: the renamed on-disk schema (task.json, name="Task")
would otherwise be synced as a brand-new DocType, leaving `tabAgent Task`
orphaned and its rows stranded. Running here renames the table first; the
sync then applies the new schema (incl. updated Link `options`) onto it.

Idempotent: each rename is guarded so a re-run (or a fresh site that already
has the new names) is a no-op.
"""

import frappe


def execute():
	renames = [
		("Agent Project", "Project"),
		("Agent Task", "Task"),
		("Agent Task Skill", "Task Skill"),
	]
	for old, new in renames:
		if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
			# force=True: rename even though the on-disk JSON already carries the
			# new name (the schema files were renamed in the same change).
			# Runs as Administrator during migrate, so no ignore_permissions kwarg
			# (this Frappe's rename_doc doesn't accept it — it raised TypeError).
			frappe.rename_doc("DocType", old, new, force=True)
