# ADR-0002 — Keep the hard fork of Frappe

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0001, ADR-0003, ADR-0007

## Context

The repository had split into two incompatible architectures with the same
name. `origin/main` carried an un-fork (#209) turning Friday into a standalone
app installable beside ERPNext, plus a breaking rename (#229) and a working CI
gate. `origin/develop` stayed a hard fork of Frappe and carried the seven seams
(#230) and actor context (#231) — 134 lines inside Frappe core that cannot
exist outside a fork.

Ten commits on one side, four on the other, built the same week. Neither had
ever been run end to end. The same vocabulary ratchet was implemented twice,
independently, on both lines.

The un-fork's argument was adoptability: a hard fork asks other people to
replace their Frappe with yours. That argument does not apply — see ADR-0003.

## Decision

**`develop` is canonical. The fork stays.** GitHub's default branch already
points at it.

The un-forked line is harvested and archived: take `ci/run_tests.py` and the
shrink-only known-red ratchet, take #229's `Agent Run` / `Agent Job` /
`Agent Blocker` renames, then tag the tip as `archive/app-era` and stop using
it. No force-push, no default-branch surgery.

## Consequences

- Upstream Frappe is now a permanent maintenance obligation. See ADR-0007.
- Actor context (Design 99) survives, and its fate is decided on evidence during
  the re-baseline rather than by the branch choice.
- Anything built on `origin/main` after this date is lost work; nothing has been
  built there since 2026-09-07.

## Evidence

- Merge base `bb2829e56c3` (2026-07-06); 10 commits on `develop`, 4 on `main`.
- Design 99 modifies `frappe/__init__.py`, `model/document.py`,
  `utils/background_jobs.py`, `app.py`, `database/database.py` — 134 lines.
- The fork is thin: outside `friday_core`, 136 commits across 81 files, of which
  `hooks.py` is 32 and the rest is largely a Desk reskin.
