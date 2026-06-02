# 52 — Hermes → Friday: The One-to-One Map

**Read this first. It is the single source of truth for the port.**

Hermes is a huge, sprawling AI-agent program (~900,000 lines, 300+ skills, 25+
chat apps, six ways to run it). Friday is **the same agent brain rebuilt as a
Frappe app** — so it lives inside your business system, uses Frappe's database,
roles, and background workers instead of its own, and only keeps the parts a
single company actually needs.

This doc maps **every part of Hermes** to **its place in Friday**, in plain
English. If a row says "Frappe already does this," that's not a gap — it means
we deleted work Hermes had to build itself.

---

## How to read the status column

| Symbol | Meaning |
|---|---|
| ✅ **Built** | Works in Friday today. |
| 🟡 **Partial** | Some of it works; the rest is designed. |
| 🔨 **Planned** | Designed and locked, not coded yet. (Feature letter = the locked design.) |
| 🚫 **Not needed** | Frappe or Raven already provides it, or it's out of scope for v0.1. |
| ❌ **Missing** | Hermes has it; Friday doesn't, and it isn't planned yet. |

---

## The 30-second answer: "what actually works as core today?"

Today, Friday can do this end-to-end, with a full audit trail:

> A message arrives → Friday checks the agent is **allowed** (Frappe roles) →
> runs a **multi-step loop** (call the model — **Minimax, OpenAI, or
> Anthropic** → run a skill in a **Docker sandbox** → observe → repeat, up to
> 15 steps) → **compresses** the history if it has grown too long → writes the
> reply back → logs every step (Execution Log + Permission Decision Log).

That is the working core. What it can't do **yet**: learn or create its own
skills — the **learning loop** (§9). That is the one big Hermes capability
Friday still lacks; everything else on the core thinking/serving path is built.

---

## 1. The thinking loop (the agent's brain)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| ReAct loop: call model → run tool → feed result back → repeat, up to **90 steps** (`run_agent.py`) | `agent_runner/runner.py` `run_turn()` — **full multi-step loop** | ✅ **Built** (Feature A) | Same loop, capped at **15 steps** (one company, not a research playground). Each step flows through the one dispatcher chokepoint. |
| De-duplicates identical tool calls in a turn; gives each a deterministic ID | `runner.py` `_deduplicate_tool_calls` / `_deterministic_call_id` | ✅ **Built** (Feature D) | Ported (within-response; cross-turn idempotency deferred). |
| Stops/interrupts, token budget, "grace call" | basic per-turn run | 🟡 | Frappe RQ job timeout + per-session lock replace the in-process budget. |

## 2. Talking to AI models (providers)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Declarative **`ProviderProfile`** (base_url, api_mode, auth type, default model…) in `providers/base.py` | **LLM Provider** DocType + `LLMProvider` base class (`llm/provider.py`) | ✅ | A provider is now a **database record** you edit in the Frappe admin screen — no code/YAML. |
| ~40 model plugins (OpenAI, Anthropic, Gemini, Bedrock, OpenRouter, DeepSeek, xAI, Minimax…) | **Minimax + OpenAI + Anthropic** | ✅ **Built** (Feature B1/B2) | The three Friday needs are built; the other ~37 are deliberately out of scope. A new native API = one subclass + one branch. |
| Transports: OpenAI chat-completions (default), Anthropic Messages, codex | Shared `_OpenAICompatibleProvider` base (Minimax/OpenAI) + native `AnthropicProvider` (Messages API) | ✅ | All adapters normalise tool calls to one canonical `{id, name, arguments}` shape before the runner sees them. |
| Credential **pool** + key rotation | one key per provider record (Frappe Password field) | 🚫 | Single tenant → no key pool. Secrets sit encrypted in the DocType. |

## 3. Tools the agent can use (built-in tools)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Tools auto-register (`tools/registry.py`) and are handed to the model as schemas | Skills become tool schemas via `skills/loader.py` `to_tool_definition()` | ✅ | In Friday a "tool" **is** a Skill (a DocType), not a Python file in a registry. |
| Browser control, computer-use, web search, shell | — | ❌ | Not built. Would arrive as Skills if a business case needs them. |
| **Delegate** tool — spawn sub-agents (`delegate_tool.py`) | — | ❌ | Friday has Agent Tasks (below) for async work instead of in-loop subagents. |
| **MCP** client + server (`mcp_tool.py`, `mcp_serve.py`) — connect any external tool server | — | ❌ | Not yet. A natural later add (Frappe could expose Skills over MCP). |
| Six **terminal backends**: local, Docker, SSH, Modal, Daytona, Singularity | Docker only (`sandbox/`) | 🚫 | One company, one safe runtime. The other five are deleted scope. |

