# 54 — Hermes Core → Friday Core: The Architecture Blueprint

**This is the master checklist. The port is DONE when every CORE row below is
✅ Built or 🚫 Not-needed.** No CORE row left ❌ / 🟡 / 🔨 = finished.

Doc 52 was the plain-English *map*. This is the engineering *blueprint*: every
core Hermes component, the exact Hermes file, its Friday home, and a status —
derived from reading the Hermes reference (`~/Documents/reference/hermes-agent/`),
not from memory.

### Status legend
| | meaning |
|---|---|
| ✅ | Built + working in Friday (most verified live on a bench) |
| 🟡 | Partly built; rest designed |
| 🔨 | Designed/locked, not coded |
| ❌ | **Missing — needed.** This is the real backlog. |
| 🚫 | Not needed — Frappe/Raven provides it, or out of v0.1 scope (done-by-deletion) |

### Scope tag
`CORE` = required for a working governed agent platform. `BIZ` = a business
capability you add on demand (a skill), not framework work. `OPT` = real Hermes
capability we can legitimately defer.

---

## 1. The scale truth — why 13.8k lines, not 900k

| Hermes subsystem | ~LOC | What Friday does with it |
|---|---:|---|
| `tests/` | 467k | Friday writes its own (329 tests) — not ported |
| `hermes_cli/` | 107k | **Mostly 🚫** — Frappe Desk + bench replace auth/backup/config UIs |
| `gateway/` | 81k | **One** gateway function; surfaces are thin Chat Message adapters |
| `tools/` | 69k | A handful become Skills; most are 🚫 consumer/dev tools |
| `agent/` | 66k | **The part we actually port** — cognition core |
| `plugins/` + `optional-skills/` | 65k | 🚫 — Skills are Friday's extension mechanism |
| `skills/` | 13k | The *mechanism* ports; the 300+ packs don't |
| `providers/` | 0.4k | → `LLM Provider` DocType |

**The strategy in one line:** port `agent/`'s cognition + the governance spine,
lean on Frappe for state/permissions/audit/jobs/UI, and add business tools as
Skills on demand. Everything tagged 🚫 below is *done by deciding not to build it.*

---

## 2. The blueprints

### 2.1 Cognition core (Hermes `agent/`) — the agent's brain

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| ReAct loop (think→act→observe) | `conversation_loop.py` | `agent_runner/runner.py` | ✅ | CORE |
| Iteration budget / grace call | `iteration_budget.py` | `MAX_REACT_ITERATIONS` | ✅ | CORE |
| Tool-call de-dup + deterministic ids | `run_agent.py` | `runner.py` `_deduplicate_tool_calls` | ✅ | CORE |
| Context compression (head/tail protect, summarise middle) | `context_compressor.py`, `conversation_compression.py`, `context_engine.py` | `llm/compression.py` + `Compaction Summary` | ✅ | CORE |
| Auxiliary (cheap) model | `auxiliary_client.py` | `Agent Settings.compression_model` | ✅ | CORE |
| Error classification + failover hints | `error_classifier.py` | `llm/error_classifier.py` | ✅ | CORE |
| Account / usage accounting | `account_usage.py` | `Execution Log.tokens_used` (no rollups) | 🟡 | CORE |
| File-write safety checks | `file_safety.py` | — | ❌ | OPT |

### 2.2 Model providers (Hermes `agent/*_adapter.py` + `providers/base.py`)

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| Declarative provider profile | `providers/base.py` `ProviderProfile` | **`LLM Provider`** DocType | ✅ | CORE |
| OpenAI / chat-completions (+ compat) | (built-in) | `OpenAIProvider` | ✅ | CORE |
| Anthropic Messages | `anthropic_adapter.py` | `AnthropicProvider` | ✅ | CORE |
| Minimax | (compat) | `MinimaxProvider` | ✅ | CORE |
| Gemini / Bedrock / Codex / Azure / xAI / ~35 more | `*_adapter.py` | — | 🚫 | BIZ (add a subclass per need) |
| Credential pool + key rotation | `credential_pool.py`, `credential_sources.py` | one key per `LLM Provider` row | 🚫 | — (single tenant) |

