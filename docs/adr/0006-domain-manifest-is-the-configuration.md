# ADR-0006 — A domain app's manifest is its configuration

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0004

## Context

"Workflow configurable per domain" could mean configured by a developer in
code, by an operator in the Desk, or both. The implementation had already chosen
without the choice being recorded: a domain app declares `STATES`,
`TRANSITIONS`, transition metadata and agent profiles as Python data, and its
provisioner rewrites the Frappe Workflow from that list on **every migrate** —
clearing and re-appending states and transitions, so Desk edits do not survive.

Left unrecorded, this reads as a bug the first time an operator's change
vanishes.

## Decision

**The domain app's manifest is the single source of truth for its pipeline.**
States, transitions, transition metadata, agent profiles and skill definitions
ship as reviewable data in the domain app and are seeded into Frappe on migrate.
The Desk is for **inspection and operation**, not pipeline authoring.

Configurable therefore means: per domain app, by a developer, under version
control and code review.

## Consequences

- Changing a pipeline is a release, not a click. This is the intended trade:
  pipelines are governed business logic and belong in review.
- The provisioner's overwrite is correct behaviour and must be documented as
  such, not "fixed".
- An operator who needs to tune something at runtime needs a field the manifest
  does **not** own — that requirement is the trigger to revisit this ADR.
- Two domains cannot fight over one workflow: each owns its own.

## Evidence

- `randompack_ai/domains/randompack_brand.py` — `STATES`, `TRANSITIONS`, the
  provisioner's `wf.set("states", [])` / `wf.set("transitions", [])` rewrite,
  and `_ensure_transition_meta` upserts, all under `after_migrate`.
- `Domain Bundle` + `Friday Workflow Transition Meta` are the kernel-side
  contract the manifest fills.
