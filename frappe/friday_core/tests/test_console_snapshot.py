# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Project Console snapshot endpoint (design 65c).

``console_snapshot`` seeds the page and is re-polled every 30s. It reuses the
Pipeline Health verdict, returns project rollups + in-flight + recent activity,
scopes to one project when asked, and fails loud (never a silent empty page).
Pure unit tests with ``frappe`` mocked.
"""

import unittest
from unittest.mock import patch


class TestConsoleSnapshot(unittest.TestCase):
	@patch("frappe.friday_core.console.console_snapshot.pipeline_health")
	@patch("frappe.friday_core.console.console_snapshot.frappe")
	def test_returns_all_zones(self, mock_frappe, mock_health):
		from frappe.friday_core.console.console_snapshot import console_snapshot

		mock_frappe.utils.now.return_value = "2026-06-13 10:00:00"
		mock_health.return_value = {"verdict": "ok"}
		mock_frappe.get_all.return_value = []

		snap = console_snapshot()

		self.assertEqual(snap["health"], {"verdict": "ok"})
		self.assertIn("projects", snap)
		self.assertIn("active_tasks", snap)
		self.assertIn("recent_activity", snap)
		self.assertEqual(snap["generated_at"], "2026-06-13 10:00:00")
		self.assertNotIn("error", snap)

	@patch("frappe.friday_core.console.console_snapshot.pipeline_health")
	@patch("frappe.friday_core.console.console_snapshot.frappe")
	def test_scopes_to_project_when_given(self, mock_frappe, mock_health):
		from frappe.friday_core.console.console_snapshot import console_snapshot

		mock_frappe.utils.now.return_value = "t"
		mock_health.return_value = {"verdict": "ok"}
		mock_frappe.get_all.return_value = []

		console_snapshot(project="PRJ-7")

		# Every get_all call must carry the project scope.
		for call in mock_frappe.get_all.call_args_list:
			filters = call.kwargs.get("filters", {})
			# Project query filters on name; task queries filter on project.
			joined = {**filters}
			self.assertTrue(
				joined.get("name") == "PRJ-7" or joined.get("project") == "PRJ-7",
				f"get_all call not scoped to project: {filters}",
			)

	@patch("frappe.friday_core.console.console_snapshot.pipeline_health")
	@patch("frappe.friday_core.console.console_snapshot.frappe")
	def test_active_tasks_query_filters_in_flight_states(self, mock_frappe, mock_health):
		from frappe.friday_core.console.console_snapshot import ACTIVE_STATES, console_snapshot

		mock_frappe.utils.now.return_value = "t"
		mock_health.return_value = {"verdict": "ok"}
		mock_frappe.get_all.return_value = []

		console_snapshot()

		# Find the Task query whose state filter is the ACTIVE set.
		state_filters = [
			c.kwargs.get("filters", {}).get("workflow_state")
			for c in mock_frappe.get_all.call_args_list
			if c.args and c.args[0] == "Task"
		]
		self.assertIn(["in", list(ACTIVE_STATES)], state_filters)

	@patch("frappe.friday_core.console.console_snapshot.pipeline_health")
	@patch("frappe.friday_core.console.console_snapshot.frappe")
	def test_fail_loud_envelope(self, mock_frappe, mock_health):
		from frappe.friday_core.console.console_snapshot import console_snapshot

		mock_frappe.utils.now.return_value = "t"
		mock_health.return_value = {"verdict": "ok"}
		mock_frappe.get_all.side_effect = RuntimeError("db down")

		snap = console_snapshot()

		self.assertIn("error", snap)
		self.assertEqual(snap["health"]["verdict"], "down")
		self.assertEqual(snap["projects"], [])
		self.assertTrue(mock_frappe.log_error.called)


if __name__ == "__main__":
	unittest.main()
