# ADR-0010 — CI blocks on a shrink-only test ratchet

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0002, ADR-0012

## Context

CI cannot fail. `.github/workflows/tests.yml` runs
`bench --site test-friday run-tests --app frappe --module frappe.friday_core.tests`
— and `friday_core/tests/__init__.py` is empty, so that module collects **zero
tests**. Every step in the workflow also ends in `|| true`, so even a real
failure is swallowed. It also fetches `--branch slice-6/first-skill`, a branch
that no longer matters.

108 test modules and 22,571 lines of test code go unexecuted on every pull
request. `pyproject.toml:167-176` additionally excludes `llm/provider.py` and
two other files from ruff **by name**.

The cost is documented: issue #232 records a misdiagnosis that "sent me down
three wrong causes". Issues #211–#214 closed eight red modules as "stale tests"
without anyone running them.

Issue #210 already specified the fix and was closed as COMPLETED; the
implementation exists only on the un-forked line.

## Decision

**Every pull request runs every test module, and CI blocks.**

- A red module must be listed in `ci/known-red.txt` with a reason and an issue.
- A listed module that turns **green** also fails the build, until it is removed
  from the list. The list only shrinks.
- No `|| true` anywhere in the test job.
- Harvest `ci/run_tests.py` and the ratchet from the archived un-forked line
  rather than rewriting them.

Packages whose scope verdict is still pending simply sit on the known-red list
until the re-baseline rules on them. No special-casing.

## Consequences

- The first green build requires an honest initial `known-red.txt`. Producing it
  is part of the re-baseline, not a prerequisite for it.
- The ruff exclusions in `pyproject.toml` are re-examined; an exclusion needs a
  reason that survives review.
- "Known-red" is a debt register with names on it, not a permanent parking bay.

## Evidence

- `.github/workflows/tests.yml:68` and every preceding step.
- `frappe/friday_core/tests/__init__.py` — empty.
- `pyproject.toml:167-176` — ruff excludes `cli/setup.py`, `llm/provider.py`,
  `tests/test_llm_provider.py`.
- `ci/` in this tree contains only `__pycache__`; the real gate is on the
  archived line.
