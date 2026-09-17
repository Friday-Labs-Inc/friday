# 41 — Porting Strategy: Hermes Core, ERPNext Work Objects, Raven War Room

> **Status:** Authoritative. Hermes / ERPNext / Raven translation decisions.
> Where doc 42 (Phase One Authority Contract) conflicts with this document on v0.1 scope, doc 42 wins.

---

## Origin: The Hermes Failure Case

The porting strategy starts from a real test: ask Hermes Agent to create profiles, build a board, create tasks, and run a multi-agent workflow.

Results:
- Basic bounded single-agent tasks worked.
- Multi-agent setup failed repeatedly.
- Agent-created profiles and skills were built incorrectly.
- Fixed Kanban columns did not match the actual workflow needed.
- The agent was forced to invent too much of the operating model from loose instructions.

**The product insight:**

> Agents should not improvise the operating model. They should operate inside one.

Hermes proves the right coordination shape. The failure case proves why Friday needs Frappe.

---

## What Is Ported vs What Is Not

This is the most important section. The port is precise.

### Ported from Hermes

**`run_agent.py` and the `agent/` module tree** — the AIAgent class, the ReAct-style conversation loop, prompt builder, tool dispatch, model provider abstraction, and session state management. This is the agent core.

**`tools/` and `model_tools.py`** — the tool registry and parallel tool execution logic.

**`hermes_state.py`** — reimplemented against PostgreSQL + pgvector instead of SQLite + FTS5.

**Skills (Level 0 / 1 / 2 progressive disclosure pattern)** — the concept of progressive skill disclosure is kept; the implementation moves from filesystem SKILL.md files to Frappe DocTypes.

### Not Ported from Hermes

**`gateway/run.py` and `gateway/platforms/`** — Raven replaces the gateway. Hermes' multi-platform adapter system is not ported. Friday uses Raven's Socket.io layer for communication.

**`cli.py` and the TUI** — Frappe Desk and the `friday` bench command group replace the CLI.

**The ACP server, API server, batch runner** — not ported.

**`jobs.json` cron daemon** — Frappe Scheduler replaces this entirely.

**The Kanban dashboard** — Frappe Workflow + Kanban View replaces Hermes' fixed Kanban.

**SQLite / FTS5 session storage** — PostgreSQL + pgvector replaces this.

**`HERMES_HOME` filesystem layout** — replaced by Frappe DocTypes and the site's PostgreSQL database.

**LiteLLM as a default dependency** — not carried forward due to supply-chain risk. Friday uses direct provider SDKs.

---

## What Friday Keeps from Hermes (as Patterns)

These are architectural patterns Friday re-implements on Frappe primitives, not code Friday inherits:

- Durable task coordination instead of fragile in-context subagent swarms
- Named agent profiles instead of anonymous subagents
- Dispatcher-driven claiming of ready work
- Worker lanes by profile or capability
- Task dependencies and dependency promotion
- Block / unblock loops for human input
- Heartbeat and stale-claim recovery
- Per-task execution history
- Circuit breaker after repeated failures
- Orchestrator agents that decompose work without executing every task themselves

---

## Hermes AIAgent → Agent Core Worker

The AIAgent class from `run_agent.py` is synchronous and ReAct-style. This is the right shape for a Frappe RQ worker, which is also synchronous. Do not try to make AIAgent async.

Three concrete changes required during porting:

**1. Cooperative cancellation.** Replace Hermes' `threading.Event` interrupt with an RQ `SIGTERM`-aware check: on each tool boundary, the worker reads a `stop_requested` flag from the Agent Task DocType. If set, the worker shuts down gracefully.

**2. State as DocTypes.** Replace Hermes' filesystem state (`SOUL.md`, `MEMORY.md`, `USER.md`, `state.db`) with DocType reads loaded once at the start of `run_conversation()` and kept immutable for that run's duration. Frappe RQ can run multiple workers; each must load its own snapshot cleanly.

**3. Memory migration.** Replace SQLite FTS5 with PostgreSQL dual-index: `tsvector` + GIN for keyword recall (the direct FTS5 replacement), and pgvector `vector(1536)` + HNSW for semantic recall. Both stored on the `agent_message` table. Queries merge results via reciprocal rank fusion.

---

## Skills: Filesystem → DocTypes

Hermes' SKILL.md system has three properties that require explicit mapping:

**Progressive disclosure (L0 / L1 / L2).** DocType fields map directly: `description` = L0 header (loaded into every prompt), `instructions` = L1 body (fetched on demand), `Skill Asset` child rows = L2 reference files.

**Agent self-mutation.** Hermes agents can write new SKILL.md files directly. Friday does not allow this. Agents propose `Skill Draft` rows; humans approve. This is not a limitation — it is the governance model. See `22-hermes-learning-loop-deep-dive.md`.

**External skill directories.** Hermes supports `external_dirs:` in config for local skill overlays. Not ported. Skills live in the database. Community-contributed skills are imported via the Skill import pipeline and go through the Draft → Review → Active flow.

**Inline shell snippets (`` `!cmd` `` in SKILL.md).** These execute on the host with no approval in Hermes. Hard-disabled in Friday. Agent-authored shell execution goes through the Docker sandbox with scoped credentials and the permission gate.

---

## ERPNext Work Objects: Port, Not Depend

