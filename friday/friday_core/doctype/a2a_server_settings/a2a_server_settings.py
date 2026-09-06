# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""A2A Server Settings controller. A single doctype that configures Friday's A2A
server: whether it's enabled, which Agent Profile's (governed) skills are exposed to
other agents + advertised on the Agent Card, and the static token calling agents
authenticate with (encrypted)."""

from __future__ import annotations

from frappe.model.document import Document


class A2AServerSettings(Document):
	pass
