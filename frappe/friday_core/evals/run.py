# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The `bench execute` entry point for the eval harness.

    bench --site <sandbox-site> execute frappe.friday_core.evals.run.run

It runs the seed suite on the REAL agent path N times each, scores every run from
the audit trail, writes a Markdown report into the site's private files, and prints
it. Returns a small summary dict so a caller (or CI, later) can assert on it.

SAFETY: this drives real LLM calls and writes Chat Message / Execution Log rows to
the current site. It prints a loud banner naming the site first. NEVER point it at
the live/production site — use a disposable sandbox (Design 91 §4 — Isolation).
"""

from __future__ import annotations

import frappe

from .fixtures import ensure_eval_fixtures
from .judge import build_panel_seats, resolve_independent_providers, run_panel
from .report import render_markdown
from .runner import run_suite
from .seeds import SEEDS

_TITLE = "Friday Agentic Eval — Slice 3"


def _profiles_in(scenarios) -> set[str]:
	"""The distinct agent profiles the suite runs as (judge must differ from each)."""
	return {s.profile for s in scenarios}


def run(n: int = 3, out_path: str | None = None, judge_provider: str | None = None) -> dict:
	"""Run the seed suite N× on the real path, write + print a Markdown report.

	`n` may arrive as a string from the `bench execute` CLI — coerced to int.
	`judge_provider` names the independent LLM Provider(s) that score open-ended quality
	(Slice 2/3); when omitted, every active provider that differs from the agent's is a
	candidate, cycled across a scenario's panel seats. If none is available, rubric
	scenarios report a SKIP'd quality axis. Probe scenarios (Slice 3) make no LLM call
	and run regardless.
	"""
	n = int(n)
	site = getattr(frappe.local, "site", "") or ""

	banner = (
		"\n" + "=" * 72 + "\n"
		f"  Friday Agentic Eval (Design 91 · Slices 1-3)\n"
		f"  Site: {site}   ·   {n} run(s) per scenario   ·   {len(SEEDS)} scenarios\n"
		"  Drives the REAL agent path + makes REAL LLM calls on THIS site.\n"
		"  Never run against production — use a disposable sandbox.\n" + "=" * 72 + "\n"
	)
	print(banner)

	# Seed the records some scenarios need (e.g. a known project for
	# project-status-by-name). Idempotent + sandbox-only.
	fixtures = ensure_eval_fixtures()
	print(f"Fixtures ensured: {fixtures}\n")

	# Resolve the INDEPENDENT judge provider(s) for the quality axis (Slice 2/3). A
	# judge must run on a different LLM Provider than the agent; a panel cycles all of
	# them across its seats. Resolve against the suite's profile.
	profile = next(iter(_profiles_in(SEEDS)), "Friday")
	resolved = resolve_independent_providers(profile, judge_provider)
	names = resolved.get("names", [])
	# Build one seat to confirm at least one provider actually constructs; if not, the
	# quality axis is unavailable (skipped), matching the "no independent judge" path —
	# never a hard fail just because a named provider can't be built.
	judge_name = None
	judge_fn = None
	if names and build_panel_seats(names, 1):
		judge_name = ", ".join(names)
		print(f"Quality judge provider(s): {judge_name} (independent of agent profile {profile!r})\n")
		judge_fn = _bind_panel_judge(names)
	else:
		reason = resolved.get("reason") or "no independent judge provider could be built"
		print(f"Quality judge UNAVAILABLE — rubric scenarios will SKIP. Reason: {reason}\n")

	results = run_suite(SEEDS, n=n, judge=judge_fn)
	report = render_markdown(results, title=_TITLE, site=site, judge_name=judge_name)

	out_path = out_path or frappe.get_site_path("private", "files", "friday-eval-report.md")
	with open(out_path, "w") as fh:
		fh.write(report)

	print(report)
	print(f"\n✓ Report written to {out_path}")

	return {
		"site": site,
		"scenarios": len(results),
		"runs_each": n,
		"fully_passing": sum(1 for r in results if r["pass_rate"] == 1.0),
		"judge_provider": judge_name,
		"quality_blocked": sum(1 for r in results if r.get("quality_unavailable")),
		"probe_scenarios": sum(1 for r in results if r.get("is_probe")),
		"report_path": out_path,
	}


def _bind_panel_judge(names: list[str]):
	"""Bind the independent provider names into a `(reply, rubric, panel_size) -> verdict`.

	Per call it builds `panel_size` seats (cycling `names`, one lens each) and votes via
	`run_panel`. `panel_size=1` collapses to a single-judge verdict (Slice 2 behaviour).
	"""

	def _judge(reply, rubric, panel_size):
		seats = build_panel_seats(names, panel_size)
		return run_panel(reply, rubric, seats)

	return _judge
