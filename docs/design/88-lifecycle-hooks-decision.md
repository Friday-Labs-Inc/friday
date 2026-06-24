# Design 88 — Lifecycle hooks: deliberately deferred (decision)

> **Status:** DECIDED 2026-06-24. Resolves gateway deep-audit gap #6
> (`hooks.py` lifecycle HookRegistry). Outcome: **deliberately not ported** —
> reclassified from "open gap" to "justified divergence." No code.

## The gap, in plain English

Hermes has a **HookRegistry** (`gateway/hooks.py`): it scans `~/.hermes/hooks/*/`
on startup, and for each directory loads a `handler.py` via `importlib` and runs
its `handle(event_type, context)` on lifecycle events (`gateway:startup`,
`session:start/end`, `agent:start/step/end`, `command:*`). It lets a user drop in
arbitrary Python that fires at points in the agent's life.

The deep audit listed this as a true gap (#6). On closer look, **porting it as-is
is the wrong call for Friday** — for three concrete reasons.

## Why defer (not port)

### 1. No consumer — Friday is single-tenant, first-party-trusted
A pluggable hook system exists to let *third parties* extend the agent without
editing core. Friday v0.1 is **one customer's site running first-party code**
(`feedback_single-tenant-not-saas`, `feedback_v01-skills-first-party-trust`).
There is no plugin ecosystem and no untrusted-extension surface. Building a
generic extension point with no extender is speculative infrastructure —
exactly the "every changed line must trace to a real need" smell.

### 2. It's a code-execution security surface
Hermes' registry **loads and executes arbitrary `handler.py` files discovered on
disk** (`gateway/hooks.py:64` `discover_and_load` → `importlib.util` → exec).
Per Friday's own severity rule (`feedback_v01-skills-first-party-trust`), an
untrusted-code-execution surface is **HIGH severity**. Introducing a
filesystem-discovered code loader — with no consumer asking for it — adds risk
for no benefit. If hooks are ever needed, the safe shape is **in-process
registered callables** (no filesystem discovery, no `importlib` of unmanaged
files), not Hermes' file-drop model.

### 3. The eventing need is already met
The actual *value* of lifecycle hooks — "react to what the agent is doing" — is
already delivered in Friday by the **observability event stream**. The agent
lifecycle already emits, via `observability.emit`:

| Event | Where |
|---|---|
| `runner.start` / `runner.complete` / `runner.error` / `runner.block` / `runner.interrupt` | `tasks/runner.py` |
| `workflow.state_change` / `workflow.executing_token_released` | `tasks/workflow.py` |
| `gateway.force_kill` | `gateway/interrupt.py` (Design 83b) |
| `reconciler.tick` / `reconciler.action` | `tasks/reconciler.py` |

These feed the **Dispatcher Console Lifecycle Trace** (Design 72) and the
immutable audit trail. A consumer that wants to "do something on agent events"
subscribes to these (a Frappe `doc_events` handler on `Dispatcher Event`, or a
realtime subscriber) — no new hook framework required.

## Decision

**Defer the pluggable HookRegistry.** Reclassify gap #6 from `MISSING` to
**deliberately diverged (justified)** in the ports ledger. This is consistent
with the standing stances:

- `feedback_hermes-floor-not-ceiling` — we port what makes Friday *more*
  trustworthy; a speculative code-loader does the opposite.
- `feedback_single-tenant-not-saas` — no multi-extender scenario to serve.
- `feedback_v01-skills-first-party-trust` — don't add an untrusted-code surface.

## If a real need appears later (the safe path)

The trigger would be a concrete consumer ("on every agent turn, do X" that can't
be a skill or a `Dispatcher Event` subscriber). At that point, port the
*concept*, not the *mechanism*:

- An **in-process registry of first-party callables** keyed by event name
  (mirroring `dispatcher._SKILL_HANDLERS`), populated by explicit imports — never
  by scanning a directory and `importlib`-ing unmanaged files.
- Or simply a documented `doc_events` subscriber on `Dispatcher Event`.

Either reuses Friday's existing eventing and avoids the security surface. Until a
driver exists, this stays deferred.

## Outcome

With this decision, **every named gateway gap from the deep audit is resolved** —
the session manager (queue/slash/interrupt/steer/cascade/force-kill), delivery
router, and cron (both slices) are shipped; lifecycle hooks are deliberately
deferred with reasoning. The gateway port is complete.
