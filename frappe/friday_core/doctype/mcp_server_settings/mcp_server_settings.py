# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""MCP Server Settings controller. A single doctype that configures Friday's MCP
server: whether it's enabled, which Agent Profile's (governed) skills are exposed as
MCP tools, and the static bearer token clients authenticate with (encrypted)."""

from __future__ import annotations

from frappe.model.document import Document


class MCPServerSettings(Document):
	pass
