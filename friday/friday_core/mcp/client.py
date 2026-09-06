# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
A minimal MCP (Model Context Protocol) streamable-HTTP client (design 67).

Friday's RQ workers are synchronous and ``requests``-based, so rather than pull
in the asyncio ``mcp`` SDK we speak the streamable-HTTP request/response subset
of MCP by hand as JSON-RPC 2.0 over HTTP POST. That's enough for the two things
Friday needs: discover a remote server's tools (``tools/list``) and call one
(``tools/call``).

Per spec the response to a POST may be a single JSON object OR an SSE stream
carrying the JSON-RPC message in a ``data:`` line — we parse both. Each operation
runs the full handshake (``initialize`` → ``notifications/initialized`` → the
call) statelessly, because a worker doesn't hold a session across jobs; the
latency cost is accepted for v1 (a per-turn session cache is a later optimization).

Scoped OUT (design 67): stdio transport, SSE *streaming* of partial results,
sampling, resources/prompts, OAuth. Static bearer/header auth only.
"""

from __future__ import annotations

import json

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "friday", "version": "0.2"}
DEFAULT_TIMEOUT = 60


class McpError(Exception):
	"""An MCP transport/protocol/tool failure (a real class — raises cleanly
	under mocked tests, and the dispatch handler turns it into a tool-result
	error the model can read)."""


def list_tools(base_url: str, *, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
	"""Return the server's advertised tools: ``[{name, description, inputSchema}]``."""
	session = _Session(base_url, headers or {}, timeout)
	session.initialize()
	result = session.request("tools/list", {})
	return result.get("tools", []) or []


def call_tool(
	base_url: str,
	tool_name: str,
	arguments: dict | None = None,
	*,
	headers: dict | None = None,
	timeout: int = DEFAULT_TIMEOUT,
) -> str:
	"""Call one tool; return its text result. Raises ``McpError`` on tool error."""
	session = _Session(base_url, headers or {}, timeout)
	session.initialize()
	result = session.request("tools/call", {"name": tool_name, "arguments": arguments or {}})
	if result.get("isError"):
		raise McpError(_extract_text(result) or "MCP tool returned an error.")
	return _extract_text(result)


class _Session:
	"""One stateless MCP conversation against a single endpoint."""

	def __init__(self, base_url: str, headers: dict, timeout: int):
		if not (base_url.startswith("http://") or base_url.startswith("https://")):
			raise McpError(f"Refusing non-http MCP URL: {base_url!r}")
		self.base_url = base_url
		self.headers = headers
		self.timeout = timeout
		self.session_id: str | None = None
		self._id = 0

	def initialize(self) -> dict:
		result = self.request(
			"initialize",
			{"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
		)
		# The server expects an `initialized` notification before real calls.
		self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, is_notification=True)
		return result

	def request(self, method: str, params: dict) -> dict:
		self._id += 1
		message = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
		if message is None:
			raise McpError(f"Empty MCP response for {method!r}.")
		if message.get("error"):
			err = message["error"]
			raise McpError(f"MCP error {err.get('code')}: {err.get('message')}")
		return message.get("result") or {}

	def _post(self, payload: dict, *, is_notification: bool = False) -> dict | None:
		headers = {
			"Content-Type": "application/json",
			"Accept": "application/json, text/event-stream",
			**self.headers,
		}
		if self.session_id:
			headers["Mcp-Session-Id"] = self.session_id

		resp = requests.post(self.base_url, json=payload, headers=headers, timeout=self.timeout)

		# Capture the session id the server may hand back on initialize.
		sid = resp.headers.get("Mcp-Session-Id")
		if sid:
			self.session_id = sid

		if is_notification:
			if resp.status_code >= 300 and resp.status_code != 202:
				raise McpError(f"MCP notification failed (HTTP {resp.status_code}).")
			return None

		if resp.status_code >= 300:
			raise McpError(f"MCP request failed (HTTP {resp.status_code}).")
		return _parse_message(resp)


def _parse_message(resp) -> dict | None:
	"""Parse a JSON-RPC message from a JSON or SSE response body."""
	ctype = (resp.headers.get("Content-Type") or "").lower()
	if "text/event-stream" in ctype:
		return _parse_sse(resp.text)
	try:
		return resp.json()
	except Exception:
		# Some servers send SSE framing without the header — try it before giving up.
		parsed = _parse_sse(resp.text)
		if parsed is not None:
			return parsed
		raise McpError("MCP response was not valid JSON.")


def _parse_sse(text: str) -> dict | None:
	"""Return the last JSON-RPC message carried in an SSE ``data:`` line."""
	message = None
	for line in (text or "").splitlines():
		line = line.strip()
		if not line.startswith("data:"):
			continue
		data = line[len("data:") :].strip()
		if not data or data == "[DONE]":
			continue
		try:
			obj = json.loads(data)
		except Exception:
			continue
		if isinstance(obj, dict) and ("result" in obj or "error" in obj or "id" in obj):
			message = obj
	return message


def _extract_text(result: dict) -> str:
	"""Join the text content blocks of a tools/call result.

	Falls back to the JSON of ``structuredContent`` when there are no text blocks,
	so a structured-only result still reaches the model rather than going blank.
	"""
	parts = [b.get("text", "") for b in (result.get("content") or []) if b.get("type") == "text"]
	if parts:
		return "\n".join(parts)
	if result.get("structuredContent"):
		return json.dumps(result["structuredContent"])
	return ""
