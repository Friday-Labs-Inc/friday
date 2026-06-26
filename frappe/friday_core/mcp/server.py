# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Friday as an MCP **server** — expose Friday's GOVERNED skills as MCP tools.

Friday already speaks MCP as a *client* (`mcp/client.py`): it discovers and calls
tools on remote MCP servers. This is the inverse — Friday *is* the server, so any MCP
client (Claude Code, Claude Desktop, another agent framework) can drive Friday's
skills as tools.

WHY THIS IS DIFFERENT FROM AN ORDINARY MCP SERVER
=================================================
An ordinary MCP server hands out *ungoverned* tools — the client calls them directly.
Friday hands out **governed** ones: every `tools/call` is routed through the real
dispatcher, so the permission MATRIX, the AUDIT log (Execution Log), and the human
APPROVAL gate all still apply. An external client gets exactly the access a designated
Agent Profile has — no more — and every call it makes is recorded. That is the
enterprise value: a governed, audited tool backend, not a raw one.

PROTOCOL
========
We speak the same streamable-HTTP JSON-RPC 2.0 subset the client speaks, on one
guest-reachable POST endpoint authenticated by a static bearer token (the MCP spec's
transport-level auth). Methods handled:

  * `initialize`                 → protocol/version + server capabilities (tools).
  * `notifications/initialized`  → accepted, no response (it's a notification).
  * `tools/list`                 → the exposed profile's skills, as MCP tool defs.
  * `tools/call`                 → run ONE skill through the governed dispatcher.

Scoped OUT (v1): resources, prompts, sampling, SSE streaming of partial results,
per-session state, OAuth. Bearer auth + request/response JSON only — symmetric with
the client's v1 scope (design 67).

DESIGN
======
`handle_jsonrpc(...)` is the PURE core — it takes a parsed request + injectable
`list_fn`/`dispatch_fn` and returns the JSON-RPC response dict. It never touches the
HTTP layer, so it is unit-testable with no Frappe, no DB, no LLM. `handle()` is the
thin whitelisted endpoint that does auth + body I/O + a raw JSON-RPC response body.
"""

from __future__ import annotations

import json

import frappe

SERVER_NAME = "friday"
SERVER_VERSION = "0.1.0"
# The MCP protocol revision we implement against (matches the client's handshake).
PROTOCOL_VERSION = "2025-03-26"

# JSON-RPC 2.0 error codes (subset we use).
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# JSON-RPC envelope helpers
# ---------------------------------------------------------------------------


def _result(req_id, result: dict) -> dict:
	return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
	return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Default (real) backends — injected so the core stays pure for tests
# ---------------------------------------------------------------------------


def _default_list_fn(profile: str) -> list[dict]:
	"""The exposed profile's skills as MCP tool definitions.

	Reuses the skill loader, so the tool list is EXACTLY what that Agent Profile is
	allowed to see (role + matrix scoped) — the MCP client never gets more than the
	profile has. Maps each skill's JSON-Schema `parameters_schema` to MCP `inputSchema`.
	"""
	from frappe.friday_core.skills.loader import load_for_profile

	tools = []
	for skill in load_for_profile(profile):
		tools.append(
			{
				"name": skill.name,
				"description": skill.description or "",
				"inputSchema": skill.parameters_schema or {"type": "object", "properties": {}},
			}
		)
	return tools


def _default_dispatch_fn(*, name: str, arguments: dict, profile: str, session_id: str):
	"""Run ONE skill through the GOVERNED dispatcher (matrix + audit + approval gate)."""
	from frappe.friday_core.agent_runner.dispatcher import dispatch

	return dispatch(
		tool_call={"id": "", "name": name, "arguments": json.dumps(arguments or {})},
		agent_profile=profile,
		session_id=session_id,
	)


# ---------------------------------------------------------------------------
# The pure protocol core
# ---------------------------------------------------------------------------


def handle_jsonrpc(body: dict, *, profile: str, list_fn=None, dispatch_fn=None) -> dict | None:
	"""Route one JSON-RPC request and return the response dict (or None for a notification).

	`list_fn(profile) -> [tool_def]` and
	`dispatch_fn(name, arguments, profile, session_id) -> DispatchResult` are injectable
	for tests; the defaults are the real loader + governed dispatcher. Never raises — a
	handler failure becomes a JSON-RPC error response so the endpoint always replies.
	"""
	list_fn = list_fn or _default_list_fn
	dispatch_fn = dispatch_fn or _default_dispatch_fn

	if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
		return _error(body.get("id") if isinstance(body, dict) else None, _INVALID_REQUEST, "Invalid Request")

	method = body["method"]
	req_id = body.get("id")
	params = body.get("params") or {}

	# Notifications carry no id and expect no response.
	if method == "notifications/initialized":
		return None

	if method == "initialize":
		return _result(
			req_id,
			{
				"protocolVersion": PROTOCOL_VERSION,
				"serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
				"capabilities": {"tools": {}},
			},
		)

	if method == "tools/list":
		try:
			return _result(req_id, {"tools": list_fn(profile)})
		except Exception as exc:
			return _error(req_id, _INTERNAL_ERROR, f"tools/list failed: {type(exc).__name__}")

	if method == "tools/call":
		return _tools_call(req_id, params, profile, dispatch_fn)

	return _error(req_id, _METHOD_NOT_FOUND, f"Method not found: {method}")


def _tools_call(req_id, params: dict, profile: str, dispatch_fn) -> dict:
	"""Run a skill via the governed dispatcher and map the outcome to an MCP tool result.

	MCP convention: a tool that ran but failed/declined is a normal result with
	`isError: true` (NOT a JSON-RPC error — that's reserved for protocol faults). So a
	permission denial or a pending-approval pause is surfaced to the client as tool
	content, keeping Friday's governance VISIBLE to the caller.
	"""
	name = (params.get("name") or "").strip()
	if not name:
		return _error(req_id, _INVALID_REQUEST, "tools/call requires a tool 'name'")
	arguments = params.get("arguments") or {}
	session_id = f"mcp:{name}"

	try:
		outcome = dispatch_fn(name=name, arguments=arguments, profile=profile, session_id=session_id)
	except Exception as exc:
		return _result(
			req_id,
			{
				"content": [{"type": "text", "text": f"Tool execution failed: {type(exc).__name__}"}],
				"isError": True,
			},
		)

	# A gated skill paused for a human — the governance surfaces to the MCP client.
	if getattr(outcome, "pending_approval", False):
		return _result(
			req_id,
			{
				"content": [
					{"type": "text", "text": outcome.content or "This action requires human approval."}
				],
				"isError": False,
			},
		)

	text = outcome.content if getattr(outcome, "content", None) else ""
	return _result(
		req_id,
		{
			"content": [{"type": "text", "text": text}],
			"isError": not bool(getattr(outcome, "success", False)),
		},
	)


# ---------------------------------------------------------------------------
# The whitelisted HTTP endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle():
	"""POST /api/method/frappe.friday_core.mcp.server.handle — the MCP server endpoint.

	Guest-reachable; the static bearer token IS the authentication. Reads a JSON-RPC
	request, runs it through `handle_jsonrpc`, and writes the JSON-RPC response as a RAW
	body (not Frappe's `{"message": ...}` wrapper — MCP clients expect the body to BE the
	JSON-RPC message).
	"""
	from werkzeug.wrappers import Response

	config = _load_config()
	if not config.get("enabled"):
		return _raw(_error(None, _INVALID_REQUEST, "MCP server is disabled."), status=404)

	# Transport auth: a static bearer token (MCP's transport-level auth).
	auth = frappe.get_request_header("Authorization") or ""
	token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
	if not config.get("token") or token != config["token"]:
		return _raw(_error(None, _INVALID_REQUEST, "Unauthorized."), status=401)

	raw = frappe.request.get_data() if frappe.request else b"{}"
	try:
		body = json.loads(raw or b"{}")
	except (ValueError, TypeError):
		return _raw(_error(None, _PARSE_ERROR, "Parse error."), status=400)

	response = handle_jsonrpc(body, profile=config["profile"])
	if response is None:
		# A notification — acknowledge with 202 and an empty body (no JSON-RPC reply).
		return Response(status=202)
	return _raw(response, status=200)


def _raw(payload: dict, *, status: int):
	"""Send `payload` as a raw JSON body with `status` (bypasses Frappe's message wrapper)."""
	from werkzeug.wrappers import Response

	return Response(json.dumps(payload), status=status, content_type="application/json")


def _load_config() -> dict:
	"""Read the MCP Server Settings single: enabled, bearer token, exposed profile."""
	doc = frappe.get_cached_doc("MCP Server Settings")
	return {
		"enabled": bool(doc.enabled),
		"token": doc.get_password("bearer_token") if doc.bearer_token else "",
		"profile": doc.agent_profile or "",
	}
