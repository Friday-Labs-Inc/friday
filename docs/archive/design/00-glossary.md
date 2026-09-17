# 00 — Glossary

> **Status:** Authoritative. Every term used across the Friday dossier resolves here first.
> If a document uses a term differently, the document is wrong and needs updating.

---

## Core Framework Terms

**Friday**
The framework. A hard fork of Frappe v16 stable with agent-native primitives built into core. Not an app installed on top of Frappe. Not a thin wrapper. The fork is Friday.

**Friday Core**
The agent kernel built into the framework: Agent Profile, Skill, Execution Log, Permission Decision Log, Workflow Request, Gateway, Dispatcher, Sandbox runtime, LLM Provider adapters. These are framework primitives, not removable apps.

**Friday App**
A domain capability installed on top of Friday Core. Examples: ERPNext operations, Raven bridge, memory/wiki, analytical agents. Apps are installable and optional. Friday Core is neither.

**Framework Console**
The operator-facing web application served by Friday. This is where humans manage agents, review executions, approve actions, and monitor the system. Also called the Control Room. Built on Frappe Workspace primitives. The product surface.

**bench**
The Frappe operational CLI. Retained in Friday unchanged. Used for site creation, app installation, migrations, and framework operations. Friday adds agent-specific commands as a `friday` command group within bench.

---

## Agent Terms

**Agent**
A running instance of an Agent Profile executing a task. Not a process in the OS sense — an agent is a Frappe-side construct: a profile, a set of permitted skills, a linked ERPNext user, and an execution context.

**Agent Profile**
A DocType defining an agent's identity: name, linked Frappe User, assigned Agent Role Profile, permitted skills, LLM provider, resource quotas, approval threshold, and status. One row per named agent in the system.

**Agent Role Profile**
A DocType defining a reusable bundle of roles, skill permissions, resource quotas, and governance rules. Applied to many Agent Profiles. The governance unit — changing an Agent Role Profile changes all agents that use it.

**Agent Core Worker**
The dedicated, long-running RQ worker process that runs the Hermes-derived agent execution loop. Separate from Gunicorn. Bound to a custom `agent_core` queue. Not an HTTP worker. Does not handle web requests.

**Agent Execution**
One complete run of an agent against a task — from task claim through skill dispatch through final result. Recorded as an Execution Log row (submittable, immutable).

---

## Skill Terms

**Skill**
A governed unit of agent capability. Defined as a DocType row with a name, description, parameter schema, required DocTypes, risk level, and status. Not a file. Not a Python function registered at import time. A row in the database that the permission engine gates before anything executes.

**Skill (Level 0 / L0)**
The short header version of a skill loaded into every agent prompt by default — roughly 3–4 lines. Used for skill discovery without blowing the context window.

**Skill (Level 1 / L1)**
The full skill instructions, fetched on demand when the agent decides to use the skill.

**Skill (Level 2 / L2)**
Reference files and extended documentation attached to a skill, fetched only when executing.

**Skill Draft**
A proposed new or updated skill submitted for human review. Agents may propose; humans approve. Skill Drafts never activate without supervisor sign-off.

**Skill Version**
An immutable snapshot of a Skill's content at a point in time. Rollback means pointing the active version pointer to a prior Skill Version row.

**Tool**
A Python callable registered with Friday's tool registry, invocable by the agent during execution. Maps to Hermes' tool concept. Governed by the skill allowlist.

**Capability**
The union of Tools + Skills + permissions granted to a specific Agent. The governance unit for what an agent can actually do at runtime.

---

## Execution Terms

**Execution Log**
A submittable Frappe DocType recording every skill invocation: agent, skill, parameters (masked), result, status, duration, tokens, and links to Permission Decision Log. Immutable once submitted. The legal audit trail.

**Permission Decision Log**
A submittable Frappe DocType recording every permission check: agent, skill, decision (allowed/denied), reason, and the permission matrix snapshot at decision time. Immutable once submitted.

