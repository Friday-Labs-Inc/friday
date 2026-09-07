# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the progress + cost rollup (design 65d).

Covers the 0/50/100 progress map, the honest per-task cost sum (None when no
rates configured, never 0), and the project rollup math — counts, %-complete,
the "only stamp end-date when everything is done" rule, and cost summation.
Pure unit tests with ``frappe`` mocked.
"""

import unittest
from unittest.mock import patch


class TestProgressForState(unittest.TestCase):
	def test_progress_map(self):
		from friday.friday_core.tasks.rollup import progress_for_state

		self.assertEqual(progress_for_state("Pending"), 0)
		self.assertEqual(progress_for_state("Assigned"), 0)
		self.assertEqual(progress_for_state("Executing"), 50)
		self.assertEqual(progress_for_state("Blocked"), 50)
		self.assertEqual(progress_for_state("Review"), 100)
		self.assertEqual(progress_for_state("Completed"), 100)
		self.assertEqual(progress_for_state("Cancelled"), 100)
		self.assertEqual(progress_for_state(None), 0)
		self.assertEqual(progress_for_state("Bogus"), 0)


class TestTaskCostFromUsage(unittest.TestCase):
	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_sums_recorded_costs(self, mock_frappe):
		from friday.friday_core.tasks.rollup import task_cost_from_usage

		mock_frappe.get_all.return_value = [
			{"estimated_cost": 0.012},
			{"estimated_cost": 0.008},
			{"estimated_cost": None},
		]
		self.assertAlmostEqual(task_cost_from_usage("42"), 0.02)
		# It queried the right session_id.
		_, kwargs = mock_frappe.get_all.call_args
		self.assertEqual(kwargs["filters"], {"session_id": "task::42"})

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_none_when_no_rates_configured(self, mock_frappe):
		from friday.friday_core.tasks.rollup import task_cost_from_usage

		# Every row has estimated_cost None (no per-million rates set).
		mock_frappe.get_all.return_value = [{"estimated_cost": None}, {"estimated_cost": None}]
		self.assertIsNone(task_cost_from_usage("42"))

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_none_when_no_usage_rows(self, mock_frappe):
		from friday.friday_core.tasks.rollup import task_cost_from_usage

		mock_frappe.get_all.return_value = []
		self.assertIsNone(task_cost_from_usage("mechanical-task"))


class TestProjectRollup(unittest.TestCase):
	def _run(self, mock_frappe, tasks):
		"""Drive recompute with a given child-task list; return the set_value dict."""
		from friday.friday_core.tasks.rollup import recompute_project_rollup

		mock_frappe.db.exists.return_value = True
		mock_frappe.get_all.return_value = tasks
		mock_frappe.utils.getdate.side_effect = lambda x: x  # identity for assertions
		recompute_project_rollup("PRJ-1")
		# set_value(doctype, name, values_dict, update_modified=False)
		args, _kwargs = mock_frappe.db.set_value.call_args
		return args[2]

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_counts_and_percent(self, mock_frappe):
		vals = self._run(
			mock_frappe,
			[
				{"workflow_state": "Completed", "cost_usd": None, "started_at": None, "completed_at": None},
				{"workflow_state": "Review", "cost_usd": None, "started_at": None, "completed_at": None},
				{"workflow_state": "Executing", "cost_usd": None, "started_at": None, "completed_at": None},
				{"workflow_state": "Pending", "cost_usd": None, "started_at": None, "completed_at": None},
			],
		)
		self.assertEqual(vals["total_tasks"], 4)
		self.assertEqual(vals["completed_tasks"], 2)  # Completed + Review
		self.assertEqual(vals["percent_complete"], 50.0)

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_percent_zero_when_no_tasks(self, mock_frappe):
		vals = self._run(mock_frappe, [])
		self.assertEqual(vals["total_tasks"], 0)
		self.assertEqual(vals["percent_complete"], 0)
		self.assertIsNone(vals["actual_cost_usd"])
		self.assertIsNone(vals["actual_end_date"])

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_cost_summed_only_from_non_null(self, mock_frappe):
		vals = self._run(
			mock_frappe,
			[
				{"workflow_state": "Completed", "cost_usd": 0.10, "started_at": None, "completed_at": None},
				{"workflow_state": "Completed", "cost_usd": 0.05, "started_at": None, "completed_at": None},
				{"workflow_state": "Completed", "cost_usd": None, "started_at": None, "completed_at": None},
			],
		)
		self.assertAlmostEqual(vals["actual_cost_usd"], 0.15)

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_cost_none_when_all_null(self, mock_frappe):
		vals = self._run(
			mock_frappe,
			[{"workflow_state": "Completed", "cost_usd": None, "started_at": None, "completed_at": None}],
		)
		self.assertIsNone(vals["actual_cost_usd"])

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_end_date_only_when_all_done(self, mock_frappe):
		# One task still Executing -> no end date even though another completed.
		vals = self._run(
			mock_frappe,
			[
				{
					"workflow_state": "Completed",
					"cost_usd": None,
					"started_at": "2026-06-01 09:00:00",
					"completed_at": "2026-06-02 10:00:00",
				},
				{
					"workflow_state": "Executing",
					"cost_usd": None,
					"started_at": "2026-06-01 11:00:00",
					"completed_at": None,
				},
			],
		)
		self.assertEqual(vals["actual_start_date"], "2026-06-01 09:00:00")  # min start
		self.assertIsNone(vals["actual_end_date"])  # not all done

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_end_date_set_when_all_terminal(self, mock_frappe):
		vals = self._run(
			mock_frappe,
			[
				{
					"workflow_state": "Completed",
					"cost_usd": None,
					"started_at": "2026-06-01 09:00:00",
					"completed_at": "2026-06-02 10:00:00",
				},
				{
					"workflow_state": "Cancelled",
					"cost_usd": None,
					"started_at": "2026-06-01 11:00:00",
					"completed_at": "2026-06-03 12:00:00",
				},
			],
		)
		self.assertEqual(vals["actual_end_date"], "2026-06-03 12:00:00")  # max completed

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_blocked_blocks_end_date(self, mock_frappe):
		# A Blocked task means the project isn't done -> no end date.
		vals = self._run(
			mock_frappe,
			[
				{
					"workflow_state": "Completed",
					"cost_usd": None,
					"started_at": "2026-06-01 09:00:00",
					"completed_at": "2026-06-02 10:00:00",
				},
				{
					"workflow_state": "Blocked",
					"cost_usd": None,
					"started_at": "2026-06-01 11:00:00",
					"completed_at": None,
				},
			],
		)
		self.assertIsNone(vals["actual_end_date"])

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_noop_when_project_missing(self, mock_frappe):
		from friday.friday_core.tasks.rollup import recompute_project_rollup

		mock_frappe.db.exists.return_value = False
		recompute_project_rollup("ghost")
		mock_frappe.db.set_value.assert_not_called()

	@patch("friday.friday_core.tasks.rollup.frappe")
	def test_noop_when_no_project(self, mock_frappe):
		from friday.friday_core.tasks.rollup import recompute_project_rollup

		recompute_project_rollup(None)
		mock_frappe.db.set_value.assert_not_called()


if __name__ == "__main__":
	unittest.main()
