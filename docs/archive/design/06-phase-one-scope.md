# 06 — Phase One Build Plan

> See `00-glossary.md` for term definitions.
> **Scope authority:** `42-phase-one-authority-contract.md`. v0.1 in-scope, out-of-scope, sandbox minimum bar, and completion gate live there. This document is the build plan — milestones, environment, risks. If anything here conflicts with 42, 42 wins.

---

## Phase positioning

| Phase | Goal | Visibility |
|---|---|---|
| **1 — Foundation** | Working v0.1 framework on a single site; governance loop proven end-to-end | Private |
| **2 — Open-source launch** | Public repo, contribution-ready, multi-platform messaging | Public on GitHub |
| **3 — Community iteration** | Feature parity with Hermes, real users, hardening | Active OSS project |
| **4 — Ecosystem integration** | Frappe upstream collaboration where useful | Frappe community |

Phase 1 must prove the **governance loop**, not feature breadth.

---

## Phase 1 thesis

> An LLM-powered agent receives a message, looks up its permitted Skills from Frappe, executes one inside a Docker sandbox, and writes the result back as a Frappe document — every step audited and permission-checked.

If that single loop runs end-to-end with governance intact, the architecture is proven. The detailed in-scope and out-of-scope lists are in `42-phase-one-authority-contract.md` §3–§4.

---

## 12-week milestones

| Week | Milestone | Definition of done |
|---|---|---|
| 1 | bench + site provisioned, PostgreSQL + pgvector, Redis, Docker | `bench start` runs; site reachable; `SELECT * FROM pg_extension WHERE extname='vector'` returns a row |
| 2 | Friday repo scaffolded; agent kernel DocTypes from 42 §3 created | bench setup clean; `friday` command group resolves; Framework Console workspace visible; DocTypes editable in Desk |
| 3 | Permission engine + Execution Log + Permission Decision Log | Programmatic permission probe returns allow/deny; both logs submit immutable rows |
| 4 | Gateway service running; CLI adapter writes Chat Message | `friday chat` produces a Chat Message DocType row |
| 5 | LLM call path + no-op skill | Gateway picks up a message, calls Minimax, writes outbound Chat Message |
| 6 | First real skill (`create_note`) | End-to-end: CLI message → permission check → skill exec → Note created → reply |
| 7 | Docker-isolated execution for `create_note` | Skill runs in a sandbox meeting 42 §5 minimum bar |
| 8 | Agent Task workflow + dispatcher | Manually created Task is claimed and executed by the dispatcher |
| 9 | Native Kanban + real-time updates | Task moves through states live on a Kanban board |
| 10 | Polish + tests + docs | README, install guide, architecture doc; permission engine ≥ 80% coverage |
| 11 | Dogfood | Friday runs Friday's own task list for one week |
| 12 | Launch prep | LICENSE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, docs site stub |

---

## Environment

| Component | Version |
|---|---|
| Python | 3.14 (Frappe v16 `version-16` branch requires `>=3.14,<3.15`) |
| Node | 24 LTS (older versions fail `yarn install`) |
| PostgreSQL | 15+ |
| pgvector | ≥ 0.8.2 |
| Redis | 7+ |
| Docker | recent stable |
| LLM provider | Minimax first (per D5); provider-agnostic adapter |

Activate Node 24 before `bench start` or any frontend command: `source ~/.nvm/nvm.sh && nvm use 24`.

Tooling: pre-commit hooks (black, ruff, mypy), pytest. Editor with Frappe-aware plugins.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Frappe permission engine too slow under agent load | Aggressive Redis caching of permission matrices and Skill rows; benchmark in week 3 |
| Docker spawn overhead too high | Pre-warmed container pool benchmarked in week 7; warm pool itself is Phase 1.5 per 42 §5 |
| LLM tool-calling unreliable with the Skill schema | Iterate on parameter schema; structured-output models if needed |
| Long-running gateway conflicts with Frappe app lifecycle | Run gateway on a dedicated RQ worker bound to the `agent_core` queue — separate from Gunicorn |
| Scope creep | 42 §4 is enforced verbatim; anything not in 42 §3 is post-v0.1 |
| Fork drift from upstream Frappe | Tag every core commit `[friday-core]`; record divergences in `docs/core-divergences.md`; absorb upstream patches per `45-fork-policy.md` |

---

## Phase 1 validation questions

By the end of Phase 1, every question must answer **yes**:

1. Does Frappe's permission system work for agent governance at runtime speeds?
2. Is gateway latency acceptable (< 200ms permission check + dispatch)?
3. Does Docker isolation work without breaking the agent loop?
4. Is authoring Skills as DocTypes pleasant or painful for the operator?
5. Do real LLMs handle the structured Skill schema reliably, or do they hallucinate calls?
6. Is the architecture obviously extensible to multi-platform, multi-agent, learning loop?

A "no" on any of these is a redesign signal **before** open-sourcing.

---

## Completion gate

The v0.1 completion gate is `42-phase-one-authority-contract.md` §7. This document does not duplicate it.
