# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Namespace Friday's tracker DocTypes so the app can live beside ERPNext.

    Project -> Agent Project
    Task    -> Agent Task
    Issue   -> Agent Issue

WHY
===
Doc 53 §7 D1 renamed these to their generic names back when Friday was a fork
and owned the whole site. As an app it does not: ERPNext v16 ships `Project`
and `Task` (projects) and `Issue` (support), and DocType names are global — so
`install-app erpnext` on a Friday site collided head-on. The agent kernel's work
objects are not ERPNext's, and the ambiguity was the bug. This reverses that
rename and extends it to Issue. `rename_tracker_doctypes`, which performed the
original rename, is deleted in the same change.

WHY pre_model_sync
==================
`frappe.rename_doc("DocType", ...)` renames the underlying table
(`tabTask` -> `tabAgent Task`) and rewrites the DocType record. It MUST run
before the model sync: the renamed on-disk schema (agent_task.json,
name="Agent Task") would otherwise sync as a brand-new DocType, leaving
`tabTask` orphaned and every row stranded.

THE GUARD THAT MATTERS
======================
On a site that already has ERPNext, `frappe.db.exists("DocType", "Task")` is
TRUE — and it is ERPNext's Task, not ours. Renaming it would rip a core ERPNext
doctype out from under the site. So every rename is gated on the source DocType
belonging to the `Friday Core` module. If it doesn't, we leave it alone: either
it is ERPNext's, or this site never had Friday's.

Console artifacts (Number Cards, Dashboard Charts, the Kanban board, workspace
links) persist the doctype name in DATA, so they are repointed here too — by
Friday's own artifact names only, never blanket-updated, for the same reason.

Idempotent: a fresh site (already on the new names) and a re-run are both no-ops.
"""

from __future__ import annotations

import json

import frappe

MODULE = "Friday Core"
RENAMES = (
	("Project", "Agent Project"),
	("Task", "Agent Task"),
	("Issue", "Agent Issue"),
)

# Friday's own console artifacts — repointed by name, so a co-installed app's
# dashboards that legitimately reference ERPNext's Task are never touched.
NUMBER_CARDS = (
	"Friday Active Projects",
	"Friday Tasks Executing",
	"Friday Tasks Blocked",
	"Friday Open Issues",
)
DASHBOARD_CHARTS = ("Friday Tasks by State", "Friday Tasks Completed")
KANBAN_BOARDS = ("Task Pipeline",)
WORKSPACES = ("Projects", "Friday")


def execute() -> None:
	renamed = _rename_doctypes()
	if not renamed:
		return  # fresh site, or already namespaced — nothing downstream to fix
	_repoint_console_artifacts(renamed)


def _rename_doctypes() -> dict[str, str]:
	"""Rename only the DocTypes that are OURS. Returns {old: new} for those done."""
	done: dict[str, str] = {}
	for old, new in RENAMES:
		if frappe.db.exists("DocType", new):
			continue  # already namespaced
		if not frappe.db.exists("DocType", old):
			continue  # nothing to rename
		if frappe.db.get_value("DocType", old, "module") != MODULE:
			# Someone else's DocType of the same name (ERPNext's, most likely).
			# Leave it completely alone.
			continue
		# force=True: the on-disk JSON already carries the new name, because the
		# schema files were renamed in the same change.
		frappe.rename_doc("DocType", old, new, force=True)
		done[old] = new
	return done


def _repoint_console_artifacts(renamed: dict[str, str]) -> None:
	"""Rewrite the doctype name where Friday's console persisted it as data."""
	for name in NUMBER_CARDS:
		_repoint_row("Number Card", name, ("document_type", "filters_json"), renamed)
	for name in DASHBOARD_CHARTS:
		_repoint_row("Dashboard Chart", name, ("document_type", "filters_json"), renamed)
	for name in KANBAN_BOARDS:
		_repoint_row("Kanban Board", name, ("reference_doctype",), renamed)

	# Workspace links point at a DocType by name in a child table.
	for workspace in WORKSPACES:
		if not frappe.db.exists("Workspace", workspace):
			continue
		for old, new in renamed.items():
			frappe.db.sql(
				"""UPDATE `tabWorkspace Link` SET link_to = %s
				   WHERE parent = %s AND parenttype = 'Workspace'
				     AND link_type = 'DocType' AND link_to = %s""",
				(new, workspace, old),
			)


def _repoint_row(doctype: str, name: str, columns: tuple[str, ...], renamed: dict[str, str]) -> None:
	if not frappe.db.table_exists(doctype) or not frappe.db.exists(doctype, name):
		return
	updates: dict[str, str] = {}
	for column in columns:
		if not frappe.db.has_column(doctype, column):
			continue
		value = frappe.db.get_value(doctype, name, column)
		if not value:
			continue
		if column.endswith("_json"):
			# Filters embed the doctype name as the first element of each clause.
			try:
				clauses = json.loads(value)
			except (TypeError, ValueError):
				continue
			changed = False
			for clause in clauses:
				if isinstance(clause, list) and clause and clause[0] in renamed:
					clause[0] = renamed[clause[0]]
					changed = True
			if changed:
				updates[column] = json.dumps(clauses)
		elif value in renamed:
			updates[column] = renamed[value]
	if updates:
		frappe.db.set_value(doctype, name, updates, update_modified=False)
