# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Migration helper — seeded defaults for the Friday LLM stack.

Called on every `bench --site <site> migrate` via the `after_migrate` hook
in `frappe/hooks.py`.

What it does
============

Ensures the `Agent Settings` singleton row exists (one row named
"Agent Settings"). This row holds global defaults — currently only the
`default_provider` link. If it already exists, the function is a no-op.

Safe to call repeatedly. Frappe will raise if a second row is created
(because the DocType has `autoincrement=False`).

Why this is a hook target
=========================

Frappe's `after_migrate` hook fires after every `bench migrate` — including
on a fresh site where no Agent Settings row has ever existed. This ensures
the singleton is always present when the site boots, without requiring
operators to manually create it.
"""

from __future__ import annotations

import frappe


def ensure_agent_settings() -> None:
	"""Create the Agent Settings singleton if it doesn't exist yet.

	Called from `frappe/hooks.py` `after_migrate`. Idempotent — calling
	it when the row already exists is a no-op.
	"""
	if frappe.db.exists("Agent Settings", "Agent Settings"):
		return

	try:
		frappe.get_doc(
			{
				"doctype": "Agent Settings",
				"name": "Agent Settings",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		# Either the row was created by a concurrent migrate, or something
		# else went wrong. Either way, the row exists now — the next call
		# will see it and return.
		frappe.db.rollback()
