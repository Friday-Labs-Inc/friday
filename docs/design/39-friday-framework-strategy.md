# 39 — Friday Framework Strategy

> **Status:** Authoritative. Framework identity and fork discipline.
> Where any other document conflicts with this one on framework identity, this document wins.

---

## The Decision

**Friday is a framework. It runs on a hard fork of Frappe v16 stable.**

This is not conditional. The Friday repository is a fork of Frappe v16 stable. Agent-native primitives are built directly into framework core. The full Frappe bench ecosystem is retained. `bench init`, `bench new-site`, apps, migrations, site operations — all of it works as before, because it is excellent operational infrastructure.

The product identity is Friday:

- Users interact with Friday. Frappe is the engine underneath.
- The default workspace is the **Framework Console**, not the generic Frappe Desk.
- The CLI has a `friday` command group for agent operations; `bench` remains available for site and framework operations.
- Agent Profile, Skill, Execution Log, Permission Decision Log, Sandbox Execution, and Workflow Request are **native framework primitives** — in every Friday site by default, the same way User and Role are in every Frappe site.
- ERPNext operations, Raven, memory, and analytics are **Friday apps** — installable, not core.

---

## Why Frappe Is the Right Substrate

Hermes and OpenClaw prove the right agentic patterns: gateway, session loop, skills, memory, tool execution, scheduling, multi-agent coordination. But they store agent state as files, config, local session logs, and runtime services.

Frappe already provides the enterprise substrate those systems need but never built:

| Agentic Requirement | Frappe Primitive |
|---|---|
| Structured, queryable agent state | DocTypes + ORM |
| Identity for humans and agents | User + Role |
| Runtime permission enforcement | Role permission matrix |
| Durable, immutable audit records | Submittable DocTypes |
| Multi-step approval flows | Workflow engine |
| Background job execution | RQ workers |
| Scheduled autonomous operations | Scheduler |
| Real-time events to the UI | Redis pubsub + socket.io |
| Artifact and file management | File DocType |
| Operational web interface | Desk / Workspace |
| Operational CLI | bench |

The Friday insight: move agent architecture from **developer-tool state** into **enterprise-record state**.

---

## Framework Shape

Three layers. Strict boundaries.

**Layer 1 — Friday Framework Core**
The Frappe v16 fork. Runtime, bench/site/app lifecycle, Desk shell, auth, DocTypes, ORM, permissions, workflows, jobs, files, realtime, agent-native core modifications.

**Layer 2 — Friday Agent Kernel**
Agent-native primitives built into framework core: Agent Profile, Agent Role Profile, Skill, Skill Version, Execution Log, Permission Decision Log, Workflow Request, Sandbox Execution, LLM Provider, Gateway, Dispatcher.

**Layer 3 — Friday Apps**
Domain products installed on the kernel: ERPNext operations, Raven bridge, memory/wiki, analytics, specialist agents, auto-research, multi-site communication.

The user experiences one framework. Internally, Layer 2 and Layer 3 never bleed into each other.

---

## What Goes in Core vs Apps

The line is **framework vs domain**.

**Core (modify freely):**
- Agent identity as a first-class actor across requests, jobs, and workflows
- Trace ID propagation from gateway → execution → audit
- Framework-level audit hooks for Permission Decision Log and Execution Log
- Agent-scoped API key authentication baked into the auth layer
- Friday shell: Framework Console workspace, `friday` CLI commands, navigation defaults

**Friday apps (never in core):**
- Business-process automation
- Raven War Room integration
- pgvector memory and knowledge graph
- Auto-research agents
- Analytical and predictive agents
- Multi-site ACP
- Industry-specific skill templates

Every core modification is documented in `docs/core-divergences.md`, tagged `[friday-core]` in git, and covered by a test.

See `45-fork-policy.md` for the full discipline.

---

## The Two-Worker Model

Friday runs two distinct process types per site:

**Gunicorn** serves HTTP requests for the Framework Console and manages WebSocket connections (via Raven/Socket.io). It does not run agent reasoning loops. It does not block on agent work.

**Agent Core Worker** is a dedicated, long-running RQ worker on a custom `agent_core` queue with a high timeout (default 30 minutes). It runs the Hermes-derived `AIAgent.run_conversation()` loop. One in-flight agent run per worker in Phase 1. It does not handle web requests.

These two processes have independent lifecycles. They communicate through shared infrastructure: PostgreSQL for state, Redis for coordination and events, Frappe REST API for the sandbox-to-framework channel.

This design is not an architectural innovation — it is a deliberate configuration of Frappe's existing process model. The innovation is recognizing that agent reasoning is a fundamentally different workload from HTTP request handling and giving it its own dedicated process accordingly.

---

## Single-Site Model

Friday runs one site per bench. This is a deliberate Phase 1 constraint, not an accident.

Frappe supports multi-tenant deployments where one bench hosts many sites. Friday disables this for the following reasons:

- Agent state (skills, memory, audit, sandbox credentials) is per-site. Multi-site multiplies blast radius for a compromised agent.
- Frappe's permission sandbox has documented bypass history. Single-site bounds the damage.
- Agent configuration, LLM credentials, and operational policy should be scoped to one business, not shared across tenants.

Multi-site is a Phase 3 consideration after single-site security is proven. See `45-fork-policy.md` for the `frappe.local.site` confinement rule.

---

## Upstream Relationship

Upstream Frappe (`frappe/frappe`) is a **read-only reference** Friday selectively absorbs from.

| Trigger | Action |
|---|---|
| Security release (CVE) | Review within 48 hours; cherry-pick if Friday is affected |
| Bug fix we hit | Cherry-pick when encountered |
| Improvement | Review quarterly; incorporate if it benefits Friday |
| Major release (v17+) | Project-level decision: migrate, stay, or skip |

There is no automatic sync. The Friday community owns the kernel's future. Upstream Frappe cannot push to the Friday fork.

---

## Product Feel Requirements

From first install, Friday feels like Friday — not a generic Frappe site.

- `bench` is available and documented for site and framework operations.
- `friday` commands exist for agent-specific workflows: `friday chat`, `friday agent`, `friday skill`.
- The first workspace is the **Framework Console**.
- Default modules: Agents, Skills, Tasks, Execution Logs, Permissions, Settings.
- New projects are agentic by default: tasks, agents, permissions, and audit are native.
- Operators see what agents can do, what they are doing, what they did, and how to stop them.
- Developers build "Friday apps" using Frappe-derived primitives — the same development experience as any Frappe app.

---

## Phase 1 Implication

Phase 1 establishes the framework shell and proves one governed execution path:

1. Friday-derived repo, bench-aware setup, Friday-facing CLI identity
2. Framework Console workspace
3. Core agent DocTypes (Agent Profile, Skill, Agent Task, Execution Log, Permission Decision Log)
4. Permission-gated skill execution
5. Sandboxed execution path
6. One end-to-end skill proving the loop

Business automation is the north-star use case. The first engineering milestone is the governed framework loop; business automation comes after the loop is proven. See `42-phase-one-authority-contract.md`.

---

## Summary

Friday is an agentic framework running on a hard fork of Frappe v16 stable with the full bench ecosystem intact. Agent-native primitives are built into core. The Framework Console is the product surface. The agent runtime is the engine. Frappe supplies the proven enterprise substrate. Friday adds the governed-agent layer the ecosystem does not yet have.
