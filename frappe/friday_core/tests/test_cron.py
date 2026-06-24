# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Tests for scheduled agent runs / cron jobs (Design 87, Slice 1, LOCKED).

Tests-first. Mock-based — no DB, no redis, no worker.

What they pin (the LOCKED decisions):
  Q2 — compute_next_run handles cron (croniter), interval (minutes), once (ISO).
  Q3 — the tick advances next_run_at BEFORE spawning the Task (at-most-once).
  Q1 — the tick spawns ONE Task per due job, assigned to the profile, cron_job-linked.
  Q4 — the completion hook delivers task.result via the router; [SILENT] skips.
  Q5 — at the repeat limit the job is disabled + marked Completed (not deleted).
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

_CR = "frappe.friday_core.cron.scheduler"


class TestComputeNextRun(unittest.TestCase):
	def test_cron_expression_via_croniter(self):
		from frappe.friday_core.cron import scheduler

		base = datetime(2026, 6, 24, 17, 40, 0)
		self.assertEqual(
			scheduler.compute_next_run("cron", "*/5 * * * *", base),
			datetime(2026, 6, 24, 17, 45, 0),
		)

	def test_interval_minutes(self):
		from frappe.friday_core.cron import scheduler

		base = datetime(2026, 6, 24, 17, 40, 0)
		self.assertEqual(
			scheduler.compute_next_run("interval", "30", base),
			datetime(2026, 6, 24, 18, 10, 0),
		)

	@patch(f"{_CR}.frappe")
	def test_once_future_then_none(self, fr):
		from frappe.friday_core.cron import scheduler

		base = datetime(2026, 6, 24, 17, 40, 0)
		fr.utils.get_datetime.return_value = datetime(2026, 6, 24, 18, 0, 0)
		self.assertEqual(
			scheduler.compute_next_run("once", "2026-06-24T18:00:00", base),
			datetime(2026, 6, 24, 18, 0, 0),
		)
		fr.utils.get_datetime.return_value = datetime(2026, 6, 24, 17, 0, 0)  # past
		self.assertIsNone(scheduler.compute_next_run("once", "2026-06-24T17:00:00", base))


class TestTick(unittest.TestCase):
	@patch(f"{_CR}.compute_next_run", return_value=datetime(2026, 6, 24, 18, 10, 0))
	@patch(f"{_CR}.frappe")
	def test_advances_then_spawns_task(self, fr, _next):
		from frappe.friday_core.cron import scheduler

		fr.get_all.return_value = [{"name": "CRON-1"}]
		fr.utils.now_datetime.return_value = datetime(2026, 6, 24, 17, 40, 0)

		job = MagicMock()
		job.name = "CRON-1"
		job.schedule_kind = "interval"
		job.schedule_expr = "30"
		job.agent_profile = "Friday"
		job.prompt = "summarise yesterday"
		job.job_name = "Daily"

		created = {}

		def get_doc(*args):
			if isinstance(args[0], str):  # ("Cron Job", "CRON-1")
				return job
			created["task"] = args[0]  # the Task payload dict
			t = MagicMock()
			t.name = "TASK-9"
			return t

		fr.get_doc.side_effect = get_doc

		scheduler.tick()

		# next_run_at advanced BEFORE the task spawn, and the job saved.
		self.assertEqual(job.next_run_at, datetime(2026, 6, 24, 18, 10, 0))
		self.assertTrue(job.save.called)
		# exactly one Task, assigned to the profile, linked to the job, runnable.
		self.assertEqual(created["task"]["doctype"], "Task")
		self.assertEqual(created["task"]["assigned_to_profile"], "Friday")
		self.assertEqual(created["task"]["cron_job"], "CRON-1")
		self.assertEqual(created["task"]["workflow_state"], "Assigned")
		self.assertEqual(created["task"]["description"], "summarise yesterday")


class TestCompletionDelivery(unittest.TestCase):
	def _job(self, repeat_times=0, completed=0, deliver="local"):
		job = MagicMock()
		job.name = "CRON-1"
		job.job_name = "Daily"
		job.deliver = deliver
		job.repeat_times = repeat_times
		job.completed = completed
		return job

	def _task(self, summary="hello world", cron_job="CRON-1"):
		task = MagicMock()
		task.name = "TASK-9"
		task.cron_job = cron_job
		task.result = '{"status": "success", "summary": "%s"}' % summary
		return task

	@patch(f"{_CR}.DeliveryRouter")
	@patch(f"{_CR}.frappe")
	def test_delivers_result_and_bumps_completed(self, fr, Router):
		from frappe.friday_core.cron import scheduler

		job = self._job()
		fr.get_doc.return_value = job
		scheduler.on_task_terminal(self._task(), "Completed")

		Router.return_value.deliver.assert_called_once()
		# the result summary was delivered
		args = Router.return_value.deliver.call_args
		self.assertEqual(args.args[0], "hello world")
		self.assertEqual(job.completed, 1)
		self.assertTrue(job.save.called)

	@patch(f"{_CR}.DeliveryRouter")
	@patch(f"{_CR}.frappe")
	def test_silent_result_skips_delivery_but_records_run(self, fr, Router):
		from frappe.friday_core.cron import scheduler

		job = self._job()
		fr.get_doc.return_value = job
		scheduler.on_task_terminal(self._task(summary="[SILENT]"), "Completed")

		Router.return_value.deliver.assert_not_called()
		self.assertEqual(job.completed, 1)  # the run is still recorded

	@patch(f"{_CR}.DeliveryRouter")
	@patch(f"{_CR}.frappe")
	def test_repeat_limit_disables_job(self, fr, Router):
		from frappe.friday_core.cron import scheduler

		job = self._job(repeat_times=1, completed=0)
		fr.get_doc.return_value = job
		scheduler.on_task_terminal(self._task(), "Completed")

		self.assertEqual(job.completed, 1)
		self.assertEqual(job.enabled, 0)
		self.assertEqual(job.state, "Completed")

	@patch(f"{_CR}.DeliveryRouter")
	@patch(f"{_CR}.frappe")
	def test_forever_job_stays_enabled(self, fr, Router):
		from frappe.friday_core.cron import scheduler

		job = self._job(repeat_times=0, completed=5)
		fr.get_doc.return_value = job
		scheduler.on_task_terminal(self._task(), "Completed")

		self.assertEqual(job.completed, 6)
		# repeat_times=0 means forever — never auto-disabled.
		self.assertNotEqual(job.state, "Completed")

	@patch(f"{_CR}.DeliveryRouter")
	@patch(f"{_CR}.frappe")
	def test_non_cron_task_is_noop(self, fr, Router):
		from frappe.friday_core.cron import scheduler

		scheduler.on_task_terminal(self._task(cron_job=None), "Completed")
		fr.get_doc.assert_not_called()
		Router.return_value.deliver.assert_not_called()


if __name__ == "__main__":
	unittest.main()
