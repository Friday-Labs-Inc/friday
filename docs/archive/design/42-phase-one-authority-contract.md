# 42 — Phase One Authority Contract

> **Status:** Highest authority for v0.1 scope. Where any other document describes "Phase 1" and conflicts with this contract, this document wins. No exceptions.

---

## 1. Authority Hierarchy

When implementation decisions conflict, resolve in this order:

1. `39-friday-framework-strategy.md` — framework identity and fork discipline
2. `41-porting-strategy-hermes-erpnext-raven.md` — Hermes / ERPNext / Raven translation
3. **This document** — v0.1 scope authority
4. `06-phase-one-scope.md`, `10-agent-execution-guide.md`, `11-agent-validation-checklist.md`
5. Other design documents — roadmap context only

---

## 2. Phase 1 Goal

Phase 1 proves the governed framework loop and the Friday product feel.

**The required proof:**

> A user can create or send work into Friday. Friday resolves an Agent Profile, loads governed Skills from DocTypes, checks permissions, executes one approved skill in a sandboxed path, records immutable logs, updates an Agent Task through a configurable workflow, and shows the result in the Framework Console.

That is the foundation. Everything else is breadth, not depth.

A business-automation flagship remains inside the Phase 1 program — but it starts **after** the governed framework loop is proven. The mistake to avoid: making business automation the first engineering slice, before the framework has identity, permissions, workflow, and audit.

---

## 3. In Scope for v0.1

### Framework Shell
- Friday repository forked from Frappe v16 stable
- Full bench ecosystem retained and documented
- `friday` command group (or bench plugin) for agent-specific operations
- Framework Console workspace as the default operator surface
- Agent-native primitives in framework core: actor context, trace propagation, audit hooks, agent-scoped auth
- Core divergences documented in `docs/core-divergences.md`

### Agent Kernel DocTypes
- `Agent Profile`
- `Agent Role Profile` (if Frappe Role Profile is insufficient after evaluation)
- `Skill`
- `Execution Log` (submittable — immutable audit trail)
- `Permission Decision Log` (submittable — immutable audit trail)
- `Workflow Request` schema
- `Agent Project`
- `Agent Task`
- `Agent Task Event` (or equivalent event/timeline record)

### Workflow and Board
- Configurable Agent Task workflow (first template may be simple)
- Kanban renders workflow states as columns
- States marked dispatchable; dispatcher claims only dispatchable tasks
- Explicit outcomes: blocked / completed / failed

### Execution
- One end-to-end skill (e.g. `create_note`)
- Permission check before execution
- Sandboxed execution path (Docker, minimum bar per §5)
- Structured result capture
- Immutable Execution Log
- Immutable Permission Decision Log

### Framework Console (minimum)
- Active tasks
- Active / suspended agents
- Recent executions
- Permission denials
- Task state changes
- Pause / suspend path for agents

### Raven
Raven is **optional for v0.1** unless the feasibility spike confirms it is low-risk to include.

If included, Raven is a War Room bridge only:
- Conversation surface
- Task and execution event posting
- Message Actions routed through Friday permission checks

Raven does not own task truth, execution truth, permissions, or audit.

---

## 4. Out of Scope for v0.1

These are not "nice to have later" — they are explicit exclusions from v0.1 that will not be considered even if a document calls them Phase 1.

- Autopilot mode
- Autonomous profile activation
- Autonomous skill activation or learning loop that changes active skills
- Semantic memory / pgvector queries (installed but not used)
- Wiki / knowledge graph
- Cross-site agent communication
- Multi-platform adapters beyond CLI or Raven (if Raven is included)
- Deep Raven fork
- Full domain-agent business suite (flagship comes after v0.1)
- Production-grade multi-host scaling

---

## 5. Sandbox Minimum Bar

Phase 1 must not be unsafe. The minimum bar is not the production sandbox.

**Required for v0.1:**
- Non-root container user
- CPU and memory resource limits
- Timeout handling
- OOM handling
- No host filesystem mounts
- No Docker socket mount
- Scoped credentials (short-lived API token, not long-lived)
- Structured stdout/stderr/result capture
- Cleanup path (no orphaned containers)
- Execution Log row for every attempt

**Deferred to Phase 1.5:**
- Warm container pool
- Egress proxy and allowlist enforcement
- Read-only rootfs on all runtimes
- Full automated security attack suite
- Multi-host orchestration
- gVisor / Firecracker backend

---

## 6. First Business-Automation Track (post-v0.1)

The first named business-automation use case is **not** v0.1. Whatever it turns out to be, it begins only after v0.1 proves the governed framework loop.

**Gate: v0.1 must be green before any business-automation track starts.**

v0.1 gates for business-track readiness:
1. Agent Project / Agent Task orchestration works
2. Agent Profile and Skill governance works
3. Permission and execution logs are reliable
4. Dispatcher handles configurable workflows
5. Framework Console lets a human understand and stop the system

**Minimum business-track scope (after v0.1):**
- A domain-specific Agent Profile
- Read-only support / alerting where it reduces risk
- Coordinator Agent basic oversight
- Operations Policy DocType (approval thresholds)
- Human approval for all high-risk and financially binding actions
- Zero unsafe actions
- Full audit traceability

---

## 7. Completion Gate

v0.1 is complete when all of the following are true:

- [ ] A Friday site installs and migrates cleanly from a fresh bench
- [ ] Framework Console exists and is the default workspace
- [ ] Agent Profile, Skill, Agent Project, Agent Task, Execution Log, and Permission Decision Log DocTypes exist
- [ ] A user can create or submit a task
- [ ] Dispatcher claims a dispatchable task exactly once (concurrency-safe)
- [ ] Agent executes one approved skill through the governed path
- [ ] Denied skill calls are logged to Permission Decision Log and rejected without execution
- [ ] Task state changes are visible in list / report / Kanban views
- [ ] Execution and permission logs are sufficient to reconstruct exactly what happened
- [ ] Tests cover permission checks, dispatcher claim safety, and the first end-to-end skill

After this gate is green, the first business-automation track begins.

---

## 8. Summary

Phase 1 is not "build all of Friday."

Phase 1 is:

> Build the smallest Friday that proves agents can operate inside a typed, permissioned, auditable Frappe-derived framework — running on Frappe v16 with agent-native primitives in core, with a Framework Console that lets a human understand and stop what the agents are doing.
