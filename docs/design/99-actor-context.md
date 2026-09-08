# Design 99 — Actor context: the framework knows who acted

**Status:** BUILT (2026-09-08), branch `feat/actor-context`.
**Why now:** the code analysis found that of the five "agents are first-class citizens" primitives, none were in core — `frappe.set_user(agent_user)` appeared in exactly two call sites, and every audit row was written by Friday's own code, so any write that skipped the skill dispatcher left no agent trail (300 `ignore_permissions=True` sites).

## Plain English

Frappe knows the **user**. It does not know the **actor** — whether that user is a person, an agent acting as itself, or the system reacting to an event; which agent; or which turn the write belongs to. Friday's whole claim is that an agent acts as itself and every decision is auditable, so the framework has to carry that.

Actor context is three fields set once per context and carried everywhere:

```
frappe.local.actor = {kind: human | agent | system, id: <Agent Profile or connector>, trace_id: <turn/request>}
```

## What core gains

| where | what |
|---|---|
| `frappe/__init__.py` | `set_actor()`, `get_actor()`, `acting_as(user, kind=…, id=…)` — a context manager that restores **both** the user and the actor, even when the block raises. `set_user()` resolves the actor through `resolve_actor` hooks, so the framework learns "this User is agent X" without knowing what an agent is. The trace id survives user switches. |
| `frappe/model/document.py` | after every non-child save/submit/cancel, `_stamp_actor()` writes `_actor_kind`, `_actor`, `_trace_id` on the row (targeted update, like `_user_tags`; only for agent writes — a human's identity is already `modified_by`), then `_run_actor_write_hooks()` hands the document to `on_actor_write` hooks. Re-entrancy guarded; a failing hook is logged, never raised. |
| `frappe/utils/background_jobs.py` | `enqueue()` puts the actor in the job payload; `execute_job()` restores it. A job now runs as the actor that queued it. |
| `frappe/app.py` | an inbound `X-Trace-Id` becomes the request's trace; the response echoes `X-Trace-Id`. |
| `frappe/model/__init__.py`, `frappe/database/database.py` | `_actor_kind`, `_actor`, `_trace_id` join the optional columns, so new tables get them automatically. |

Two hooks are the whole extension surface: **`resolve_actor`** (dotted paths, `fn(username) -> {kind, id} | None`) and **`on_actor_write`** (`fn(doc, action)`).

## What Friday adds on top

- `identity.agent_identity.resolve_actor` — a User that belongs to an Agent Profile acts as that agent (cached per user, never raises).
- `audit.actor_write.on_actor_write` → **Agent Write Log**: one append-only row per document an agent writes — doctype, name, action, agent, user, trace — with the log doctypes themselves skipped. This is the framework-level audit the analysis said was missing: a write that never touches the dispatcher is still recorded.
- `engine.governance.acting_as` now delegates to `frappe.acting_as`, so a workflow transition fired as an agent is stamped as that agent.
- The dispatcher, the task runner and the connector event processor declare their actor: skill execution and the whole task run as `kind=agent, id=<profile>`; an inbound connector event runs as `kind=system, id=connector:<name>` with the envelope id as the trace.
- `Execution Log` and `Permission Decision Log` carry `trace_id`.
- Patch `add_actor_columns` adds the three columns to every existing non-child table (579 columns across 193 tables on the dev site) — a stamp that lands on some tables and not others is worse than none.

## What it does NOT do

- No new permission check. The actor is *identity and provenance*; the permission matrix and the approval gate are unchanged.
- No stamp on child rows — they belong to their parent, which carries it.
- No cost or quota enforcement — that is the next primitive.

## Tests

`tests/test_actor_context.py` (9): default actor for a user; invalid kind rejected; `acting_as` restores user **and** actor after an exception; trace survives a user switch; an agent's User resolves to `kind=agent` through the hook; rows are stamped; **an agent write is audited without the dispatcher**; a human write is not audited; a queued job carries the actor.
