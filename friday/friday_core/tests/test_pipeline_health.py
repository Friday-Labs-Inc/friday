# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the Pipeline Health endpoint (design 61b, Q3).

This is the single signal that answers "is the autonomous loop alive?" for
both the human operator and the AI watching it. Strict thresholds (Q3
LOCKED) — when something is wrong it goes red within 60s, never silently
reassures.

The endpoint is whitelisted and returns a structured dict; the Desk page
renders it. Tests mock the Frappe data layer so they run headless.
"""

import unittest
from unittest.mock import MagicMock, patch


def _baseline_db(mock_frappe):
	"""Pin the mocked DB to a known-healthy default; per-test overrides clobber."""
	mock_frappe.db.count.return_value = 0
	mock_frappe.db.get_all.return_value = []
	mock_frappe.db.get_value.return_value = None
	mock_frappe.db.sql.return_value = []
	# Platform defaults: Raven present (required), Raven's own AI off (locked —
	# Friday is the engine). Without these the mock returns a truthy MagicMock
	# and every baseline test reads as "Raven AI switched on".
	mock_frappe.db.table_exists.return_value = True
	mock_frappe.db.get_single_value.return_value = 0


class TestVerdictStrict(unittest.TestCase):
	"""Q3 LOCKED — strict thresholds. 'down' is loud, 'degraded' is loud, 'ok' is earned."""

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_ok_when_everything_healthy(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30  # seconds since last tick — fresh
		mock_inflight.return_value = {"default": 0, "friday": 0, "short": 0, "long": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "ok")

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_down_when_friday_worker_missing(self, mock_frappe, mock_tick, mock_inflight):
		"""The bench-serve trap from the Legion incident: scheduler up, no friday worker."""
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		# No 'friday' key at all = worker has never connected.
		mock_inflight.return_value = {"default": 0, "short": 0, "long": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "down")
		self.assertFalse(out["workers"]["friday"]["present"])

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_degraded_when_raven_ai_enabled(self, mock_frappe, mock_tick, mock_inflight):
		"""Locked: Raven is the surface, Friday is the engine. Raven's own AI runtime
		writes to documents with no permission matrix, no Execution Log and no
		approval gate — a second, ungoverned engine on the same records. Not a
		Friday outage, so 'degraded', but never silent."""
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_frappe.db.table_exists.return_value = True
		mock_frappe.db.get_single_value.return_value = 1  # Raven AI switched on
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "degraded")
		self.assertTrue(out["surfaces"]["raven_ai_enabled"])

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_down_when_raven_missing(self, mock_frappe, mock_tick, mock_inflight):
		"""Raven is a REQUIRED platform component, so its absence is 'down' — not a
		quiet skip. Without it there is no bot to DM, no per-project channels and
		no war room, and the operator must see that immediately."""
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_frappe.db.table_exists.return_value = False
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "down")
		self.assertFalse(out["surfaces"]["raven_installed"])

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_down_when_no_scheduler_tick_in_5_min(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 6 * 60  # 6 minutes since last tick
		mock_inflight.return_value = {"default": 0, "friday": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "down")

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_degraded_when_many_pending(self, mock_frappe, mock_tick, mock_inflight):
		"""Q3 LOCKED — pending > 10 OR open Issues > 5 → degraded."""
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		# 11 pending tasks → degraded
		def count(doctype, filters=None):
			if doctype == "Task" and filters and filters.get("workflow_state") == "Pending":
				return 11
			return 0

		mock_frappe.db.count.side_effect = count

		out = pipeline_health()

		self.assertEqual(out["verdict"], "degraded")

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_verdict_degraded_when_many_open_issues(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		def count(doctype, filters=None):
			if doctype == "Issue":
				return 6
			return 0

		mock_frappe.db.count.side_effect = count

		out = pipeline_health()

		self.assertEqual(out["verdict"], "degraded")


class TestStuckCounts(unittest.TestCase):
	"""The 'stuck' block surfaces what the reconciler will act on next tick."""

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_stuck_block_present_with_real_numbers(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		# Wire the count() mock to return distinct numbers per call so we can
		# verify each stuck_* lands in the right slot.
		def count(doctype, filters=None):
			if doctype != "Task":
				return 0
			f = filters or {}
			state = f.get("workflow_state")
			if state == "Assigned":
				return 2  # assigned_orphaned
			if state == "Executing":
				return 1  # executing_stale
			if state == "Blocked":
				return 3  # transient_blocked_pending_retry
			return 0

		mock_frappe.db.count.side_effect = count

		out = pipeline_health()

		self.assertIn("stuck", out)
		# Exact numbers — we trust the count mock and the wiring.
		self.assertEqual(out["stuck"]["assigned_orphaned"], 2)
		self.assertEqual(out["stuck"]["executing_stale"], 1)
		self.assertEqual(out["stuck"]["transient_blocked_pending_retry"], 3)


class TestRandomPackHealth(unittest.TestCase):
	"""Q7a — the health page surfaces stuck RandomPack events."""

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_connector_block_present(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		def count(doctype, filters=None):
			if doctype != "Connector Event":
				return 0
			s = (filters or {}).get("status")
			if s == "Received":
				return 4
			if s == "Failed":
				return 1
			return 0

		mock_frappe.db.count.side_effect = count

		out = pipeline_health()

		self.assertEqual(out["connectors"]["events_received_pending"], 4)
		self.assertEqual(out["connectors"]["events_failed_retriable"], 1)


class TestFailLoud(unittest.TestCase):
	"""If the health check itself fails, the response must SAY SO loudly."""

	@patch("friday.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("friday.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("friday.friday_core.health.pipeline_health.frappe")
	def test_db_error_does_not_silently_return_ok(self, mock_frappe, mock_tick, mock_inflight):
		from friday.friday_core.health.pipeline_health import pipeline_health

		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}
		mock_frappe.db.count.side_effect = RuntimeError("simulated DB blip")

		out = pipeline_health()

		# Fail-loud about fail-loud: the verdict goes 'down', the operator sees why.
		self.assertEqual(out["verdict"], "down")
		self.assertIn("error", out)


class TestSchedulerTickAge(unittest.TestCase):
	"""``_scheduler_tick_age`` reads liveness from Scheduled Job Type.last_execution.

	Real-DB (not mocked): the rest of the suite mocks this function away, which is
	exactly how the original bug shipped — it read the sparse ``Scheduled Job
	Log`` (only written for ``create_log=1`` types), so a healthy scheduler whose
	last *logged* job was minutes old looked stale and forced a false ``down``.
	This pins the source to ``max(Scheduled Job Type.last_execution)``.
	"""

	def test_tick_age_matches_max_job_type_last_execution(self):
		import frappe
		from friday.friday_core.health.pipeline_health import _scheduler_tick_age
		from frappe.query_builder.functions import Max
		from frappe.utils import now_datetime, time_diff_in_seconds

		job_type = frappe.qb.DocType("Scheduled Job Type")
		expected_last = (
			frappe.qb.from_(job_type).select(Max(job_type.last_execution)).where(job_type.stopped == 0)
		).run()[0][0]

		age = _scheduler_tick_age()

		if expected_last is None:
			# fresh site, scheduler never fired — None (which maps to verdict=down)
			self.assertIsNone(age)
		else:
			expected_age = int(time_diff_in_seconds(now_datetime(), expected_last))
			self.assertIsNotNone(age)
			# small clock drift between the two now() reads is fine; the point is
			# it tracks last_execution, not the (staler) Scheduled Job Log.
			self.assertLessEqual(abs(age - expected_age), 5)


if __name__ == "__main__":
	unittest.main()
