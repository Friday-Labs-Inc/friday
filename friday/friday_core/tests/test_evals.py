# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Unit tests for the eval harness (Design 91 · Slice 1).

These are deterministic and DB-free: the audit-trail reads are faked with
`mock.patch`, the agent turn is an injected stub, and the clock is injected. So they
are safe to run anywhere (they never touch the live site — unlike a real eval run,
which deliberately drives the real path on a sandbox).

NOTE — what these CANNOT prove (the harness's own thesis, applied to itself): a
green run here does NOT prove the harness catches a real agent regression. Only a
real eval run on a sandbox (`bench execute friday.friday_core.evals.run.run`) drives
the genuine loader → matrix → run_turn → dispatch path. These tests pin the
*plumbing* (scoring math, aggregation, report rendering); the sandbox run pins the
*agent*. That distinction is the whole reason this harness exists.
"""

from __future__ import annotations

import datetime
import unittest
from unittest import mock

from friday.friday_core.evals import metrics, report, runner
from friday.friday_core.evals.scenario import Scenario

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
		from friday.friday_core.evals import fixtures

		with mock.patch.object(fixtures, "frappe") as fr:
			fr.db.exists.return_value = False
			out = fixtures.ensure_eval_fixtures()
		fr.get_doc.assert_called_once()
		payload = fr.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "Agent Project")
		self.assertEqual(payload["project_name"], fixtures.EVAL_PROJECT)
		self.assertEqual(out["created"], [fixtures.EVAL_PROJECT])

	def test_idempotent_when_present(self):
		from friday.friday_core.evals import fixtures

		with mock.patch.object(fixtures, "frappe") as fr:
			fr.db.exists.return_value = True
			out = fixtures.ensure_eval_fixtures()
		fr.get_doc.assert_not_called()
		self.assertEqual(out["created"], [])


class TestSeeds(unittest.TestCase):
	def test_seeds_are_well_formed(self):
		from friday.friday_core.evals.seeds import SEEDS

		names = [s.name for s in SEEDS]
		self.assertEqual(len(names), len(set(names)), "scenario names must be unique")
		# The anti-overcorrection seed is forbid-only (no required tool) by design.
		contrast = next(s for s in SEEDS if s.name == "listing-not-session-search")
		self.assertEqual(contrast.expect_skills, ())
		self.assertIn("session_search", contrast.forbid_skills)
		# The project scenario references the fixture project by its exact name.
		from friday.friday_core.evals.fixtures import EVAL_PROJECT

		proj = next(s for s in SEEDS if s.name == "project-status-by-name")
		self.assertIn(EVAL_PROJECT, proj.prompt)

	def test_open_ended_seed_carries_a_rubric(self):
		from friday.friday_core.evals.seeds import SEEDS

		q = next(s for s in SEEDS if s.name == "self-intro-quality")
		self.assertTrue(q.rubric, "the open-ended seed must define a rubric")
		self.assertEqual(len(q.rubric), 3)
		# It is a quality seed, not a tool-selection one.
		self.assertEqual(q.expect_skills, ())


# ---------------------------------------------------------------------------
# Slice 2 — the LLM-judge (quality axis)
# ---------------------------------------------------------------------------


class _FakeProvider:
	"""A provider stub: `.chat(messages)` returns a fixed `{"content": ...}` (or raises)."""

	def __init__(self, content=None, raises=None):
		self._content = content
		self._raises = raises

	def chat(self, messages, tools=None, model=None):
		if self._raises is not None:
			raise self._raises
		return {"content": self._content}


_RUBRIC = ("is on-topic", "is concise")


class TestJudge(unittest.TestCase):
	def test_build_messages_carries_reply_and_criteria(self):
		from friday.friday_core.evals import judge

		msgs = judge.build_judge_messages("the reply text", _RUBRIC, "be lenient")
		user = msgs[-1]["content"]
		self.assertIn("the reply text", user)
		for crit in _RUBRIC:
			self.assertIn(crit, user)
		self.assertIn("be lenient", user)

	def test_all_criteria_met(self):
		from friday.friday_core.evals import judge

		content = (
			'{"criteria": ['
			'{"criterion": "is on-topic", "met": true, "reason": "yes"},'
			'{"criterion": "is concise", "met": true, "reason": "short"}]}'
		)
		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider(content))
		self.assertTrue(v["ok"])
		self.assertEqual(v["unmet"], [])
		self.assertEqual(v["met_count"], 2)

	def test_one_criterion_unmet(self):
		from friday.friday_core.evals import judge

		content = (
			'{"criteria": ['
			'{"criterion": "is on-topic", "met": true, "reason": "yes"},'
			'{"criterion": "is concise", "met": false, "reason": "too long"}]}'
		)
		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider(content))
		self.assertFalse(v["ok"])
		self.assertEqual(v["unmet"], ["is concise"])

	def test_strips_code_fences(self):
		from friday.friday_core.evals import judge

		content = '```json\n{"criteria": [{"criterion": "is on-topic", "met": true, "reason": "ok"}, {"criterion": "is concise", "met": true, "reason": "ok"}]}\n```'
		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider(content))
		self.assertTrue(v["ok"])

	def test_unparseable_output_is_a_fail_not_a_crash(self):
		from friday.friday_core.evals import judge

		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider("I think it's fine, honestly"))
		self.assertFalse(v["ok"])
		self.assertIn("unparseable", v["error"])
		self.assertEqual(v["unmet"], list(_RUBRIC))

	def test_provider_error_is_a_fail_not_a_crash(self):
		from friday.friday_core.evals import judge

		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider(raises=RuntimeError("boom")))
		self.assertFalse(v["ok"])
		self.assertIn("judge call failed", v["error"])

	def test_truncated_judgement_fails_by_omission(self):
		from friday.friday_core.evals import judge

		# Judge returned only 1 of 2 criteria — the missing one cannot pass silently.
		content = '{"criteria": [{"criterion": "is on-topic", "met": true, "reason": "ok"}]}'
		v = judge.judge_quality("hi", _RUBRIC, provider=_FakeProvider(content))
		self.assertFalse(v["ok"])

	def test_empty_rubric_is_not_applicable(self):
		from friday.friday_core.evals import judge

		v = judge.judge_quality("hi", (), provider=_FakeProvider("anything"))
		self.assertTrue(v["ok"])
		self.assertEqual(v["total"], 0)


class TestResolveJudgeProvider(unittest.TestCase):
	def test_rejects_provider_equal_to_agents(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}):
			out = judge.resolve_judge_provider("Friday", judge_provider_name="MiniMax")
		self.assertIsNone(out["provider"])
		self.assertIn("not independent", out["reason"].lower())

	def test_explicit_independent_provider(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		sentinel = object()
		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch.object(prov, "get_provider_by_name", return_value=sentinel),
		):
			out = judge.resolve_judge_provider("Friday", judge_provider_name="Claude")
		self.assertIs(out["provider"], sentinel)
		self.assertEqual(out["name"], "Claude")

	def test_autodiscovers_first_different_active_provider(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		sentinel = object()
		rows = [{"name": "MiniMax"}, {"name": "Claude"}]
		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch("frappe.get_all", return_value=rows),
			mock.patch.object(prov, "get_provider_by_name", return_value=sentinel),
		):
			out = judge.resolve_judge_provider("Friday")
		self.assertEqual(out["name"], "Claude")
		self.assertIs(out["provider"], sentinel)

	def test_explicit_provider_build_failure_is_blocked_not_crash(self):
		# A named provider that can't build (e.g. no stored api_key → ValidationError,
		# NOT LLMError) must return a reason, never propagate. (Live-run lesson.)
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		def boom(_):
			raise RuntimeError("Password not found for LLM Provider Claude api_key")

		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch.object(prov, "get_provider_by_name", side_effect=boom),
		):
			out = judge.resolve_judge_provider("Friday", judge_provider_name="Claude")
		self.assertIsNone(out["provider"])
		self.assertIn("Password not found", out["reason"])

	def test_autodiscovery_skips_unbuildable_then_takes_next(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		sentinel = object()

		def gp(name):
			if name == "Broken":
				raise RuntimeError("Password not found")
			return sentinel

		rows = [{"name": "MiniMax"}, {"name": "Broken"}, {"name": "Good"}]
		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch("frappe.get_all", return_value=rows),
			mock.patch.object(prov, "get_provider_by_name", side_effect=gp),
		):
			out = judge.resolve_judge_provider("Friday")
		self.assertEqual(out["name"], "Good")
		self.assertIs(out["provider"], sentinel)

	def test_blocked_when_only_agent_provider_is_active(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch("frappe.get_all", return_value=[{"name": "MiniMax"}]),
		):
			out = judge.resolve_judge_provider("Friday")
		self.assertIsNone(out["provider"])
		self.assertIn("no independent judge", out["reason"].lower())


class TestRunnerQuality(unittest.TestCase):
	def _rubric_scenario(self):
		return Scenario(name="q", profile="Friday", prompt="hi", rubric=("must be nice",))

	def _driver(self, scn, sid):
		return "hello there"

	def test_quality_pass_gates_into_overall_pass(self):
		def judge(reply, rubric, panel_size):
			return {
				"ok": True,
				"unmet": [],
				"criteria": [{"criterion": "must be nice", "met": True, "reason": "ok"}],
			}

		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(
				self._rubric_scenario(), n=1, driver=self._driver, now=_clock([_T0, _T0]), judge=judge
			)
		self.assertEqual(agg["pass_rate"], 1.0)
		self.assertEqual(agg["quality_ok_rate"], 1.0)
		self.assertFalse(agg["quality_unavailable"])

	def test_quality_fail_fails_the_run(self):
		def judge(reply, rubric, panel_size):
			return {
				"ok": False,
				"unmet": ["must be nice"],
				"criteria": [{"criterion": "must be nice", "met": False, "reason": "rude"}],
			}

		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(
				self._rubric_scenario(), n=1, driver=self._driver, now=_clock([_T0, _T0]), judge=judge
			)
		self.assertEqual(agg["pass_rate"], 0.0)
		self.assertEqual(agg["quality_ok_rate"], 0.0)
		self.assertFalse(agg["runs"][0]["pass"])
		self.assertEqual(agg["runs"][0]["quality"]["unmet"], ["must be nice"])

	def test_no_judge_skips_quality_without_failing(self):
		# Rubric scenario, judge=None (no independent provider). Quality is skipped: it
		# does NOT gate the pass, but the aggregate flags the axis as unavailable.
		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(
				self._rubric_scenario(), n=1, driver=self._driver, now=_clock([_T0, _T0])
			)
		self.assertTrue(agg["quality_unavailable"])
		self.assertIsNone(agg["quality_ok_rate"])
		self.assertEqual(agg["pass_rate"], 1.0)  # tool + outcome still pass
		self.assertTrue(agg["runs"][0]["quality"]["skipped"])

	def test_no_rubric_means_judge_is_not_applied(self):
		# A scenario with no rubric must never invoke the judge, even if one is passed.
		def exploding_judge(reply, rubric, panel_size):
			raise AssertionError("judge must not run for a no-rubric scenario")

		scn = Scenario(name="nr", profile="Friday", prompt="hi")
		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(
				scn, n=1, driver=self._driver, now=_clock([_T0, _T0]), judge=exploding_judge
			)
		self.assertFalse(agg["has_rubric"])
		self.assertIsNone(agg["quality_ok_rate"])
		self.assertIsNone(agg["runs"][0]["quality"])
		self.assertEqual(agg["pass_rate"], 1.0)


class TestReportQuality(unittest.TestCase):
	def _row(self, **over):
		base = {
			"scenario": "q",
			"tags": ["quality"],
			"note": "",
			"n": 1,
			"pass_rate": 1.0,
			"tool_ok_rate": 1.0,
			"has_rubric": True,
			"quality_ok_rate": 1.0,
			"quality_unavailable": False,
			"latency_ms": {"median": 1, "min": 1, "max": 1, "mean": 1},
			"tokens": {"median": 1, "min": 1, "max": 1, "mean": 1},
			"cost_usd_mean": 0.0,
			"errors": [],
			"runs": [],
		}
		base.update(over)
		return base

	def test_quality_column_and_blocked_banner(self):
		results = [
			self._row(scenario="judged"),
			self._row(scenario="blocked", quality_ok_rate=None, quality_unavailable=True),
		]
		md = report.render_markdown(results, site="sandbox.localhost", judge_name="Claude")
		self.assertIn("| Quality |", md)
		self.assertIn("Quality axis blocked", md)
		self.assertIn("SKIP", md)
		# The judge provider is named in the header so a reader knows it was independent.
		self.assertIn("`Claude`", md)

	def test_quality_failure_shows_criterion_reason(self):
		row = self._row(
			scenario="q",
			pass_rate=0.0,
			quality_ok_rate=0.0,
			runs=[
				{
					"i": 0,
					"pass": False,
					"error": None,
					"tool": {"called": [], "missing": [], "forbidden_hit": []},
					"outcome": {"missing": []},
					"quality": {
						"ok": False,
						"unmet": ["be concise"],
						"criteria": [{"criterion": "be concise", "met": False, "reason": "too long"}],
					},
				}
			],
		)
		md = report.render_markdown([row])
		self.assertIn("unmet rubric ['be concise']", md)
		self.assertIn("too long", md)

	def test_panel_vote_split_rendered(self):
		row = self._row(
			scenario="panel",
			pass_rate=0.0,
			quality_ok_rate=0.0,
			runs=[
				{
					"i": 0,
					"pass": False,
					"error": None,
					"tool": {"called": [], "missing": [], "forbidden_hit": []},
					"outcome": {"missing": []},
					"quality": {
						"ok": False,
						"unmet": ["beginner-friendly"],
						"criteria": [
							{
								"criterion": "beginner-friendly",
								"met": False,
								"reason": "jargon",
								"votes": "1/3",
							}
						],
					},
				}
			],
		)
		md = report.render_markdown([row])
		self.assertIn("[1/3]", md)  # the panel vote split appears in the failure breakdown

	def test_probe_failure_shows_failed_checks(self):
		row = {
			"scenario": "force-kill-audit",
			"tags": ["probe"],
			"note": "",
			"n": 1,
			"is_probe": True,
			"pass_rate": 0.0,
			"tool_ok_rate": None,
			"has_rubric": False,
			"quality_ok_rate": None,
			"quality_unavailable": False,
			"latency_ms": {"median": 1, "min": 1, "max": 1, "mean": 1},
			"tokens": {"median": 0, "min": 0, "max": 0, "mean": 0},
			"cost_usd_mean": 0.0,
			"errors": [],
			"runs": [
				{
					"i": 0,
					"pass": False,
					"error": None,
					"tool": None,
					"outcome": None,
					"quality": None,
					"probe": {
						"ok": False,
						"checks": [{"name": "task → ForceKilled", "ok": False, "detail": "Executing"}],
					},
				}
			],
		}
		md = report.render_markdown([row])
		self.assertIn("check(s) failed", md)
		self.assertIn("task → ForceKilled", md)
		self.assertIn("Executing", md)
		# A probe scenario has no tool axis → its Tool-sel cell is an em dash.
		self.assertIn("| force-kill-audit | 0% | — |", md)


# ---------------------------------------------------------------------------
# Slice 3 — judge panel + non-chat probes
# ---------------------------------------------------------------------------


def _met(crit, reason="ok"):
	return '{"criteria": [{"criterion": "%s", "met": true, "reason": "%s"}]}' % (crit, reason)


def _unmet(crit, reason="no"):
	return '{"criteria": [{"criterion": "%s", "met": false, "reason": "%s"}]}' % (crit, reason)


class TestPanel(unittest.TestCase):
	def _seat(self, content, lens=""):
		return {"provider": _FakeProvider(content), "name": "P", "lens": lens}

	def test_majority_met_passes(self):
		from friday.friday_core.evals import judge

		seats = [self._seat(_met("c1")), self._seat(_met("c1")), self._seat(_unmet("c1"))]
		v = judge.run_panel("reply", ("c1",), seats)
		self.assertTrue(v["ok"])
		self.assertEqual(v["criteria"][0]["votes"], "2/3")
		self.assertEqual(v["panel_size"], 3)

	def test_minority_met_fails(self):
		from friday.friday_core.evals import judge

		seats = [self._seat(_met("c1")), self._seat(_unmet("c1")), self._seat(_unmet("c1"))]
		v = judge.run_panel("reply", ("c1",), seats)
		self.assertFalse(v["ok"])
		self.assertEqual(v["criteria"][0]["votes"], "1/3")
		self.assertEqual(v["unmet"], ["c1"])

	def test_omitted_verdict_counts_as_not_met(self):
		from friday.friday_core.evals import judge

		# Two seats return unparseable output → no met vote → 1/3 → criterion fails.
		seats = [self._seat(_met("c1")), self._seat("garbage"), self._seat("also garbage")]
		v = judge.run_panel("reply", ("c1",), seats)
		self.assertFalse(v["ok"])
		self.assertEqual(v["criteria"][0]["votes"], "1/3")

	def test_single_seat_behaves_like_single_judge(self):
		from friday.friday_core.evals import judge

		v = judge.run_panel("reply", ("c1",), [self._seat(_met("c1"))])
		self.assertTrue(v["ok"])
		self.assertEqual(v["criteria"][0]["votes"], "1/1")
		self.assertEqual(v["panel_size"], 1)

	def test_no_seats_is_skipped_not_a_fail(self):
		# No buildable seats → the quality axis is unavailable → SKIP, never a 0% that
		# scores the agent down for a judge-config problem.
		from friday.friday_core.evals import judge

		v = judge.run_panel("reply", ("c1",), [])
		self.assertTrue(v["skipped"])
		self.assertIsNone(v["ok"])
		self.assertEqual(v["panel_size"], 0)

	def test_seats_summary_carries_lens(self):
		from friday.friday_core.evals import judge

		seats = [self._seat(_met("c1"), lens="strict-literal")]
		v = judge.run_panel("reply", ("c1",), seats)
		self.assertEqual(v["seats"][0]["lens"], "strict-literal")


class TestBuildPanelSeats(unittest.TestCase):
	def test_cycles_names_and_assigns_distinct_lenses(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with mock.patch.object(prov, "get_provider_by_name", side_effect=lambda nm: f"prov-{nm}"):
			seats = judge.build_panel_seats(["A", "B"], 3)
		self.assertEqual([s["name"] for s in seats], ["A", "B", "A"])
		# Lenses assigned by seat index from the deterministic order — all distinct here.
		self.assertEqual([s["lens"] for s in seats], list(judge._LENS_ORDER))
		self.assertEqual(seats[0]["provider"], "prov-A")

	def test_single_seat_has_no_lens(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with mock.patch.object(prov, "get_provider_by_name", side_effect=lambda nm: f"prov-{nm}"):
			seats = judge.build_panel_seats(["A"], 1)
		self.assertEqual(len(seats), 1)
		self.assertEqual(seats[0]["lens"], "")

	def test_skips_unbuildable_provider(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		# IMPORTANT: a real build failure is NOT always an LLMError — a provider row with
		# no stored api_key raises frappe.ValidationError ("Password not found"). A live
		# run on friday.localhost hit exactly this and crashed the whole eval, because the
		# code (and this test) had only caught LLMError. Simulate a non-LLMError here so a
		# narrow `except LLMError` regression is caught by the suite next time.
		def gp(nm):
			if nm == "B":
				raise RuntimeError("Password not found for LLM Provider B api_key")
			return f"prov-{nm}"

		with mock.patch.object(prov, "get_provider_by_name", side_effect=gp):
			seats = judge.build_panel_seats(["A", "B"], 2)
		self.assertEqual([s["name"] for s in seats], ["A"])

	def test_empty_names_or_zero_size(self):
		from friday.friday_core.evals import judge

		self.assertEqual(judge.build_panel_seats([], 3), [])
		self.assertEqual(judge.build_panel_seats(["A"], 0), [])


class TestJudgeRobustness(unittest.TestCase):
	"""Hardening: scoring is anchored on the rubric, matched by text — not by position."""

	def test_reordered_criteria_are_matched_by_text(self):
		from friday.friday_core.evals import judge

		rubric = ("first thing", "second thing")
		# Judge returns them in the WRONG order — text-match must still score correctly.
		content = (
			'{"criteria": ['
			'{"criterion": "second thing", "met": false, "reason": "no"},'
			'{"criterion": "first thing", "met": true, "reason": "yes"}]}'
		)
		v = judge.judge_quality("r", rubric, provider=_FakeProvider(content))
		self.assertEqual([c["criterion"] for c in v["criteria"]], ["first thing", "second thing"])
		self.assertTrue(v["criteria"][0]["met"])  # "first thing" met
		self.assertFalse(v["criteria"][1]["met"])  # "second thing" not
		self.assertEqual(v["unmet"], ["second thing"])

	def test_count_gaming_cannot_pass_an_unaddressed_criterion(self):
		from friday.friday_core.evals import judge

		rubric = ("alpha", "beta")
		# Right COUNT (2) but both are "alpha" — "beta" was never judged → must be not-met.
		content = (
			'{"criteria": ['
			'{"criterion": "alpha", "met": true, "reason": "ok"},'
			'{"criterion": "alpha", "met": true, "reason": "dup"}]}'
		)
		v = judge.judge_quality("r", rubric, provider=_FakeProvider(content))
		self.assertFalse(v["ok"])
		self.assertEqual(v["unmet"], ["beta"])

	def test_punctuation_and_case_differences_still_match(self):
		from friday.friday_core.evals import judge

		rubric = ("Is concise",)
		content = '{"criteria": [{"criterion": "is concise.", "met": true, "reason": "ok"}]}'
		v = judge.judge_quality("r", rubric, provider=_FakeProvider(content))
		self.assertTrue(v["ok"])

	def test_invented_extra_criterion_is_ignored(self):
		from friday.friday_core.evals import judge

		rubric = ("only this",)
		content = (
			'{"criteria": ['
			'{"criterion": "only this", "met": true, "reason": "ok"},'
			'{"criterion": "an invented criterion", "met": false, "reason": "noise"}]}'
		)
		v = judge.judge_quality("r", rubric, provider=_FakeProvider(content))
		self.assertTrue(v["ok"])  # the invented not-met item is noise, not a rubric criterion
		self.assertEqual(len(v["criteria"]), 1)

	def test_model_is_passed_through_to_chat(self):
		from friday.friday_core.evals import judge

		seen = {}

		class _CapturingProvider:
			def chat(self, messages, tools=None, model=None):
				seen["model"] = model
				return {"content": '{"criteria": [{"criterion": "c", "met": true, "reason": "ok"}]}'}

		judge.judge_quality("r", ("c",), provider=_CapturingProvider(), model="judge-model-x")
		self.assertEqual(seen["model"], "judge-model-x")


class TestPanelRobustness(unittest.TestCase):
	def _seat(self, content, lens=""):
		return {"provider": _FakeProvider(content), "name": "P", "lens": lens}

	def test_panel_matches_reordered_seat_verdicts(self):
		from friday.friday_core.evals import judge

		rubric = ("aa", "bb")
		# Seat returns criteria reversed; the panel must still vote per the right criterion.
		reordered = (
			'{"criteria": ['
			'{"criterion": "bb", "met": true, "reason": "b-ok"},'
			'{"criterion": "aa", "met": false, "reason": "a-bad"}]}'
		)
		seats = [self._seat(reordered)]
		v = judge.run_panel("r", rubric, seats)
		by_crit = {c["criterion"]: c for c in v["criteria"]}
		self.assertFalse(by_crit["aa"]["met"])
		self.assertTrue(by_crit["bb"]["met"])

	def test_failed_criterion_surfaces_a_dissenting_reason(self):
		from friday.friday_core.evals import judge

		# 1 met (reason "good"), 2 not-met (reasons "jargon"): criterion fails 1/3 and the
		# shown reason must be a not-met one, not the lone "good".
		seats = [
			self._seat('{"criteria": [{"criterion": "c", "met": true, "reason": "good"}]}'),
			self._seat('{"criteria": [{"criterion": "c", "met": false, "reason": "jargon"}]}'),
			self._seat('{"criteria": [{"criterion": "c", "met": false, "reason": "jargon"}]}'),
		]
		v = judge.run_panel("r", ("c",), seats)
		self.assertFalse(v["ok"])
		self.assertEqual(v["criteria"][0]["reason"], "jargon")

	def test_all_seats_unavailable_skips_with_reason(self):
		# Every seat's provider raises (e.g. keyless rows → LLMAuthError). The panel can't
		# judge → SKIP with the error surfaced, NOT a 0% that blames the agent. (Live-run
		# finding on friday.localhost: 3 keyless judge rows.)
		from friday.friday_core.evals import judge

		seats = [
			{"provider": _FakeProvider(raises=RuntimeError("bad key")), "name": "P1", "lens": ""},
			{"provider": _FakeProvider(raises=RuntimeError("bad key")), "name": "P2", "lens": ""},
		]
		v = judge.run_panel("r", ("c",), seats)
		self.assertTrue(v["skipped"])
		self.assertIsNone(v["ok"])
		self.assertIn("unavailable", v["reason"])

	def test_one_unavailable_seat_excluded_others_still_vote(self):
		# 1 seat errors (excluded), 2 valid seats both say met → 2/2 → met. The dead seat
		# must not drag the vote down (it's absent, not a not-met vote).
		from friday.friday_core.evals import judge

		seats = [
			{"provider": _FakeProvider(raises=RuntimeError("dead")), "name": "P0", "lens": ""},
			self._seat(_met("c")),
			self._seat(_met("c")),
		]
		v = judge.run_panel("r", ("c",), seats)
		self.assertTrue(v["ok"])
		self.assertEqual(v["criteria"][0]["votes"], "2/2")  # denominator = votable seats only


class TestResolveIndependentProviders(unittest.TestCase):
	def test_explicit_same_as_agent_is_rejected(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}):
			out = judge.resolve_independent_providers("Friday", judge_provider_name="MiniMax")
		self.assertEqual(out["names"], [])
		self.assertIn("not independent", out["reason"].lower())

	def test_explicit_independent_is_the_only_candidate(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}):
			out = judge.resolve_independent_providers("Friday", judge_provider_name="Claude")
		self.assertEqual(out["names"], ["Claude"])

	def test_autodiscovery_excludes_agent_provider(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		rows = [{"name": "MiniMax"}, {"name": "Claude"}, {"name": "GPT"}]
		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch("frappe.get_all", return_value=rows),
		):
			out = judge.resolve_independent_providers("Friday")
		self.assertEqual(out["names"], ["Claude", "GPT"])

	def test_blocked_when_only_agent_provider(self):
		from friday.friday_core.evals import judge
		from friday.friday_core.llm import provider as prov

		with (
			mock.patch.object(prov, "_resolve_provider_row", return_value={"name": "MiniMax"}),
			mock.patch("frappe.get_all", return_value=[{"name": "MiniMax"}]),
		):
			out = judge.resolve_independent_providers("Friday")
		self.assertEqual(out["names"], [])
		self.assertIn("no independent judge", out["reason"].lower())


class TestProbes(unittest.TestCase):
	def test_force_kill_audit_happy_path(self):
		import types

		from friday.friday_core.evals import probes

		op = probes._FORCE_KILL_OPERATOR
		m_task = mock.MagicMock()
		m_task.name = "TASK-1"
		m_task.insert.return_value = m_task

		with (
			mock.patch.object(probes, "frappe") as fr,
			mock.patch(
				"friday.friday_core.gateway.interrupt.force_kill_session",
				return_value={
					"tasks_now_forcekilled": ["TASK-1"],
					"jobs_cancelled": 0,
					"jobs_already_done": 1,
				},
			),
		):
			# The probe inserts ONLY a Task now (no Chat Message — that would trigger the
			# real inbound gateway). One get_doc call.
			fr.get_doc.return_value = m_task
			fr.db.get_value.return_value = types.SimpleNamespace(
				workflow_state="ForceKilled", force_killed_by=op, force_kill_reason="operator /stop force"
			)
			fr.get_all.return_value = [{"name": "EV-1"}]
			v = probes.probe_force_kill_audit(None, "sess-1")

		self.assertTrue(v["ok"], v)
		self.assertTrue(all(c["ok"] for c in v["checks"]))
		# The Chat Message branch is gone — exactly one doc (the Task) is created.
		self.assertEqual(fr.get_doc.call_count, 1)

	def test_force_kill_audit_flags_wrong_state(self):
		import types

		from friday.friday_core.evals import probes

		m_task = mock.MagicMock()
		m_task.name = "TASK-1"
		m_task.insert.return_value = m_task

		with (
			mock.patch.object(probes, "frappe") as fr,
			mock.patch(
				"friday.friday_core.gateway.interrupt.force_kill_session",
				return_value={"tasks_now_forcekilled": [], "jobs_cancelled": 0, "jobs_already_done": 0},
			),
		):
			fr.get_doc.return_value = m_task
			fr.db.get_value.return_value = types.SimpleNamespace(
				workflow_state="Executing", force_killed_by=None, force_kill_reason=None
			)
			fr.get_all.return_value = []
			v = probes.probe_force_kill_audit(None, "sess-1")

		self.assertFalse(v["ok"])
		states = {c["name"]: c["ok"] for c in v["checks"]}
		self.assertFalse(states["task → ForceKilled"])

	def test_audit_event_check_is_soft_and_does_not_gate(self):
		# Hard audit checks pass but the best-effort Dispatcher Event is absent: the probe
		# must still PASS (a missing observability row isn't a force-kill failure).
		import types

		from friday.friday_core.evals import probes

		op = probes._FORCE_KILL_OPERATOR
		m_task = mock.MagicMock()
		m_task.name = "TASK-1"
		m_task.insert.return_value = m_task

		with (
			mock.patch.object(probes, "frappe") as fr,
			mock.patch(
				"friday.friday_core.gateway.interrupt.force_kill_session",
				return_value={
					"tasks_now_forcekilled": ["TASK-1"],
					"jobs_cancelled": 0,
					"jobs_already_done": 1,
				},
			),
		):
			fr.get_doc.return_value = m_task
			fr.db.get_value.return_value = types.SimpleNamespace(
				workflow_state="ForceKilled", force_killed_by=op, force_kill_reason="operator /stop force"
			)
			fr.get_all.return_value = []  # no audit event row
			v = probes.probe_force_kill_audit(None, "sess-1")

		self.assertTrue(v["ok"])  # soft check absence does not gate
		soft = [c for c in v["checks"] if c.get("soft")]
		self.assertTrue(soft and not soft[0]["ok"])

	def test_pgvector_probe_skips_on_non_postgres(self):
		from friday.friday_core.evals import probes

		with mock.patch.object(probes, "frappe") as fr:
			fr.db.db_type = "mysql"
			v = probes.probe_pgvector_no_poison(None, "sess-1")
		self.assertTrue(v["ok"])
		self.assertIn("postgres-only", v["checks"][0]["name"])

	def test_pgvector_probe_postgres_happy_path(self):
		from friday.friday_core.evals import probes
		from friday.friday_core.llm import after_migrate

		with (
			mock.patch.object(probes, "frappe") as fr,
			mock.patch.object(after_migrate, "ensure_memory_search_schema") as m1,
			mock.patch.object(after_migrate, "ensure_memory_embedding_schema") as m2,
			mock.patch.object(after_migrate, "ensure_chatmessage_search_schema") as m3,
		):
			# The probe labels each check by the function's __name__; MagicMocks lack one.
			m1.__name__, m2.__name__, m3.__name__ = ("ensure_memory_search_schema", "emb", "fts")
			fr.db.db_type = "postgres"
			fr.db.sql.return_value = [(1,)]
			v = probes.probe_pgvector_no_poison(None, "sess-1")
		self.assertTrue(v["ok"], v)
		# The savepoint-recovery check must be present (the core #132 invariant).
		self.assertTrue(any("savepoint" in c["name"] for c in v["checks"]))


class TestRunnerProbeAndPanel(unittest.TestCase):
	def test_probe_scenario_passes_on_ok(self):
		scn = Scenario(name="p", profile="Friday", prompt="x", probe="myprobe")

		def lookup(name):
			return lambda scenario, sid: {"ok": True, "checks": [{"name": "c", "ok": True}]}

		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(scn, n=1, now=_clock([_T0, _T0]), probe_lookup=lookup)
		self.assertTrue(agg["is_probe"])
		self.assertEqual(agg["pass_rate"], 1.0)
		self.assertIsNone(agg["tool_ok_rate"])
		self.assertTrue(agg["runs"][0]["probe"]["ok"])

	def test_unknown_probe_is_an_error(self):
		scn = Scenario(name="p", profile="Friday", prompt="x", probe="missing")
		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(scn, n=1, now=_clock([_T0, _T0]), probe_lookup=lambda name: None)
		self.assertEqual(agg["pass_rate"], 0.0)
		self.assertIn("no probe registered", agg["errors"][0])

	def test_probe_exception_is_caught(self):
		def boom(scenario, sid):
			raise RuntimeError("kaboom")

		scn = Scenario(name="p", profile="Friday", prompt="x", probe="boom")
		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(scn, n=1, now=_clock([_T0, _T0]), probe_lookup=lambda name: boom)
		self.assertEqual(agg["pass_rate"], 0.0)
		self.assertTrue(agg["errors"][0].startswith("RuntimeError"))

	def test_panel_size_is_threaded_to_the_judge(self):
		captured = {}

		def judge(reply, rubric, panel_size):
			captured["panel_size"] = panel_size
			return {"ok": True, "unmet": [], "criteria": [], "panel_size": panel_size}

		scn = Scenario(name="q", profile="Friday", prompt="hi", rubric=("c",), judge_panel=3)
		with mock.patch("frappe.get_all", return_value=[]):
			agg = runner.run_scenario(
				scn, n=1, driver=lambda s, sid: "hi", now=_clock([_T0, _T0]), judge=judge
			)
		self.assertEqual(captured["panel_size"], 3)
		self.assertEqual(agg["runs"][0]["quality"]["panel_size"], 3)


class TestSlice3Seeds(unittest.TestCase):
	def test_panel_and_probe_seeds_present(self):
		from friday.friday_core.evals.seeds import SEEDS

		by_name = {s.name: s for s in SEEDS}
		panel = by_name["explain-clearly-panel"]
		self.assertEqual(panel.judge_panel, 3)
		self.assertTrue(panel.rubric)
		self.assertEqual(by_name["force-kill-audit"].probe, "force_kill_audit")
		self.assertEqual(by_name["pgvector-no-poison"].probe, "pgvector_no_poison")
		# Probe seeds must name a probe that actually exists in the registry.
		from friday.friday_core.evals.probes import PROBES

		for name in ("force-kill-audit", "pgvector-no-poison"):
			self.assertIn(by_name[name].probe, PROBES)


if __name__ == "__main__":
	unittest.main()
