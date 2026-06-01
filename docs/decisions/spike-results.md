# Spike Results — D1 through D8

> **Status:** All decisions resolved.
> **Date:** 2026-05-17
> **Method:** Owner review — decisions made by project owner based on product goals, not from a throwaway PoC. The spike PoC is skipped; decisions are recorded directly.

---

## D1 — Frappe Version

**Decision: Frappe v16 stable**

Frappe v16 is the current stable release with the longest support window. Friday forks from v16 stable as its starting point.

---

## D2 — Database

**Decision: PostgreSQL**

PostgreSQL with the pgvector extension is the database from day one. This enables AI-powered memory search (finding things by meaning, not just exact name) which is central to Friday's agent intelligence. The extra setup cost upfront is worth it — retrofitting pgvector onto MariaDB later would be far harder.

---

## D3 — Raven

**Decision: Excluded from v0.1. CLI-first.**

Friday v0.1 has no chat UI. Agents are triggered and tested from the bench CLI. Raven (the messaging/chat layer) ships in v0.2 once the core framework is proven. This keeps the first build focused on what matters: the governed execution loop.

---

## D4 — Business-Automation Use Cases

**Decision: Not relevant to this phase.**

Business-process automation is a use case, not a framework requirement. It does not affect how we build the agent runtime, permissions, skills, sandbox, or audit layer. Deferred entirely until the framework is working.

---

## D5 — CLI Strategy

**Decision: Extend bench with a `friday` command group**

No custom entrypoint. Friday adds its commands to the existing `bench` CLI that Frappe developers already know. Example: `bench --site mysite friday run-skill skill_name`. Clean, no new tools to install.

---

## D6 — LLM Provider

**Decision: Provider-agnostic from day one. Minimax as the primary provider.**

Friday talks to any LLM through one standard interface. Swapping the provider changes one config value, not the code. Minimax is the first provider wired up — strong multilingual support suits Indian business users. Claude, OpenAI, Gemini and others can be added through the same interface without touching Friday's core.

---

## D7 — Sandbox Backend

**Decision: Docker**

Docker is already installed on the development machine. Each agent runs in an isolated Docker container — its own locked room with scoped credentials, no access to the host filesystem, and resource limits enforced. Standard, proven, sufficient for v0.1.

---

## D8 — Fork Strategy

**Decision: Hard fork of Frappe v16 stable**

Already recorded in `39-friday-framework-strategy.md`, `40-gap-analysis-and-resolution-plan.md`, `42-phase-one-authority-contract.md`, `44-technical-feasibility-spike.md`, and `45-fork-policy.md`. Friday IS the fork. The full bench ecosystem is retained. Agent-native primitives are built into framework core.

---

## Summary

| # | Decision | Choice |
|---|---|---|
| D1 | Frappe version | v16 stable |
| D2 | Database | PostgreSQL + pgvector |
| D3 | Raven | Excluded — v0.2 |
| D4 | ERPNext | Not relevant this phase |
| D5 | CLI | Extend bench with `friday` group |
| D6 | LLM provider | Provider-agnostic, Minimax first |
| D7 | Sandbox | Docker |
| D8 | Fork | Hard fork of Frappe v16 |

**All decisions resolved. Implementation can begin.**

Next step: start Phase 1 implementation per `42-phase-one-authority-contract.md`. First milestone: the governed framework loop — one agent, one skill, permissions checked, execution sandboxed, result logged.
