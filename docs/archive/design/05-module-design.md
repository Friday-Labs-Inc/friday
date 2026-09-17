# 05 — Module Design

> **⚠️ Authority & v0.1 status.** This document lists the *target* module + DocType
> structure, including modules and DocTypes that are not yet built. **The real `friday_core/`
> tree and schema differ** — the **AS BUILT** notes below mark every gap. This was the *root
> cause* of the foundations drift (doc 49 finding **M1**): code was written against the ghosts
> on this page. [Doc 42](42-phase-one-authority-contract.md) is the v0.1 scope authority;
> [doc 49](49-foundations-deviation-audit.md) audits the drift. Verified against `main @ 0f2cdd9`.

> See `00-glossary.md` for term definitions.
> See `45-fork-policy.md` for the one-repo kernel model and `39-friday-framework-strategy.md` for the fork-not-app framing.
> See `14-integrated-architecture.md` for request flow and runtime architecture (this doc covers structure, not flow).
> See `42-phase-one-authority-contract.md` for v0.1 scope.

---

## Layering

| Layer | Owns |
|---|---|
| Friday Framework Core | Frappe v16 fork — runtime, bench/site/app lifecycle, Desk shell, auth, DocTypes, ORM, permissions, workflows, scheduler, RQ, Socket.io, REST API, agent-native core primitives |
| Friday Core (agent kernel) | Agent Profile, Agent Role Profile, Skill, Execution Log, Permission Decision Log, Workflow Request, Gateway, Dispatcher, Sandbox runtime, LLM Provider adapters — built into the framework, not an installable app |
| Friday Apps | ERPNext operations (ported), Raven bridge, memory/wiki, analytics, specialist agents, auto-research, multi-site communication — installable on top |

Friday Core is part of the fork. Removing or disabling it is not supported. Friday Apps are installable and optional.

---

## Module layout

Agent kernel modules live inside the Frappe source tree per `45-fork-policy.md` (one-repo kernel model).

**AS BUILT (`main @ 0f2cdd9`).** This is the real `friday_core/` tree. Note two structural
differences from the earlier plan: (1) all DocTypes live in **one central `doctype/`**
directory, not in per-module `doctype/` subfolders; (2) the directory names differ from the
plan below (`agent_runner/` not `agents/`, no `messaging/` / `approvals/` / `memory/` /
`tools/` / `api/v1/`).

```
frappe/friday_core/
├── doctype/         ← ALL agent-kernel DocTypes live here (agent_profile, skill,
│                       agent_task, execution_log, permission_decision_log, chat_message, …)
├── gateway/         ← unified inbound chokepoint (service.handle_inbound), run-turn pipeline
├── agent_runner/    ← profile-scoped runner + skill dispatcher (the chat execution path)
├── skills/          ← Skill schema + loader (governed-skill resolution)
├── tasks/           ← agent project / task / dispatcher / workflow
├── permissions/     ← permission matrix engine + decision log writer
├── sandbox/         ← Docker runner, limits, credentials
├── llm/             ← LLM provider adapters
├── routing/         ← surface/intent routing
├── warroom/         ← Raven War Room publisher
├── cli/             ← friday CLI surface
└── tests/           ← module tests
```

**PLANNED (target — NOT as built).** The tree below is the longer-term module vision. Several
of these directories do **not exist** yet (`messaging/`, `approvals/`, `memory/`, `tools/`,
`api/v1/`) and several DocTypes are not built (see the DocType notes further down). Keep it as
a roadmap, not a map of today's code.

```
frappe/friday_core/
├── gateway/                ← session orchestrator, prompt builder, response delivery
├── agents/                 ← profile + execution            (built as agent_runner/)
├── skills/                 ← schema, loader, curator, learner
├── tasks/                  ← agent project / task / dispatcher
├── messaging/              ← platform adapters               (NOT built — see routing/, cli/)
├── approvals/              ← human-in-the-loop               (NOT built — Workflow Request unbuilt)
├── memory/                 ← long-term store, pgvector       (NOT built — out of v0.1 scope)
├── tools/                  ← browser, vision, image gen, MCP (NOT built — Phase 2)
├── permissions/            ← gateway permission engine + decision log
├── sandbox/                ← Docker runner, cgroups, network isolation
└── api/v1/                 ← REST endpoints used by containers (NOT built as a module)
```

Phase 2 and later modules (browser, vision, image gen, MCP, multi-platform messaging) are
roadmap per `42-phase-one-authority-contract.md` staging — they are not shipped in v0.1.

---

## Phase 1 DocTypes

### Agent Profile

Types corrected to the **as-built** `agent_profile.json`. ⚠️ rows mark drift.

