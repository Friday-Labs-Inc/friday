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
from .report import render_markdown
from .runner import run_suite
from .seeds import SEEDS


def run(n: int = 3, out_path: str | None = None) -> dict:
	"""Run the seed suite N× on the real path, write + print a Markdown report.

	`n` may arrive as a string from the `bench execute` CLI — coerced to int.
	"""
	n = int(n)
	site = getattr(frappe.local, "site", "") or ""

	banner = (
		"\n" + "=" * 72 + "\n"
		f"  Friday Agentic Eval (Design 91 · Slice 1)\n"
		f"  Site: {site}   ·   {n} run(s) per scenario   ·   {len(SEEDS)} scenarios\n"
		"  Drives the REAL agent path + makes REAL LLM calls on THIS site.\n"
		"  Never run against production — use a disposable sandbox.\n" + "=" * 72 + "\n"
	)
	print(banner)

	# Seed the records some scenarios need (e.g. a known project for
	# project-status-by-name). Idempotent + sandbox-only.
	fixtures = ensure_eval_fixtures()
	print(f"Fixtures ensured: {fixtures}\n")

	results = run_suite(SEEDS, n=n)
	report = render_markdown(results, site=site)

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
		"report_path": out_path,
	}
