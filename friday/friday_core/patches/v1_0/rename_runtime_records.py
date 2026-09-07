"""Agent Project / Agent Task / Agent Issue -> Agent Run / Agent Job / Agent Blocker.

They are the ENGINE's runtime records — a run of agent work, one job inside it,
a blocker that needs a human — not project management. On a site that also
runs ERPNext the old names read as a second PM tool. Pre-model-sync, gated on
the source DocType belonging to Friday Core (never touches another app's).

Also deletes the tracker surfaces provision_console used to create (Kanban,
Number Cards, Dashboard Charts, the Projects and Friday workspaces): the
studio product and the dispatcher console are the operator surfaces now.
"""

import frappe

MODULE = "Friday Core"
RENAMES = [("Agent Project", "Agent Run"), ("Agent Task", "Agent Job"), ("Agent Issue", "Agent Blocker")]
NUMBER_CARDS = ['Friday Active Projects', 'Friday Tasks Executing', 'Friday Tasks Blocked', 'Friday Open Issues']
DASHBOARD_CHARTS = ["Friday Tasks by State", "Friday Tasks Completed"]
KANBAN_BOARDS = ["Task Pipeline"]
WORKSPACES = ["Projects", "Friday"]


def execute():
	for old, new in RENAMES:
		if frappe.db.get_value("DocType", old, "module") != MODULE:
			continue
		if frappe.db.exists("DocType", new):
			continue
		frappe.rename_doc("DocType", old, new, force=True)
	# Only OUR artifacts. Workspace / Number Card / Dashboard Chart carry a module;
	# ERPNext ships a "Projects" workspace of its own and must not be touched.
	for doctype, names in (
		("Number Card", NUMBER_CARDS),
		("Dashboard Chart", DASHBOARD_CHARTS),
		("Workspace", WORKSPACES),
	):
		if not frappe.db.table_exists(doctype):
			continue
		for name in names:
			if frappe.db.get_value(doctype, name, "module") == MODULE:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	# Kanban Board has no module; ours is the one on the engine's job DocType.
	if frappe.db.table_exists("Kanban Board"):
		ours = {new for _, new in RENAMES} | {old for old, _ in RENAMES}
		for name in KANBAN_BOARDS:
			if frappe.db.get_value("Kanban Board", name, "reference_doctype") in ours:
				frappe.delete_doc("Kanban Board", name, force=True, ignore_permissions=True)
	frappe.db.commit()