| Field | Type | Notes |
|---|---|---|
| `profile_name` | Data | Unique |
| `description` | Text | |
| ~~`agent_role_profile`~~ | ⚠️ **not built** | Earlier draft listed `Link → Agent Role Profile`. No such field exists; native Frappe roles are used instead (doc 49 §3). Reading it raised `AttributeError` (finding **M5**). |
| `assigned_roles` | Table → Has Role | Roles set explicitly on the profile |
| `model_provider` | Link → LLM Provider | Pluggable via provider adapter interface |
| `model_name` | Data | Specific model identifier |
| `system_prompt` | Long Text | Persona / SOUL |
| `permitted_skills` | Table → Agent Profile Skill | Explicit Skill whitelist (child table) |
| ~~`resource_quota`~~ | ⚠️ **not built** | Earlier draft listed a `Section` for CPU/memory/tokens/wall-clock. No such field exists; sandbox limits fall back to hard-coded defaults (finding **M2**). |
| `network_allowlist` | Small Text ⚠️ | **Not a Table** — newline-delimited hosts as built |
| `requires_approval_above_risk` | Select | low / medium / high / always. Field exists; enforcement unbuilt (**H2**). |
| `status` | Select | Active / Suspended / Retired |

### Skill

| Field | Type | Notes |
|---|---|---|
| `skill_name` | Data | Unique |
| `description` | Text | Used for L0 matching |
| `when_to_use` | Long Text | L1 disclosure |
| `instructions` | Long Text | L2 disclosure |
| `parameters_schema` | JSON | OpenAPI-compatible |
| `required_doctypes` | Table | Permission inputs |
| `required_operations` | Table | read / write / submit / cancel |
| `risk_level` | Select | low / medium / high / critical |
| `requires_approval` | Check | Auto-creates Workflow Request when set |
| `status` | Select | Active / Draft / Experimental / Retired / Archived |
| `current_version` | Link → Skill Version | Active version pointer (rollback target) |
| `usage_count` | Int | Read-only, updated by hook |
| `last_used` | Datetime | Read-only |
| `created_by_agent` | Link → Agent Profile | Set when learned |

### Agent Task

| Field | Type | Notes |
|---|---|---|
| `title` | Data | |
| `description` | Long Text | |
| `project` | Link → Agent Project | |
| `assigned_to_profile` | Link → Agent Profile | Set by dispatcher |
| `required_skills` | Table → Skill | Dispatcher matching input |
| `workflow_state` | Link → Workflow State | Per Frappe Workflow |
| `dispatchable` | Check | True only when current state is in the dispatchable set |
| `priority` | Select | low / normal / high / urgent |
| `dependencies` | Table → Agent Task | Blocking dependencies |
| `current_execution` | Link → Execution Log | Active run, if any |
| `result` | Long Text / JSON | |
| `started_at`, `completed_at` | Datetime | |

### Chat Message

| Field | Type | Notes |
|---|---|---|
| `session_id` | Data ⚠️ | **Not** `Link → Agent Session` — Agent Session is not a v0.1 DocType; conversation identity is a plain `Data` string |
| `platform` | Link → Chat Platform | CLI (Phase 1); Telegram/Discord/Slack/etc. (Phase 2) |
| `direction` | Select | inbound / outbound |
| `sender_id` | Data | Platform-specific |
| `agent_profile` | Link → Agent Profile | Set for outbound |
| `content` | Long Text | |
| `attachments` | Table | |
| `timestamp` | Datetime | |
| `processed` | Check | |

### Execution Log

| Field | Type | Notes |
|---|---|---|
| `agent_profile` | Link | |
| `skill` | Link | |
| `task` | Link → Agent Task | Optional |
| `parameters` | JSON | Masked at the boundary |
| `result` | JSON | |
| `status` | Select | success / failed / rejected / timeout |
| `permission_decision` | Link → Permission Decision Log | |
| `duration_ms` | Int | |
| `tokens_used` | Int | |
| Submittable | Yes | Append-only audit trail |

### Permission Decision Log

| Field | Type | Notes |
|---|---|---|
| `agent_profile` | Link | |
| `skill` | Link | |
| `decision` | Select | allowed / denied |
| `reason` | Text | Free-text explanation from the permission engine |
| `matrix_snapshot` | JSON | Permission matrix at decision time |
| `decided_at` | Datetime | |
| Submittable | Yes | Append-only audit trail |

### Workflow Request

> **AS BUILT.** In scope per [doc 42 §3](42-phase-one-authority-contract.md) but **not yet
> built** — zero occurrences in code (doc 49 finding **H2**). The schema below is the target;
> a future slice must create it before any `requires_approval` skill is activated.

| Field | Type | Notes |
|---|---|---|
| `agent_profile` | Link | |
| `skill` | Link | |
| `parameters` | JSON | |
| `risk_level` | Select | |
| `requested_at` | Datetime | |
| `approved_by` | Link → User | |
| `decision` | Select | approved / rejected / expired |
| `decision_reason` | Text | |

