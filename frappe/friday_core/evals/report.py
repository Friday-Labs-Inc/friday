# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Render aggregated eval verdicts to Markdown.

Two sections:
  1. A summary table — one row per scenario with pass-rate, tool-selection rate, and
     the economics *distributions* (median latency / tokens, mean $/run). Rates, not
     single pass/fail, because the whole point is to show variance.
  2. A "where + why" failures section — for any scenario that didn't fully pass,
     every failing run is broken down into *why* (errored / never called the
     expected tool / called a forbidden tool / reply missing a phrase) and *what it
     actually called*. This is the credit-assignment view (Design 91 §hard-problem 2):
     it localizes the failure instead of just saying "fail".
"""

from __future__ import annotations


def render_markdown(
	results: list[dict], *, title: str = "Friday Agentic Eval — Slice 1", site: str = ""
) -> str:
	n = results[0]["n"] if results else 0
	total = len(results)
	fully_passing = sum(1 for r in results if r["pass_rate"] == 1.0)

	lines = [f"# {title}", ""]
	if site:
		lines.append(
			f"_Site: `{site}` · {n} run(s) per scenario · real path (loader → matrix → run_turn → dispatch)._"
		)
		lines.append("")
	lines.append(f"**{fully_passing}/{total} scenarios fully passing.**")
	lines.append("")
	lines.append("| Scenario | Pass | Tool-sel | Latency p50 (ms) | Tokens p50 | $/run | Tags |")
	lines.append("|---|---|---|---|---|---|---|")
	for r in results:
		lines.append(
			"| {s} | {p:.0%} | {t:.0%} | {lat:.0f} | {tok:.0f} | {cost:.4f} | {tags} |".format(
				s=r["scenario"],
				p=r["pass_rate"],
				t=r["tool_ok_rate"],
				lat=r["latency_ms"]["median"],
				tok=r["tokens"]["median"],
				cost=r["cost_usd_mean"],
				tags=", ".join(r["tags"]),
			)
		)

	fails = [r for r in results if r["pass_rate"] < 1.0]
	if fails:
		lines += ["", "## Failures — where + why", ""]
		for r in fails:
			lines.append(f"### `{r['scenario']}` — {r['pass_rate']:.0%} pass")
			if r.get("note"):
				lines.append(f"_{r['note']}_")
			for run in r["runs"]:
				if run["pass"]:
					continue
				why = []
				if run["error"]:
					why.append(f"errored ({run['error']})")
				if run["tool"]["missing"]:
					why.append(f"never called {run['tool']['missing']}")
				if run["tool"]["forbidden_hit"]:
					why.append(f"called forbidden {run['tool']['forbidden_hit']}")
				if run["outcome"]["missing"]:
					why.append(f"reply missing {run['outcome']['missing']}")
				lines.append(f"- **run {run['i']}**: " + "; ".join(why or ["unknown"]))
				lines.append(f"  - tools actually called: `{run['tool']['called'] or '[]'}`")
			lines.append("")
	else:
		lines += ["", "_No failures — every scenario passed every run._", ""]

	return "\n".join(lines)
