# Design 98 — The surface contract (Raven leaves the kernel)

**Status:** DECIDED 2026-09-07 (debated; owner agreed). Build after the stage-table
driver (Design 01 in randompack), alongside the back-office SPA. Issue #222.
**Supersedes:** Design 58's "Raven is required, fail loudly" — right for a kernel
that *was* the human interface; wrong for one that sits under a studio console.
Raven AI stays **off** regardless (58 §Raven AI still applies).

## Plain English

Friday promises governed execution: identity, permissions, audit, durable work,
approvals. It does not promise a chat window. A chat app is a *surface* — one of
several (Raven, Slack, a web console, the CLI) — and a plural thing cannot be
required. Today Raven is named in 32 kernel files because, until the studio
console existed, Raven *was* the only way a human met an agent. That premise is
gone: the studio app owns the human interface, and the kernel exposes what a
surface needs.

## The contract

A **surface** is anything that can carry these four operations, registered by an
app through the `friday_surfaces` hook and described by a `Chat Platform` row
(`adapter_module` — already the registry for CLI, Raven and Slack):

| operation | meaning | today's Raven code that moves behind it |
|---|---|---|
| `announce(work_item, text, kind)` | tell the room something happened | `warroom/publisher`, engine dispatch announcements, `gateway/mirror` |
| `ask(role, request) -> Approval` | put a decision in front of whoever holds a role | approval DMs, delegation prompts, `gateway/interrupt` |
| `notify(user, text, link)` | reach one person | `gateway/delivery`, `tasks/runner` pings |
| `open_room(work_item) -> room_ref` | a place per engagement | `conversation/project_channel` (Design 73) |

Rules:

1. **The approval is the record, not the message.** `ask` creates an approval
   record in the kernel; every surface renders it and every surface's "approve"
   resolves the *same* record. The SPA is the system of record; Raven mirrors.
2. **The kernel never names a product.** After the move, `grep -i raven` over
   `friday_core/` minus tests returns nothing. `test_surface_boundary.py` holds
   the line from today: no new file may mention Raven; the allow-list only shrinks.
3. **Minimum surface = CLI + whitelisted API.** The kernel is fully operable by
   API (that is what the SPA uses). `pipeline_health` reports `surfaces.chat`
   = *degraded* when no chat surface is registered — not *down*.
4. **Session → work-item resolution is a surface concern.** `llm/memory.
   project_for_session` asks the registered surfaces "which work item is this
   room for?" instead of querying `Raven Channel`.
5. **Bootstrapping is the surface's job.** Bot user, channels, `is_ai_bot = 0`
   pinning move with the adapter; the kernel's setup wizard asks surfaces to
   provision themselves and reports what answered.

`required_apps = ["frappe"]`.

## Where Raven goes

`randompack/surfaces/raven/` — adapter, bootstrap, war room, project
channels, the 17 kernel test modules that touch Raven tables. A package, so it
can be lifted into a `friday_raven` app later if a non-studio deployment wants it.

## Migration (safe sequencing)

1. Land the contract types + hook + CLI surface + health signal, with Raven
   still in the kernel but *calling through the contract* (no behaviour change).
2. Move the Raven package to randompack; kernel allow-list goes to zero.
3. Flip `required_apps`. Kernel CI stops installing Raven; randompack CI keeps it.
4. SPA renders approvals from the record (randompack #11); Raven's approve
   action resolves the same record.

## What does not change

Design 95 (human creates, AI produces), the permission matrix, the Execution
Log, the durable task pipeline, the six domain seams. This is the seventh seam.
