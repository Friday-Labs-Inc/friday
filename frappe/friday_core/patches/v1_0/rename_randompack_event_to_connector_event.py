# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Rename `RandomPack Event` -> `Connector Event` (Design 81b, decision B).

WHY pre_model_sync
==================
`frappe.rename_doc("DocType", ...)` renames the underlying table
(`tabRandomPack Event` -> `tabConnector Event`) and rewrites the DocType
record. This MUST run *before* the model sync: the on-disk schema
(connector_event.json, name="Connector Event") would otherwise be synced as a
brand-new DocType, leaving `tabRandomPack Event` orphaned and its live event
history stranded. Running here renames the table first; the sync then applies
the new schema (incl. the added `connector` Link field) onto it.

Idempotent: guarded so a re-run — or a fresh site that never had the old
DocType — is a clean no-op. The post_model_sync companion
(`migrate_randompack_settings_to_connector`) backfills `connector` on the
renamed rows.
"""

import frappe


def execute():
	if frappe.db.exists("DocType", "RandomPack Event") and not frappe.db.exists(
		"DocType", "Connector Event"
	):
		# force=True: rename even though the on-disk JSON already carries the new
		# name (the schema file was renamed in the same change). Runs as
		# Administrator during migrate, so no ignore_permissions kwarg.
		frappe.rename_doc("DocType", "RandomPack Event", "Connector Event", force=True)