Friday ports selected DocTypes from ERPNext into the Friday app. It does not install ERPNext as a dependency.

**Ported and renamed:**

| ERPNext Source | Friday Name | What's kept | What's dropped |
|---|---|---|---|
| Project | Agent Project | Container semantics, status, comments, timeline | Billing, timesheet coupling, customer accounting |
| Task | Agent Task | Assignment, priorities, dependencies, Kanban/list/Gantt | ERP-specific fields, invoice linking |
| Issue | Agent Issue | Blocker tracking, escalation routing | Customer-facing ticketing fields |

**Added to Agent Task:**
- `assigned_to_profile` (Link → Agent Profile)
- `required_skills` (child table)
- `risk_level`
- `approval_policy`
- `dispatchable_state` flag
- `current_execution` (Link → Execution Log)
- `war_room_channel`
- `automation_mode`
- `blocked_reason`

The ported DocTypes are Friday's own — they live in the Friday app, are maintained by the Friday team, and carry no ERPNext dependency.

---

## Raven: Communication Layer, Not Truth Layer

Raven owns: conversation, channels, direct messages, message reactions, file sharing, message actions, and real-time collaboration.

Friday owns: workflow truth, task state, execution truth, permissions, audit, approvals, sandboxing, and dispatcher decisions.

**War Room behavior:**
- One Raven channel auto-created per Agent Project on `after_insert`
- Agent Task state changes post to the channel
- Message Actions route through Friday permission checks before triggering any state change
- Raven messages are mirrored to Frappe Timeline where audit relevance exists
- Execution Log remains the legal and operational proof — not Raven

**Raven's existing AI agent flow (v2) is replaced.** Raven v2 dispatches AI agents via `frappe.enqueue(timeout=600)` against OpenAI Assistants. Friday intercepts this via a `doc_events` hook on Raven Message `on_update` and reroutes to the `agent_core` queue. This is done as a hook, not a Raven fork. Upstream Raven can be updated without breaking the integration.

---

## Flexible Workflow, Not Fixed Columns

Hermes' default lifecycle:
`Triage → Todo → Ready → In Progress → Blocked → Done`

Friday does not hardcode this. Real business workflows vary:

- Procurement: `Draft → Supplier Follow-up → Internal Review → Approval Needed → PO Drafted → Completed`
- Engineering: `Idea → Spec → Build → Review → Changes Requested → Merged`
- Research: `Question → Source Gathering → Synthesis → Review → Published`

**Friday's principle:** Kanban is a view, not the workflow.

The workflow is defined in Frappe Workflow. Kanban renders whatever states are configured. The dispatcher claims only tasks in states explicitly marked `dispatchable`. Agents move tasks only through transitions they are permitted to make.

---

## Dispatcher Contract

The dispatcher queries validated records. It does not infer the world from text.

Selection logic:
1. Find Agent Tasks whose workflow state is dispatchable
2. Exclude tasks with incomplete dependencies
3. Exclude tasks with pending approvals
4. Exclude tasks whose required skills are not Active status
5. Exclude Agent Profiles that are inactive or over resource quota
6. Match candidate Agent Profiles by required_skills ⊆ profile.permitted_skills AND role authorization
7. Atomically claim: `SELECT ... FOR UPDATE SKIP LOCKED`
8. Create an Execution Log row (status: running)
9. Emit real-time event to Agent Core Worker
10. Require terminal outcome: completed / blocked / failed / timeout / cancelled

This is where Friday becomes more reliable than prompt-led orchestration.

---

## Profile and Skill Governance

Agents may propose profiles, skills, tasks, and workflows. They may not silently activate safety-critical structure.

| Object | Agent May Propose | Human/Supervisor Must Approve |
|---|---|---|
| Agent Profile | Yes | Before Active |
| Agent Role Profile | Yes | Before Active |
| Skill | Yes (as Skill Draft) | Before Active |
| Skill Version | Yes | Before becoming default |
| Workflow | Yes | Before dispatchable |
| High-risk skill invocation | Yes | Before execution (Workflow Request) |

---

## Phase 1 Port Scope

**Required for v0.1:**
- Validated Agent Profile with linked Frappe User
- Validated Skill with DocType-based discovery
- Agent Project and Agent Task with configurable workflow
- Kanban rendered from workflow states
- Dispatcher claiming only dispatchable tasks
- Execution Log per run
- Task event history
- Basic block / unblock path
- Sandboxed execution path
- Manual approval path for high-risk skill calls

**Deferred:**
- Autonomous Skill Draft generation (learning loop)
- Full Raven War Room integration (if not included in v0.1 per spike decision)
- Complex memory (semantic + FTS dual index — pgvector installed but not yet used)
- Cross-site agent communication
- Hermes' gateway platform adapters (Telegram, Discord, etc.)
- Tirith command scanning

---

## Summary

> Hermes proves that durable multi-agent coordination beats fragile in-context subagent swarms.
>
> The real-world failure case proves the missing layer: typed, validated, governable business structure.
>
> Friday's answer: Hermes-style agent coordination rebuilt on Frappe DocTypes, flexible workflows, ERPNext-derived work objects, and Raven War Rooms — where agents execute inside a governed operating model instead of improvising one at runtime.
>
> The port is `run_agent.py` and `agent/`. Everything else — gateways, adapters, Kanban, cron, session storage, approval routing — Frappe and Raven provide.
