# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Render aggregated eval verdicts to Markdown.

Sections:
  1. A summary table — one row per scenario with pass-rate, tool-selection rate, an
     open-ended QUALITY rate (Slice 2: the share of judged runs that met every rubric
     criterion, or `SKIP` when no independent judge was available, or `—` for a
     scenario with no rubric), and the economics *distributions* (median latency /
     tokens, mean $/run). Rates, not single pass/fail, because the point is variance.
  2. A "where + why" failures section — for any scenario that didn't fully pass, every
     failing run is broken down into *why* (errored / wrong tool / missing phrase /
     unmet rubric criterion + the judge's reason) and *what it actually called*. This
     is the credit-assignment view (Design 91 §hard-problem 2): it localizes the
     failure instead of just saying "fail".

When any rubric scenario could not be judged, a loud banner names the gap and how to
fix it — the quality axis is *blocked*, never silently passed (Slice 2's locked
"require a separate independent judge provider" decision).
"""

from __future__ import annotations


def _quality_cell(r: dict) -> str:
	"""The Quality column for one scenario row."""
	if not r.get("has_rubric"):
		return "—"
	if r.get("quality_unavailable"):
		return "SKIP"
	rate = r.get("quality_ok_rate")
	return f"{rate:.0%}" if rate is not None else "SKIP"


def _tool_cell(r: dict) -> str:
	"""The Tool-sel column — '—' for a probe scenario (no tool axis)."""
	rate = r.get("tool_ok_rate")
	return "—" if rate is None else f"{rate:.0%}"


def render_markdown(
	results: list[dict],
	*,
	title: str = "Friday Agentic Eval — Slice 2",
	site: str = "",
	judge_name: str | None = None,
) -> str:
	n = results[0]["n"] if results else 0
	total = len(results)
	fully_passing = sum(1 for r in results if r["pass_rate"] == 1.0)
	blocked = [r for r in results if r.get("quality_unavailable")]

	lines = [f"# {title}", ""]
	if site:
		lines.append(
			f"_Site: `{site}` · {n} run(s) per scenario · real path (loader → matrix → run_turn → dispatch)._"
		)
		if judge_name:
			lines.append(f"_Quality judge: `{judge_name}` (independent provider — not the agent's)._")
		lines.append("")
	lines.append(f"**{fully_passing}/{total} scenarios fully passing.**")
	lines.append("")

	if blocked:
		names = ", ".join(f"`{r['scenario']}`" for r in blocked)
		lines += [
			f"> ⚠️ **Quality axis blocked for {len(blocked)} scenario(s)** ({names}): no "
			"independent judge provider was available, so their rubric was not scored. "
			"Configure a second active `LLM Provider` (different from the agent's) to "
			"enable open-ended quality scoring.",
			"",
		]

	lines.append("| Scenario | Pass | Tool-sel | Quality | Latency p50 (ms) | Tokens p50 | $/run | Tags |")
	lines.append("|---|---|---|---|---|---|---|---|")
	for r in results:
		lines.append(
			"| {s} | {p:.0%} | {t} | {q} | {lat:.0f} | {tok:.0f} | {cost:.4f} | {tags} |".format(
				s=r["scenario"],
				p=r["pass_rate"],
				t=_tool_cell(r),
				q=_quality_cell(r),
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
				probe = run.get("probe")
				if run.get("tool") is None and (probe is not None or run["error"]):
					# Probe run: report the failed checks (the probe's own audit view).
					why = []
					if run["error"]:
						why.append(f"errored ({run['error']})")
					failed = [c for c in (probe or {}).get("checks", []) if not c.get("ok")]
					if failed:
						why.append(f"{len(failed)} check(s) failed")
					lines.append(f"- **run {run['i']}**: " + "; ".join(why or ["unknown"]))
					for c in failed:
						lines.append(f"  - ✗ {c.get('name', '')} — {c.get('detail', '')}")
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
				quality = run.get("quality") or {}
				if quality.get("error"):
					why.append(f"judge error ({quality['error']})")
				elif quality.get("unmet") and not quality.get("skipped"):
					why.append(f"unmet rubric {quality['unmet']}")
				lines.append(f"- **run {run['i']}**: " + "; ".join(why or ["unknown"]))
				lines.append(f"  - tools actually called: `{run['tool']['called'] or '[]'}`")
				# Per-criterion judge reasons — the open-ended credit-assignment view.
				# For a panel, show the vote split (e.g. "1/3") alongside the reason.
				for crit in quality.get("criteria", []):
					if not crit.get("met"):
						votes = f" [{crit['votes']}]" if crit.get("votes") else ""
						lines.append(f"  - ✗ _{crit['criterion']}_{votes} — {crit.get('reason', '')}")
			lines.append("")
	else:
		lines += ["", "_No failures — every scenario passed every run._", ""]

	return "\n".join(lines)
