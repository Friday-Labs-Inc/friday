# 02 — Feature Comparison

> See `00-glossary.md` for all term definitions.
> Hermes Agent and OpenClaw are the two upstream agent frameworks Friday draws from. This document maps capability-by-capability what Friday keeps, replaces, or adds when re-implementing those patterns on Frappe v16.

---

## Core Agent Capabilities

| Feature | Hermes | OpenClaw | Friday |
|---|---|---|---|
| Agent loop (perceive → plan → act) | AIAgent class | yes | Inherited from Hermes; runs on Agent Core Worker |
| Skill system | Markdown + manifests | Skill registry | Skill DocType (database-backed, governed) |
| Self-improving skills | Autonomous Curator | limited | Skill Draft DocType + human-review workflow |
| Multi-agent / sub-agents | Kanban dispatcher | yes | Agent Project + Agent Task + Dispatcher |
| Cron / scheduled jobs | jobs.json + 60s tick | yes | Frappe Scheduler + RQ workers |
| Memory (persistent) | FTS5 + optional vector | Markdown + optional vector | PostgreSQL + pgvector |
| User modeling | Honcho integration | none | User Model DocType |
| Skill curation | Autonomous Curator | none | Background job + Skill status flags |

## Messaging & Platforms

| Feature | Hermes | OpenClaw | Friday |
|---|---|---|---|
| Telegram, Discord, Slack, WhatsApp, Signal | yes | yes | Adapter writes Chat Message DocType |
| Email (IMAP/SMTP) | yes | partial | Frappe native email |
| MS Teams / Google Chat | yes | none | Adapter writes Chat Message DocType |
| CLI / TUI | yes | yes | Phase 1 primary surface |
| Web UI | third-party | native | Framework Console (Frappe Workspace + custom views) |
| Voice in/out | Whisper + TTS | partial | Voice via attachment workflow |

## Tooling

| Feature | Hermes | OpenClaw | Friday |
|---|---|---|---|
| Terminal / shell execution | multiple backends | yes | Sandboxed in Docker |
| Browser automation | Browserbase, CDP | yes | Browser Task DocType + worker |
| Web search | yes | yes | yes |
| Vision (image analysis) | yes | yes | Vision Task DocType |
| Image generation | FAL.ai | partial | Image Generation Task DocType |
| File I/O | yes | yes | yes (sandboxed FS) |
| MCP server support | yes | partial | MCP Server DocType registration |

## Governance & Security

| Concern | Hermes | OpenClaw | Friday |
|---|---|---|---|
| Role-based permissions | config only | config only | **Frappe role matrix, enforced at the gateway before dispatch** |
| Agent isolation | HERMES_HOME folder | folder-based | Agent Profile DocType + Docker container per skill invocation |
| Audit trail | log files | log files | Execution Log + Permission Decision Log (immutable, submittable) |
| Approval workflows | Slack/Telegram buttons | partial | Workflow Request DocType + Frappe Workflow |
| Sandboxing | process-level | process-level | Docker, non-root, network-restricted, scoped credentials |
| Secret management | .env files | .env files | Frappe Password field type + integration tokens |
| Command-level threat scanning | Tirith | partial | Tirith inherited; permission pre-check added |
| Resource quotas / rate limits | limited | limited | Frappe rate limiter + cgroups |

## Persistence & Data

| Feature | Hermes | OpenClaw | Friday |
|---|---|---|---|
| Session storage | SQLite + FTS5 | SQLite | PostgreSQL (Frappe) |
| Vector embeddings | optional, plugin | optional | pgvector, first-class |
| Skill storage | Markdown files | Registry + files | Skill DocType (queryable, versioned) |
| Real-time pubsub | custom | custom | Redis pub/sub + Socket.io (Frappe native) |
| Background jobs | custom scheduler | custom | Frappe RQ workers |

---

## Decisions

**Inherited from Hermes (re-implemented on Frappe primitives, not ported as code):**

- Multi-platform unified gateway pattern (adapters + GatewayRunner)
- Progressive-disclosure skills (L0/L1/L2) — stored as DocType fields, not files
- Cron with natural-language scheduling
- Approval routing for high-risk commands
- Tirith command-level security scanning
- Model fallback and provider switching
- Sub-agent spawning for parallel workstreams
- Honcho-style user modeling
- MCP server integration
- Full-text session search (PostgreSQL FTS, not SQLite FTS5)

**Replaced (Hermes pattern → Friday primitive):**

- Custom Kanban + SQLite → Agent Project + Agent Task + Frappe Kanban view
- Markdown skill files in `~/.hermes/skills/` → Skill DocType
- `jobs.json` cron → Frappe Scheduler
- `HERMES_HOME` profile folders → Agent Profile DocType + scoped database access
- Log files for audit → Execution Log DocType
- Custom WebSocket for live dashboards → Frappe Socket.io + Redis pub/sub
- `.env` for secrets → Frappe Password fields + integration tokens

**Net-new in Friday (not present in either upstream):**

- Permission enforcement at the gateway, before a skill is queued
- Skill schema with explicit status flags (Active / Draft / Experimental / Retired)
- Skill Version rows for immutable rollback
- Frappe Workflow-based approval chains (multi-step, multi-role)
- Per-Agent-Profile resource quotas via Frappe rate limiter
- Native multi-tenant: one Friday installation hosts multiple isolated sites
- Framework-level agent primitives — not an installable app, part of the fork
