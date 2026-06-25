# Design 91 — Agentic Eval Harness (proposal)

> **Status:** PROPOSAL — awaiting decision. A first draft to react to, with the
> design forks pre-decided (recommendations, all reversible). Triggered by a
> recurring, costly pattern: **green unit tests that hide real agent failures.**

## Why — the pattern that justifies this

Over one program of work, **four** issues shipped with passing unit tests and were
only caught by adversarial testing **on a real deployment**:

| Bug | Unit test said | Reality |
|---|---|---|
| pgvector DDL txn-poison | ✅ green | a missing extension poisoned the whole migrate |
| `/stop force` job-id | ✅ green | SIGTERM hit a non-existent rq key — killed nothing |
| `session_search` loader gate | ✅ green | the permission matrix dropped the skill — agent could never call it |
| `session_search` vs `list-records` cue | ✅ green | the model picked the wrong tool on vague phrasing |

Every one passed because the test **mocked the seam under test** (the redis call,
the rq id, the loader, the model's tool choice). The lesson is blunt: **unit tests
verify the parts; they cannot verify the agent.** An agentic system is
non-deterministic, multi-step, tool-using, and governed — its behavior is an
emergent property of the *real* path: `inbound → loader → permission matrix →
run_turn → tool selection → dispatch → memory → compression`.

This harness tests Friday **the way an agent actually runs** — the real path, on a
sandbox, scored across the dimensions that matter — and reports where the core is
weak so Claude Code can fix it with evidence instead of vibes.

**It is a developer instrument, not an autonomous self-modifier.** The loop is:
*Claude Code builds → the harness measures → Claude Code learns + improves → the
harness re-measures (regression-gated).* The human + Claude Code are the
improvers; the harness is the microscope.

## What it is — four stages

```
Scenarios → Runner (sandbox, real path, N×) → Scorer (trace + judge) → Report + Baseline diff
```

1. **Scenarios** — declarative test cases (version-controlled files). A scenario =
   `{ seed, expectations, rubric, tags }`:
   - **seed** — how to start the agent: a profile + an inbound message (or a Task,
     or a Project), e.g. *"as Friday, 'search our past conversations for X'"*.
   - **expectations** — deterministic asserts on the outcome (a row created, a
     specific skill called, a file produced, a gate resolved).
   - **rubric** — the criteria an LLM-judge scores open-ended output against.
   - **tags** — which axes it exercises (tool-use, memory, robustness, …).
2. **Runner** — drives each scenario through the **REAL** path (`run_turn` / the
   gateway pipeline / the loader+matrix — no mocks) on an **isolated sandbox
   site**, capturing the full trace. Runs each scenario **N times** to measure
   variance (agentic ≠ deterministic).
3. **Scorer** — reads Friday's **own audit trail** for each run and computes
   per-axis scores (see taxonomy). Mostly *extraction*, because Friday is already
   deeply observable.
4. **Report + Baseline** — aggregates across runs into a report (per-scenario,
   per-axis, **distributions** not single numbers) + a **diff vs the last accepted
   baseline** (the regression gate). Output: a Markdown/HTML report Claude Code
   reads; later, a CI check.

## The leverage: Friday is already observable

This is buildable, not sci-fi, because the signal already flows. The Scorer
mostly **reads existing rows**:

| Axis | What it measures | Signal it reads |
|---|---|---|
| **Outcome** | task success · output quality | deterministic asserts + an LLM-judge on the result |
| **Tool use** | right tool? wasted/denied calls? | `Execution Log`, `Permission Decision Log` |
| **Reasoning** | loop discipline, recovery, thrash | ReAct iterations, retries, empty-response retries |
| **Memory** | recall *relevance* — surfaced the right fact? | the recall block vs. the fact the scenario needed |
| **Robustness** | interrupt/steer/cascade, compression fidelity | gateway events, `Compaction Summary` |
| **Governance** | permission/approval correct, **no leak** | `Permission Decision Log`, the approval gate |
| **Economics** | tokens · $ · latency · retries | `LLM Usage Log` |
| **Reliability** | **variance across N runs** — flakiness | re-run the scenario, measure spread |

## The hard problems (designed-for, not hand-waved)

1. **Non-determinism** — same input, different path. → run N, report
   **distributions** (median + spread), never a single pass/fail.
2. **Credit assignment** — when a multi-step run fails, *which* component? → the
   full trace + per-axis scoring **localizes** the failure (e.g. "loader dropped
   the tool" vs "model picked wrong" vs "tool errored").
3. **Judge reliability** — an LLM-judge is itself noisy. → a strict rubric, and a
   self-consistency / multi-judge vote for the scores that gate decisions.
4. **Isolation** — `bench run-tests` mutates live data (it once deactivated the
   live MiniMax provider). → a **disposable sandbox site** (or transactional
   rollback per run). **Never the live site.**

## Slice plan (incremental — the wedge first)

- **Slice 1 — the real-path wedge.** Runner over a small scenario suite on a
  sandbox, driving the *actual* `loader → matrix → run_turn → dispatch`. Score
  **Outcome (success) + Tool-selection-correctness + Economics (cost/latency)**,
  with **N-run variance**. Tool-selection is first *because that's where the bugs
  lived* — the harness's whole reason is "test what mocks hide." Output: a
  Markdown report. On-demand.
- **Slice 2 — quality judge.** Add the LLM-judge + rubric scoring for open-ended
  outcomes (briefs, summaries) where pass/fail isn't enough.
- **Slice 3 — robustness.** Scenarios that interrupt/steer/`/stop force`/cascade a
  running turn and verify the right end-state; long-context compression fidelity.
- **Slice 4 — memory.** Recall-relevance scenarios (seed a fact, ask a question
  whose answer needs it, score whether recall surfaced it).
- **Slice 5 — CI gate + baseline.** Promote a curated, fast subset to a CI check
  that blocks a PR regressing success/cost beyond the accepted baseline.

## Decisions (pre-made for the draft — change any)

1. **Where it lives → in the Friday repo** (`friday_core/evals/`). It must drive
   the real code and read the real audit trail; a standalone tool would duplicate
   the substrate and drift. It versions + CIs alongside what it tests.
2. **First axis → tool-selection + outcome + economics** (Slice 1 above), because
   that's the demonstrated pain. Quality/robustness/memory layer on after.
3. **Run cadence → both, staged.** Primary: an **on-demand dev instrument** Claude
   Code runs while building. Then promote a subset to a **CI gate** once a
   baseline exists.
4. **Scenarios → version-controlled files** (YAML/Python) for v1, not a doctype —
   they live with the code, diff in PRs, and need no migration. (A doctype-backed
   UI for non-devs is a later option.)
5. **Sandbox → a dedicated disposable test site** seeded from a fixture, reset
   between runs. Not the live site, ever.
6. **Judge model → the configured provider** (or a stronger judge model if set),
   with the rubric + self-consistency for gating scores.

## Definition of a first slice landing

- A `friday_core/evals/` harness: a scenario format, a runner that drives the real
  path on a sandbox N×, a scorer reading the audit trail, a Markdown report.
- 5–8 seed scenarios, including **regression scenarios for the 4 bugs above**
  (so the harness would have caught each).
- Run via `bench … execute friday_core.evals.run` (or a `bench friday eval`
  command); output a report + a baseline file.
- Two-layer docs + the usual migrate/test gates.

## What this is NOT (scope guard)

- Not autonomous self-modification (Claude Code + human are the improvers).
- Not a replacement for unit tests (those still pin the parts; this pins the
  *agent*).
- Not a live-traffic monitor (that's observability/D72); this is an *offline eval*
  on curated scenarios.

---

*Proposal. Nothing is built until the forks above are confirmed (or amended).*
