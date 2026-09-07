# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Scorers that read Friday's own audit trail — pure, no agent logic.

The leverage of this harness (Design 91 §"already observable"): every tool call,
permission decision, and token spend is already a row. So scoring is mostly
*extraction*. Each function here reads rows for one run and returns a small verdict
dict. They never write, never call an LLM, and never raise on a clean run — so they
are trivial to unit-test with a fake `frappe.get_all`.

A NOTE ON SCOPING (a real, disclosed constraint)
------------------------------------------------
`LLM Usage Log` carries `session_id`, so economics is scoped by session — exact.
`Execution Log`, however, has NO `session_id` column (fields: agent_profile, skill,
task, status, duration_ms, tokens_used, …). A chat turn has no Task either. So
tool-selection is scoped by **agent_profile + a [since, until] time window** — the
run's own wall-clock window. That is exact ONLY on an isolated sandbox where this
run is the sole activity for that profile (Design 91 §4 — Isolation). A clean future
improvement is to add `session_id` to Execution Log; until then the sandbox
assumption is the boundary, and it is stated loudly in the runner + report.
"""

from __future__ import annotations

import frappe


def tool_selection(
	profile: str,
	since,
	until,
	expect_skills: tuple[str, ...],
	forbid_skills: tuple[str, ...],
) -> dict:
	"""Did the agent call the right tools (and avoid the wrong ones) this run?

	Reads Execution Log rows for `profile` whose `creation` falls in the run's
	[since, until] window. `since`/`until` are datetimes from the runner's clock.
	"""
	rows = frappe.get_all(
		"Execution Log",
		filters={"agent_profile": profile, "creation": [">=", since]},
		fields=["skill", "status", "creation"],
		order_by="creation asc",
	)
	# Upper-bound in Python: a `between` filter's inclusivity varies by backend, and
	# the window is a heuristic anyway — keep the boundary logic here and obvious.
	called = [r["skill"] for r in rows if r.get("creation") is None or r["creation"] <= until]
	called_set = set(called)
	missing = [s for s in expect_skills if s not in called_set]
	forbidden_hit = [s for s in forbid_skills if s in called_set]
	return {
		"called": called,
		"missing": missing,
		"forbidden_hit": forbidden_hit,
		"ok": not missing and not forbidden_hit,
	}


def economics(session_id: str, latency_ms: float) -> dict:
	"""Token + dollar + latency cost of one run, scoped by session_id (exact)."""
	rows = frappe.get_all(
		"LLM Usage Log",
		filters={"session_id": session_id},
		fields=["total_tokens", "estimated_cost"],
	)
	tokens = sum(int(r.get("total_tokens") or 0) for r in rows)
	cost = sum(float(r.get("estimated_cost") or 0) for r in rows)
	return {
		"llm_calls": len(rows),
		"tokens": tokens,
		"cost_usd": cost,
		"latency_ms": round(float(latency_ms), 1),
	}


def outcome(reply: str, expect_contains: tuple[str, ...]) -> dict:
	"""Cheap deterministic outcome check: does the reply contain each phrase?

	Case-insensitive substring match. Slice 2 layers an LLM-judge on top for
	open-ended quality where substrings aren't enough.
	"""
	text = (reply or "").lower()
	missing = [s for s in expect_contains if s.lower() not in text]
	return {"reply_chars": len(reply or ""), "missing": missing, "ok": not missing}


def stats(values: list) -> dict:
	"""Median / min / max / mean over a run's values — the variance picture.

	Median (not mean) is the headline because an agent's latency/tokens are skewed:
	one slow retry shouldn't move the typical-case number.
	"""
	if not values:
		return {"median": 0, "min": 0, "max": 0, "mean": 0}
	s = sorted(values)
	n = len(s)
	median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
	return {"median": median, "min": s[0], "max": s[-1], "mean": sum(s) / n}
