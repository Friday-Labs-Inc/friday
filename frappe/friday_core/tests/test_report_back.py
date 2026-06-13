# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for agent report-back (design 62).

Two behaviours:
  - the War Room post leads with the AGENT as speaker (not the task);
  - a task with an originating_session writes one outbound Chat Message
    back to that session on a terminal transition, authored by the
    agent profile that did the work.
"""

import unittest
from unittest.mock import MagicMock, patch

_RB = "frappe.friday_core.tasks.report_back"
_PUB = "frappe.friday_core.warroom.publisher"


class TestWarRoomSpeakerIdentity(unittest.TestCase):
	"""The War Room message names the agent that did the work."""

	def test_format_leads_with_agent_profile(self):
		from frappe.friday_core.warroom.publisher import _format_message_text

		text = _format_message_text("TASK-42", "completed", {"profile": "Copywriter"})

		# Agent identity must appear, and the message must read as that agent
		# speaking — not just a faceless task line.
		self.assertIn("Copywriter", text)
		self.assertIn("TASK-42", text)
		# The profile leads (appears before the task ref in the rendered text).
		self.assertLess(text.index("Copywriter"), text.index("TASK-42"))

	def test_format_without_profile_still_renders(self):
		from frappe.friday_core.warroom.publisher import _format_message_text

		text = _format_message_text("TASK-42", "completed", None)
		self.assertIn("TASK-42", text)


class TestReportBackWritesChatMessage(unittest.TestCase):
	"""A terminal task with an origin writes one outbound Chat Message."""

	@patch(f"{_RB}.frappe")
	def test_writes_outbound_to_originating_session(self, mock_frappe):
		from frappe.friday_core.tasks.report_back import report_back

		task = MagicMock()
		task.name = "TASK-42"
		task.get.side_effect = lambda f, d=None: {
			"originating_session": "CH-001",
			"originating_platform": "raven",
			"assigned_to_profile": "Copywriter",
			"title": "Write naming options",
			"result": '{"status": "success", "summary": "Three options: A, B, C."}',
		}.get(f, d)

		report_back(task, "Completed")

		# One Chat Message inserted, to the right session, as the agent.
		mock_frappe.get_doc.assert_called_once()
		doc_arg = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(doc_arg["doctype"], "Chat Message")
		self.assertEqual(doc_arg["session_id"], "CH-001")
		self.assertEqual(doc_arg["platform"], "raven")
		self.assertEqual(doc_arg["direction"], "outbound")
		self.assertEqual(doc_arg["agent_profile"], "Copywriter")
		self.assertIn("Copywriter", doc_arg["content"])
		self.assertIn("Three options", doc_arg["content"])

	@patch(f"{_RB}.frappe")
	def test_no_origin_writes_nothing(self, mock_frappe):
		from frappe.friday_core.tasks.report_back import report_back

		task = MagicMock()
		task.name = "TASK-99"
		task.get.side_effect = lambda f, d=None: {
			"originating_session": "",  # no origin (e.g. a RandomPack pipeline task)
			"assigned_to_profile": "Copywriter",
		}.get(f, d)

		report_back(task, "Completed")

		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_RB}.frappe")
	def test_non_terminal_state_writes_nothing(self, mock_frappe):
		from frappe.friday_core.tasks.report_back import report_back

		task = MagicMock()
		task.get.side_effect = lambda f, d=None: {
			"originating_session": "CH-001",
			"assigned_to_profile": "Copywriter",
		}.get(f, d)

		report_back(task, "Executing")  # not terminal

		mock_frappe.get_doc.assert_not_called()

	@patch(f"{_RB}.frappe")
	def test_blocked_state_reports_back_too(self, mock_frappe):
		"""A blocked task still tells the requester it needs attention."""
		from frappe.friday_core.tasks.report_back import report_back

		task = MagicMock()
		task.name = "TASK-7"
		task.get.side_effect = lambda f, d=None: {
			"originating_session": "CH-001",
			"originating_platform": "raven",
			"assigned_to_profile": "Designer",
			"title": "Do the thing",
			"result": '{"status": "error"}',
		}.get(f, d)

		report_back(task, "Blocked")

		mock_frappe.get_doc.assert_called_once()
		content = mock_frappe.get_doc.call_args.args[0]["content"]
		# The reply signals trouble, not false success.
		self.assertTrue(any(w in content.lower() for w in ("blocked", "couldn", "need", "attention")))

	@patch(f"{_RB}.frappe")
	def test_never_raises_on_write_failure(self, mock_frappe):
		"""A report-back failure must never break the task pipeline."""
		from frappe.friday_core.tasks.report_back import report_back

		task = MagicMock()
		task.name = "TASK-1"
		task.get.side_effect = lambda f, d=None: {
			"originating_session": "CH-001",
			"originating_platform": "raven",
			"assigned_to_profile": "Copywriter",
			"result": "{}",
		}.get(f, d)
		mock_frappe.get_doc.side_effect = RuntimeError("DB down")

		# Must not raise.
		report_back(task, "Completed")
		mock_frappe.log_error.assert_called()


if __name__ == "__main__":
	unittest.main()
