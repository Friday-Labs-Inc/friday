# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the task dispatcher.

Covers: atomic task claim with FOR UPDATE SKIP LOCKED, profile matching,
no-match warning logging, and publish_realtime emission on assignment.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestTickNoTasks(unittest.TestCase):
	"""tick() does nothing when no dispatchable tasks exist."""

	@patch("frappe.friday_core.tasks.dispatcher._fetch_dispatchable_tasks")
	def test_tick_returns_early_when_no_tasks(self, mock_fetch):
		from frappe.friday_core.tasks.dispatcher import tick

		mock_fetch.return_value = []

		tick()

		mock_fetch.assert_called_once_with(limit=5)


class TestFetchDispatchableTasksQuery(unittest.TestCase):
	"""_fetch_dispatchable_tasks uses the correct SQL query."""

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_query_uses_for_update_skip_locked(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _fetch_dispatchable_tasks

		mock_frappe.db.sql.return_value = []
		mock_frappe.get_doc.return_value = MagicMock()

		_fetch_dispatchable_tasks(limit=3)

		sql_call = mock_frappe.db.sql.call_args
		sql = sql_call[0][0]
		self.assertIn("FOR UPDATE SKIP LOCKED", sql)

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_query_filters_dispatchable_and_pending(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _fetch_dispatchable_tasks

		mock_frappe.db.sql.return_value = []
		mock_frappe.get_doc.return_value = MagicMock()

		_fetch_dispatchable_tasks()

		sql_call = mock_frappe.db.sql.call_args
		sql = sql_call[0][0]
		self.assertIn("dispatchable = 1", sql)
		self.assertIn("workflow_state = 'Pending'", sql)
		self.assertIn("assigned_to_profile IS NULL", sql)

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_query_orders_by_priority_then_creation(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _fetch_dispatchable_tasks

		mock_frappe.db.sql.return_value = []
		mock_frappe.get_doc.return_value = MagicMock()

		_fetch_dispatchable_tasks()

		sql_call = mock_frappe.db.sql.call_args
		sql = sql_call[0][0]
		self.assertIn("CASE priority", sql)
		self.assertIn("creation ASC", sql)


class TestClaimAndDispatchNoProfile(unittest.TestCase):
	"""_claim_and_dispatch logs a warning when no profile matches."""

	@patch("frappe.friday_core.tasks.dispatcher._match_profiles")
	def test_no_match_logs_warning(self, mock_match):
		from frappe.friday_core.tasks.dispatcher import _claim_and_dispatch

		mock_match.return_value = []  # no eligible profile

		task_doc = MagicMock()
		task_doc.name = "AT-000001"
		task_doc.required_skills = [MagicMock(skill="create_note")]

		with patch("frappe.friday_core.tasks.dispatcher._logger") as mock_logger:
			_claim_and_dispatch(task_doc)

			mock_logger.warning.assert_called()
			self.assertIn("No eligible profile", mock_logger.warning.call_args[0][0])

		# save should NOT be called
		task_doc.save.assert_not_called()


class TestClaimAndDispatchWithProfile(unittest.TestCase):
	"""_claim_and_dispatch assigns and emits event when a profile matches."""

	@patch("frappe.friday_core.tasks.dispatcher._match_profiles")
	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_assigns_first_eligible_profile(self, mock_frappe, mock_match):
		from frappe.friday_core.tasks.dispatcher import _claim_and_dispatch

		mock_match.return_value = ["note_taker", "researcher"]

		task_doc = MagicMock()
		task_doc.name = "AT-000042"

		_claim_and_dispatch(task_doc)

		self.assertEqual(task_doc.assigned_to_profile, "note_taker")
		task_doc.save.assert_called_once_with(ignore_permissions=True)

	@patch("frappe.friday_core.tasks.dispatcher._match_profiles")
	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_emits_realtime_event(self, mock_frappe, mock_match):
		from frappe.friday_core.tasks.dispatcher import _claim_and_dispatch

		mock_match.return_value = ["note_taker"]

		task_doc = MagicMock()
		task_doc.name = "AT-000042"

		_claim_and_dispatch(task_doc)

		mock_frappe.publish_realtime.assert_called_once_with(
			event="agent_task.assigned",
			message={
				"task_name": "AT-000042",
				"assigned_to_profile": "note_taker",
				"workflow_state": "Assigned",
			},
			doctype="Task",
			after_commit=True,
		)


class TestMatchProfilesExact(unittest.TestCase):
	"""_match_profiles returns profiles whose permitted_skills cover all required."""

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_profile_with_all_required_skills_is_matched(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _match_profiles

		task_doc = MagicMock()
		task_doc.required_skills = [
			MagicMock(skill="create_note"),
			MagicMock(skill="web_search"),
		]

		profile_a = MagicMock()
		profile_a.name = "profile_a"
		profile_b = MagicMock()
		profile_b.name = "profile_b"

		mock_frappe.get_all.return_value = [profile_a, profile_b]

		def load_permitted(name):
			if name == "profile_a":
				return {"create_note", "web_search"}
			return {"create_note"}  # missing web_search

		with patch(
			"frappe.friday_core.tasks.dispatcher._load_permitted_skills",
			side_effect=load_permitted,
		):
			result = _match_profiles(task_doc)

		self.assertEqual(result, ["profile_a"])

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_profile_missing_one_required_skill_is_excluded(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _match_profiles

		task_doc = MagicMock()
		task_doc.required_skills = [
			MagicMock(skill="create_note"),
			MagicMock(skill="web_search"),
		]

		profile_row = MagicMock(name="profile_incomplete")
		mock_frappe.get_all.return_value = [profile_row]

		with patch(
			"frappe.friday_core.tasks.dispatcher._load_permitted_skills",
			return_value={"create_note"},  # missing web_search
		):
			result = _match_profiles(task_doc)

		self.assertEqual(result, [])


class TestMatchProfilesNoRequiredSkills(unittest.TestCase):
	"""Tasks with no required_skills can be taken by any active profile."""

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_no_required_skills_returns_all_active_profiles(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _match_profiles

		task_doc = MagicMock()
		task_doc.required_skills = []

		profile_a = MagicMock()
		profile_a.name = "profile_alpha"
		profile_b = MagicMock()
		profile_b.name = "profile_beta"
		mock_frappe.get_all.return_value = [profile_a, profile_b]

		result = _match_profiles(task_doc)

		self.assertEqual(result, ["profile_alpha", "profile_beta"])


class TestLoadPermittedSkillsFromProfile(unittest.TestCase):
	"""_load_permitted_skills reads permitted_skills table, then role_profile."""

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_returns_skills_from_profile_permitted_table(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _load_permitted_skills

		profile_doc = MagicMock()
		profile_doc.permitted_skills = [
			MagicMock(skill="create_note"),
			MagicMock(skill="web_search"),
		]
		profile_doc.agent_role_profile = None
		mock_frappe.get_doc.return_value = profile_doc

		result = _load_permitted_skills("note_taker")

		self.assertEqual(result, {"create_note", "web_search"})

	@patch("frappe.friday_core.tasks.dispatcher.frappe")
	def test_falls_back_to_role_profile_when_no_explicit_skills(self, mock_frappe):
		from frappe.friday_core.tasks.dispatcher import _load_permitted_skills

		profile_doc = MagicMock()
		profile_doc.permitted_skills = []
		profile_doc.agent_role_profile = "admin_role"
		mock_frappe.get_doc.return_value = profile_doc

		role_doc = MagicMock()
		role_doc.get.return_value = [MagicMock(skill="create_note")]
		mock_frappe.get_doc.side_effect = [profile_doc, role_doc]

		result = _load_permitted_skills("note_taker")

		self.assertIn("create_note", result)


if __name__ == "__main__":
	unittest.main()