# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Sync an MCP server's tools into governed Skill rows (design 67).

The keystone of the design: an MCP tool becomes a first-class ``Skill`` named
``mcp_<server>_<tool>`` (its ``inputSchema`` → ``parameters_schema``), so the
loader, the prompt's tool list, the permission matrix, the approval gate and the
Execution Log all work unchanged. Sync creates/updates those Skills and archives
ones the server no longer advertises — it grants nothing to any agent (that's the
operator's explicit opt-in via ``Agent Profile.permitted_skills``).
"""

from __future__ import annotations

import json
import re

import frappe
from friday.friday_core.mcp import client
from frappe.utils import now_datetime


def sanitize(name: str) -> str:
	"""Lowercase + collapse non-alphanumerics to underscores (skill-name safe)."""
	return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def skill_name_for(server_slug: str, tool_name: str) -> str:
	return f"mcp_{server_slug}_{sanitize(tool_name)}"


def server_headers(doc) -> dict:
	"""Build the static request headers for a server: bearer + any extra headers."""
	headers: dict = {}
	token = ""
	try:
		token = doc.get_password("auth_token", raise_exception=False) or ""
	except Exception:
		token = ""
	if token:
		headers["Authorization"] = f"Bearer {token}"
	extra = doc.get("headers_json")
	if extra:
		try:
			parsed = json.loads(extra) if isinstance(extra, str) else extra
			if isinstance(parsed, dict):
				headers.update({str(k): str(v) for k, v in parsed.items()})
		except Exception:
			pass
	return headers


def _split(value: str | None) -> set[str]:
	if not value:
		return set()
	return {p.strip() for p in re.split(r"[,\n]", value) if p.strip()}


def _filter_tools(tools: list[dict], include: str | None, exclude: str | None) -> list[dict]:
	inc, exc = _split(include), _split(exclude)
	if inc:
		return [t for t in tools if t.get("name") in inc]
	if exc:
		return [t for t in tools if t.get("name") not in exc]
	return tools


@frappe.whitelist()
def sync_server(server_name: str) -> dict:
	"""Whitelisted: discover + upsert a server's tools as Skills. Admin only."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("MCP Server", server_name)
	return _sync(doc)


def sync_all_due() -> dict:
	"""Cron entry: re-sync every enabled server, failure-isolated per server."""
	results = {}
	for name in frappe.get_all("MCP Server", filters={"enabled": 1}, pluck="name"):
		try:
			results[name] = _sync(frappe.get_doc("MCP Server", name))
		except Exception:
			frappe.log_error(title=f"mcp.sync: sync failed for {name!r}", message=frappe.get_traceback())
			results[name] = {"error": True}
	return results


def _sync(doc) -> dict:
	"""Do the discovery + upsert + reconcile for one server. Stamps status."""
	try:
		tools = client.list_tools(doc.base_url, headers=server_headers(doc))
		tools = _filter_tools(tools, doc.tool_include, doc.tool_exclude)
		synced = _upsert_skills(doc, tools)
		_archive_stale(doc, {t.get("name") for t in tools})
		doc.db_set("last_synced", now_datetime(), update_modified=False)
		doc.db_set("last_sync_status", f"ok: {len(synced)} tool(s)", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		return {"synced": synced, "count": len(synced)}
	except Exception as exc:
		doc.db_set(
			"last_sync_status",
			f"error: {type(exc).__name__}: {str(exc)[:200]}",
			update_modified=False,
		)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		raise


def _upsert_skills(doc, tools: list[dict]) -> list[str]:
	slug = sanitize(doc.server_name)
	created: list[str] = []
	for tool in tools:
		tool_name = tool.get("name")
		if not tool_name:
			continue
		sn = skill_name_for(slug, tool_name)
		schema = tool.get("inputSchema") or {"type": "object"}
		values = {
			"description": (tool.get("description") or f"MCP tool {tool_name} from {doc.server_name}")[:1000],
			"when_to_use": f"Provided by the {doc.server_name} MCP server.",
			"parameters_schema": json.dumps(schema),
			"mcp_server": doc.name,
			"mcp_tool_name": tool_name,
			"status": "Active",
		}
		if frappe.db.exists("Skill", sn):
			sdoc = frappe.get_doc("Skill", sn)
			for key, val in values.items():
				setattr(sdoc, key, val)
			sdoc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Skill", "skill_name": sn, "risk_level": "low", **values}).insert(
				ignore_permissions=True
			)
		created.append(sn)
	return created


def _archive_stale(doc, current_tool_names: set[str]) -> None:
	"""Archive skills for tools the server no longer advertises (never delete —
	preserves audit history + any profile links)."""
	slug = sanitize(doc.server_name)
	keep = {skill_name_for(slug, tn) for tn in current_tool_names if tn}
	for row in frappe.get_all("Skill", filters={"mcp_server": doc.name}, fields=["name", "status"]):
		if row["name"] not in keep and row["status"] != "Archived":
			frappe.db.set_value("Skill", row["name"], "status", "Archived")
