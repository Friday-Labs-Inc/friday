# ADR-0013 — Decisions parked because they belong to a domain app

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0004, ADR-0006

## Context

A restructuring session surfaced several open questions that felt like Friday
decisions but are not. They belong to `randompack_ai` — the domain app — or to
the RandomPack product. Recording them here keeps them from being lost, and
keeps them out of the kernel where they would re-create the leak ADR-0009 just
cleaned up.

The trigger: the human Creative Director role was withdrawn. It was an
experimental role for testing, and roughly 2,400 lines of `randompack_ai` plus
three design documents assume it exists.

## Decision

**Parked. Not Friday's to decide, and not worked on in this repository.**

| Parked question | Where it belongs |
|---|---|
| Who creates the brand identity — the direction options and design system | `randompack_ai` pipeline manifest |
| Who inspects production before the client sees it | `randompack_ai` pipeline manifest |
| Whether agents draft and a human picks, and which human | `randompack_ai` personas |
| The CD apprenticeship study loop (~541 lines) and confidence ledger | `randompack_ai` |
| "The dial" — per-function autonomy for the assistant | RandomPack |
| The seat and capability model (four seats, thirteen capabilities) | RandomPack |
| Three stale Friday endpoint paths in `randompack/docs/CONTRACT.md` | RandomPack |

The last one is a live defect and is recorded as such below, not fixed here.

## Consequences

- One reading of the CD removal — agents draft, a human picks — was stated in
  the session. It is an input to the domain app's redesign, not a decision made
  here.
- The kernel takes no position on how many humans a pipeline has. That is
  exactly what ADR-0006 puts in the domain manifest.

## Known defect recorded, not fixed

`randompack/docs/CONTRACT.md` names three endpoints that moved out of the kernel
into `randompack_ai` in September (#230):

| Contract says (lines 187, 306, 307) | Actual location now |
|---|---|
| `frappe.friday_core.surfaces.randompack.receive_event` | `randompack_ai.surfaces.randompack.receive_event` |
| `frappe.friday_core.surfaces.randompack_chat.chat_send` | `randompack_ai.surfaces.randompack_chat.chat_send` |
| `frappe.friday_core.surfaces.randompack_chat.chat_finalize` | `randompack_ai.surfaces.randompack_chat.chat_finalize` |

Nothing is broken today because the seam has never carried a live message — no
subscriber, no shared secret. It would fail on the first attempt to wire it.
