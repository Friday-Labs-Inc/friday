# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The seed scenario suite for Slice 1.

The wedge is TOOL-SELECTION, because that is where the real bugs lived (Design 91).
These five seeds are deliberately small and adversarial:

  * `transcript-search-tool`  — the #144 + #145 regression in one. The agent MUST
    reach `session_search` (so the permission matrix must surface it — #144) and
    MUST NOT grab generic `list-records` on vague "search our past chats" phrasing
    (#145). If either old bug returns, this scenario goes red.
  * `list-records-contrast`   — the inverse, an anti-overcorrection guard: a plain
    "show me the Skill records" request MUST use `list-records`, NOT `session_search`.
    Pairs with the one above so sharpening one tool's cue can't quietly steal the
    other's traffic.
  * `list-projects-tool`      — the #147 capability: "list all projects" must reach
    the new `list-projects` skill (and it must have loaded at all).
  * `project-status-by-name`  — a named-project status must reach `project-status`.
  * `smalltalk-no-tool`       — a bare greeting must call NO tool (over-eager guard).

NOT YET COVERED HERE (honest scope): the other two of the four motivating bugs —
the pgvector migrate txn-poison (#132) and `/stop force` job-id (#138) — are NOT
run_turn tool-selection cases. pgvector is a migrate-gate concern; `/stop force` is
a robustness/interrupt case → Slice 3. Stated plainly so the suite isn't mistaken
for "covers all four".

Outcome (`expect_contains`) is intentionally light here — Slice 1 scores mainly
tool-selection + economics; Slice 2 adds an LLM-judge for open-ended quality.
"""

from __future__ import annotations

from .scenario import Scenario

SEEDS: list[Scenario] = [
	Scenario(
		name="transcript-search-tool",
		profile="Friday",
		prompt="Search our past conversations for what we decided about the pricing model.",
		expect_skills=("session_search",),
		forbid_skills=("list-records",),
		tags=("tool-selection", "regression:#144", "regression:#145"),
		note=(
			"Must reach session_search (matrix must surface it — #144) and must NOT "
			"grab list-records on a transcript search (#145)."
		),
	),
	Scenario(
		name="listing-not-session-search",
		profile="Friday",
		prompt="Show me a list of the Task records in the system.",
		forbid_skills=("session_search",),
		tags=("tool-selection", "anti-overcorrection"),
		note=(
			"A plain record-listing must NOT be routed to session_search — the #145 "
			"cue sharpening must not over-correct. Forbid-only by design: ANY "
			"non-session_search handling passes (list-records, a dedicated skill, or a "
			"direct answer); the point is the transcript tool isn't grabbed for a "
			"non-transcript request. (The first live run showed an over-strict "
			"require-list-records here failed when the agent answered conversationally.)"
		),
	),
	Scenario(
		name="list-projects-tool",
		profile="Friday",
		prompt="List all the projects you're tracking right now.",
		expect_skills=("list-projects",),
		tags=("tool-selection", "regression:#147"),
		note="list-projects must have loaded and be chosen for a list-all (vs project-status, which needs a name).",
	),
	Scenario(
		name="project-status-by-name",
		profile="Friday",
		prompt="What's the current status of the 'Eval Sample Project' project?",
		expect_skills=("project-status",),
		tags=("tool-selection",),
		note=(
			"A named-project status request should reach project-status. Requires the "
			"eval fixture project (fixtures.ensure_eval_fixtures) to exist — the first "
			"live run referenced a project that wasn't on the site, so the agent "
			"correctly list-projects'd to find it instead. With a real target it goes "
			"straight to project-status (a list-projects-then-status path also passes)."
		),
	),
	Scenario(
		name="smalltalk-no-tool",
		profile="Friday",
		prompt="Hey Friday — quick hello. In one line, what are you?",
		forbid_skills=("list-records", "session_search", "list-projects", "project-status"),
		tags=("tool-selection", "no-op"),
		note="A bare greeting must trigger NO tool call (over-eager-tool guard).",
	),
]
