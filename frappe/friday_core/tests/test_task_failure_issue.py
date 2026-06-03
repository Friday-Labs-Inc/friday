# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the task-failure -> Issue auto-raise (Feature D6, doc 53).

Mock-based — no DB. When an Agent Task fails, the task runner files an
Agent-raised `Failure` Issue so a supervisor sees the holdup as a ticket. Two
paths:
  - a skill-level failure (SandboxResult.status != success) -> `_block_task`,
  - an unexpected crash in the runner -> the `on_agent_task_assigned` handler.

The DB-backed integration (a real Issue on a real failed Task) runs on a bench.
"""

import unittest
from unittest.mock import MagicMock, patch

_T = "frappe.friday_core.tasks.runner"


class TestFailureIssueWrapper(unittest.TestCase):
	@patch(f"{_T}.raise_failure_issue", return_value="ISS-1")
	def test_wrapper_calls_through(self, mock_raise):
		from frappe.friday_core.tasks.runner import _raise_failure_issue
		name = _raise_failure_issue("T1", "oom", details="d", execution_log="EL-1")
		self.assertEqual(name, "ISS-1")
		mock_raise.assert_called_once_with(
			"T1", error_type="oom", details="d", execution_log="EL-1"
		)

	@patch(f"{_T}.raise_failure_issue", side_effect=RuntimeError("boom"))
	def test_wrapper_never_raises(self, mock_raise):
		# Best-effort: a hiccup raising the Issue must not mask the task failure.
		from frappe.friday_core.tasks.runner import _raise_failure_issue
		self.assertIsNone(_raise_failure_issue("T1", "error"))


class TestBlockTaskRaisesFailureIssue(unittest.TestCase):
	@patch(f"{_T}._post_warroom")
	@patch(f"{_T}.raise_failure_issue", return_value="ISS-2")
	@patch(f"{_T}._task_transition")
	@patch(f"{_T}.frappe")
	def test_block_task_files_failure_issue_and_references_it(
		self, mock_frappe, _mock_trans, mock_raise, mock_warroom
	):
		from frappe.friday_core.tasks.runner import _block_task
		mock_frappe.as_json = lambda x: "json"
		task = MagicMock()
		task.name = "T1"
		# A failed skill carries its own status (here: oom) — it becomes the
		# Issue's error_type, so the failure kind survives onto the ticket.
		result = MagicMock(status="oom", result={"err": "x"}, skill="s")

		_block_task(task, [result])

		mock_raise.assert_called_once()
		self.assertEqual(mock_raise.call_args.args[0], "T1")
		self.assertEqual(mock_raise.call_args.kwargs["error_type"], "oom")
		# The War Room "blocked" post references the Issue.
		warroom_details = mock_warroom.call_args.args[2]
		self.assertEqual(warroom_details["issue"], "ISS-2")


class TestRunnerCrashRaisesFailureIssue(unittest.TestCase):
	@patch(f"{_T}._post_warroom")
	@patch(f"{_T}.raise_failure_issue", return_value="ISS-3")
	@patch(f"{_T}._run_task", side_effect=RuntimeError("kaboom"))
	def test_unexpected_crash_raises_failure_issue(self, _mock_run, mock_raise, mock_warroom):
		from frappe.friday_core.tasks.runner import on_agent_task_assigned
		on_agent_task_assigned({"task_name": "T1", "assigned_to_profile": "P"})
		mock_raise.assert_called_once()
		self.assertEqual(mock_raise.call_args.kwargs["error_type"], "error")
		self.assertEqual(mock_warroom.call_args.args[2]["issue"], "ISS-3")


if __name__ == "__main__":
	unittest.main()
