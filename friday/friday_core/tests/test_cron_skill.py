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

_CS = "friday.friday_core.skills.handlers_cron"


class TestManageCronJobs(unittest.TestCase):
	@patch(f"{_CS}.frappe")
	def test_create_defaults_to_caller_and_channel(self, fr):
		from friday.friday_core.skills import handlers_cron

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
	def test_create_ignores_llm_supplied_agent_profile(self, fr):
		# SECURITY (privilege escalation): the owning profile comes ONLY from the
		# unspoofable dispatch context, never from the model's parameters. An agent that
		# slips agent_profile into its params must NOT create a job owned by another
		# (higher-privileged) profile.
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Worker-Low", "session_id": "CH-1"}
		job = MagicMock()
		job.name = "CRON-1"
		job.next_run_at = "T"
		fr.get_doc.return_value = job

		handlers_cron.manage_cron_jobs(
			"manage-cron-jobs",
			{
				"action": "create",
				"prompt": "p",
				"schedule_expression": "0 9 * * *",
				"agent_profile": "Orchestrator-Privileged",  # the attack — must be ignored
			},
		)
		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["agent_profile"], "Worker-Low")  # the caller, NOT the param

	@patch(f"{_CS}.frappe")
	def test_create_aliases_origin_to_current_channel(self, fr):
		# Agents reach for deliver="origin"; resolve it to the channel they're in
		# so the result actually posts there (not the silent local fallback).
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": "CH-7"}
		job = MagicMock()
		job.name = "CRON-1"
		job.next_run_at = "T"
		fr.get_doc.return_value = job
		handlers_cron.manage_cron_jobs(
			"manage-cron-jobs",
			{"action": "create", "prompt": "p", "schedule_expression": "0 9 * * *", "deliver": "origin"},
		)
		self.assertEqual(fr.get_doc.call_args[0][0]["deliver"], "raven:CH-7")

	@patch(f"{_CS}.frappe")
	def test_create_requires_prompt(self, fr):
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": "CH-1"}
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs(
				"manage-cron-jobs", {"action": "create", "schedule_expression": "x"}
			)

	@patch(f"{_CS}.frappe")
	def test_list_is_scoped_to_caller(self, fr):
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		fr.get_all.return_value = [{"name": "CRON-1"}]
		res = handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "list"})
		self.assertEqual(res["count"], 1)
		self.assertEqual(fr.get_all.call_args.kwargs["filters"]["agent_profile"], "Friday")

	@patch(f"{_CS}.frappe")
	def test_pause_refuses_another_agents_job(self, fr):
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		fr.db.exists.return_value = True
		fr.db.get_value.return_value = "OtherAgent"  # owner != caller
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "pause", "name": "CRON-9"})

	@patch(f"{_CS}.frappe")
	def test_pause_own_job(self, fr):
		from friday.friday_core.skills import handlers_cron

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
		from friday.friday_core.skills import handlers_cron

		fr.flags.get.return_value = {"agent_profile": "Friday", "session_id": ""}
		with self.assertRaises(ValueError):
			handlers_cron.manage_cron_jobs("manage-cron-jobs", {"action": "explode"})


if __name__ == "__main__":
	unittest.main()