### 2.3 Governance (Hermes scatters it; Friday centralises — **this is our edge**)

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| Human approval | `tools/approval.py` | `approvals/` + `Workflow Request` (H2) | ✅ | CORE |
| Permission / allow-lists | (prompts) | `permissions/matrix.py` (deny-by-default on Frappe roles) | ✅ *(stronger)* | CORE |
| Immutable audit | (file logs) | `Execution Log` + `Permission Decision Log` | ✅ *(stronger)* | CORE |
| Container isolation | `tools/backend.py` | `sandbox/runner.py` + pool | ✅ | CORE |
| Scoped per-run credential token | (varies) | `sandbox/credentials.py` (H3) | ✅ | CORE |
| Threat / URL / shell-policy guards | `threat_patterns.py`, `url_safety.py`, `tirith_security.py`, `website_policy.py` | — | ❌ | OPT (hardening) |

### 2.4 Tools / capabilities (Hermes `tools/`) — the agent's hands

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| Tool auto-registration → schemas | `tools/registry.py` | `skills/loader.py` (a Skill **is** a tool) | ✅ | CORE |
| **Delegate / spawn sub-agents** | `tools/delegate.py` | — | ❌ | **CORE (multi-agent)** |
| **MCP client (external tool servers)** | `tools/mcp.py`, `mcp_oauth*.py` | — | ❌ | **CORE (integrations)** |
| Sandboxed skill execution | `code_execution_tool.py` | `sandbox/` (one skill today) | 🟡 | CORE |
| Shell / terminal | `terminal_tool.py` | — | 🚫 | — (disallowed v0.1) |
| Browser + computer-use | `browser*.py`, `computer_use_tool.py` | — | ❌ | BIZ |
| Memory tool (recall) | `tools/memory.py` | — | ❌ | OPT (learning loop) |
| Send-message / clarify | `send_message.py`, `clarify_tool.py` | gateway outbound | 🟡 | CORE |
| Todo / kanban / cron jobs | `todo.py`, `kanban_tools.py`, `cronjob_tools.py` | `tasks/` + Frappe scheduler + tracker | 🟡 | CORE |
| Web / search | `web_tools.py`, `x_search.py`, `session_search.py` | — | 🚫 | BIZ |
| Image / video / vision / TTS / voice | `image_generation.py`, `video_generation.py`, `vision_tools.py`, `tts.py`, `voice_mode.py` | — | 🚫 | BIZ |
| Integrations (Discord, Feishu, MS-Graph, HomeAssistant) | `discord.py`, `feishu_*.py`, `microsoft_graph_*.py` | — | 🚫 | BIZ (as Skills) |
| Checkpoint / interrupt | `checkpoint_manager.py`, `interrupt.py` | — | ❌ | OPT |

### 2.5 Skills + the Learning loop (Hermes' signature; Friday's biggest gap)

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| Skill format + menu | `SKILL.md`, `skills_sync.py`, `tools/registry.py` | `Skill` DocType + `skills/loader.py` | ✅ | CORE |
| Skill provenance / usage stats | `skill_provenance.py`, `skill_usage.py` | `Skill.usage_count` / `last_used` | 🟡 | CORE |
| Skill guard / AST audit (safe self-creation) | `skills_guard.py`, `skills_ast_audit.py` | — | ❌ | OPT |
| **Curator — promote/retire skills** | `curator.py` | — | ❌ | OPT |
| **Learner — draft new skills from experience** | `background_review.py`, `insights.py` | — | ❌ | OPT |
| **Memory / recall** | `memory_manager.py`, `memory_provider.py` | — | ❌ | OPT |
| The actual business skills | 300+ packs | **1** (`slice6-create-note`) | ❌ | **BIZ (your product)** |

> The three ❌ marked OPT here are the **learning loop** — "the thing that makes
> Hermes Hermes." It is the one *core-feeling* subsystem we can ship v0.1
> without. Decide explicitly: defer, or build after the agent fleet works.