**Workflow Request**
A DocType representing a pending approval for a high-risk skill invocation. Created when a skill exceeds the agent's auto-approval threshold. Routes to the appropriate approver via Frappe Workflow. Outcome logged immutably.

**Sandbox**
The Docker container in which skill execution happens. Non-root user, resource-capped, network-restricted, ephemeral filesystem. The Frappe REST API is the only permitted channel back to the framework.

---

## Coordination Terms

**Agent Task**
A unit of work assigned to an agent. A DocType derived from ERPNext Task and extended with Friday fields: `assigned_to_profile`, `required_skills`, `risk_level`, `dispatchable`, `current_execution`. Tasks move through Frappe Workflow states.

**Agent Project**
A container for related Agent Tasks. Derived from ERPNext Project. Has an associated War Room channel (if Raven is installed). One project = one workflow context = one set of assigned agent profiles.

**Dispatcher**
A Frappe scheduled job (runs every 60 seconds) that queries dispatchable Agent Tasks, matches them to eligible Agent Profiles, and atomically claims them. Uses `SELECT ... FOR UPDATE SKIP LOCKED` to prevent double-claiming.

**Dispatchable State**
A workflow state on Agent Task explicitly marked as claimable by the dispatcher. Only tasks in dispatchable states enter the dispatcher's query. States like Blocked, Review, Completed are never dispatchable.

**War Room**
A Raven channel auto-created per Agent Project. The real-time communication surface for the project — agents post status updates, humans post instructions, escalations surface here. War Room reflects truth; it does not own it. Frappe DocTypes own truth.

---

## Memory Terms

**Memory Entry**
A persistent, vector-indexed record of something an agent learned, observed, or was told. Stored in PostgreSQL with a pgvector embedding for semantic retrieval. Domain-scoped.

**Memory Search**
A skill (`memory_search`) the agent calls explicitly to retrieve relevant past memories. Memory is never auto-injected into every prompt — only fetched on demand.

**Domain**
A tag on Skills, Agent Role Profiles, Memory Entries, and Agent Projects that scopes knowledge and learning. Examples: `customer-support`, `infra-kubernetes`, `general`. Prevents cross-contamination between unrelated domains.

---

## Infrastructure Terms

**Gunicorn Worker**
The standard Frappe web process. Serves the Framework Console (HTTP requests, WebSocket connections via Raven/Socket.io). Does not run agent loops. Does not block on agent reasoning.

**Agent Core Worker**
See above. The dedicated RQ worker for the agent execution loop. High timeout (configurable, default 30 minutes). One in-flight agent run at a time per worker in Phase 1.

**Redis**
Three roles in Friday: (1) cache for permission matrices, skill definitions, and ERPNext master data; (2) job queue for background workers; (3) pub/sub for real-time events to Raven and the Framework Console.

**pgvector**
A PostgreSQL extension providing vector similarity search. Used for semantic memory retrieval. Friday pins pgvector at v0.8.2 or later.

---

## What These Terms Are NOT

| Term used elsewhere | What Friday calls it |
|---|---|
| "Agentic site" | Framework Console (it is not just an agent-scoped site) |
| "Hermes dashboard" | Framework Console (Raven + Frappe Workspace, not a Hermes concept) |
| "Kanban" (as the workflow) | Kanban is a **view** — the workflow is defined in Frappe Workflow |
| "Skills as files" | Skills are DocType rows — no filesystem scanning |
| "LLM App" | Friday is a framework, not an LLM app |
| "Agentic framework layer on top of Frappe" | Friday IS the fork — there is no "on top of" |
| "Raven fork" | Raven is an installed Friday app, not forked |
| "ERPNext dependency" | Specific DocTypes are **ported** from ERPNext into Friday Core — no ERPNext dependency |

---

*This glossary is a living document. Propose additions via PR. Every new term introduced in the dossier must appear here before it can be used in other documents.*
