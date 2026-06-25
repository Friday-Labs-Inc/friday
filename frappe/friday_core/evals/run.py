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
from .judge import judge_quality, resolve_judge_provider
from .report import render_markdown
from .runner import run_suite
from .seeds import SEEDS


def _profiles_in(scenarios) -> set[str]:
	"""The distinct agent profiles the suite runs as (judge must differ from each)."""
	return {s.profile for s in scenarios}


def run(n: int = 3, out_path: str | None = None, judge_provider: str | None = None) -> dict:
	"""Run the seed suite N× on the real path, write + print a Markdown report.

	`n` may arrive as a string from the `bench execute` CLI — coerced to int.
	`judge_provider` names the independent LLM Provider that scores open-ended quality
	(Slice 2); when omitted, the first active provider that differs from the agent's is
	auto-discovered. If none is available, rubric scenarios report a SKIP'd quality axis.
	"""
	n = int(n)
	site = getattr(frappe.local, "site", "") or ""

	banner = (
		"\n" + "=" * 72 + "\n"
		f"  Friday Agentic Eval (Design 91 · Slices 1-2)\n"
		f"  Site: {site}   ·   {n} run(s) per scenario   ·   {len(SEEDS)} scenarios\n"
		"  Drives the REAL agent path + makes REAL LLM calls on THIS site.\n"
		"  Never run against production — use a disposable sandbox.\n" + "=" * 72 + "\n"
	)
	print(banner)

	# Seed the records some scenarios need (e.g. a known project for
	# project-status-by-name). Idempotent + sandbox-only.
	fixtures = ensure_eval_fixtures()
	print(f"Fixtures ensured: {fixtures}\n")

	# Resolve an INDEPENDENT judge for the quality axis (Slice 2). The judge must run
	# on a different LLM Provider than the agent; resolve against the suite's profile.
	profile = next(iter(_profiles_in(SEEDS)), "Friday")
	resolved = resolve_judge_provider(profile, judge_provider)
	judge_name = resolved.get("name")
	judge_fn = None
	if resolved.get("provider") is not None:
		print(f"Quality judge: {judge_name!r} (independent of agent profile {profile!r})\n")
		judge_fn = _bind_judge(resolved["provider"])
	else:
		print(f"Quality judge UNAVAILABLE — rubric scenarios will SKIP. Reason: {resolved.get('reason')}\n")

	results = run_suite(SEEDS, n=n, judge=judge_fn)
	report = render_markdown(results, site=site, judge_name=judge_name)

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
		"report_path": out_path,
	}


def _bind_judge(provider):
	"""Bind a resolved provider into a `(reply, rubric) -> verdict` callable for the runner."""

	def _judge(reply, rubric):
		return judge_quality(reply, rubric, provider=provider)

	return _judge
