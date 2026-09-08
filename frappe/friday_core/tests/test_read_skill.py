# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the generic governed read tools (design 66a).

These tools end the "agent fabricates records because it has no read tool"
failure mode. The contract:

  - Every read goes through ``frappe.has_permission`` for the agent's
    profile. A denial returns a structured error — never a row.
  - Password-typed fields are stripped from the response so an agent
    cannot leak credentials it can "read".
  - Not-found and permission-denied collapse to one shape so the agent
    cannot probe existence of forbidden records.
"""

import unittest
from unittest.mock import MagicMock, patch

_H = "frappe.friday_core.skills.handlers_read"


def _ctx(profile="Friday", session="sess-1"):
	return {"agent_profile": profile, "session_id": session}


class TestReadRecordParameterValidation(unittest.TestCase):
	"""Parameters are validated before any DB or permission check fires."""

	@patch(f"{_H}.frappe")
	def test_missing_doctype_raises(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		with self.assertRaises(ValueError) as cm:
			read_record("read-record", {"name": "DEMO-0001"})
		self.assertIn("doctype", str(cm.exception).lower())

	@patch(f"{_H}.frappe")
	def test_missing_name_raises(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		with self.assertRaises(ValueError) as cm:
			read_record("read-record", {"doctype": "Demo Record"})
		self.assertIn("name", str(cm.exception).lower())

	@patch(f"{_H}.frappe")
	def test_missing_profile_raises(self, mock_frappe):
		"""Without an agent profile we cannot perform a permission check."""
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = {}
		with self.assertRaises(ValueError) as cm:
			read_record("read-record", {"doctype": "Demo Record", "name": "DEMO-0001"})
		self.assertIn("profile", str(cm.exception).lower())


class TestReadRecordPermissions(unittest.TestCase):
	"""Permission checks gate every read."""

	@patch(f"{_H}.frappe")
	def test_permission_denied_returns_structured_error_not_a_row(self, mock_frappe):
		"""Denial must be loud and structured — never a fake-success empty dict."""
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.db.exists.return_value = "DEMO-0001"
		mock_frappe.has_permission.return_value = False

		out = read_record("read-record", {"doctype": "Demo Record", "name": "DEMO-0001"})

		# Permission denial collapses to not_found_or_unreadable — deliberately
		# ambiguous so an agent cannot probe forbidden-vs-missing.
		self.assertEqual(out["error"], "not_found_or_unreadable")
		self.assertNotIn("record", out)

	@patch(f"{_H}.frappe")
	def test_unknown_doctype_returns_structured_error(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		# Frappe raises DoesNotExistError on get_meta for unknown DocTypes.
		mock_frappe.get_meta.side_effect = Exception("DoesNotExistError")

		out = read_record("read-record", {"doctype": "Imaginary Type", "name": "X"})

		self.assertEqual(out["error"], "unknown_doctype")

	@patch(f"{_H}.frappe")
	def test_not_found_returns_structured_error(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.db.exists.return_value = None  # row truly missing

		out = read_record("read-record", {"doctype": "Demo Record", "name": "DEMO-NOPE"})

		self.assertEqual(out["error"], "not_found_or_unreadable")


class TestReadRecordSuccess(unittest.TestCase):
	"""On allowed reads, the row's fields come back, sensitive ones stripped."""

	@patch(f"{_H}.frappe")
	def test_returns_row_fields_on_success(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.db.exists.return_value = "DEMO-0001"
		mock_frappe.has_permission.return_value = True

		# Frappe meta + doc behaviour
		field1 = MagicMock(fieldname="direction_name", fieldtype="Data")
		field2 = MagicMock(fieldname="concept_story", fieldtype="Long Text")
		meta = MagicMock()
		meta.fields = [field1, field2]
		mock_frappe.get_meta.return_value = meta

		doc = MagicMock()
		doc.as_dict.return_value = {
			"name": "DEMO-0001",
			"direction_name": "Midnight Atelier",
			"concept_story": "Story...",
			"creation": "2026-06-13 12:00:00",
			"modified": "2026-06-13 12:00:00",
			"owner": "agent@friday",
			"docstatus": 0,
		}
		mock_frappe.get_doc.return_value = doc

		out = read_record("read-record", {"doctype": "Demo Record", "name": "DEMO-0001"})

		self.assertEqual(out["doctype"], "Demo Record")
		self.assertEqual(out["name"], "DEMO-0001")
		self.assertEqual(out["record"]["direction_name"], "Midnight Atelier")
		self.assertEqual(out["record"]["concept_story"], "Story...")

	@patch(f"{_H}.frappe")
	def test_password_fields_are_stripped(self, mock_frappe):
		"""A Password-type field must never appear in the returned record."""
		from frappe.friday_core.skills.handlers_read import read_record

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.db.exists.return_value = "P-1"
		mock_frappe.has_permission.return_value = True

		field_api = MagicMock(fieldname="api_key", fieldtype="Password")
		field_name = MagicMock(fieldname="provider_name", fieldtype="Data")
		meta = MagicMock()
		meta.fields = [field_api, field_name]
		mock_frappe.get_meta.return_value = meta

		doc = MagicMock()
		doc.as_dict.return_value = {
			"name": "P-1",
			"provider_name": "Anthropic",
			"api_key": "sk-secret-do-not-leak",
		}
		mock_frappe.get_doc.return_value = doc

		out = read_record("read-record", {"doctype": "LLM Provider", "name": "P-1"})

		self.assertNotIn("api_key", out["record"])
		self.assertEqual(out["record"]["provider_name"], "Anthropic")


class TestListRecords(unittest.TestCase):
	"""list-records returns a permission-gated, capped slice of rows."""

	@patch(f"{_H}.frappe")
	def test_missing_doctype_raises(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import list_records

		mock_frappe.flags.get.return_value = _ctx()
		with self.assertRaises(ValueError):
			list_records("list-records", {})

	@patch(f"{_H}.frappe")
	def test_passes_filters_through_to_frappe_get_all(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import list_records

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.has_permission.return_value = True
		mock_frappe.get_meta.return_value = MagicMock(fields=[])
		mock_frappe.db.get_all.return_value = []

		list_records(
			"list-records",
			{"doctype": "Demo Record", "filters": {"project": "PRJ-0001"}, "limit": 20},
		)

		call = mock_frappe.db.get_all.call_args
		self.assertEqual(call.args[0], "Demo Record")
		self.assertEqual(call.kwargs["filters"], {"project": "PRJ-0001"})
		# Limit must be capped to a sane maximum even if caller passes more
		# (prevents the agent from accidentally pulling 50k rows).
		self.assertLessEqual(call.kwargs.get("limit_page_length", 0), 100)

	@patch(f"{_H}.frappe")
	def test_caps_limit_at_max(self, mock_frappe):
		from frappe.friday_core.skills.handlers_read import list_records

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.has_permission.return_value = True
		mock_frappe.get_meta.return_value = MagicMock(fields=[])
		mock_frappe.db.get_all.return_value = []

		list_records("list-records", {"doctype": "Demo Record", "limit": 50000})

		call = mock_frappe.db.get_all.call_args
		self.assertEqual(call.kwargs["limit_page_length"], 100)  # MAX_LIST_ROWS

	@patch(f"{_H}.frappe")
	def test_permission_denied_returns_empty_list_not_a_crash(self, mock_frappe):
		"""Denial returns rows=[] with the denied flag — never raises into the agent's turn."""
		from frappe.friday_core.skills.handlers_read import list_records

		mock_frappe.flags.get.return_value = _ctx()
		mock_frappe.has_permission.return_value = False

		out = list_records("list-records", {"doctype": "Demo Record"})

		self.assertEqual(out["rows"], [])
		self.assertTrue(out.get("denied"))


class TestPromptFrame(unittest.TestCase):
	"""The fail-loud governance line lands in every agent's system prompt."""

	def test_governance_text_present_in_frame(self):
		from frappe.friday_core.llm.prompt_builder import _build_system_prompt

		profile = MagicMock()
		profile.system_prompt = "Be helpful."

		out = _build_system_prompt(profile)

		self.assertIn("GOVERNANCE", out)
		# Key fail-loud assertions — phrasing may evolve but the intent stays.
		self.assertIn("do not have a tool", out.lower())
		self.assertIn("never invent", out.lower())
		# The operator's prompt still rides along, verbatim, AFTER the frame.
		self.assertTrue(out.endswith("Be helpful."))


if __name__ == "__main__":
	unittest.main()
