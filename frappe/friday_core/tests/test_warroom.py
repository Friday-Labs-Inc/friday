# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the War Room publisher.

Covers:
- Raven installed + channel exists → posts message (HTTP call made)
- Raven not installed → logs INFO, no exception
- Raven installed + channel not found → logs WARNING, no exception
- Network error on POST → logs ERROR, no exception
- _is_raven_installed() returns True when doctype exists
- _is_raven_installed() returns False when doctype does not exist
- post_task_update() returns early when Raven not installed
- post_task_update() returns early when channel not found
"""

import unittest
from unittest.mock import MagicMock, patch


class TestPostTaskUpdateRavenInstalledChannelFound(unittest.TestCase):
	"""Raven installed + channel exists → HTTP POST is made."""

	@patch("frappe.friday_core.warroom.publisher._post_to_raven")
	@patch("frappe.friday_core.warroom.publisher._get_channel_id")
	@patch("frappe.friday_core.warroom.publisher._is_raven_installed")
	def test_posts_message(self, mock_installed, mock_get_id, mock_post):
		from frappe.friday_core.warroom.publisher import post_task_update

		mock_installed.return_value = True
		mock_get_id.return_value = "raven-channel-123"

		post_task_update("AT-000042", "executing", {"profile": "note_taker"})

		mock_post.assert_called_once()
		call_args = mock_post.call_args[0]
		self.assertEqual(call_args[0], "raven-channel-123")
		self.assertIn("AT-000042", call_args[1]["text"])
		self.assertIn("executing", call_args[1]["text"])


class TestPostTaskUpdateRavenNotInstalled(unittest.TestCase):
	"""Raven not installed → logs INFO, no exception, no HTTP call."""

	@patch("frappe.friday_core.warroom.publisher._is_raven_installed")
	@patch("frappe.friday_core.warroom.publisher._get_channel_id")
	@patch("frappe.friday_core.warroom.publisher._post_to_raven")
	@patch("frappe.friday_core.warroom.publisher._logger")
	def test_logs_info_and_returns(self, mock_logger, mock_post, mock_get_id, mock_installed):
		from frappe.friday_core.warroom.publisher import post_task_update

		mock_installed.return_value = False

		# Must not raise.
		post_task_update("AT-000042", "completed", {"duration_ms": 500})

		mock_logger.info.assert_called()
		self.assertIn("Raven not installed", mock_logger.info.call_args[0][0])
		mock_post.assert_not_called()
		mock_get_id.assert_not_called()


class TestPostTaskUpdateRavenInstalledChannelNotFound(unittest.TestCase):
	"""Raven installed but FRIDAY_WAR_ROOM channel not found → logs WARNING."""

	@patch("frappe.friday_core.warroom.publisher._is_raven_installed")
	@patch("frappe.friday_core.warroom.publisher._get_channel_id")
	@patch("frappe.friday_core.warroom.publisher._post_to_raven")
	@patch("frappe.friday_core.warroom.publisher._logger")
	def test_logs_warning_and_returns(self, mock_logger, mock_post, mock_get_id, mock_installed):
		from frappe.friday_core.warroom.publisher import post_task_update

		mock_installed.return_value = True
		mock_get_id.return_value = None  # channel not found

		# Must not raise.
		post_task_update("AT-000042", "blocked")

		mock_logger.warning.assert_called()
		self.assertIn("not found", mock_logger.warning.call_args[0][0])
		mock_post.assert_not_called()


class TestPostTaskUpdateNetworkError(unittest.TestCase):
	"""Network error on POST → logs ERROR, no exception."""

	@patch("frappe.friday_core.warroom.publisher._is_raven_installed")
	@patch("frappe.friday_core.warroom.publisher._get_channel_id")
	@patch("frappe.friday_core.warroom.publisher._post_to_raven")
	@patch("frappe.friday_core.warroom.publisher._logger")
	def test_logs_error_and_returns(self, mock_logger, mock_post, mock_get_id, mock_installed):
		import requests

		from frappe.friday_core.warroom.publisher import post_task_update

		mock_installed.return_value = True
		mock_get_id.return_value = "raven-channel-123"
		mock_post.side_effect = requests.exceptions.RequestException("connection refused")

		# Must not raise.
		post_task_update("AT-000042", "executing")

		mock_logger.error.assert_called()
		self.assertIn("failed", mock_logger.error.call_args[0][0])


class TestIsRavenInstalledDoctypeExists(unittest.TestCase):
	"""_is_raven_installed() returns True when Raven Channel doctype exists.

	Probes the table catalogue (frappe.db.table_exists), NOT a query against
	the table — querying a missing table aborts the Postgres transaction even
	when the exception is caught (fix shipped in #75).
	"""

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_true_when_doctype_exists(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _is_raven_installed

		mock_frappe.db.table_exists.return_value = True

		result = _is_raven_installed()

		self.assertTrue(result)

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_false_when_doctype_not_found(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _is_raven_installed

		mock_frappe.db.table_exists.return_value = False

		result = _is_raven_installed()

		self.assertFalse(result)

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_false_on_exception(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _is_raven_installed

		mock_frappe.db.table_exists.side_effect = Exception("DB error")

		result = _is_raven_installed()

		self.assertFalse(result)


class TestGetChannelId(unittest.TestCase):
	"""_get_channel_id() returns channel name when found, None when not found."""

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_channel_name_when_found(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _get_channel_id

		mock_channel = MagicMock()
		mock_channel.name = "raven-channel-friday-war-room"
		mock_frappe.db.get_value.return_value = mock_channel

		result = _get_channel_id()

		self.assertEqual(result, "raven-channel-friday-war-room")

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_none_when_not_found(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _get_channel_id

		mock_frappe.db.get_value.return_value = None

		result = _get_channel_id()

		self.assertIsNone(result)

	@patch("frappe.friday_core.warroom.publisher.frappe")
	def test_returns_none_on_exception(self, mock_frappe):
		from frappe.friday_core.warroom.publisher import _get_channel_id

		mock_frappe.db.get_value.side_effect = Exception("DB error")

		result = _get_channel_id()

		self.assertIsNone(result)


class TestBuildPayload(unittest.TestCase):
	"""_build_payload() returns a correctly structured message dict."""

	def test_text_contains_task_name_and_event(self):
		from frappe.friday_core.warroom.publisher import _build_payload

		payload = _build_payload("AT-000042", "completed", {"duration_ms": 1234})

		self.assertIn("AT-000042", payload["text"])
		self.assertIn("completed", payload["text"])
		self.assertEqual(payload["message_type"], "Text")
		self.assertFalse(payload["hide_in_message_history"])

	def test_text_contains_error_message(self):
		from frappe.friday_core.warroom.publisher import _build_payload

		payload = _build_payload("AT-000042", "blocked", {"error_message": "sandbox timeout"})

		self.assertIn("sandbox timeout", payload["text"])

	def test_text_contains_duration_ms(self):
		from frappe.friday_core.warroom.publisher import _build_payload

		payload = _build_payload("AT-000042", "completed", {"duration_ms": 5000})

		self.assertIn("5000ms", payload["text"])

	def test_text_contains_profile(self):
		from frappe.friday_core.warroom.publisher import _build_payload

		payload = _build_payload("AT-000042", "executing", {"profile": "note_taker"})

		self.assertIn("note_taker", payload["text"])

	def test_text_contains_skills(self):
		from frappe.friday_core.warroom.publisher import _build_payload

		payload = _build_payload(
			"AT-000042",
			"executing",
			{"skills": ["create_note", "web_search"]},
		)

		self.assertIn("create_note", payload["text"])
		self.assertIn("web_search", payload["text"])


if __name__ == "__main__":
	unittest.main()
