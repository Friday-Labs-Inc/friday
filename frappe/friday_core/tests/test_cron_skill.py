# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for the manage-cron-jobs skill (Design 87, Slice 2). Mock-based.

Pins: create defaults to the caller + current channel; list is scoped to the
caller; pause/resume/remove/trigger refuse another agent's job (ownership guard);
unknown action + missing required params raise.
"""

import unittest
from unittest.mock import MagicMock, patch

_CS = "frappe.friday_core.skills.handlers_cron"


class TestManageCronJobs(unittest.TestCase):
	@patch(f"{_CS}.frappe")
	def test_create_defaults_to_caller_and_channel(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": "CH-1"}
		job = MagicMock()
		job.name = "CRON-1"
		job.next_run_at = "T"
		fr.get_doc.return_value = job

		res = handlers_cron.manage_cron_jobs(
			"manage-cron-jobs",
			{"action": "create", "prompt": "summarise the day", "schedule_expression": "0 9 * * *"},
		)
		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["agent_profile"], "Friday")  # owned by the caller
		self.assertEqual(payload["deliver"], "raven:CH-1")  # back into the channel
		self.assertEqual(res["status"], "created")

	@patch(f"{_CS}.frappe")
	def test_create_requires_prompt(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": "CH-1"}
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs(
				"manage-cron-jobs", {"action": "create", "schedule_expression": "x"}
			)

	@patch(f"{_CS}.frappe")
	def test_list_is_scoped_to_caller(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		fr.get_all.return_value = [{"name": "CRON-1"}]
		res = handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "list"})
		self.assertEqual(res["count"], 1)
		self.assertEqual(fr.get_all.call_args.kwargs["filters"]["agent_profile"], "Friday")

	@patch(f"{_CS}.frappe")
	def test_pause_refuses_another_agents_job(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		fr.db.exists.return_value = True
		fr.db.get_value.return_value = "OtherAgent"  # owner != caller
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "pause", "name": "CRON-9"})

	@patch(f"{_CS}.frappe")
	def test_pause_own_job(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		fr.db.exists.return_value = True
		fr.db.get_value.return_value = "Friday"  # owner == caller
		job = MagicMock()
		job.next_run_at = "T"
		fr.get_doc.return_value = job
		res = handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "pause", "name": "CRON-1"})
		self.assertEqual(job.enabled, 0)
		self.assertEqual(job.state, "Paused")
		self.assertEqual(res["status"], "paused")

	@patch(f"{_CS}.frappe")
	def test_unknown_action_raises(self, fr):
		from frappe.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "explode"})


if __name__ == "__main__":
	unittest.main()
