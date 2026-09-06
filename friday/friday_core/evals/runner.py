# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Drive each scenario on the REAL agent path, N times, then aggregate.

The runner is deliberately thin: for each of N runs it (1) stamps a start time,
(2) drives the real turn, (3) stamps an end time, (4) asks the metrics module to
score the run from the audit trail, (5) records a pass/fail. Then `aggregate`
collapses the N runs into one per-scenario verdict with **distributions** (median +
spread), because an agent is non-deterministic and a single number lies.

The real driver (`_drive_real`) calls `run_turn` — the exact entry the gateway uses
— so the loader, permission matrix, ReAct loop, and dispatch are all the genuine
code. Tests inject a fake `driver` + a fake `now` clock so the runner is verifiable
without an LLM or a clock.
"""

from __future__ import annotations

import frappe

from . import metrics
from .scenario import Scenario


def _drive_real(scenario: Scenario, session_id: str) -> str:
	"""Drive ONE real agent turn and return the reply text.

	Imported lazily so importing the harness (e.g. to run its own unit tests)
	doesn't pull the whole agent stack.
	"""
	from friday.friday_core.agent_runner.runner import run_turn

	return run_turn(scenario.profile, session_id, scenario.prompt)


def _ms(since, until) -> float:
	"""Milliseconds between two datetimes (the turn's wall-clock latency)."""
	return (until - since).total_seconds() * 1000.0


def _default_probe_lookup(name: str):
	"""Resolve a probe by name from the registry (lazy import keeps the harness light)."""
	from . import probes

	return probes.PROBES.get(name)


def run_scenario(
	scenario: Scenario, n: int = 3, driver=None, now=None, judge=None, probe_lookup=None
) -> dict:
	"""Run one scenario N times on the real path and return its aggregate verdict.

	`driver(scenario, session_id) -> reply`, `now() -> datetime`,
	`judge(reply, rubric, panel_size) -> verdict`, and `probe_lookup(name) -> probe_fn`
	are injectable for tests; their defaults are the real turn + clock + (judge) None +
	the real probe registry.

	Two scenario shapes:
	  - **chat** (no `probe`): drive run_turn, score tool-selection + economics +
	    outcome + (if a rubric) the judge/panel quality axis.
	  - **probe** (`probe` set, Slice 3): drive a different real path (force-stop,
	    migrate-gate) via the named probe, which returns its own `{ok, checks}`.

	The `judge` axis (Slice 2/3) only engages for rubric scenarios. Run WITHOUT a judge
	(no independent provider) → quality is *skipped*: it does NOT gate the pass and is
	surfaced as a visible gap. A scenario with no rubric is unaffected.
	"""
	driver = driver or _drive_real
	now = now or frappe.utils.now_datetime
	probe_lookup = probe_lookup or _default_probe_lookup

	runs = [_run_once(scenario, i, driver, now, judge, probe_lookup) for i in range(n)]
	return aggregate(scenario, runs)


def _run_once(scenario: Scenario, i: int, driver, now, judge, probe_lookup) -> dict:
	"""Execute one run (chat or probe) and return its scored record."""
	# A fresh session per run keeps economics (scoped by session_id) clean and gives
	# each run an independent conversation / probe target — no cross-run bleed.
	session_id = f"eval-{scenario.name}-{i}"
	if scenario.probe:
		return _run_probe(scenario, i, session_id, now, probe_lookup)

	since = now()
	error = None
	reply = ""
	try:
		reply = driver(scenario, session_id)
	except Exception as exc:  # a crash IS a failed run — record, don't propagate.
		error = f"{type(exc).__name__}: {exc}"
	until = now()

	tool = metrics.tool_selection(
		scenario.profile, since, until, scenario.expect_skills, scenario.forbid_skills
	)
	econ = metrics.economics(session_id, _ms(since, until))
	out = metrics.outcome(reply, scenario.expect_contains)
	quality = _score_quality(scenario, reply, judge, error)

	# Quality gates the pass ONLY when it was actually judged. A skipped quality
	# (rubric present, no judge) leaves the gate on tool + outcome alone.
	quality_gate = True
	if quality is not None and not quality.get("skipped"):
		quality_gate = bool(quality["ok"])

	return {
		"i": i,
		"session_id": session_id,
		"error": error,
		"tool": tool,
		"econ": econ,
		"outcome": out,
		"quality": quality,
		"probe": None,
		"pass": error is None and tool["ok"] and out["ok"] and quality_gate,
	}


def _run_probe(scenario: Scenario, i: int, session_id: str, now, probe_lookup) -> dict:
	"""Execute one probe run: drive a non-chat real path, score from its checks."""
	since = now()
	error = None
	verdict = None
	probe_fn = probe_lookup(scenario.probe)
	if probe_fn is None:
		error = f"LookupError: no probe registered as {scenario.probe!r}"
	else:
		try:
			verdict = probe_fn(scenario, session_id)
		except Exception as exc:
			error = f"{type(exc).__name__}: {exc}"
	until = now()
	econ = metrics.economics(session_id, _ms(since, until))
	passed = error is None and bool(verdict and verdict.get("ok"))
	return {
		"i": i,
		"session_id": session_id,
		"error": error,
		"tool": None,
		"econ": econ,
		"outcome": None,
		"quality": None,
		"probe": verdict,
		"pass": passed,
	}


def _score_quality(scenario: Scenario, reply: str, judge, error) -> dict | None:
	"""Quality verdict for one run, or None when the scenario defines no rubric.

	Returns a *skipped* verdict when a rubric exists but no judge is available, so the
	report can show the gap instead of silently passing.
	"""
	if not scenario.rubric:
		return None
	if error is not None:
		# The turn crashed — there is no reply to judge. The error already fails the
		# run; mark quality skipped-on-error rather than spend a judge call.
		return {"ok": False, "skipped": True, "reason": "turn errored — nothing to judge", "unmet": []}
	if judge is None:
		return {
			"ok": None,
			"skipped": True,
			"reason": "no independent judge provider available",
			"unmet": [],
		}
	# Slice 3: the injected judge is panel-aware — it builds `judge_panel` seats.
	return judge(reply, scenario.rubric, scenario.judge_panel)


def aggregate(scenario: Scenario, runs: list[dict]) -> dict:
	"""Collapse N runs into one verdict — rates + distributions, never a lone number."""
	n = len(runs)
	is_probe = bool(scenario.probe)
	passes = sum(1 for r in runs if r["pass"])
	# tool-selection is a chat-only axis (probe runs carry tool=None).
	tool_ok = sum(1 for r in runs if r.get("tool") and r["tool"]["ok"])
	# Quality is rate-able only over runs that were actually judged (a rubric scenario
	# with no judge contributes a *skipped* verdict, which we report but don't score).
	judged = [r for r in runs if r.get("quality") and not r["quality"].get("skipped")]
	quality_ok = sum(1 for r in judged if r["quality"].get("ok"))
	has_rubric = bool(scenario.rubric)
	return {
		"scenario": scenario.name,
		"tags": list(scenario.tags),
		"note": scenario.note,
		"n": n,
		"is_probe": is_probe,
		"pass_rate": passes / n if n else 0,
		# Meaningless for a probe scenario — None so the report shows "—".
		"tool_ok_rate": None if is_probe else (tool_ok / n if n else 0),
		"has_rubric": has_rubric,
		"quality_ok_rate": (quality_ok / len(judged)) if judged else None,
		# A rubric scenario that never got judged → the quality axis was blocked.
		"quality_unavailable": has_rubric and not judged,
		"latency_ms": metrics.stats([r["econ"]["latency_ms"] for r in runs]),
		"tokens": metrics.stats([r["econ"]["tokens"] for r in runs]),
		"cost_usd_mean": (sum(r["econ"]["cost_usd"] for r in runs) / n) if n else 0,
		"errors": [r["error"] for r in runs if r["error"]],
		"runs": runs,
	}


def run_suite(
	scenarios: list[Scenario], n: int = 3, driver=None, now=None, judge=None, probe_lookup=None
) -> list[dict]:
	"""Run every scenario N× and return the list of aggregate verdicts.

	`judge` is a bound `(reply, rubric, panel_size) -> verdict` callable shared by every
	scenario (resolved once by the caller from independent providers), or None when no
	independent judge is available — rubric scenarios then report a skipped quality
	axis. `probe_lookup` defaults to the real registry. Injecting both here keeps
	`run.py` (which does the DB-backed resolution) separate from this orchestration.
	"""
	return [
		run_scenario(s, n=n, driver=driver, now=now, judge=judge, probe_lookup=probe_lookup)
		for s in scenarios
	]
