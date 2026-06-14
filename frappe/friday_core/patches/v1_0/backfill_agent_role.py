# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Backfill agent_role on existing Agent Profiles (design 68, Q6).

Profiles created before this design had no agent_role field. The DocType
default ("Specialist") only fires on new inserts, so existing rows would
read as blank. This patch sets every blank row to "Specialist" — the
gentlest role (no skill seed, default approval = medium, same prompt
shape as the pre-68 behaviour). Idempotent: rows already set to anything
are left alone.
"""

import frappe


def execute():
	rows = frappe.get_all(
		"Agent Profile",
		filters={"agent_role": ["in", ("", None)]},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value("Agent Profile", name, "agent_role", "Specialist")
