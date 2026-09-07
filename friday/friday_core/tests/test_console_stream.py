# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the live activity stream (design 65c).

``publish_activity`` pushes one Task transition to the site-wide ``"all"`` room
so every Desk console client sees it without subscribing. It must carry the
agent + project, flag terminal states, and NEVER raise (a realtime hiccup can't
break a task save). Pure unit tests with ``frappe`` mocked.
"""

import unittest
from unittest.mock import MagicMock, patch


class _Task(dict):
	def get(self, k, default=None):
		return super().get(k, default)


class TestPublishActivity(unittest.TestCase):
	def _task(self, **over):
		base = {
			"name": "42",
			"title": "Draft naming options",
			"assigned_to_profile": "Copywriter",
			"project": "PRJ-1",
		}
		base.update(over)
		return _Task(base)

	@patch("friday.friday_core.console.console_stream.frappe")
	def test_emits_site_wide_event_with_payload(self, mock_frappe):
		from friday.friday_core.console.console_stream import ACTIVITY_EVENT, publish_activity

		mock_frappe.utils.now.return_value = "2026-06-13 10:00:00"
		publish_activity(self._task(), "Executing")

		mock_frappe.publish_realtime.assert_called_once()
		args, kwargs = mock_frappe.publish_realtime.call_args
		# event is the first positional arg; NO room/user/doctype -> site room "all".
		self.assertEqual(args[0], ACTIVITY_EVENT)
		self.assertNotIn("room", kwargs)
		self.assertNotIn("doctype", kwargs)
		payload = args[1]
		self.assertEqual(payload["task"], "42")
		self.assertEqual(payload["state"], "Executing")
		self.assertEqual(payload["profile"], "Copywriter")
		self.assertEqual(payload["project"], "PRJ-1")
		self.assertEqual(payload["is_terminal"], False)

	@patch("friday.friday_core.console.console_stream.frappe")
	def test_terminal_state_flagged(self, mock_frappe):
		from friday.friday_core.console.console_stream import publish_activity

		mock_frappe.utils.now.return_value = "t"
		publish_activity(self._task(), "Completed")
		payload = mock_frappe.publish_realtime.call_args[0][1]
		self.assertTrue(payload["is_terminal"])

	@patch("friday.friday_core.console.console_stream.frappe")
	def test_never_raises_on_publish_failure(self, mock_frappe):
		from friday.friday_core.console.console_stream import publish_activity

		mock_frappe.utils.now.return_value = "t"
		mock_frappe.publish_realtime.side_effect = RuntimeError("socket down")
		mock_frappe.logger.return_value = MagicMock()

		# Must not propagate — a realtime outage cannot break the task pipeline.
		publish_activity(self._task(), "Executing")


if __name__ == "__main__":
	unittest.main()
