# ADR-0012 — The re-baseline ends when every package has a verdict and one turn runs

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0008, ADR-0009, ADR-0010

## Context

No previous phase of this project defined what "done" meant. That is how ~30
documents came to be marked LOCKED and 12 marked BUILT for a system whose
governed loop has never run end to end — message in, LLM call, skill dispatched,
submitted Execution Log out.

The same gap produced a commit message claiming `bench migrate` ran clean, eight
red test modules closed as stale without being run, and a port ledger that
declared itself COMPLETE and was found "badly stale" on its first re-audit.

## Decision

**The re-baseline is finished when both are true:**

1. **Every kernel package has an ADR verdict** — in scope, out of scope, or
   deferred — with the evidence that produced it.
2. **One governed turn has executed end to end on a real bench**: an inbound
   `Chat Message`, an LLM call, a skill dispatched through
   `agent_runner.dispatcher.dispatch`, and a submitted `Execution Log` row
   linked to its `Permission Decision Log` row.

Paper and runtime. Neither alone.

The first proof of the *product* — the team using Friday daily in Raven — comes
after, and is a separate bar.

## Consequences

- A package cannot be marked done on inspection. If its behaviour matters, it
  has to be run.
- The turn requirement forces the bench, the worker, a provider and the audit
  chain to all work together once, early, rather than being discovered later.
- Any future phase of work states its exit criterion before it starts. A phase
  without one does not start.

## Evidence

- `docs/ports/hermes-port-ledger.md` re-audit note: "the ledger was **badly
  stale** — almost every 'gap' had been built."
- Issues #211–#214, closed 2026-09-07 as stale tests; #232 reopened the same
  failure the following day.
