# ADR-0007 — Merge upstream Frappe v16 quarterly

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0002

## Context

The fork absorbed `frappe/frappe` at **v16.18.2**. Upstream is at **v16.34.0** —
1,764 commits and 300+ files, security fixes included. `docs/design/45-fork-policy.md`
called upstream "a read-only resource" and mentioned quarterly review of
*performance and architectural improvements*, but never said whether the fork
merges upstream releases or freezes against them. Nobody has merged anything.

A fork that never merges cannot take a security patch without hand-porting it,
and puts a future v17 permanently out of reach.

## Decision

**Merge upstream Frappe v16 on a quarterly cadence**, plus out-of-band for any
security release that affects us.

The first merge lands **after** the re-baseline completes, so the audit is taken
against a stationary tree rather than a moving one.

## Consequences

- Merge cost is bounded by keeping the fork thin: five seams plus a module. Any
  new core modification raises the recurring cost and must justify itself
  against that, per ADR-0014.
- The first merge is the largest — 16 releases — and should be treated as its
  own piece of work with its own verification, not folded into a feature branch.
- `docs/design/45-fork-policy.md` is archived with the rest of the dossier; this
  ADR replaces its upstream section.

## Evidence

- `docs/design/45-fork-policy.md:36` — base recorded as v16.18.2.
- `frappe/frappe` latest v16 tag: v16.34.0. Compare: 1,764 commits.
- Outside `friday_core`, the fork touches 81 files; `hooks.py` accounts for 32
  of 136 commits.
