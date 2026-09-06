# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Unit tests for MCP tool sync + the dispatch handler (design 67)."""

import json
import unittest
from unittest.mock import MagicMock, patch


class _FakeDoc(dict):
	def __getattr__(self, k):
		return self.get(k)

	def __setattr__(self, k, v):
		self[k] = v

	def get_password(self, field, raise_exception=True):
		return self.get(f"__pw_{field}")

	def db_set(self, k, v, update_modified=True):
		self[k] = v

	def insert(self, *a, **kw):
		self["__inserted"] = True

	def save(self, *a, **kw):
		self["__saved"] = True


class TestPureHelpers(unittest.TestCase):
	def test_sanitize_and_skill_name(self):
		from friday.friday_core.mcp import sync

		self.assertEqual(sync.sanitize("My-Server!"), "my_server")
		self.assertEqual(sync.skill_name_for("github", "create-file"), "mcp_github_create_file")

	def test_filter_include_wins(self):
		from friday.friday_core.mcp import sync

		tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
		self.assertEqual([t["name"] for t in sync._filter_tools(tools, "a, c", "b")], ["a", "c"])

	def test_filter_exclude_when_no_include(self):
		from friday.friday_core.mcp import sync

		tools = [{"name": "a"}, {"name": "b"}]
		self.assertEqual([t["name"] for t in sync._filter_tools(tools, "", "b")], ["a"])


class TestServerHeaders(unittest.TestCase):
	def test_bearer_and_extra_headers(self):
		from friday.friday_core.mcp import sync

		doc = _FakeDoc({"__pw_auth_token": "tok", "headers_json": json.dumps({"X-Api": "1"})})
		headers = sync.server_headers(doc)
		self.assertEqual(headers["Authorization"], "Bearer tok")
		self.assertEqual(headers["X-Api"], "1")

	def test_no_token_no_auth(self):
		from friday.friday_core.mcp import sync

		self.assertNotIn("Authorization", sync.server_headers(_FakeDoc({})))


class TestSync(unittest.TestCase):
	@patch("friday.friday_core.mcp.sync.now_datetime", return_value="2026-06-13 12:00:00")
	@patch("friday.friday_core.mcp.sync.client")
	@patch("friday.friday_core.mcp.sync.frappe")
	def test_upserts_new_skills_and_archives_stale(self, mock_frappe, mock_client, _now):
		from friday.friday_core.mcp import sync

		doc = _FakeDoc({"server_name": "GitHub", "name": "GitHub", "base_url": "https://x/mcp"})
		mock_client.list_tools.return_value = [
			{"name": "search", "description": "find", "inputSchema": {"type": "object"}}
		]
		mock_frappe.db.exists.return_value = False
		built = []
		mock_frappe.get_doc.side_effect = lambda spec: (built.append(spec), _FakeDoc(spec))[1]
		# one stale skill from a previous sync that's no longer advertised
		mock_frappe.get_all.return_value = [{"name": "mcp_github_old_tool", "status": "Active"}]

		out = sync._sync(doc)

		self.assertEqual(out["count"], 1)
		# new skill inserted with the right name + mcp linkage
		skill_spec = next(s for s in built if s.get("doctype") == "Skill")
		self.assertEqual(skill_spec["skill_name"], "mcp_github_search")
		self.assertEqual(skill_spec["mcp_server"], "GitHub")
		self.assertEqual(skill_spec["mcp_tool_name"], "search")
		self.assertEqual(skill_spec["status"], "Active")
		# stale one archived
		mock_frappe.db.set_value.assert_called_with("Skill", "mcp_github_old_tool", "status", "Archived")
		self.assertTrue(doc["last_sync_status"].startswith("ok"))

	@patch("friday.friday_core.mcp.sync.client")
	@patch("friday.friday_core.mcp.sync.frappe")
	def test_records_error_status_and_reraises(self, mock_frappe, mock_client):
		from friday.friday_core.mcp import sync

		doc = _FakeDoc({"server_name": "Bad", "name": "Bad", "base_url": "https://x/mcp"})
		mock_client.list_tools.side_effect = RuntimeError("boom")

		with self.assertRaises(RuntimeError):
			sync._sync(doc)
		self.assertTrue(doc["last_sync_status"].startswith("error"))


class TestHandler(unittest.TestCase):
	@patch("friday.friday_core.skills.handlers_mcp.mcp_sync")
	@patch("friday.friday_core.skills.handlers_mcp.client")
	@patch("friday.friday_core.skills.handlers_mcp.frappe")
	def test_invoke_success(self, mock_frappe, mock_client, mock_sync):
		from friday.friday_core.skills import handlers_mcp

		mock_frappe.get_doc.side_effect = [
			_FakeDoc({"mcp_server": "GitHub", "mcp_tool_name": "search"}),  # Skill
			_FakeDoc({"name": "GitHub", "enabled": 1, "base_url": "https://x/mcp"}),  # Server
		]
		mock_client.call_tool.return_value = "results here"
		mock_client.McpError = Exception

		out = handlers_mcp.invoke("mcp_github_search", {"q": "x"})
		self.assertEqual(out["result"], "results here")
		mock_client.call_tool.assert_called_once()

	@patch("friday.friday_core.skills.handlers_mcp.mcp_sync")
	@patch("friday.friday_core.skills.handlers_mcp.client")
	@patch("friday.friday_core.skills.handlers_mcp.frappe")
	def test_invoke_disabled_server_raises(self, mock_frappe, mock_client, mock_sync):
		from friday.friday_core.skills import handlers_mcp

		mock_client.McpError = RuntimeError
		mock_frappe.get_doc.side_effect = [
			_FakeDoc({"mcp_server": "GitHub", "mcp_tool_name": "search"}),
			_FakeDoc({"name": "GitHub", "enabled": 0}),
		]
		with self.assertRaises(RuntimeError):
			handlers_mcp.invoke("mcp_github_search", {})

	@patch("friday.friday_core.skills.handlers_mcp.frappe")
	def test_resolve_handler(self, mock_frappe):
		from friday.friday_core.skills import handlers_mcp

		mock_frappe.db.get_value.return_value = "GitHub"
		self.assertIs(handlers_mcp.resolve_handler("mcp_github_search"), handlers_mcp.invoke)
		mock_frappe.db.get_value.return_value = None
		self.assertIsNone(handlers_mcp.resolve_handler("read-record"))


if __name__ == "__main__":
	unittest.main()