---

## Background jobs

The runtime architecture and request flow are in `14-integrated-architecture.md`. The jobs below are scheduled work that does not appear there.

> **AS BUILT.** The **Curator and Learner are out of v0.1 scope.** [Doc 42 §4](42-phase-one-authority-contract.md)
> explicitly excludes the "autonomous skill activation or learning loop that changes active
> skills" and semantic-memory queries. Neither job is wired in `hooks.py` today (the real
> `scheduler_events` runs only the task dispatcher). Treat the two jobs below as roadmap.

### Curator (daily)

```
1. Skill where status='Experimental' and created_at < 30 days ago
   - usage_count > threshold and success_rate > 80% → promote to 'Active'
   - else → 'Archived'
2. Skill where status='Active' and last_used < 90 days ago
   → 'Retired'
3. Detect overlapping skills (description embedding similarity)
   → flag for human consolidation
4. Write curator run report as a DocType row
```

### Learner (every 6 hours)

```
1. Successful Execution Logs from the last 6 hours
2. Cluster by similar task patterns (embedding similarity)
3. Per cluster:
   - no Skill covers it → create Skill Draft
   - more efficient pattern emerged → propose Skill Draft edit
4. Notify supervisor role to review Skill Drafts
```

Skill Drafts never activate without supervisor approval.

---

## REST API surface

All endpoints under `/api/method/friday.api.v1.*`. Used by sandbox containers and external integrations. Every endpoint authenticates with a Frappe API key scoped to one Agent Profile and re-runs the permission check server-side.

> **AS BUILT.** This endpoint surface is the *target*; there is **no `api/v1/` module** in
> `friday_core/` today (see the module tree above). `memory.search` (pgvector) is **out of v0.1
> scope** per [doc 42 §4](42-phase-one-authority-contract.md). Treat this table as roadmap.

| Endpoint | Purpose |
|---|---|
| `skills.list` | Paginated, filtered by the calling agent's permissions |
| `skills.invoke` | Execute a skill (synchronous) or queue and return `job_id` |
| `tasks.claim` | Atomic claim of the next dispatchable task for this profile |
| `tasks.update_state` | Workflow state transition |
| `messages.send` | Outbound message — writes a Chat Message row |
| `memory.search` | Semantic search via pgvector |
| `permissions.check` | Explicit permission probe for agent planning |

---

## Hooks wiring (`hooks.py`)

**AS BUILT (`main @ 0f2cdd9`).** Two corrections from earlier drafts: the module prefix is
`frappe.friday_core.` (not `friday.`), and the inbound chokepoint is
**`gateway.service.handle_inbound`** (not the fictional `gateway.session_manager.on_new_message`).
There are **no** curator/learner scheduler entries (those jobs are out of v0.1 scope, above).

```python
doc_events = {
    "Agent Profile": {
        "on_update": [
            "frappe.friday_core.permissions.cache.invalidate_for_profile",
            "frappe.friday_core.skills.loader.invalidate_for_profile",
        ],
    },
    "Role": {
        "on_update": [
            "frappe.friday_core.permissions.cache.invalidate_all",
            "frappe.friday_core.skills.loader.invalidate_all",
        ],
    },
    "Skill": {
        # on_update only — no after_insert; method is invalidate_for_skill
        "on_update": "frappe.friday_core.skills.loader.invalidate_for_skill",
    },
    "Chat Message": {
        # The unified gateway chokepoint — every inbound message from any
        # surface (CLI, Telegram, Slack, Raven, A2A) lands here.
        "after_insert": "frappe.friday_core.gateway.service.handle_inbound",
    },
    "Agent Task": {
        "on_update": "frappe.friday_core.tasks.workflow.on_state_change",
    },
}

scheduler_events = {
    "cron": {
        # Every 60 seconds — task dispatcher claims dispatchable tasks.
        "*/1 * * * *": ["frappe.friday_core.tasks.dispatcher.tick"],
        # Sweeps orphaned inbound Chat Messages (async-dispatch recovery).
        # "<cron>": ["frappe.friday_core.gateway.recovery.sweep_orphans"],
    },
}
```

The dispatcher fires every 60 seconds. Cache-invalidation hooks keep the permission matrix and
skill loader fresh when an Agent Profile, Role, or Skill changes.

---

## What this module list is not

- It is not a runtime architecture diagram — see `14`.
- It is not an end-to-end request flow — see `14` §request flow.
- It is not a port-plan — see `41-porting-strategy-hermes-erpnext-raven.md`.
- It is not v0.1 scope — see `42-phase-one-authority-contract.md`.

This document defines what modules exist and what DocTypes they own. Everything else has a canonical home.
