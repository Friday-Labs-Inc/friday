# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Take the Friday kernel out of the Frappe fork and into the `friday` app.

PLAIN ENGLISH
=============
Friday used to BE a fork of Frappe: its code lived at `frappe/friday_core/` and
the "Friday Core" module belonged to the `frappe` app. It is now an ordinary
Frappe app, so three pointers on an existing site still say `frappe`:

  1. `Module Def "Friday Core".app_name` — which app owns the module, and
     therefore where Frappe looks for its DocType files. Wrong value here and
     `bench migrate` treats every Friday DocType as an orphan and DELETES it,
     data included. This is why the patch runs pre-model-sync.
  2. Dotted Python paths persisted in DATA, not code: `Chat Platform.
     adapter_module` and `Connector.handler_module` both hold
     `frappe.friday_core.…` strings that no longer import.
  3. Scheduled Job Types created from the old hooks. Frappe re-syncs these from
     the new app's hooks on migrate; the stale rows are removed here so a dead
     `frappe.friday_core.…` job can't fire in the window between.

Idempotent, and a no-op on a fresh install (nothing to re-home).
"""

from __future__ import annotations

import frappe

MODULE = "Friday Core"
OLD_PREFIX = "frappe.friday_core."
NEW_PREFIX = "friday.friday_core."

# (doctype, column) pairs that persist a dotted Python path.
PATH_COLUMNS = (
	("Chat Platform", "adapter_module"),
	("Connector", "handler_module"),
)


def execute() -> None:
	_rehome_module()
	_rewrite_stored_paths()
	_drop_stale_scheduled_jobs()


def _rehome_module() -> None:
	"""Point the module at the `friday` app so schema sync finds its files."""
	if not frappe.db.exists("Module Def", MODULE):
		return  # fresh install — install-app creates it owned by `friday`
	if frappe.db.get_value("Module Def", MODULE, "app_name") != "friday":
		frappe.db.set_value("Module Def", MODULE, "app_name", "friday", update_modified=False)


def _rewrite_stored_paths() -> None:
	"""Repoint dotted paths held in DATA at the new import root."""
	for doctype, column in PATH_COLUMNS:
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, column):
			continue
		frappe.db.sql(
			f"""UPDATE `tab{doctype}`
			    SET `{column}` = REPLACE(`{column}`, %s, %s)
			    WHERE `{column}` LIKE %s""",
			(OLD_PREFIX, NEW_PREFIX, f"{OLD_PREFIX}%"),
		)


def _drop_stale_scheduled_jobs() -> None:
	"""Remove Scheduled Job Types pointing at the old import root.

	Frappe recreates them from the new app's `scheduler_events` during this same
	migrate, so deleting is safe and leaves no window where a dead dotted path
	is scheduled to fire.
	"""
	if not frappe.db.table_exists("Scheduled Job Type"):
		return
	stale = frappe.get_all(
		"Scheduled Job Type",
		filters={"method": ("like", f"{OLD_PREFIX}%")},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)
