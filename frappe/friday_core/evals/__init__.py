# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""Friday Agentic Eval Harness (Design 91) — Slice 1: the real-path wedge.

WHAT THIS IS, IN PLAIN ENGLISH
------------------------------
Unit tests check the *parts* of Friday in isolation — and they keep passing even
when the *agent as a whole* is broken, because each test mocks the very seam it is
supposed to prove. Four real bugs shipped green-unit-tested and were only caught
by hand on a live box (a permission gate silently dropped a tool; the model picked
the wrong tool on vague phrasing; …).

This harness tests Friday the way an agent ACTUALLY runs: it drives the REAL path
— `load_for_profile → permission matrix → run_turn → tool dispatch` — over a small
suite of scenarios, several times each (because an agent is non-deterministic), and
scores every run by reading Friday's OWN audit trail (Execution Log + LLM Usage
Log). Then it writes a Markdown report a human or Claude Code can read.

It is a DEVELOPER INSTRUMENT, not an autonomous self-modifier and not a replacement
for unit tests. The parts still need their unit tests; this pins the agent.

HOW TO RUN
----------
    bench --site <sandbox-site> execute frappe.friday_core.evals.run.run

SAFETY (Design 91 §4 — Isolation)
---------------------------------
Running drives REAL LLM calls and writes Chat Message / Execution Log rows to
whatever site you point it at. NEVER run it against the live/production site — use
a disposable sandbox. `run.run` prints a loud banner naming the site before it
starts so a wrong target is obvious.

MODULE MAP
----------
  scenario.py — the Scenario dataclass (one declarative test case).
  seeds.py    — the version-controlled seed suite (incl. the regression scenarios).
  metrics.py  — pure scorers that read the audit trail (tool-selection, economics,
                outcome) + a tiny stats helper. No agent logic inside.
  runner.py   — drives each scenario N× on the real path and aggregates the runs.
  report.py   — renders the aggregated results to Markdown (distributions, not
                single numbers; a "where + why" failure section).
  run.py      — the `bench execute` entry point.
"""