## 4. Skills (the agent's playbooks)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| A skill = a folder with **`SKILL.md`** (name, description, when-to-use, tags) | **Skill** DocType (description, when_to_use, parameters schema, risk level, requires_approval) | ✅ | A skill is a **database record**, not a Markdown file. Same idea, Frappe-native. |
| Loads skills, picks relevant ones by description, injects into the prompt | `skills/loader.py` builds the per-agent menu, filtered by status **and** permissions, cached in Redis | ✅ | Each agent only sees the skills its **Frappe roles** allow — stronger than Hermes. |
| **300+ built-in + 100+ optional** skill packs (GitHub, research, finance, Apple, mlops…) | none shipped | 🚫 | Friday ships **its own business skills**; it doesn't need Hermes' consumer/dev packs. The *mechanism* is what we port. |
| **Self-creating & self-improving** skills — the agent writes new skills from experience and refines them | — | ❌ | **Not in Friday.** This is Hermes' signature "learning loop" (see §9). Biggest missing piece; design docs exist, code doesn't. |

## 5. Permissions & safety (the governance layer)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Command **approval** prompts, DM pairing, allow-lists | **Deny-by-default permission matrix** on Frappe roles (`permissions/matrix.py`) | ✅ | Friday reuses Frappe's enterprise **role/DocPerm** system. Far stronger than Hermes' approval prompts. |
| (logs to files) | **Permission Decision Log** + **Execution Log** — immutable DocTypes, every allow & deny | ✅ | Real audit trail a regulator can read. Core to Friday's whole point. |
| Per-skill risk, human approval | `requires_approval` flag on Skill → Workflow Request | 🔨 **H2** | Uses Frappe's native Workflow for human sign-off. |
| Container isolation | Docker sandbox + **scoped, short-lived token** per run (`sandbox/credentials.py`) | ✅ | The agent inside the box only gets a token good for that one job. |

## 6. Running skills safely (the sandbox)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Docker environment backend | `sandbox/runner.py` + **warm container pool** (`sandbox/pool.py`) | ✅ | Pre-warmed containers so skills start fast; OOM/timeout guarded. |
| Secrets passed to the tool | `sandbox/credentials.py` resolves per-(agent, skill) creds + scoped token | ✅ | Secrets decrypted from DocTypes, injected only into the sandbox. |
| (network open) | network egress lockdown | 🔨 **C2/L3** | Hardening accepted for a later pass. |

