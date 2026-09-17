# 01 — Vision & Architecture

> See `00-glossary.md` for all term definitions.
> See `39-friday-framework-strategy.md` for fork and framework identity decisions.
> See `42-phase-one-authority-contract.md` for v0.1 scope.

---

## Vision

Friday is an open-source agentic framework built on a hard fork of Frappe v16 stable. It makes AI agents first-class primitives of an enterprise application platform — not an app you install on top, not a thin wrapper, but a native part of the framework itself.

The goal: an agentic framework that enterprises can actually deploy because governance is built in, not bolted on. Permissions are architecture, not configuration. Audit is a property of every action, not a feature you add later.

**The mission:** every Indian SMB owner gets a back-office agent team that never sleeps, runs on their own infrastructure, operates within auditable boundaries, and costs a fraction of hiring.

---

## Design Principles

1. **Permission first.** Every skill invocation passes through Frappe's role-based permission engine before it executes. No exceptions. Denied calls are logged immutably.

2. **Frappe is the source of truth.** Every agent, skill, task, permission decision, and execution is a DocType row. No scattered files, no ad-hoc JSON state, no SQLite session databases.

3. **Sandboxed execution.** Every skill runs in an isolated Docker container with scoped credentials, resource limits, and network restrictions. The Frappe REST API is the only permitted channel back to the framework.

4. **Audit everything.** Execution Log and Permission Decision Log are submittable DocTypes — immutable once submitted. Every action is reconstructable from logs.

5. **Kanban is a view, not the workflow.** Business workflows are defined in Frappe Workflow. Kanban renders whatever states are configured. Agents operate inside governed workflows; they do not invent them.

6. **Framework-first product feel.** Users interact with Friday. Frappe is the engine. The Framework Console is the product surface.

7. **Open source by default.** GPL v3 from day one, developed in public.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PLATFORM ADAPTERS                                              │
│  CLI (Phase 1) · Raven (Phase 2) · Telegram, Slack, etc.        │
└────────────────────────────┬────────────────────────────────────┘
                             │ (messages → Chat Message DocType)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  GUNICORN  —  Framework Console (HTTP + WebSocket)              │
│  Serves the operator-facing web application                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ (real-time events via Redis pubsub)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  AGENT CORE WORKER  —  Dedicated RQ worker, custom queue        │
│  Runs the Hermes-derived AIAgent.run_conversation() loop        │
│  ─ Dispatcher (claims dispatchable Agent Tasks)                 │
│  ─ Permission gate (checks every skill before dispatch)         │
│  ─ Skill loader (Redis-cached Skill DocTypes)                   │
│  ─ LLM provider adapter (Minimax Phase 1; provider-agnostic)    │
│  ─ Sandbox orchestrator (spawns Docker containers)              │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Sandbox  │   │ Sandbox  │   │ Sandbox  │   ← Docker containers
        │ (skill A)│   │ (skill B)│   │ (skill N)│     scoped creds
        └────┬─────┘   └────┬─────┘   └────┬─────┘     resource caps
             │              │              │             network isolated
             └──────────────┼──────────────┘
                            │ (Frappe REST API only)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  FRIDAY FRAMEWORK CORE  —  Frappe v16 fork                      │
│  DocTypes · ORM · Role Permissions · Workflows · Scheduler      │
│  RQ Workers · Realtime pubsub · REST API · Bench ecosystem      │
│  + Agent-native patches: actor context, trace ID, audit hooks   │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌────────────┐  ┌──────────┐  ┌──────────────┐
       │ PostgreSQL │  │  Redis   │  │    Docker    │
       │ + pgvector │  │ cache +  │  │  runtime     │
       │ (all state)│  │ queues + │  │ (sandboxing) │
       └────────────┘  │ pubsub   │  └──────────────┘
                       └──────────┘
