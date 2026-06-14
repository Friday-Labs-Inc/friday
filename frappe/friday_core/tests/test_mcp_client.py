# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Unit tests for the MCP streamable-HTTP client (design 67)."""

import json
import unittest
from unittest.mock import MagicMock, patch


def _resp(status=200, body=None, ctype="application/json", session_id=None):
	r = MagicMock()
	r.status_code = status
	headers = {"Content-Type": ctype}
	if session_id:
		headers["Mcp-Session-Id"] = session_id
	r.headers = headers
	r.text = body if isinstance(body, str) else json.dumps(body or {})
	r.json.return_value = body or {}
	return r


def _rpc_ok(result):
	return {"jsonrpc": "2.0", "id": 1, "result": result}


class TestListTools(unittest.TestCase):
	@patch("frappe.friday_core.mcp.client.requests")
	def test_handshake_then_list(self, mock_requests):
		from frappe.friday_core.mcp import client

		mock_requests.post.side_effect = [
			_resp(body=_rpc_ok({"protocolVersion": "x"}), session_id="sess-1"),  # initialize
			_resp(status=202, body=""),  # initialized notification
			_resp(body=_rpc_ok({"tools": [{"name": "search", "inputSchema": {"type": "object"}}]})),
		]
		tools = client.list_tools("https://mcp.example.com/mcp")
		self.assertEqual(tools[0]["name"], "search")
		self.assertEqual(mock_requests.post.call_count, 3)
		# session id captured from initialize is sent on the tools/list call
		third_headers = mock_requests.post.call_args_list[2].kwargs["headers"]
		self.assertEqual(third_headers["Mcp-Session-Id"], "sess-1")


class TestCallTool(unittest.TestCase):
	@patch("frappe.friday_core.mcp.client.requests")
	def test_success_returns_text(self, mock_requests):
		from frappe.friday_core.mcp import client

		mock_requests.post.side_effect = [
			_resp(body=_rpc_ok({})),  # initialize
			_resp(status=202, body=""),  # initialized
			_resp(body=_rpc_ok({"content": [{"type": "text", "text": "hello world"}]})),
		]
		out = client.call_tool("https://mcp.example.com/mcp", "search", {"q": "x"})
		self.assertEqual(out, "hello world")

	@patch("frappe.friday_core.mcp.client.requests")
	def test_is_error_raises(self, mock_requests):
		from frappe.friday_core.mcp import client

		mock_requests.post.side_effect = [
			_resp(body=_rpc_ok({})),
			_resp(status=202, body=""),
			_resp(body=_rpc_ok({"isError": True, "content": [{"type": "text", "text": "boom"}]})),
		]
		with self.assertRaises(client.McpError):
			client.call_tool("https://mcp.example.com/mcp", "search", {})

	@patch("frappe.friday_core.mcp.client.requests")
	def test_jsonrpc_error_raises(self, mock_requests):
		from frappe.friday_core.mcp import client

		mock_requests.post.side_effect = [
			_resp(body={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no method"}}),
		]
		with self.assertRaises(client.McpError):
			client.call_tool("https://mcp.example.com/mcp", "search", {})

	@patch("frappe.friday_core.mcp.client.requests")
	def test_structured_content_fallback(self, mock_requests):
		from frappe.friday_core.mcp import client

		mock_requests.post.side_effect = [
			_resp(body=_rpc_ok({})),
			_resp(status=202, body=""),
			_resp(body=_rpc_ok({"structuredContent": {"answer": 42}})),
		]
		out = client.call_tool("https://mcp.example.com/mcp", "calc", {})
		self.assertEqual(json.loads(out), {"answer": 42})


class TestSseParsing(unittest.TestCase):
	@patch("frappe.friday_core.mcp.client.requests")
	def test_parses_sse_response(self, mock_requests):
		from frappe.friday_core.mcp import client

		sse = "event: message\ndata: " + json.dumps(_rpc_ok({"tools": []})) + "\n\n"
		mock_requests.post.side_effect = [
			_resp(body=_rpc_ok({})),  # initialize (plain JSON)
			_resp(status=202, body=""),
			_resp(body=sse, ctype="text/event-stream"),  # tools/list as SSE
		]
		tools = client.list_tools("https://mcp.example.com/mcp")
		self.assertEqual(tools, [])
		self.assertEqual(mock_requests.post.call_count, 3)


class TestUrlGuard(unittest.TestCase):
	def test_non_http_url_refused(self):
		from frappe.friday_core.mcp import client

		with self.assertRaises(client.McpError):
			client.list_tools("file:///etc/passwd")


if __name__ == "__main__":
	unittest.main()
