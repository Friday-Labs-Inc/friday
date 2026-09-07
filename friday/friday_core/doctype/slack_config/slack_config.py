# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Slack Config controller (Design 90). A single doctype holding the Slack bot
token + signing secret (encrypted Password fields) and routing defaults."""

from __future__ import annotations

from frappe.model.document import Document


class SlackConfig(Document):
	pass
