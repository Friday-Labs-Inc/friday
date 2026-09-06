# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Dispatch handler for MCP-sourced skills (design 67).

MCP skills have dynamic names (``mcp_<server>_<tool>``), so they can't be
pre-registered in the static handler table. Instead the dispatcher falls back to
``resolve_handler``: if a Skill row carries an ``mcp_server`` link, this generic
handler routes the call to that server via the MCP client.

It returns ``{"result": <text>}`` on success and **raises** ``McpError`` on
failure so the dispatcher's exception path writes the error Execution Log and
surfaces a tool-result error to the model — never a silent empty success. Error
text is scrubbed of obvious secret patterns first.
"""

from __future__ import annotations

import re

import frappe
from friday.friday_core.mcp import client
from friday.friday_core.mcp import sync as mcp_sync

# Strip obvious credential shapes from any error text before the model sees it.
_SECRET_RE = re.compile(
	r"(Bearer\s+[A-Za-z0-9._\-]+|sk-[A-Za-z0-9._\-]+|ghp_[A-Za-z0-9]+|(?:token|key|secret|password)\s*[=:]\s*\S+)",
	re.IGNORECASE,
)


def _scrub(text: str) -> str:
	return _SECRET_RE.sub("[redacted]", text or "")


def invoke(skill_name: str, parameters: dict) -> dict:
	"""Call the MCP tool backing ``skill_name``. Returns ``{"result": text}``."""
	skill = frappe.get_doc("Skill", skill_name)
	server = frappe.get_doc("MCP Server", skill.mcp_server)
	if not server.enabled:
		raise client.McpError(f"MCP server {server.name!r} is disabled.")
	try:
		text = client.call_tool(
			server.base_url,
			skill.mcp_tool_name,
			parameters or {},
			headers=mcp_sync.server_headers(server),
		)
	except client.McpError as exc:
		# Re-raise scrubbed so the dispatcher's error path can't leak a secret.
		raise client.McpError(_scrub(str(exc))) from None
	return {"result": text}


def resolve_handler(skill_name: str):
	"""Return ``invoke`` if this skill is MCP-backed, else None (dispatcher seam)."""
	if frappe.db.get_value("Skill", skill_name, "mcp_server"):
		return invoke
	return None
