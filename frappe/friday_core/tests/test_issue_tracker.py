# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the agent issue-raising logic (doc 53 §5, decisions D5/D6).

Mock-based — no database, so they run anywhere `import frappe` works. They
pin the *contract* of the two auto-raise paths and the dependency check:

  - `unfinished_dependencies(task)` — which `depends_on` tasks still block it.
  - `raise_failure_issue(...)`       — Agent-raised `Failure` Issue (D6).
  - `raise_dependency_wait_issue(..)` — Agent-raised `Dependency-Wait` Issue (D5).

The DocType-contract and true end-to-end checks (a real Issue row created on a
real failed Task) run on a bench — see the rollout doc.
"""

import unittest
from unittest.mock import MagicMock, patch


def _dep_row(task_name):
	"""A stand-in for one `Task Depends On` child row."""
	row = MagicMock()
	row.task = task_name
	return row


class TestUnfinishedDependencies(unittest.TestCase):
	"""Returns only the depends_on tasks not in a settled (Completed/Cancelled) state."""

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_returns_only_unsettled_dependencies(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import unfinished_dependencies

		task = MagicMock(depends_on=[_dep_row("T1"), _dep_row("T2"), _dep_row("T3")])
		statuses = {"T1": "Completed", "T2": "Working", "T3": "Cancelled"}
		mock_frappe.db.get_value.side_effect = lambda dt, name, field: statuses[name]

		self.assertEqual(unfinished_dependencies(task), ["T2"])

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_no_dependencies_returns_empty_and_skips_db(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import unfinished_dependencies

		self.assertEqual(unfinished_dependencies(MagicMock(depends_on=[])), [])
		mock_frappe.db.get_value.assert_not_called()

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_all_settled_returns_empty(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import unfinished_dependencies

		task = MagicMock(depends_on=[_dep_row("T1"), _dep_row("T2")])
		mock_frappe.db.get_value.return_value = "Completed"

		self.assertEqual(unfinished_dependencies(task), [])


class TestRaiseFailureIssue(unittest.TestCase):
	"""D6 — a failed task files an Agent-raised `Failure` Issue."""

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_builds_agent_raised_failure_issue(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import raise_failure_issue

		created = MagicMock()
		mock_frappe.get_doc.return_value = created

		raise_failure_issue("T1", error_type="SandboxTimeout", execution_log="EL-1")

		payload = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(payload["doctype"], "Issue")
		self.assertEqual(payload["source"], "Agent-raised")
		self.assertEqual(payload["reason"], "Failure")
		self.assertEqual(payload["status"], "Open")
		self.assertEqual(payload["related_task"], "T1")
		self.assertEqual(payload["execution_log"], "EL-1")
		self.assertIn("SandboxTimeout", payload["subject"])
		created.insert.assert_called_once_with(ignore_permissions=True)

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_subject_without_error_type(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import raise_failure_issue

		mock_frappe.get_doc.return_value = MagicMock()
		raise_failure_issue("T9")

		payload = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(payload["subject"], "Task T9 failed")


class TestRaiseDependencyWaitIssue(unittest.TestCase):
	"""D5 — a task blocked on an unfinished dependency files a `Dependency-Wait` Issue."""

	@patch("frappe.friday_core.issues.raise_issue.frappe")
	def test_builds_dependency_wait_issue(self, mock_frappe):
		from frappe.friday_core.issues.raise_issue import raise_dependency_wait_issue

		created = MagicMock()
		mock_frappe.get_doc.return_value = created

		raise_dependency_wait_issue("T2", "T1")

		payload = mock_frappe.get_doc.call_args.args[0]
		self.assertEqual(payload["source"], "Agent-raised")
		self.assertEqual(payload["reason"], "Dependency-Wait")
		self.assertEqual(payload["status"], "Open")
		self.assertEqual(payload["related_task"], "T2")
		self.assertEqual(payload["waiting_on"], "T1")
		self.assertIn("T1", payload["subject"])
		created.insert.assert_called_once_with(ignore_permissions=True)


if __name__ == "__main__":
	unittest.main()
