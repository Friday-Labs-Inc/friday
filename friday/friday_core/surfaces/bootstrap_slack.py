# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Provisioning for the Slack surface (Design 90). Idempotent; runs on every
migrate. Ensures the `slack` Chat Platform row exists (dispatch_mode=async, so
inbound webhook calls return fast and the friday worker runs the turn) and the
Slack Config single exists for the operator to fill in.

The operator still does the one-time external setup: create a Slack app, add the
bot token + signing secret to Slack Config, and point the app's Event
Subscriptions request URL at `…/api/method/friday.friday_core.surfaces.slack_adapter.receive_event`.
"""

from __future__ import annotations

import frappe

SLACK_PLATFORM = "slack"
_ADAPTER_MODULE = "friday.friday_core.surfaces.slack_adapter"


def provision() -> dict:
	"""Ensure the `slack` Chat Platform row + the Slack Config single. Idempotent."""
	if not frappe.db.exists("Chat Platform", SLACK_PLATFORM):
		frappe.get_doc(
			{
				"doctype": "Chat Platform",
				"platform_name": SLACK_PLATFORM,
				"adapter_module": _ADAPTER_MODULE,
				"enabled": 0,
				"dispatch_mode": "async",
			}
		).insert(ignore_permissions=True)

	# Touch the single so it exists in Desk for the operator to configure.
	if frappe.db.exists("DocType", "Slack Config") and not frappe.db.exists("Slack Config", "Slack Config"):
		frappe.get_doc({"doctype": "Slack Config"}).insert(ignore_permissions=True)

	return {"platform": SLACK_PLATFORM}
