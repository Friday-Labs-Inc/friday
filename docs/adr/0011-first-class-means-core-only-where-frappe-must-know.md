# ADR-0011 — "First-class" means core only where Frappe itself must know

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0001, ADR-0002, ADR-0007

## Context

ADR-0001 says Hermes is ported into Frappe "as a first-class citizen". That
phrase had no operational meaning. `docs/design/45-fork-policy.md` §3 promised
several core changes — agent-scoped API key auth, a framework-level audit hook
surface, agent-native execution primitives. Only one ever landed: actor context
(Design 99), which put 134 lines into `frappe/__init__.py`,
`model/document.py`, `utils/background_jobs.py`, `app.py` and
`database/database.py`.

Every line in Frappe core is a line that must survive a quarterly upstream merge
(ADR-0007). "First-class" cannot mean "as much as possible".

## Decision

**A capability goes into Frappe core only when the framework itself must carry
it** — when the behaviour has to hold for writes that never pass through
Friday's own code. Everything else stays in the `friday_core` module and reaches
Frappe through hooks.

Actor context is the model case and the precedent: Frappe has to know *who is
acting* on every document save, because a write that skips the dispatcher still
has to be attributable. That is a framework concern. A skill registry is not.

The test, applied per capability during the re-baseline:

1. Does correctness depend on covering paths Friday does not control?
2. Can a hook or a subclass achieve it without editing core?
3. What does it cost at every upstream merge?

Only a clear yes to (1) and no to (2) justifies core.

## Consequences

- `docs/design/45-fork-policy.md` §3's remaining promises are not commitments.
  Each is re-judged on this test or dropped.
- The seam count is a tracked number. Growing it needs an ADR.
- Design 99's own fate is still open — this ADR sets the test it will be judged
  by, not the verdict. See ADR-0012.

## Evidence

- `frappe/hooks.py:733-735` — `resolve_actor` and `on_actor_write`: two hooks
  are the entire extension surface Design 99 needed.
- Fork surface outside `friday_core`: 81 files, of which `hooks.py` is the bulk.
