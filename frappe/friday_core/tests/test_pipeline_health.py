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


class TestVerdictStrict(unittest.TestCase):
	"""Q3 LOCKED — strict thresholds. 'down' is loud, 'degraded' is loud, 'ok' is earned."""

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_verdict_ok_when_everything_healthy(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30  # seconds since last tick — fresh
		mock_inflight.return_value = {"default": 0, "friday": 0, "short": 0, "long": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "ok")

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_verdict_down_when_friday_worker_missing(self, mock_frappe, mock_tick, mock_inflight):
		"""The bench-serve trap from the Legion incident: scheduler up, no friday worker."""
		from frappe.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		# No 'friday' key at all = worker has never connected.
		mock_inflight.return_value = {"default": 0, "short": 0, "long": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "down")
		self.assertFalse(out["workers"]["friday"]["present"])

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_verdict_down_when_no_scheduler_tick_in_5_min(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 6 * 60  # 6 minutes since last tick
		mock_inflight.return_value = {"default": 0, "friday": 0}

		out = pipeline_health()

		self.assertEqual(out["verdict"], "down")

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_verdict_degraded_when_many_pending(self, mock_frappe, mock_tick, mock_inflight):
		"""Q3 LOCKED — pending > 10 OR open Issues > 5 → degraded."""
		from frappe.friday_core.health.pipeline_health import pipeline_health

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

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_verdict_degraded_when_many_open_issues(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

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

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_stuck_block_present_with_real_numbers(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

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

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_randompack_block_present(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

		_baseline_db(mock_frappe)
		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}

		def count(doctype, filters=None):
			if doctype != "RandomPack Event":
				return 0
			s = (filters or {}).get("status")
			if s == "Received":
				return 4
			if s == "Failed":
				return 1
			return 0

		mock_frappe.db.count.side_effect = count

		out = pipeline_health()

		self.assertEqual(out["randompack"]["events_received_pending"], 4)
		self.assertEqual(out["randompack"]["events_failed_retriable"], 1)


class TestFailLoud(unittest.TestCase):
	"""If the health check itself fails, the response must SAY SO loudly."""

	@patch("frappe.friday_core.health.pipeline_health._inflight_jobs_by_queue")
	@patch("frappe.friday_core.health.pipeline_health._scheduler_tick_age")
	@patch("frappe.friday_core.health.pipeline_health.frappe")
	def test_db_error_does_not_silently_return_ok(self, mock_frappe, mock_tick, mock_inflight):
		from frappe.friday_core.health.pipeline_health import pipeline_health

		mock_tick.return_value = 30
		mock_inflight.return_value = {"default": 0, "friday": 0}
		mock_frappe.db.count.side_effect = RuntimeError("simulated DB blip")

		out = pipeline_health()

		# Fail-loud about fail-loud: the verdict goes 'down', the operator sees why.
		self.assertEqual(out["verdict"], "down")
		self.assertIn("error", out)


if __name__ == "__main__":
	unittest.main()
