# Agentic Eval Harness — Slice 2 (2026-06-25)

> Design 91, Slice 2 — "the quality judge." Slice 1 proved Friday picks the right
> *tool*; Slice 2 proves Friday writes a *good answer* when there is no right tool —
> graded by an **independent** model, not by Friday grading itself.

## The one-paragraph why

Slice 1 scored two things well: **tool-selection** (did the agent reach the right
skill, from the Execution Log) and **economics** (tokens + dollars, from the LLM
Usage Log). For an open-ended reply — a self-introduction, a brief, a summary —
neither helps. The only Slice 1 outcome check was `expect_contains`: does the reply
contain a substring? That is too weak. A good summary can omit any particular word;
a bad one can contain it. So Slice 2 adds an **LLM-as-judge**: a scenario carries a
`rubric` (plain-sentence criteria), and a separate model marks each criterion
met / not-met with a reason. The scenario passes the quality axis only if **every**
criterion is met (a per-criterion checklist, so a failure says *which* criterion and
*why* — the same "where + why" credit-assignment Slice 1 brought to tools).

## The one locked rule: the judge must be independent

Letting the agent grade its own work bakes in its blind spots and an optimistic
bias. So the judge **must** run on a *different* `LLM Provider` row than the agent
ran on. `resolve_judge_provider`:

1. honors an explicitly named judge provider — but still rejects it if it is the
   same row the agent uses (not independent);
2. otherwise **auto-discovers** the first active provider whose name differs from
   the agent's;
3. if none exists, the quality axis is **blocked** — every rubric scenario reports a
   visible `SKIP`, the report prints a loud banner telling you to configure a second
   provider, and the run does **not** silently pass and does **not** hard-fail.

That last point is the whole meaning of "require a separate independent judge
provider": no second model → no quality score, and the report says so.

## What landed

No new files moved the needle on the schema — Slice 2 is pure Python plus one new
seed. (No DocType, no patch, no hook: `bench migrate` is a no-op for this change.)

| File | Change |
|---|---|
| `scenario.py` | `Scenario` gains `rubric: tuple[str, ...]` + `rubric_note`. Empty rubric → no quality scoring (unchanged behaviour for Slice 1 seeds). |
| `judge.py` *(new)* | `judge_quality(reply, rubric, *, provider)` — calls the provider tool-less, parses strict JSON (robust to code-fences / chatty wrappers), and **never raises**: a transport error or unparseable reply becomes a quality FAIL with a reason. `resolve_judge_provider(...)` enforces the independence rule above. |
| `runner.py` | Threads an injectable `judge` callable. Quality gates the overall pass **only when actually judged**; a skipped quality (no judge) leaves the pass on tool + outcome and flags `quality_unavailable`. `aggregate` adds `quality_ok_rate` + `quality_unavailable`. |
| `report.py` | New **Quality** column (`%`, `SKIP`, or `—`), a judge-provider line, the blocked banner, and per-criterion `✗ criterion — reason` lines in the failures section. |
| `seeds.py` | One new open-ended seed, `self-intro-quality`: a 2–3 sentence self-introduction graded against a 3-point rubric (on-topic / concise / no fabricated specifics). Dogfoods the judge on every real run. |
| `run.py` | Resolves the judge once (optional `judge_provider` kwarg), prints which provider judges (or that quality is unavailable), and passes the judge name into the report. |

`tests/test_evals.py` grows from 19 to 33 cases — all DB-free and LLM-free: the
judge is exercised with a fake provider, provider resolution is exercised with
mocked rows, and the runner's quality gate is exercised with an injected judge.

## Why this is the right shape (and what it is not)

- **The judge is injectable**, exactly like Slice 1's `driver` and `now`. That keeps
  the unit tests deterministic and offline; the *real* judge only runs on a sandbox
  eval, where it makes a real LLM call.
- **The judge never crashes a run.** One flaky judge response degrades to a single
  quality FAIL with a reason, not a dead suite.
- **A truncated judge reply can't pass by omission.** If the judge returns fewer
  verdicts than there are criteria, the shortfall counts as not-met.
- **No production schema change.** The judge provider is resolved by name through the
  existing `get_provider_by_name` (the same mechanism the compression aux-model
  uses), so the eval harness — a dev instrument — stays out of the production
  `Agent Settings` schema.

What it is *not*: a general benchmark, and not a panel of judges. A single
independent judge per run is the Slice 2 scope; a multi-judge vote (for contested,
high-stakes rubrics) is a natural Slice 3 option.

## How to run it

```bash
# Needs TWO active LLM Providers on the sandbox: the agent's, and a different one to
# judge. With only one, rubric scenarios report SKIP (everything else still runs).
bench --site <sandbox-site> execute frappe.friday_core.evals.run.run

# name the judge explicitly (must differ from the agent's provider):
bench --site <sandbox-site> execute frappe.friday_core.evals.run.run --kwargs '{"judge_provider": "Claude"}'
```

Sandbox-only, as in Slice 1: it drives the real agent path and makes real LLM calls
(now including the judge's). The report it writes gains the Quality column and, when
no independent judge is configured, the blocked banner.
