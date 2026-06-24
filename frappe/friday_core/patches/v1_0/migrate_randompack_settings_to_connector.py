# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Migrate the `RandomPack Settings` singleton onto the Connector spine (Design 81b).

Companion to the pre_model_sync `rename_randompack_event_to_connector_event`.
By the time this runs (post model sync), `tabConnector` and `tabConnector Event`
exist. This patch:

  1. Copies the old RandomPack Settings config + encrypted secrets into the
     `randompack-system` Connector row (decision A: migrate then delete).
  2. Backfills `connector` on the renamed Connector Event rows.
  3. Retires the RandomPack Settings DocType (and its Singles / auth traces) so
     it cannot resurrect on a later migrate.

Meta-independent on purpose: the RandomPack Settings on-disk schema is deleted
in the same change, so we read the old values straight from `tabSingles` +
the encrypted-password store rather than via `get_single` (which needs meta).

Idempotent: a re-run, or a fresh site that never had RandomPack Settings, is a
clean no-op (the domain's after_migrate creates a disabled Connector stub
instead).
"""

import frappe
from frappe.utils.password import get_decrypted_password

CONNECTOR_NAME = "randompack-system"
HANDLER_MODULE = "frappe.friday_core.surfaces.randompack"
OLD_SETTINGS = "RandomPack Settings"


def execute():
	# NB: query tabSingles by raw SQL — `frappe.db.exists("Singles", ...)` emits
	# `SELECT name FROM tabSingles`, but that table has no `name` column
	# (doctype/field/value), which errors and poisons the transaction.
	had_settings = bool(
		frappe.db.sql("SELECT 1 FROM `tabSingles` WHERE doctype=%s LIMIT 1", (OLD_SETTINGS,))
	)

	if had_settings:
		values = frappe.db.get_singles_dict(OLD_SETTINGS) or {}
		api_secret = _decrypt(OLD_SETTINGS, "api_secret")
		webhook_secret = _decrypt(OLD_SETTINGS, "webhook_secret")

		if frappe.db.exists("Connector", CONNECTOR_NAME):
			connector = frappe.get_doc("Connector", CONNECTOR_NAME)
		else:
			connector = frappe.new_doc("Connector")
			connector.connector_name = CONNECTOR_NAME

		connector.modality = "system"
		connector.direction = "Both"
		connector.handler_module = HANDLER_MODULE
		connector.enabled = int(values.get("enabled") or 0)
		connector.api_base_url = values.get("api_base_url") or ""
		connector.api_key = values.get("api_key") or ""
		connector.signature_tolerance_seconds = int(values.get("signature_tolerance_seconds") or 300)
		# Only set secrets we actually recovered — never blank an existing one.
		if api_secret:
			connector.api_secret = api_secret
		if webhook_secret:
			connector.webhook_secret = webhook_secret
		connector.save(ignore_permissions=True)

	# Backfill the connector tag on the renamed event history.
	if frappe.db.exists("DocType", "Connector Event"):
		frappe.db.sql(
			"UPDATE `tabConnector Event` SET connector=%s WHERE connector IS NULL OR connector=''",
			(CONNECTOR_NAME,),
		)

	# Retire the old singleton so the model sync can't recreate it.
	if frappe.db.exists("DocType", OLD_SETTINGS):
		try:
			frappe.delete_doc("DocType", OLD_SETTINGS, force=True, ignore_missing=True)
		except Exception:
			frappe.log_error(title="81b: delete RandomPack Settings DocType failed")
	# Scrub any residual Single values + encrypted-password rows regardless.
	frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype=%s", (OLD_SETTINGS,))
	frappe.db.sql("DELETE FROM `__Auth` WHERE doctype=%s", (OLD_SETTINGS,))


def _decrypt(doctype: str, fieldname: str) -> str:
	try:
		return get_decrypted_password(doctype, doctype, fieldname, raise_exception=False) or ""
	except Exception:
		return ""
