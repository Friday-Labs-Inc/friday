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
	from frappe.friday_core.agent_runner.runner import run_turn

	return run_turn(scenario.profile, session_id, scenario.prompt)


def _ms(since, until) -> float:
	"""Milliseconds between two datetimes (the turn's wall-clock latency)."""
	return (until - since).total_seconds() * 1000.0


def run_scenario(scenario: Scenario, n: int = 3, driver=None, now=None) -> dict:
	"""Run one scenario N times on the real path and return its aggregate verdict.

	`driver(scenario, session_id) -> reply` and `now() -> datetime` are injectable
	for tests; their defaults are the real turn + the real clock.
	"""
	driver = driver or _drive_real
	now = now or frappe.utils.now_datetime

	runs = []
	for i in range(n):
		# A fresh session per run keeps economics (scoped by session_id) clean and
		# gives each run an independent conversation — no cross-run memory bleed.
		session_id = f"eval-{scenario.name}-{i}"
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
		runs.append(
			{
				"i": i,
				"session_id": session_id,
				"error": error,
				"tool": tool,
				"econ": econ,
				"outcome": out,
				"pass": error is None and tool["ok"] and out["ok"],
			}
		)

	return aggregate(scenario, runs)


def aggregate(scenario: Scenario, runs: list[dict]) -> dict:
	"""Collapse N runs into one verdict — rates + distributions, never a lone number."""
	n = len(runs)
	passes = sum(1 for r in runs if r["pass"])
	tool_ok = sum(1 for r in runs if r["tool"]["ok"])
	return {
		"scenario": scenario.name,
		"tags": list(scenario.tags),
		"note": scenario.note,
		"n": n,
		"pass_rate": passes / n if n else 0,
		"tool_ok_rate": tool_ok / n if n else 0,
		"latency_ms": metrics.stats([r["econ"]["latency_ms"] for r in runs]),
		"tokens": metrics.stats([r["econ"]["tokens"] for r in runs]),
		"cost_usd_mean": (sum(r["econ"]["cost_usd"] for r in runs) / n) if n else 0,
		"errors": [r["error"] for r in runs if r["error"]],
		"runs": runs,
	}


def run_suite(scenarios: list[Scenario], n: int = 3, driver=None, now=None) -> list[dict]:
	"""Run every scenario N× and return the list of aggregate verdicts."""
	return [run_scenario(s, n=n, driver=driver, now=now) for s in scenarios]
