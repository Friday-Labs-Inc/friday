# Friday Architecture

Friday is a governed agentic framework built on Frappe. This document gives a high-level overview of how the pieces fit together.

For deep dives, see the [Design Documents Index](design/00-README.md).

---

## System Overview

```
User → CLI / API → Gateway → LLM → Skill Loader → Permission Engine
                                                       ↓
                                         Allowed?  ──→ Dispatcher → Sandbox → Frappe API
                                         Denied    ──→ Execution Log (rejected)
```

The agent is **stateless** between turns. All state lives in Frappe DocTypes.

---

## Core DocTypes

| DocType | Role |
|---------|------|
| **Agent Profile** | Defines a single agent identity — permitted skills, LLM provider, system prompt |
| **Agent Role Profile** | Groups Frappe roles for RBAC permission resolution |
| **Skill** | A callable tool with a handler, schema, and risk level |
| **Skill Credential** | Per-skill secrets injected into the sandbox at runtime |
| **Agent Project** | Groups related tasks under a business objective |
| **Agent Task** | A unit of work tracked through a Kanban workflow |
| **Chat Message** | A single inbound or outbound message in a session |
| **Chat Platform** | A delivery channel (CLI, webhook, etc.) |
| **Execution Log** | Record of every skill execution attempt (success/failed/rejected) |
| **Permission Decision Log** | Record of every permission check |

---

## Modules

### `friday.friday_core.gateway`
Receives inbound messages from chat platforms and routes them to the agent runner.

- Subscribes to `chat_message.after_insert` via Frappe hooks
- Resolves Agent Profile from Chat Platform default
- Calls the runner and emits the outbound response

### `friday.friday_core.llm`
LLM provider abstraction layer.

- `LLMProvider` ABC — swap providers without changing agent logic
- Minimax M2 adapter included; others can be added
- Prompt builder assembles system prompt + history + current message
- All API keys stored in DocType (Password field, encrypted at rest)

### `friday.friday_core.skills.loader`
Loads the skill manifest for a given Agent Profile.

- Reads from DB, filters by `status='Active'` and permission matrix
- Cached in Redis with 5-minute TTL
- Invalidated on Skill or Agent Profile changes

### `friday.friday_core.permissions.matrix`
Role-based permission engine.

- Computes a `PermissionMatrix` per profile (which roles grant which DocType ops)
- Caches in Redis; invalidated on role or profile changes
- Every call writes a `PermissionDecisionLog` row

### `friday.friday_core.agent_runner.dispatcher`
Executes a skill call from the LLM.

1. Parse the tool call (skill name + parameters)
2. Call `permissions.matrix.check(profile, skill)` → decision
3. If allowed: execute the skill handler
4. Write `ExecutionLog` row
5. Return result to the LLM

### `friday.friday_core.sandbox`
Docker-based skill execution environment.

- Skills run in ephemeral containers (no persistent state)
- Network isolation: only Frappe API is reachable
- CPU/memory limits enforced by Docker
- Scoped API tokens injected at runtime (short-lived, profile-scoped)
- Warm container pool for sub-second cold starts

### `friday.friday_core.tasks`
Async task dispatch and execution (Slice 8).

- **Workflow hook** — derives `dispatchable` from workflow state on every Agent Task save
- **Dispatcher** — cron job (every 60s) that claims pending tasks via `FOR UPDATE SKIP LOCKED` and matches them to profiles
- **Runner** — listens on Redis pub/sub for `agent_task.assigned` events, executes in sandbox, transitions state

### `friday.friday_core.doctor`
System health checks.

- Verifies all required DocTypes exist
- Checks agent supervisors have correct roles
- Warns on misconfigured LLM providers

---

## Security Model

See [04-security-model.md](design/04-security-model.md) for the full threat model.

Key layers:
1. **RBAC via Frappe roles** — Agent Profiles have Frappe roles; permissions checked before any operation
2. **Gateway pre-check** — skills validated before dispatch
3. **Docker sandbox** — skill code cannot reach the host or external network
4. **Scoped credentials** — per-execution API tokens, never long-lived
5. **Audit trail** — every permission decision and skill execution is logged

---

## Data Flow — Single Chat Turn

```
1. User sends message via CLI / webhook
2. Gateway writes ChatMessage (direction=inbound)
3. Gateway hook fires on chat_message.after_insert
4. Resolve Agent Profile from Chat Platform
5. Build prompt (system + history + current message)
6. Call LLM → receives tool call or text reply
7. If tool call:
   a. Permission check
   b. If allowed: execute skill → return result
   c. If denied: log rejection → return denial message
8. Write ChatMessage (direction=outbound) with reply
9. Gateway hook fires → prints reply to user
```

---

## Configuration Checklist

1. At least one **LLM Provider** with a valid API key
2. **Agent Settings** has a default LLM Provider
3. **Agent Profile** linked to LLM Provider, with permitted skills
4. Agent Profile's roles grant the necessary DocType permissions
5. Skills are `Active` with handlers registered
6. Docker running (for sandbox mode)

---

## Slice Roadmap

| Slice | What's Built |
|-------|-------------|
| Slice 1 | DocType skeletons |
| Slice 2 | Permission engine |
| Slice 3 | Skill loader |
| Slice 4 | Gateway + CLI adapter |
| Slice 5 | LLM integration (Minimax) |
| Slice 6 | First skill (`create_note`) |
| Slice 7 | Docker sandbox |
| Slice 8 | Agent Task + Kanban + Dispatcher |
| Slice 9 | Polish, docs, CI (you are here) |

See [ROADMAP.md](ROADMAP.md) for Phase 1.5 and Phase 2 plans.

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md). AI agents are welcome under the published AI Contributors Policy.