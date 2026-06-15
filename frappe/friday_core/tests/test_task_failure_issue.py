# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the task-failure -> Issue auto-raise (Feature D6, doc 53).

Mock-based — no DB. When an Task fails, the task runner files an
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
		mock_raise.assert_called_once_with("T1", error_type="oom", details="d", execution_log="EL-1")

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


class TestAgenticFailureRecordsBlockedReason(unittest.TestCase):
	"""A failed agentic turn records the LLMError's classified reason on
	Task.blocked_reason, so the reconciler can auto-retry transient failures."""

	@patch("frappe.friday_core.tasks.rollup.task_cost_from_usage", return_value=None)
	@patch("frappe.friday_core.agent_runner.runner.run_turn")
	@patch(f"{_T}._post_warroom")
	@patch(f"{_T}._raise_failure_issue", return_value="ISS-9")
	@patch(f"{_T}._elapsed_ms", return_value=100)
	@patch(f"{_T}.now_datetime", return_value="2026-01-01 00:00:00")
	@patch(f"{_T}.frappe")
	def test_retryable_llm_error_sets_transient_blocked_reason(
		self, mock_frappe, _now, _elapsed, _issue, _warroom, mock_run_turn, _cost
	):
		from frappe.friday_core.llm.provider import LLMError
		from frappe.friday_core.tasks.runner import _run_task_agentic

		mock_frappe.as_json = lambda x: "json"
		err = LLMError("minimax timed out")
		err.reason = "timeout"
		err.retryable = True
		mock_run_turn.side_effect = err

		task = MagicMock(name="task")
		task.name = "T-AG"
		task.title = "t"
		task.description = "d"

		_run_task_agentic(task, "P")

		self.assertEqual(task.workflow_state, "Blocked")
		# the fix: the classified reason is recorded → reconciler auto-retries it
		self.assertEqual(task.blocked_reason, "timeout")

	@patch("frappe.friday_core.tasks.rollup.task_cost_from_usage", return_value=None)
	@patch("frappe.friday_core.agent_runner.runner.run_turn")
	@patch(f"{_T}._post_warroom")
	@patch(f"{_T}._raise_failure_issue", return_value="ISS-9")
	@patch(f"{_T}._elapsed_ms", return_value=100)
	@patch(f"{_T}.now_datetime", return_value="2026-01-01 00:00:00")
	@patch(f"{_T}.frappe")
	def test_unclassified_error_leaves_blocked_reason_none(
		self, mock_frappe, _now, _elapsed, _issue, _warroom, mock_run_turn, _cost
	):
		from frappe.friday_core.tasks.runner import _run_task_agentic

		mock_frappe.as_json = lambda x: "json"
		mock_run_turn.side_effect = RuntimeError("a real bug, not transient")

		task = MagicMock(name="task")
		task.name = "T-AG2"
		task.title = "t"
		task.description = "d"

		_run_task_agentic(task, "P")

		self.assertEqual(task.workflow_state, "Blocked")
		# non-LLM error has no reason → stays Blocked for a human, never auto-retried
		self.assertIsNone(task.blocked_reason)


if __name__ == "__main__":
	unittest.main()
