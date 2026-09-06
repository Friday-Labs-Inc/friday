# Agentic Eval Harness — Slice 3 (2026-06-25)

> Design 91, Slice 3 — "the panel and the probes." Two additions: a multi-judge
> **panel** vote for contested quality calls, and two **non-chat probes** that finally
> bring the last two of the four motivating bugs (#138, #132) under the harness.

## Why a panel

Slice 2's single independent judge is enough for a clear-cut rubric ("did it invent a
fake client name?"). It's shaky for a *contested* one — "is this explanation clear to
a beginner?" is a judgement reasonable people split on, and one judge's opinion is one
sample. Slice 3 lets a scenario request a **panel**: N independent judges each score
the rubric, and a criterion passes by **majority vote**. The scenario opts in with
`judge_panel: N` (default 1 = Slice 2's single judge).

**Where the N judges come from (the locked decision).** A sandbox often has just one
independent provider. So the panel **cycles** the available independent providers
across its seats, and when seats must share a provider, each seat gets a different
**lens** — `strict-literal`, `charitable-intent`, `fact-focused` — appended to its
instructions. So three seats on one provider are three genuinely different
perspectives, not the same call three times. With more independent providers
configured, the seats spread across them. The judge is still **never** the agent's own
provider.

A criterion that a seat omitted or errored on counts as **not-met** for that seat — a
short or broken judge reply can't win a vote by omission. The report shows the split
(e.g. `beginner-friendly [1/3] — too much jargon`).

## Why probes

Two of the four bugs that motivated this whole harness were never chat turns, so
Slice 1–2 couldn't touch them. Slice 3 adds a **probe** scenario kind: instead of
driving `run_turn`, a probe drives a *different* real path and returns its own checks.
A scenario opts in with `probe: "<name>"` (then the chat/judge fields are ignored).

| Probe | Bug | What it drives + asserts |
|---|---|---|
| `force_kill_audit` | **#138** `/stop force` | Creates a live `Executing` Task + an in-flight chat-job row, calls the genuine `force_kill_session`, and scores the **audit trail**: Task → `ForceKilled` with `force_killed_by` / `force_kill_reason` set, the task appears in the force-kill summary, and the job-id transform ran without throwing. |
| `pgvector_no_poison` | **#132** pgvector migrate-gate | Re-runs the real (idempotent) pgvector + FTS schema setup, then proves on **this** Postgres that a deliberately-failing statement inside a savepoint, rolled back, leaves the transaction usable — the exact invariant whose absence poisoned `bench migrate`. Cleanly **skips** on a non-Postgres backend. |

**Honest scope (stated, not hidden):** the `force_kill_audit` probe pins the live
*audit outcome* a unit test can't, but it does not spin up a real RQ worker — so #138's
exact job-id-key regression stays pinned by the mocked `test_stop_force.py`. The
`pgvector` probe proves the savepoint *recovery* on the real backend; where pgvector is
installed the schema DDL simply succeeds, so the savepoint check is what carries the
#132 signal. Each probe cleans up the rows it creates and is **sandbox-only**.

## What landed

| File | Change |
|---|---|
| `scenario.py` | `Scenario` gains `judge_panel: int` (default 1) and `probe: str` (default ""). |
| `judge.py` | Per-seat **lenses**; `run_panel(...)` (vote per criterion by majority, omission = not-met, returns the vote split + a seats summary); `resolve_independent_providers(...)` and `build_panel_seats(...)` (cycle names, one lens per seat, skip a provider that won't build). `judge_quality` takes an optional `lens`. |
| `runner.py` | Branches a `probe` scenario to `_run_probe` (drives the named probe, passes/fails on its `ok`); the judge axis is now **panel-aware** (`judge(reply, rubric, panel_size)`); `aggregate` reports `is_probe` and a `None` tool-rate for probes. |
| `probes.py` *(new)* | The probe registry + the `force_kill_audit` and `pgvector_no_poison` probes. |
| `report.py` | A probe's failed **checks** render in the "where + why" section; the Tool-sel cell is `—` for a probe; panel failures show the **vote split**. |
| `seeds.py` | Three new seeds: `explain-clearly-panel` (a contested 3-judge panel) + the two probe seeds. |
| `run.py` | Resolves independent provider(s), binds a panel-aware judge that builds seats per call, threads probe scenarios (no LLM), Slice 3 banner/title. |

`tests/test_evals.py`: **33 → 58** DB-free / LLM-free cases — panel voting (majority /
minority / omission / single-seat / no-seats), seat building (cycle + lens + skip
unbuildable), independent-provider resolution, both probes (mocked frappe + a mocked
`force_kill_session`), the runner's probe + panel branches, and the new report
rendering. All green, ruff clean.

## Migrate / verification

**No DocType / patch / hook change.** `scenario.py` adds *dataclass* fields (not schema);
the probes *drive* existing doctypes (Task, Chat Message, Dispatcher Event) but define
nothing — so `bench migrate` is a no-op. Verified the realistic risks for this change:
the full suite is green, imports are clean, the report renders the probe + panel rows
end-to-end, and the `force_kill_audit` probe targets the **real** `Task.originating_session`
field that `collect_active_subtree` queries (so it will actually find its task live, not
just in the mocked test).

## Hardening (stability pass)

A judge is an LLM, so the scoring must not trust the judge to behave. The aggregation
is therefore **anchored on the rubric, not on what the judge echoed**, matched by
normalised text (case + punctuation insensitive) — never by array position:

- **Reordering** — a judge that returns criteria out of order is still scored against
  the right criterion (text match), so a panel vote can't be misattributed.
- **Count-gaming / duplication** — returning the right *number* of items can't pass a
  criterion the judge never actually addressed (no index fallback: two copies of
  criterion A and no B → B is **not-met**, never silently matched to the second A).
- **Invented criteria** — items that match no rubric criterion are ignored as noise.
- **Truncation / omission** — an unmatched rubric criterion is not-met (can't pass by
  omission), in both the single judge and the panel.
- **Panel reasons** — a failed criterion surfaces a *dissenting* (not-met) reason in
  the report, not a stray supporting one, so the "why" line is actually informative.

`judge_quality` now also passes its optional `model` through to the provider (was an
unused parameter). Seven targeted tests pin each of these (65 total, all DB-free).

## How to run it

```bash
# A panel benefits from 2+ independent providers, but runs on one (shared provider,
# distinct lenses). Probes need no judge and run regardless.
bench --site <sandbox-site> execute friday.friday_core.evals.run.run

# name the judge provider(s) explicitly (still must differ from the agent's):
bench --site <sandbox-site> execute friday.friday_core.evals.run.run --kwargs '{"judge_provider": "Claude"}'
```

Sandbox-only: chat scenarios drive real LLM calls (now including the panel's), and the
probes write rows / run DDL. The report gains a vote split on panel failures, a probe
checks breakdown, and the Slice 3 banner.
