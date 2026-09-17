# 03 — Technical Stack

> See `00-glossary.md` for term definitions.
> See `39-friday-framework-strategy.md` for the fork-not-app framing.

---

## Stack

| Layer | Technology | Reason |
|---|---|---|
| Framework | Hard fork of Frappe v16 stable (`version-16` branch) | DocTypes, permissions, workflows, scheduler, RQ workers, Socket.io, REST API — agent primitives are patched into core, not bolted on top |
| Primary database | PostgreSQL 15+ | pgvector support, `jsonb` + GIN indexes, superior FTS, stronger multi-writer concurrency than MariaDB |
| Vector search | pgvector ≥ 0.8.2 | Semantic retrieval on Memory Entries and execution traces — no external vector DB |
| In-memory layer | Redis | Cache (permission matrices, Skill rows, ERPNext master data), RQ job queue, Socket.io pub/sub |
| Job queue | Frappe RQ (Redis-backed) | Standard Frappe; the agent loop runs on a dedicated `agent_core` queue and worker |
| Real-time | Frappe Socket.io + Redis pub/sub | Console events, Raven channel updates, Kanban state changes |
| Container runtime | Docker | Per-skill sandbox: non-root, network-restricted, resource-capped, ephemeral FS |
| Server language | Python 3.14 | Required by Frappe v16's `version-16` branch (`>=3.14,<3.15`) |
| Frontend language | JavaScript + Frappe UI + Vue components | Framework Console renders on Frappe Workspace primitives |
| Frontend toolchain | Node 24 LTS | Frappe v16 frontend requires Node ≥ 24; older versions fail `yarn install` |
| LLM access | Provider-agnostic adapter; Minimax M2 first, Anthropic/OpenAI/OpenRouter/local switchable per Agent Profile | Provider lock-in is rejected; provider choice is configuration |

---

## PostgreSQL, not MariaDB

Frappe defaults to MariaDB. Friday ships on PostgreSQL.

- `pgvector` gives native vector similarity — no Pinecone, no Weaviate, no second source of truth.
- `jsonb` with GIN indexes stores Skill parameter schemas and tool-call payloads efficiently.
- Postgres FTS replaces SQLite FTS5 (used in Hermes) for session and execution search.
- Multi-writer concurrency matters once the dispatcher claims tasks across many agents.

Cost: slightly higher resource footprint. Accepted.

## Redis is load-bearing in three roles

1. **Cache** in front of PostgreSQL — Skill rows, permission matrices, ERPNext masters.
2. **Queues** for all background work via Frappe RQ — agent runs, learning jobs, curator passes.
3. **Pub/sub** for real-time events — Raven channels, Framework Console, gateway message delivery.

Redis Stack is optional. If installed, hot Memory Entries can use in-RAM vector similarity with pgvector as cold storage. This is an optimisation, not a dependency.

## Docker is the sandbox boundary

Every skill invocation runs inside a fresh Docker container:

- **cgroups** cap CPU, memory, disk.
- **Network namespace** restricts egress to the Frappe REST API plus any explicitly allowed external endpoints.
- **Credentials** are scoped to the Agent Profile's permitted DocTypes and integrations — nothing more.
- **Filesystem** is ephemeral; skill content is mounted read-only; persistent writes go through the REST API.
- **Teardown** is immediate after execution. Nothing survives in the container.

This raises the security floor relative to Hermes' process-level isolation, where a compromised skill inherits the host user's authority.

## Why the Frappe fork, not FastAPI from scratch

Evaluated against FastAPI + custom permission layer, Django, and Flask:

- DocType system gives declarative schema with automatic CRUD, validation, hooks, and UI.
- Role-based permission engine — fine-grained, multi-role, per-document, hardened in production for years.
- Workflow engine — multi-state, multi-role approval chains, no extra code.
- Native Kanban view — Agent Tasks render as a board with no UI work.
- Real-time via Socket.io — out of the box.
- Background workers via Frappe RQ — out of the box.
- REST API auto-generated per DocType — no hand-written endpoints for CRUD.
- `bench execute` — invoke Python in site context for trusted admin paths.
- Multi-tenant — one bench, many sites, isolated per Friday deployment.

Rebuilding any of these is months of work that Frappe already shipped.

---

## Phase-staged components

| Component | Purpose | Phase |
|---|---|---|
| Tirith | Command-level threat scanning, inherited from Hermes | 2 |
| Whisper (local or API) | Voice transcription | 2 |
| TTS service | Spoken replies | 2 |
| Browser automation (Browserbase, Playwright, CDP) | Browser Task DocType + worker | 2 |
| MCP server clients | External tool integration via MCP Server DocType | 2 |
| Image generation (FAL.ai or local SD) | Image Generation Task DocType | 3 |

Phase 1 scope is fixed in `42-phase-one-authority-contract.md`. Anything not listed there is post-v0.1.

---

## Rejected technologies

- **MongoDB and schema-less stores.** Lose transactional guarantees and break Frappe's permission integration.
- **External vector databases (Pinecone, Weaviate).** Adds cost, complexity, and a second source of truth. pgvector is sufficient.
- **Heavy message brokers (RabbitMQ, Kafka).** Overkill for projected throughput. Redis + RQ holds until proven otherwise.
- **Reinventing Frappe primitives.** If the framework already provides workflows, permissions, scheduler, Kanban, or real-time, use it. New implementations of solved problems are rejected on sight.