```

**Two processes, one site.** Gunicorn and the Agent Core Worker run as separate processes on the same bench, communicating through PostgreSQL, Redis, and the Frappe REST API. They do not share execution context. Each can be stopped, restarted, and scaled independently.

---

## Request Flow (End-to-End)

1. **Inbound** — a user submits a task via CLI (Phase 1) or Raven channel (Phase 2+). A Chat Message DocType row is created.
2. **Real-time event** — Frappe's Redis pubsub wakes the Agent Core Worker.
3. **Session resolution** — Worker loads the Agent Profile and recent session context.
4. **Skill loading** — Worker pulls permitted Skills from Redis cache (fallback to DocType query on miss).
5. **Permission check** — Worker calls the permission engine. If denied: log to Permission Decision Log, reject, post error. If allowed: continue.
6. **LLM call** — Worker calls the configured LLM provider with the system prompt, skill definitions (L0 headers), and conversation history.
7. **Tool dispatch** — LLM returns a tool call. Worker verifies permission again. Spawns Docker sandbox.
8. **Sandboxed execution** — Container authenticates with a scoped API token, calls Frappe REST API, executes the skill, returns structured JSON.
9. **Result persistence** — Execution Log row submitted (immutable). Agent Task workflow state updated. Result written back as outbound Chat Message.
10. **Console update** — Framework Console receives real-time event; task state and execution log update live.

**Every step is auditable.** Every permission decision is a submitted row. Every skill execution is a submitted row. Nothing happens silently.

---

## Multi-Agent Coordination

Agents coordinate through Frappe DocTypes, not through direct calls to each other.

**Agent Project** = a workflow context with associated agent profiles and tasks.

**Agent Task** = a unit of work moving through a configurable Frappe Workflow (e.g. `Pending → Assigned → Executing → Blocked → Review → Completed`). States are fully configurable per project type.

**Dispatcher** = a Frappe scheduled job (60-second interval) that atomically claims dispatchable tasks for eligible Agent Profiles.

**War Room** (Raven channel, Phase 2+) = the human-visible communication surface for a project. Agents post status updates; humans post instructions; escalations surface here. The War Room reflects truth; it does not own it.

Agents never call each other directly. Inter-agent work flows through Agent Task delegation — one agent creates a sub-task, the dispatcher claims it for another profile, and that profile executes it with its own permissions.

---

## What Makes Friday Different

| Concern | Hermes / OpenClaw | Friday |
|---|---|---|
| Skill storage | Markdown files on disk | Structured DocType rows |
| Permission model | Per-tool config, easy to misconfigure | Frappe role matrix, enforced at gateway before every execution |
| Multi-agent board | Custom Kanban + SQLite | Frappe Workflow + configurable Kanban view |
| Audit trail | Log files | Submittable DocTypes — immutable, queryable, exportable |
| Isolation | Process-level | Docker + Frappe REST API boundary |
| Memory | File-based + optional vector | PostgreSQL + pgvector (Phase 2+) |
| Real-time | Custom WebSocket | Frappe's built-in pubsub |
| Background jobs | Custom cron | Frappe RQ workers |
| Approval flow | Ad-hoc Slack buttons | Frappe Workflow on Workflow Request DocType |

---

## Framework Positioning

Friday is a framework, not a product feature or an installable app.

The Friday repository is a hard fork of Frappe v16 stable:
- Frappe supplies the engine: DocTypes, ORM, permissions, users, workflows, scheduler, workers, files, realtime, bench, and Desk.
- Friday adds agent-native primitives to framework core: agent identity, execution trace, governed skill dispatch, sandboxed execution.
- Friday-native DocTypes are core framework concepts — present in every site, not removable apps.
- The Framework Console is the product surface. The agent runtime is the engine.

See `39-friday-framework-strategy.md` for fork discipline.
See `41-porting-strategy-hermes-erpnext-raven.md` for the Hermes port decisions.
See `45-fork-policy.md` for upstream absorption rules.
