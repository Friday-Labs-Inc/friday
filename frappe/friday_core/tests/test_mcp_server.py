# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Unit tests for the MCP server core (Friday as a governed MCP server).

DB-free: `handle_jsonrpc` is the pure protocol+governance core with injectable
`list_fn`/`dispatch_fn`, so these exercise the JSON-RPC routing, the skill→tool
mapping, and — the whole point — that `tools/call` goes through the GOVERNED dispatcher
and surfaces denial / pending-approval to the client. No Frappe, no DB, no HTTP.
"""

from __future__ import annotations

import types
import unittest
from unittest import mock

from frappe.friday_core.mcp import server


def _ok(content="done", success=True, pending=False):
	"""A fake DispatchResult."""
	return types.SimpleNamespace(content=content, success=success, pending_approval=pending)


class TestInitialize(unittest.TestCase):
	def test_initialize_advertises_tools_capability(self):
		resp = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, profile="P")
		self.assertEqual(resp["id"], 1)
		self.assertEqual(resp["result"]["serverInfo"]["name"], "friday")
		self.assertIn("tools", resp["result"]["capabilities"])
		self.assertEqual(resp["result"]["protocolVersion"], server.PROTOCOL_VERSION)

	def test_initialized_notification_has_no_response(self):
		resp = server.handle_jsonrpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, profile="P")
		self.assertIsNone(resp)


class TestToolsList(unittest.TestCase):
	def test_lists_the_profiles_skills_as_mcp_tools(self):
		def list_fn(profile):
			self.assertEqual(profile, "P")
			return [
				{"name": "list-projects", "description": "List projects", "inputSchema": {"type": "object"}}
			]

		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, profile="P", list_fn=list_fn
		)
		tools = resp["result"]["tools"]
		self.assertEqual(tools[0]["name"], "list-projects")
		self.assertIn("inputSchema", tools[0])

	def test_list_failure_is_a_jsonrpc_error_not_a_crash(self):
		def boom(profile):
			raise RuntimeError("loader down")

		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, profile="P", list_fn=boom
		)
		self.assertIn("error", resp)


class TestToolsCallIsGoverned(unittest.TestCase):
	def test_call_routes_through_the_dispatcher_with_the_profile(self):
		seen = {}

		def dispatch_fn(*, name, arguments, profile, session_id):
			seen.update(name=name, arguments=arguments, profile=profile, session_id=session_id)
			return _ok(content="3 projects")

		resp = server.handle_jsonrpc(
			{
				"jsonrpc": "2.0",
				"id": 3,
				"method": "tools/call",
				"params": {"name": "list-projects", "arguments": {"limit": 5}},
			},
			profile="Friday",
			dispatch_fn=dispatch_fn,
		)
		# Routed through the governed dispatcher AS the exposed profile.
		self.assertEqual(seen["name"], "list-projects")
		self.assertEqual(seen["profile"], "Friday")
		self.assertEqual(seen["arguments"], {"limit": 5})
		# Successful tool result.
		self.assertFalse(resp["result"]["isError"])
		self.assertEqual(resp["result"]["content"][0]["text"], "3 projects")

	def test_denied_or_failed_call_is_a_tool_error_not_a_protocol_error(self):
		# A permission denial / failure is conveyed as a normal result with isError=true
		# (MCP convention) — NOT a JSON-RPC error. Governance stays visible to the client.
		def dispatch_fn(**kw):
			return _ok(content="I don't have permission to do that.", success=False)

		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "danger"}},
			profile="Friday",
			dispatch_fn=dispatch_fn,
		)
		self.assertIn("result", resp)
		self.assertTrue(resp["result"]["isError"])
		self.assertIn("permission", resp["result"]["content"][0]["text"].lower())

	def test_pending_approval_is_surfaced_to_the_client(self):
		# The enterprise differentiator: a gated skill called over MCP PAUSES for a human,
		# and the client is told so — the approval gate is enforced for external callers.
		def dispatch_fn(**kw):
			return _ok(content="This action needs human approval (Workflow Request WR-9).", pending=True)

		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "send-email"}},
			profile="Friday",
			dispatch_fn=dispatch_fn,
		)
		self.assertFalse(resp["result"]["isError"])
		self.assertIn("approval", resp["result"]["content"][0]["text"].lower())

	def test_dispatch_exception_becomes_a_tool_error(self):
		def dispatch_fn(**kw):
			raise RuntimeError("sandbox down")

		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "x"}},
			profile="Friday",
			dispatch_fn=dispatch_fn,
		)
		self.assertTrue(resp["result"]["isError"])

	def test_call_without_name_is_invalid(self):
		resp = server.handle_jsonrpc(
			{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {}}, profile="Friday"
		)
		self.assertIn("error", resp)


class TestProtocolErrors(unittest.TestCase):
	def test_unknown_method(self):
		resp = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 8, "method": "resources/list"}, profile="P")
		self.assertEqual(resp["error"]["code"], -32601)

	def test_malformed_request_is_invalid(self):
		resp = server.handle_jsonrpc({"not": "jsonrpc"}, profile="P")
		self.assertEqual(resp["error"]["code"], -32600)


class TestEndpointIsRoutable(unittest.TestCase):
	"""The bug this guards (caught on a real-path probe, not by the core tests): `handle()`
	shipped WITHOUT `@frappe.whitelist`, so the HTTP endpoint was unreachable (403
	not-whitelisted) even when enabled — invisible to tests that call `handle_jsonrpc`
	directly. Assert the Frappe ROUTING registration, not just the protocol core."""

	def test_handle_is_whitelisted_guest_post(self):
		import frappe

		self.assertIn(server.handle, frappe.whitelisted)
		self.assertIn(server.handle, frappe.guest_methods)
		self.assertIn("POST", frappe.allowed_http_methods_for_whitelisted_func[server.handle])


class TestAuth(unittest.TestCase):
	"""The token rides the `X-MCP-Token` header, NOT `Authorization: Bearer` — Frappe's
	auth middleware 401s any non-OAuth Bearer before the endpoint runs (caught live on
	ai.randompack.com). These pin the header name + the constant-time compare."""

	def test_reads_the_x_mcp_token_header(self):
		with mock.patch.object(server, "frappe") as fr:
			fr.get_request_header.return_value = "s3cr3t"
			self.assertTrue(server._authorized({"token": "s3cr3t"}))
		fr.get_request_header.assert_called_once_with("X-MCP-Token")  # NOT "Authorization"

	def test_wrong_token_rejected(self):
		with mock.patch.object(server, "frappe") as fr:
			fr.get_request_header.return_value = "nope"
			self.assertFalse(server._authorized({"token": "s3cr3t"}))

	def test_missing_header_rejected(self):
		with mock.patch.object(server, "frappe") as fr:
			fr.get_request_header.return_value = None
			self.assertFalse(server._authorized({"token": "s3cr3t"}))

	def test_unconfigured_token_rejects_everything(self):
		# No configured token → unreachable even if a header is sent (fail closed).
		with mock.patch.object(server, "frappe") as fr:
			fr.get_request_header.return_value = "anything"
			self.assertFalse(server._authorized({"token": ""}))


if __name__ == "__main__":
	unittest.main()
