# ADR-0003 — Friday is an internal platform, enterprise-grade

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0002, ADR-0004

## Context

"Enterprise agentic orchestration system" was ambiguous between two very
different products: software enterprises install, and a platform with
enterprise-grade properties that one operator runs. The repository was public
and described as a kernel; a separate domain bundle (`randompack-ai`) was
published beside it and described as "installed on each studio's Friday bench",
which reads like distribution.

The distinction decides the fork question, the API-stability burden, the
documentation burden, and whether single-tenant assumptions in the kernel are
gaps or correct.

## Decision

**Friday Labs is the only operator.** Enterprise describes the *properties* —
audit trail, RBAC, approval gates, durable work, cost control — not the
customers. Nobody outside Friday Labs installs Friday. Customers receive
outcomes from products; they never receive the platform.

The enterprise-grade properties v1 must have, beyond what exists:

| Property | State today |
|---|---|
| Cost / quota enforcement that stops a turn | **absent** |
| Tested backup and restore of the Friday bench | untested |
| Every skill runs sandboxed | only `create_note` reaches the sandbox |
| SSO / directory login for operators | Frappe ships it; unwired |

## Consequences

- The seven single-tenant assumptions in the kernel are **correct**, not
  gaps — they should be documented as decisions, not filed as debt.
- No public API stability guarantee, no external contributor burden, no
  migration path to maintain for anyone else.
- The public repository is a side effect, not a strategy. Its description should
  stop implying adoption.
- Sandboxing moves from "nice to have" to a prerequisite, because the Hermes
  waist includes a terminal tool. See ADR-0008.

## Evidence

- Kernel single-tenant assumptions: `identity/agent_identity.py:31`,
  `cli/__init__.py:43`, `llm/memory.py:14`, `console/console_stream.py:69`.
- Frappe already ships LDAP, social login, OAuth (`connected_app`), rate
  limiting and backup utilities inside the fork.
