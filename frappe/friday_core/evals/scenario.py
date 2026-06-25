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
  expect_contains substrings the final reply should contain (a cheap outcome check;
                  Slice 2 adds an LLM-judge for open-ended quality).
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
	tags: tuple[str, ...] = ()
	note: str = ""
