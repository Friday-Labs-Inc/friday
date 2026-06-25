# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Unit tests for the eval harness (Design 91 · Slice 1).

These are deterministic and DB-free: the audit-trail reads are faked with
`mock.patch`, the agent turn is an injected stub, and the clock is injected. So they
are safe to run anywhere (they never touch the live site — unlike a real eval run,
which deliberately drives the real path on a sandbox).

NOTE — what these CANNOT prove (the harness's own thesis, applied to itself): a
green run here does NOT prove the harness catches a real agent regression. Only a
real eval run on a sandbox (`bench execute frappe.friday_core.evals.run.run`) drives
the genuine loader → matrix → run_turn → dispatch path. These tests pin the
*plumbing* (scoring math, aggregation, report rendering); the sandbox run pins the
*agent*. That distinction is the whole reason this harness exists.
"""

from __future__ import annotations

import datetime
import unittest
from unittest import mock

from frappe.friday_core.evals import metrics, report, runner
from frappe.friday_core.evals.scenario import Scenario

_T0 = datetime.datetime(2026, 6, 25, 12, 0, 0)


def _clock(steps):
	"""A fake `now()` that returns each datetime in `steps` on successive calls."""
	it = iter(steps)
	return lambda: next(it)


class TestMetrics(unittest.TestCase):
	def test_tool_selection_ok(self):
		rows = [{"skill": "session_search", "status": "success", "creation": _T0}]
		with mock.patch("frappe.get_all", return_value=rows):
			v = metrics.tool_selection("Friday", _T0, _T0, ("session_search",), ("list-records",))
		self.assertTrue(v["ok"])
		self.assertEqual(v["missing"], [])
		self.assertEqual(v["forbidden_hit"], [])

	def test_tool_selection_missing_expected(self):
		with mock.patch("frappe.get_all", return_value=[]):
			v = metrics.tool_selection("Friday", _T0, _T0, ("session_search",), ())
		self.assertFalse(v["ok"])
		self.assertEqual(v["missing"], ["session_search"])

	def test_tool_selection_forbidden_hit(self):
		rows = [{"skill": "list-records", "status": "success", "creation": _T0}]
		with mock.patch("frappe.get_all", return_value=rows):
			v = metrics.tool_selection("Friday", _T0, _T0, (), ("list-records",))
		self.assertFalse(v["ok"])
		self.assertEqual(v["forbidden_hit"], ["list-records"])

	def test_tool_selection_window_excludes_late_rows(self):
		# A row created AFTER the run window must not count toward this run.
		late = _T0 + datetime.timedelta(seconds=30)
		rows = [{"skill": "session_search", "status": "success", "creation": late}]
		with mock.patch("frappe.get_all", return_value=rows):
			v = metrics.tool_selection("Friday", _T0, _T0, ("session_search",), ())
		self.assertEqual(v["called"], [])
		self.assertFalse(v["ok"])

	def test_economics_sums(self):
		rows = [
			{"total_tokens": 100, "estimated_cost": 0.001},
			{"total_tokens": 250, "estimated_cost": 0.0025},
		]
		with mock.patch("frappe.get_all", return_value=rows):
			v = metrics.economics("sess-1", latency_ms=1234.5)
		self.assertEqual(v["tokens"], 350)
		self.assertAlmostEqual(v["cost_usd"], 0.0035)
		self.assertEqual(v["llm_calls"], 2)
		self.assertEqual(v["latency_ms"], 1234.5)

	def test_outcome(self):
		ok = metrics.outcome("Here are your Projects: A, B", ("projects",))
		self.assertTrue(ok["ok"])
		miss = metrics.outcome("nothing relevant", ("projects",))
		self.assertFalse(miss["ok"])
		self.assertEqual(miss["missing"], ["projects"])

	def test_stats(self):
		self.assertEqual(metrics.stats([])["median"], 0)
		self.assertEqual(metrics.stats([5, 1, 3])["median"], 3)
		self.assertEqual(metrics.stats([1, 2, 3, 4])["median"], 2.5)
		s = metrics.stats([10, 20, 30])
		self.assertEqual((s["min"], s["max"], s["mean"]), (10, 30, 20))


class TestRunner(unittest.TestCase):
	def _scenario(self):
		return Scenario(
			name="demo",
			profile="Friday",
			prompt="hi",
			expect_skills=("session_search",),
			forbid_skills=("list-records",),
			expect_contains=("found",),
		)

	def test_run_scenario_all_pass(self):
		# Fake driver "calls session_search" + replies "found"; fake audit reads agree.
		def driver(scn, sid):
			return "found 2 results"

		exec_rows = [{"skill": "session_search", "status": "success", "creation": _T0}]
		usage_rows = [{"total_tokens": 120, "estimated_cost": 0.001}]

		def fake_get_all(doctype, **kw):
			return exec_rows if doctype == "Execution Log" else usage_rows

		# 2 clock reads per run (since, until); n=2 → 4 datetimes.
		steps = [_T0, _T0, _T0, _T0]
		with mock.patch("frappe.get_all", side_effect=fake_get_all):
			agg = runner.run_scenario(self._scenario(), n=2, driver=driver, now=_clock(steps))

		self.assertEqual(agg["pass_rate"], 1.0)
		self.assertEqual(agg["tool_ok_rate"], 1.0)
		self.assertEqual(agg["tokens"]["median"], 120)
		self.assertEqual(agg["errors"], [])

	def test_run_scenario_counts_driver_crash_as_fail(self):
		def driver(scn, sid):
			raise RuntimeError("boom")

		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(self._scenario(), n=1, driver=driver, now=_clock([_T0, _T0]))

		self.assertEqual(agg["pass_rate"], 0.0)
		self.assertTrue(agg["errors"][0].startswith("RuntimeError"))
		self.assertFalse(agg["runs"][0]["pass"])

	def test_run_scenario_wrong_tool_fails(self):
		def driver(scn, sid):
			return "found it"

		# Agent grabbed the forbidden list-records instead of session_search.
		exec_rows = [{"skill": "list-records", "status": "success", "creation": _T0}]

		def fake_get_all(doctype, **kw):
			return exec_rows if doctype == "Execution Log" else []

		with mock.patch("frappe.get_all", side_effect=fake_get_all):
			agg = runner.run_scenario(self._scenario(), n=1, driver=driver, now=_clock([_T0, _T0]))

		self.assertEqual(agg["pass_rate"], 0.0)
		self.assertEqual(agg["runs"][0]["tool"]["forbidden_hit"], ["list-records"])
		self.assertEqual(agg["runs"][0]["tool"]["missing"], ["session_search"])


class TestReport(unittest.TestCase):
	def test_render_includes_table_and_failure_reasons(self):
		results = [
			{
				"scenario": "good",
				"tags": ["tool-selection"],
				"note": "",
				"n": 2,
				"pass_rate": 1.0,
				"tool_ok_rate": 1.0,
				"latency_ms": {"median": 500, "min": 400, "max": 600, "mean": 500},
				"tokens": {"median": 100, "min": 90, "max": 110, "mean": 100},
				"cost_usd_mean": 0.001,
				"errors": [],
				"runs": [],
			},
			{
				"scenario": "bad",
				"tags": ["regression:#145"],
				"note": "must pick session_search",
				"n": 2,
				"pass_rate": 0.5,
				"tool_ok_rate": 0.5,
				"latency_ms": {"median": 700, "min": 600, "max": 800, "mean": 700},
				"tokens": {"median": 200, "min": 180, "max": 220, "mean": 200},
				"cost_usd_mean": 0.002,
				"errors": [],
				"runs": [
					{
						"i": 0,
						"pass": True,
						"error": None,
						"tool": {"called": ["session_search"], "missing": [], "forbidden_hit": []},
						"outcome": {"missing": []},
					},
					{
						"i": 1,
						"pass": False,
						"error": None,
						"tool": {
							"called": ["list-records"],
							"missing": ["session_search"],
							"forbidden_hit": ["list-records"],
						},
						"outcome": {"missing": []},
					},
				],
			},
		]
		md = report.render_markdown(results, site="sandbox.localhost")
		self.assertIn("1/2 scenarios fully passing", md)
		self.assertIn("| good |", md)
		self.assertIn("Failures — where + why", md)
		self.assertIn("never called ['session_search']", md)
		self.assertIn("called forbidden ['list-records']", md)


class TestFixtures(unittest.TestCase):
	def test_creates_project_when_missing(self):
		from frappe.friday_core.evals import fixtures

		with mock.patch.object(fixtures, "frappe") as fr:
			fr.db.exists.return_value = False
			out = fixtures.ensure_eval_fixtures()
		fr.get_doc.assert_called_once()
		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Project")
		self.assertEqual(payload["project_name"], fixtures.EVAL_PROJECT)
		self.assertEqual(out["created"], [fixtures.EVAL_PROJECT])

	def test_idempotent_when_present(self):
		from frappe.friday_core.evals import fixtures

		with mock.patch.object(fixtures, "frappe") as fr:
			fr.db.exists.return_value = True
			out = fixtures.ensure_eval_fixtures()
		fr.get_doc.assert_not_called()
		self.assertEqual(out["created"], [])


class TestSeeds(unittest.TestCase):
	def test_seeds_are_well_formed(self):
		from frappe.friday_core.evals.seeds import SEEDS

		names = [s.name for s in SEEDS]
		self.assertEqual(len(names), len(set(names)), "scenario names must be unique")
		# The anti-overcorrection seed is forbid-only (no required tool) by design.
		contrast = next(s for s in SEEDS if s.name == "listing-not-session-search")
		self.assertEqual(contrast.expect_skills, ())
		self.assertIn("session_search", contrast.forbid_skills)
		# The project scenario references the fixture project by its exact name.
		from frappe.friday_core.evals.fixtures import EVAL_PROJECT

		proj = next(s for s in SEEDS if s.name == "project-status-by-name")
		self.assertIn(EVAL_PROJECT, proj.prompt)


if __name__ == "__main__":
	unittest.main()