## 7. Talking to humans (surfaces & the gateway)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| **One gateway process** serves all chat apps (`gateway/run.py`) | **One gateway function** every message flows through (`gateway/service.py` `handle_inbound`) | ✅ | Same "one front door" idea, done as a Frappe `Chat Message.after_insert` hook + RQ. |
| 25+ platform adapters (Telegram, Slack, Discord, WhatsApp, Signal, Matrix, Teams, email…) | **CLI** built; Telegram/Slack/Raven/A2A designed | 🟡 → 🔨 | Each surface is a thin adapter that just **writes a Chat Message row**. Raven (Frappe's chat) is the main human surface. |
| Picks which agent answers | `routing/resolve.py` (today: platform's default agent) | ✅ | Grows into a routing DocType when a real adapter needs it. |
| Full **TUI** (Ink/React) + **web UI** + docs website | — | 🚫 | **Frappe Desk** is the admin UI; **Raven** is the chat UI. No custom UI to build. |
| Conversation continuity, per-session locking | per-session Redis lock in the pipeline | ✅ | One message per session at a time; no double-answers. |

## 8. Background & scheduled work

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Async work, parallel subagents, batch runner | **Agent Task** DocType run in a sandbox (`tasks/runner.py`), state machine Executing→Review/Blocked | 🟡 | Built, but the auto-trigger is a stub today (`register_task_runner` no-op); a scheduler tick / doc-event will drive it. |
| **Cron scheduler + "routines"** — natural-language scheduled jobs delivered to any platform | — | 🔨 | Will use Frappe's built-in **scheduler** instead of Hermes' own cron. |
| Kanban multi-agent board | — | 🚫 | Out of scope for v0.1. |

## 9. Memory & the learning loop (Hermes' signature — Friday's biggest gap)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Agent-curated **memory** (MEMORY.md / USER.md) + periodic "nudges" to save what it learned | — | ❌ | Not built. Design docs 22/29/32/34 explore it; no code. |
| **FTS5 full-text search** over all past conversations + LLM summaries for recall (`hermes_state.py`) | — | ❌ | Would become Frappe search over Chat Message rows. |
| Pluggable memory backends (Honcho, mem0, supermemory…) + Honcho **user modeling** | — | 🚫 | Too much for v0.1; revisit later as one Frappe-native memory store. |
| **Self-improving skills** (see §4) | — | ❌ | The headline "self-improving agent" capability is **entirely future work**. |

## 10. Remembering conversations (state & history)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| **SQLite SessionDB** — sessions + messages tables, on disk (`hermes_state.py`) | **Chat Message** DocType rows in Frappe's database | ✅ | Conversation history is just database rows now — backed up, searchable, admin-visible for free. |
| Profile-aware paths, `~/.hermes/config.yaml`, `.env` | **Agent Settings** + **LLM Provider** DocTypes | ✅ | All config lives in the database, edited in the admin screen. |
| Long conversations get **compressed** (protect head+tail, summarize the middle, mark "reference only") | `llm/compression.py` + **Compaction Summary** DocType | ✅ **Built** (Feature C) | Ported; summary stored as a durable `Compaction Summary` row, old turns flagged `compacted`. |
| Smart **error classification / failover** (retryable? compress? fall back?) | `llm/error_classifier.py` — one shared classifier; `MinimaxProvider` routes through it | ✅ **Built** (Feature F) | One shared classifier; no key-rotation (single tenant). |

## 11. Where it runs (deployment)

| In Hermes | In Friday | Status | How it changes for Frappe |
|---|---|---|---|
| Docker image + **s6 supervision**, docker-compose, **Nix** flake, Homebrew, install scripts, serverless (Modal/Daytona) | Runs as a normal **Frappe app on a bench** (Redis + Postgres + RQ workers) | 🚫 | The Frappe **bench** is the runtime and process supervisor. All of Hermes' packaging is replaced by `bench`. |
| Batch trajectory generation + trajectory compression (for training models) | — | 🚫 | Research feature. Not a business need. |

## 12. Friday-only additions (not in Hermes)

| In Friday | What it is | Status |
|---|---|---|
| **War Room** (`warroom/publisher.py`) | Posts every Agent Task status change into a Raven chat channel so a human team watches the agents work | ✅ (activates when Raven is installed) |
| **Everything-is-a-DocType** | Agents, skills, providers, messages, logs are all Frappe records — editable, permissioned, audited, backed-up natively | ✅ |
| **Immutable audit logs** | Execution Log + Permission Decision Log are first-class, not an afterthought | ✅ |
| **Project / Issue tracker** (`doctype/issue`, `issues/raise_issue.py`) | Generic Project/Task/Issue work objects + an *agent* issue tracker that auto-raises an Issue on a task failure or cross-agent dependency-wait. Ported from ERPNext (port, not depend) — doc 53. | 🟡 (Issue + auto-raise built; the rename + dependency wiring are next) |

---

## What to build next (the short version)

In order, each already has a locked design:

1. ✅ **Feature A** — multi-step thinking loop (§1) — *done*.
2. ✅ **Feature F** — error classifier (§10) — *done*.
3. ✅ **Feature D** — tool-call de-dup + IDs (§1) — *done*.
4. ✅ **Feature B1 / B2** — OpenAI + Anthropic providers (§2) — *done*.
5. ✅ **Feature C** — conversation compression (§10) — *done*.
6. Finish the **Project/Issue tracker** (§8 / doc 53) — rename to generic Project/Task, add `depends_on`, wire the Dependency-Wait + Failure auto-raise. ← **next**
7. **H2/H3** — approval workflow + scoped-token polish (§5).

The whole **Hermes-core feature block (A, F, D, B1, B2, C) is now built.** What
remains is the tracker port, the two HIGH security items, and — further out —
the learning loop.

Further out (currently ❌): the **learning loop** (§9) — memory, recall, and
self-improving skills. That is what makes Hermes "Hermes"; decide later if and
how Friday wants it.

---

## Glossary (plain English)

- **DocType** — a Frappe "table"/record type. A form + a database table + permission rules, all in one.
- **Skill** — one thing the agent knows how to do (e.g. "create a Note"). In Friday it's a DocType.
- **Gateway** — the single front door every incoming message passes through.
- **Sandbox** — a locked Docker box where a skill runs so it can't touch anything it shouldn't.
- **Matrix / permission check** — the yes/no gate: "is this agent allowed to do this?"
- **RQ** — Redis Queue, Frappe's built-in background-job system.
- **Raven** — the open-source chat app (like Slack) that runs inside Frappe; Friday's main human chat surface.
