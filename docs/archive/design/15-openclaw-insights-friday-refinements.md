# 15 — OpenClaw Insights and Friday Refinements

> See `00-glossary.md` for term definitions.
>
> Source: Alex Krentsel, "Principles for Autonomous System Design: OpenClaw Deep Dive" (UC Berkeley NEXT seminar, March 30, 2026; expanded talk April 2026). The talk dissects OpenClaw's internal architecture and extracts principles for autonomous system design. Friday is not affiliated with OpenClaw, Krentsel, or UC Berkeley — the talk is cited because it crystallises principles the agentic community is converging on, and Friday reflects those principles where they fit an enterprise focus.

---

## 1. Six insights, six refinements

### Insight 1 — Three-layer architecture is the right shape

OpenClaw decomposes into:

- **Connectors** — platform interfaces (WhatsApp, Gmail, iMessage, plugins).
- **Gateway Controller** — sessions, memory, configuration, cron.
- **Agent Runtime** — LLM calls, tools, skills, providers.

**Friday position:** the structure (Raven adapters → Gateway → Agent Runner) is already the same shape. Confirmation, not change. The layers stay strictly separated: tools never bypass the Gateway; connectors never invoke skills directly.

---

### Insight 2 — Sessions as processes, plus a heartbeat

OpenClaw treats sessions like OS processes — own context, parallel execution, isolated permissions, optional sandboxing — plus two special sessions:

- **`main`** — admin session, full permissions, accessible via UI.
- **`heartbeat`** — auto-pings every 30 minutes, with a `HEARTBEAT.md` in context.

The heartbeat is OpenClaw's mechanism for autonomy: a periodic moment for the agent to check state, review pending work, and decide whether anything needs attention.

**Friday refinement:** add a Heartbeat Session pattern.

| Component | Detail |
|---|---|
| New fields on Agent Profile | `heartbeat_enabled` (Check), `heartbeat_interval_minutes` (Int, default 30) |
| Frappe Scheduler job | Every N minutes posts a "heartbeat poll" message to the agent's queue |
| Agent loop | On heartbeat: review recent Execution Logs, pending Tasks, escalations; return an action or `HEARTBEAT_OK` |
| New DocType | `Heartbeat Log` (submittable) records each heartbeat and what (if anything) the agent did |

Agents become proactively self-maintaining, not purely reactive.

---

### Insight 3 — Memory as tools, not context injection

OpenClaw deliberately does not inject memory into the system prompt. Memory is exposed only through `memory_search` and `memory_get` tools.

Reasons:

- **Relevance:** the model fetches only when needed.
- **Token budget:** always-injecting burns context every request.
- **Freshness:** the tool returns current indexed hits at decision time.
- **Safety:** broad auto-injection enlarges prompt-injection surface.

**Friday refinement:** memory is a tool, never an auto-injected context block.

| Tool | Purpose |
|---|---|
| `memory_search(query, limit=5)` | Top-N relevant entries from semantic memory (pgvector) |
| `memory_get(memory_id)` | Full content of a specific Memory Entry |
| `memory_list(filter)` | Recent memories matching a structured filter (agent, project, time) |
| `memory_save(content, tags)` | Persists a new Memory Entry the agent decides is important |

Skills reference memory tools in `instructions` so the agent knows when to call them.

---

### Insight 4 — Hard ceilings on Skill context

OpenClaw enforces:

- Maximum 150 skills in context at any time.
- Maximum 30,000 characters of skill content in context.
- Intelligent filter decides the subset.

Progressive disclosure:

- **L0:** header only (~3–4 lines), always in context.
- **L1:** body (skill instructions), fetched on demand.
- **L2:** linked files, fetched only when executing.

**Friday refinement:** bake the limits into the Skill Loader from day one.

| Constant | Value |
|---|---|
| `MAX_SKILLS_IN_CONTEXT` | 150 |
| `MAX_SKILL_CHARS_IN_CONTEXT` | 30000 |
| `L0_HEADER_MAX_LINES` | 4 |

Loader algorithm:

1. Gather all Active Skills permitted to the agent.
2. Rank by recency-of-use × success-rate × relevance-to-task.
3. Take top-K headers until either limit is reached.
4. Expose `skill_get(skill_name)` so the agent can pull L1/L2 on demand.

Cheap to enforce from day one. Expensive to retrofit.

---

### Insight 5 — Auto-configuration through conversation

OpenClaw bootstraps itself via `BOOTSTRAP.md` — the agent's first action is to talk to the user and discover its identity, persona, and preferences, writing them to `IDENTITY.md`, `USER.md`, `SOUL.md`.

> "The agent is becoming the interface for configuring itself."

**Friday refinement:** Agent Profiles can self-configure via War Room conversation. The DocType form remains; conversation is an alternative onboarding path.

| Step | Action |
|---|---|
| New Agent Profile in `Draft` status | Gateway spawns a one-time bootstrap conversation in War Room |
| Bootstrap agent runs a Skill `bootstrap_profile` | Asks supervisor: name, purpose, expected workload, preferred LLM, risk tolerance |
| Skill writes back to Agent Profile fields | Conversation persists as a normal Chat Message thread |
| When complete | Profile transitions to `Active` |

---

### Insight 6 — LLM-as-policy; don't over-prescribe

Krentsel's meta-observations:

- Design abstractions matter more than implementation polish.
- Don't over-prescribe architecture — let the LLM be the policy layer.
- The boundary between prompts, skills, and tools is unsettled — leave it pluggable.

**Friday refinement:** audit specs for over-prescription.

| Spec | Refinement |
|---|---|
| Detailed dispatcher matching algorithm | Specify the contract (inputs / outputs), not the algorithm — let it evolve |
| Hard-coded skill ranking heuristic | Make pluggable so deployments swap policies |
| Approval threshold logic | User-configurable rules, not hard-coded enums |
| Heartbeat behaviour | Don't prescribe what the agent does on heartbeat; let the model decide given context |

Friday provides primitives (skills, permissions, memory tools, sandbox). The LLM decides how to use them. Business logic does not get baked into Python where a Skill row would do the job.

---

## 2. OpenClaw choices Friday rejects

OpenClaw optimises for personal autonomy. Friday optimises for enterprise governance. Same architectural shape, opposite defaults.

| OpenClaw choice | Friday position |
|---|---|
| `.openclaw/cron/jobs.json` for scheduling | Frappe Scheduler — DocType-backed, role-permissioned, auditable |
| Markdown-only persona files (`USER.md`, `SOUL.md`) | Agent Profile DocType fields with audit history |
| Permissive session defaults | Least-privilege; sessions inherit Agent Role Profile permissions |
| SQLite session DB | PostgreSQL + Frappe DocTypes |
| Agent edits its own config files freely | Config changes gated through Workflow Request |

---

## 3. Phase mapping

Three insights affect Phase 1 scope per `42-phase-one-authority-contract.md`:

- **Insight 3 (memory as tool):** Phase 1 has minimal memory; the tool-only access pattern is locked in from `10-agent-execution-guide.md` slice 5. No memory context injection.
- **Insight 4 (Skill ceilings):** slice 3 (Skill Loader) enforces 150 / 30000 from day one.
- **Insight 6 (LLM-as-policy):** slice 2 (permission engine) exposes a contract, not a fixed algorithm.

Insights 1, 2, 5 (three-layer confirmation, heartbeat, auto-configuration) are Phase 2 or Phase 3 additions.
