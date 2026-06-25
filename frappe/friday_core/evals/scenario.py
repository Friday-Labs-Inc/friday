# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""One declarative eval case.

A Scenario says: "start the agent like THIS, and here's what a good run looks
like." It carries no logic — the runner drives it and the metrics score it. Keeping
scenarios as plain frozen data means they diff cleanly in PRs and need no migration
(Design 91 §4 — scenarios are version-controlled files, not a doctype).

Fields
------
  name            short, file-safe id (used in session ids + the report).
  profile         the Agent Profile to run as (e.g. "Friday").
  prompt          the inbound user message that seeds the turn.
  expect_skills   skills the agent SHOULD call this turn (tool-selection ✓).
  forbid_skills   skills the agent must NOT call (guards over-eager / wrong-tool).
  expect_contains substrings the final reply should contain (a cheap outcome check
                  for closed answers; too weak for open-ended prose — that's `rubric`).
  rubric          criteria an LLM-judge scores the reply against (Slice 2). Each is a
                  plain sentence; the judge marks every one met / not-met with a
                  reason, and the scenario passes the quality axis only if ALL are met
                  (per-criterion checklist). Empty → no quality scoring for this case.
  rubric_note     optional guidance handed to the judge alongside the rubric (e.g.
                  "be lenient on phrasing, strict on factual claims").
  tags            which axes / regressions this exercises (free-form labels).
  note            a human sentence on what the scenario is really pinning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
	name: str
	profile: str
	prompt: str
	expect_skills: tuple[str, ...] = ()
	forbid_skills: tuple[str, ...] = ()
	expect_contains: tuple[str, ...] = ()
	rubric: tuple[str, ...] = ()
	rubric_note: str = ""
	tags: tuple[str, ...] = ()
	note: str = ""

	def __post_init__(self) -> None:
		# Frozen dataclasses still run __post_init__; we only read here (no mutation),
		# so a plain assertion is enough to catch a malformed seed at import time.
		if self.rubric and not isinstance(self.rubric, tuple):
			raise TypeError(f"Scenario {self.name!r}: rubric must be a tuple of strings")