### 2.6 Multi-agent orchestration (spread across Hermes; nascent in Friday)

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| In-loop sub-agents | `tools/delegate.py` | — | ❌ | CORE |
| Async task fleet (work items) | (cron + tools) | `tasks/` + `Project`/`Task`/`Issue` | 🟡 | CORE |
| Orchestrator (match work → agent) | (varies) | `tasks/dispatcher.py` `tick()` (skill-match) | 🟡 | CORE |
| Dependency-wait / blocked-on | (varies) | doc 53 D5 (Task.depends_on auto-raise) | 🔨 | CORE |
| Failure → governed ticket | — | D6 `Issue` auto-raise | ✅ | CORE |

### 2.7 Surfaces + gateway (Hermes `gateway/`, 25+ adapters)

| Hermes component | Hermes file | Friday home | Status | Scope |
|---|---|---|---|---|
| One gateway process / front door | `gateway/run.py` | `gateway/service.py` `handle_inbound` | ✅ | CORE |
| CLI surface | `hermes_cli/` | `cli/` (`friday chat`) | 🟡 | CORE |
| Raven (in-Frappe chat) | — | — | 🔨 | CORE |
| Telegram / Slack / Discord / WhatsApp / Signal / … | 25 adapters | thin Chat Message adapters | 🔨 | BIZ |
| Agent-to-agent (A2A / ACP) | `acp_adapter/` | — | 🔨 | OPT |

### 2.8 Execution backends (Hermes has 6; Friday needs 1)

| Hermes backend | Friday | Status | Scope |
|---|---|---|---|
| Docker | `sandbox/` | ✅ | CORE |
| local / SSH / Modal / Daytona / Singularity | — | 🚫 | — (one company, one safe runtime) |

### 2.9 CLI commands (Hermes `hermes_cli/`, 107k)

| Hermes command | Hermes file | Friday | Status | Scope |
|---|---|---|---|---|
| `chat` | `commands.py` | `bench friday chat` | ✅ | CORE |
| **`setup` (configure models/providers)** | `config.py`, setup flow | — | ❌ | **CORE (the `hermes setup` twin)** |
| `auth` / login | `auth_commands.py` | Frappe login | 🚫 | — |
| `backup` | `backup.py` | `bench backup` | 🚫 | — |
| `cron` | `cron.py` | Frappe `scheduler_events` | 🚫 | — |
| checkpoints / bundles / completion | various | — | 🚫/❌ | OPT |

---

## 3. What's ACTUALLY left — the finite CORE backlog

Strip out every 🚫 and 🟡-that's-fine, and the **entire remaining core port** is
this list. It ends.

1. **Business skills** — the agent can do 1 thing. This *is* your product (Draft). `BIZ` ❌
2. **`bench friday setup`** — the `hermes setup` twin (configure provider/model/profile in one command). Small. `CORE` ❌
3. **Multi-agent: `delegate` sub-agents + finish the tracker** (D5 dependency-wait wiring; the dispatcher already matches work→agents). `CORE` 🟡→❌
4. **Raven surface** — the first real human surface beyond CLI. `CORE` 🔨
5. **MCP client** — lets the agent use external tool servers (integrations without writing each one). `CORE` ❌
6. **Account/usage rollups + send/clarify polish.** `CORE` 🟡
7. **Hardening** — threat/url/file-safety guards (H-class). `OPT` ❌
8. **The learning loop** — Curator + Learner + Memory. The big one. `OPT` ❌ — *decide: defer or build last.*

Everything not on this list is either ✅ done or 🚫 deliberately not built.

---

## 4. The "DONE" definition (so this ends)

- **v0.1 governed agent platform is DONE** when items **1–4** above are ✅
  (skills for your business + a one-command setup + a working agent fleet + Raven).
  That is a *finite, shippable* target — the cognition core, providers, governance,
  sandbox, and gateway underneath are already ✅ and live-certified.
- **v1.0 framework is DONE** when **5–7** land (MCP, usage, hardening).
- **The learning loop (8)** is the explicit fork: it's what elevates Friday from
  "governed agent runner" to "self-improving agent platform." Ship v0.1/v1.0
  without it; build it when the fleet is proven.

Anything a future request asks for should map to a row here. If it doesn't, it's
either 🚫 (we don't build it) or a new row (amend this doc). **That is how the
port stops being infinite.**
