# Copyright (c) 2026, Friday Labs and contributors
"""`on_actor_write` hook (Design 99): record every row an agent writes.

The framework calls this after any non-child document save/submit/cancel/delete.
We keep only AGENT actors, skip the audit/log doctypes themselves, and never
raise — the audit trail must not be able to break the write it records.
"""

import frappe

SKIP_DOCTYPES = frozenset({
	"Agent Write Log", "Execution Log", "Permission Decision Log", "LLM Usage Log",
	"Dispatcher Event", "Turn Event", "Task Completion Summary", "Version", "Error Log",
	"Comment", "Activity Log", "Access Log", "Deleted Document", "Notification Log",
})


def on_actor_write(doc, action: str) -> None:
	actor = frappe.get_actor()
	if actor.get("kind") != "agent" or doc.doctype in SKIP_DOCTYPES:
		return
	if not frappe.db.table_exists("Agent Write Log"):
		return
	try:
		frappe.db.savepoint("friday_actor_write")
		frappe.get_doc({
			"doctype": "Agent Write Log",
			"ref_doctype": doc.doctype,
			"ref_name": doc.name,
			"action": action,
			"actor": actor.get("id"),
			"actor_kind": actor.get("kind"),
			"user": frappe.session.user,
			"trace_id": actor.get("trace_id"),
		}).insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point="friday_actor_write")
		frappe.logger("friday.audit").warning("agent write log failed", exc_info=True)
