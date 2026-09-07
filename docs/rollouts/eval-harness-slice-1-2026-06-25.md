# Agentic Eval Harness — Slice 1 (2026-06-25)

> Design 91, Slice 1 — "the real-path wedge." Ships the first working slice of the
> harness that tests Friday **the way an agent actually runs**, not the way mocks
> pretend it does.

## The one-paragraph why

Four bugs shipped with **green unit tests** and were only caught by hand on a live
box: a permission gate silently dropped a tool so the agent could never call it; the
model grabbed the wrong tool on vague phrasing; a missing DB extension poisoned a
migrate; a `/stop force` killed nothing. Each unit test passed because it **mocked
the very seam that was broken**. The lesson, stated bluntly in Design 91: *unit
tests verify the parts; they cannot verify the agent.* An agent's behaviour is an
emergent property of the **real path** — `inbound → loader → permission matrix →
run_turn → tool selection → dispatch`. This harness drives that real path on a
sandbox, several times per case, and scores each run from Friday's own audit trail.

## What landed

A new package, `friday_core/evals/`, with six small files:

| File | Job |
|---|---|
| `scenario.py` | The `Scenario` dataclass — one declarative test case (profile + prompt + expected/forbidden tools + tags). Plain frozen data, so scenarios diff in PRs and need no migration. |
| `seeds.py` | The five seed scenarios (below), including the regression cases. |
| `metrics.py` | Pure scorers that **read the audit trail**: `tool_selection` (Execution Log), `economics` (LLM Usage Log), `outcome` (reply substrings), plus a `stats` helper. No agent logic; trivially unit-testable. |
| `runner.py` | Drives each scenario **N times** on the real path (`run_turn`) and aggregates the runs into rates + **distributions** (median + spread), because an agent is non-deterministic and a single number lies. |
| `report.py` | Renders the aggregate to Markdown: a summary table + a **"where + why" failure section** that localizes each failure (errored / never called the expected tool / called a forbidden tool / reply missing a phrase). |
| `run.py` | The `bench execute` entry point. |

## How to run it

```bash
bench --site <sandbox-site> execute friday.friday_core.evals.run.run
# optional: run each scenario 5×  →  ... evals.run.run --kwargs '{"n": 5}'
```

It prints a loud banner naming the site, runs the suite, writes
`sites/<site>/private/files/friday-eval-report.md`, and prints the report.

> **Safety.** A real run makes **real LLM calls** and writes **Chat Message /
> Execution Log** rows to whatever site you point it at. **Never the live site** —
> use a disposable sandbox (Design 91 §4 — Isolation). The banner exists so a wrong
> target is impossible to miss.

## The five seed scenarios

| Scenario | Pins | Bug it would have caught |
|---|---|---|
| `transcript-search-tool` | must call `session_search`, must **not** call `list-records` on a transcript search | #144 (loader dropped the skill) **and** #145 (wrong-tool cue) |
| `list-records-contrast` | a real record listing must use `list-records`, not `session_search` | anti-overcorrection — sharpening one tool's cue can't steal the other's traffic |
| `list-projects-tool` | "list all projects" must reach the new `list-projects` skill | #147 (capability + load) |
| `project-status-by-name` | a named-project status must reach `project-status` | tool disambiguation |
| `smalltalk-no-tool` | a bare greeting must call **no** tool | over-eager-tool guard |

## Honest scope — what Slice 1 does **not** cover

- The other two of the four motivating bugs are **not** run_turn tool-selection
  cases, so they are out of this slice on purpose: the **pgvector migrate
  txn-poison (#132)** is a migrate-gate concern, and **`/stop force` job-id
  (#138)** is a robustness/interrupt case → **Slice 3**. The suite is not "covers
  all four"; it covers the two tool-selection-class bugs (#144/#145) plus #147 and
  the over-eager guard.
- Outcome scoring is a **cheap substring check** here. Open-ended quality (briefs,
  summaries) needs the **LLM-judge → Slice 2**.
- Memory-recall relevance → **Slice 4**. CI gate + baseline diff → **Slice 5**.

## A real, disclosed design constraint (tool-selection scoping)

`LLM Usage Log` carries `session_id`, so **economics is scoped by session** —
exact. `Execution Log` has **no `session_id`** column and a chat turn has no Task,
so **tool-selection is scoped by `agent_profile` + the run's `[since, until]` time
window**. That is exact *only on an isolated sandbox* where this run is the sole
activity for that profile — which is exactly how the harness is meant to run. The
clean future fix is to add `session_id` to Execution Log; until then the sandbox
assumption is the boundary, and it's stated in `metrics.py`, the runner banner, and
here.

## Tests

`friday_core/tests/test_evals.py` — 11 deterministic, DB-free tests (audit reads
faked, agent turn stubbed, clock injected): the scoring math, the time-window
boundary, aggregation, a driver-crash counted as a fail, a wrong-tool run, and the
report's failure section.

> The tests pin the **plumbing**. They deliberately do **not** prove the harness
> catches a real regression — only a sandbox run drives the genuine agent path.
> That is the harness's own thesis applied to itself, and it's written into the
> test module's docstring so nobody mistakes a green test run for a real eval.

## Next

Slice 2 (LLM-judge for open-ended quality) is the natural follow-on; Slice 3
(robustness: interrupt/steer/`/stop force`/cascade) folds in the remaining two of
the four motivating bugs.
