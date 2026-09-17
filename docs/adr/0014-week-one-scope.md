# ADR-0014 — Week one: re-ledger v2, one pillar running, docs cleared

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0008, ADR-0009, ADR-0012

## Context

ADR-0008 sets today's Hermes as the target and the narrow waist as the boundary.
ADR-0012 sets the exit criterion for the whole re-baseline. Between them sits
the question of what the first week actually produces, given that the existing
ledger maps to a Hermes file layout that no longer exists.

## Decision

**By the end of week one, three things exist.**

1. **Ledger v2** — every applicable Hermes waist module at `7a963716b81b`
   mapped to its Friday counterpart with a verdict (`verbatim-port` ·
   `frappe-adapted` · `improved` · `simplified` · `MISSING` ·
   `not-applicable (edge)`), citing `file:line` on both sides. The MISSING list
   becomes the backlog for the continuous cadence.
2. **One pillar verified running** — the ReAct turn loop, executed on the live
   bench, producing a governed turn per ADR-0012's definition.
3. **Docs cleared** — the archive in ADR-0009 carried out, `CONTEXT.md` and this
   ADR set in place.

Porting gaps is **not** in week one. The list has to be real first.

## Consequences

- Visible progress in week one is a map and one working loop, not new features.
  That is the intended trade after a period where features were declared done
  without running.
- Ledger v2 replaces `docs/ports/hermes-port-ledger.md` as the working document;
  the old one is kept for lineage.
- The remaining six pillars are verified in subsequent weeks against the same
  bar.

## Evidence

- Hermes restructured in September ("facade + siblings"), so the June ledger's
  file map no longer resolves — `run.py` is now `run_*.py` siblings, `session.py`
  is `session_*.py`.
- A live bench already exists on this machine (`friday-dev-frappe-1`, Python
  3.14.7, sites `friday.localhost` and `kernel.localhost`, this checkout mounted
  at `/workspace/friday-bench/apps/frappe`), so (2) needs no new infrastructure.
