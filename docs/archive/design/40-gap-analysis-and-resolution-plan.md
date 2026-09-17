# 40 — Gap Analysis & Resolution Plan

> **Status:** All gaps resolved. Implementation can begin.
> This document is a control record — it shows what was ambiguous and how each ambiguity was resolved. Do not reopen resolved gaps without a documented reason.

---

## Executive Summary

Friday's core thesis is sound: use a Frappe-derived framework to make AI agents governed, auditable, and permission-bound business actors. Before implementation started, the dossier had one structural problem — several documents defined different versions of "Phase 1." That is now resolved by `42-phase-one-authority-contract.md`.

All eight stack decisions are resolved in `docs/decisions/spike-results.md`. All documents requiring updates from those decisions are marked below.

---

## Resolved Gaps

### G1 — Competing Phase 1 Definitions

**Was:** Three documents defined conflicting Phase 1 scopes (docs 06/10/11 = CLI MVP; docs 14/16/24 = integrated platform with Raven; docs 19/30/35 = ERPNext business automation).

**Resolution:** `42-phase-one-authority-contract.md` is the single source of truth for v0.1 scope. Phase 1 proves the governed framework loop. The first business-automation track starts after v0.1 is complete. All other documents calling something "Phase 1" are roadmap context unless explicitly included in doc 42.

---

### G2 — Framework Strategy Was Under-Specified

**Was:** Doc 05 described a Friday app architecture. Doc 39 described a framework strategy. These were inconsistent.

**Resolution:** `39-friday-framework-strategy.md` is authoritative on framework identity. Friday is a hard fork of Frappe v16. Agent-native primitives go in core. Domain features go in Friday apps. The two-worker model (Gunicorn for the Framework Console, dedicated Agent Core Worker for the agent loop) is the deployment shape. Single-site model is the Phase 1 constraint.

---

### G3 — Frappe Version Was Open

**Was:** Earlier documents targeted Frappe v15. Doc 13 discussed v16 as a future upgrade.

**Resolution:** **Frappe v16 stable.** Confirmed by the feasibility spike (`44-technical-feasibility-spike.md`, decision D1). The implementation log (`docs/project/IMPLEMENTATION_LOG.md`) confirms Frappe 16.18.2 running on the development machine.

---

### G4 — Database Was Open

**Was:** Frappe defaults to MariaDB. PostgreSQL was described as the target but not confirmed viable.

**Resolution:** **PostgreSQL + pgvector.** Confirmed by spike (D2). PostgreSQL 18.3 with pgvector 0.8.1 running. Note: Frappe PostgreSQL support is described as experimental by upstream maintainers. Friday owns this choice and accepts the maintenance responsibility. Pin pgvector at v0.8.2 or later (CVE-2026-3172 buffer overflow fix).

---

### G5 — Raven Scope in v0.1

**Was:** Docs 14 and 16 included Raven in Phase 1. Docs 06 and 10 were CLI-first.

**Resolution:** **Raven excluded from v0.1.** Spike decision D3. Friday v0.1 is CLI-first. Raven is a v0.2 feature. If the feasibility spike had proven Raven low-risk to include, doc 42 §3 would have been updated. It was not — Raven is v0.2.

---

### G6 — ERPNext as Dependency vs Ported DocTypes

**Was:** Multiple documents were unclear whether Friday depends on ERPNext or ports selected DocTypes.

**Resolution:** **No ERPNext dependency.** Spike decision D4: ERPNext is not relevant to Phase 1. Specific DocTypes (Agent Project from ERPNext Project, Agent Task from ERPNext Task) are ported into the Friday app. See `41-porting-strategy-hermes-erpnext-raven.md` §3 for the field-level porting decision.

---

### G7 — Memory / pgvector Scope

**Was:** Docs 26, 28, 33, 34 described pgvector-backed memory as Phase 1. Doc 06 deferred it.

**Resolution:** **PostgreSQL + pgvector installed on Day 1; semantic memory feature deferred to Phase 2.** The database is PostgreSQL with the pgvector extension enabled. No memory DocTypes, no embedding calls, and no vector search queries are required for v0.1. Phase 1 may use basic Frappe full-text search if needed.

---

### G8 — Sandbox Scope

**Was:** Doc 24 described a hardened production sandbox (warm pool, egress allowlist, full security test suite) as Phase 1. Doc 06 described a minimal sandbox.

**Resolution:** **Doc 42 §5 minimum bar applies to v0.1.** Non-root container, resource limits, timeout/OOM handling, no host mounts, no Docker socket, scoped credentials, structured result capture, cleanup path, Execution Log per attempt. Warm pool, egress allowlist, and full security attack suite are Phase 1.5.

---

### G9 — Security Claims

**Was:** Docs 04 and 20 contained specific CVE numbers, vulnerability counts, and audit dates about Hermes and OpenClaw that were not sourced.

**Resolution:** `46-security-claims-audit.md` audits every claim. Claims with specific CVE numbers and vulnerability counts are replaced with architectural-pattern language. Docs 04 and 20 require follow-up edits per doc 46 §5 before public release.

---

### G10 — License Decision

**Was:** Docs described GPL v3 now, AGPL v3 under consideration.

**Resolution:** **GPL v3 for Phase 1 (private).** AGPL v3 to be evaluated before public launch (Phase 2). Spike decision D8 confirms the hard fork strategy; GPL v3 is the natural license for a Frappe derivative.

---

### G11 — CLI Strategy

**Was:** Unclear whether Friday used its own `friday` entrypoint, a bench wrapper, or something else.

**Resolution:** **Extend bench with a `friday` command group.** Spike decision D5. `bench friday <command>` for agent-specific operations. `bench` unchanged for site and framework operations. No new CLI tool to install.

---

### G12 — LLM Provider

**Was:** Unclear which provider to implement first and how abstraction should work.

**Resolution:** **Provider-agnostic from day one. Minimax as the first provider.** Spike decision D6. The provider interface must support swapping with a config change. Phase 1 implements Minimax; Claude, OpenAI, Gemini, and local models use the same interface in Phase 2+.

---

### G13 — Fork Strategy

**Was:** Whether Friday should be a hard fork of Frappe or a Frappe app.

**Resolution:** **Hard fork of Frappe v16 stable.** Spike decision D8. The Friday repository IS the fork. Full bench ecosystem retained. Agent-native primitives in core. Domain features in Friday apps. See `39-friday-framework-strategy.md` and `45-fork-policy.md`.

---

## Missing Documents (Completed)

| Document | Status |
|---|---|
| `42-phase-one-authority-contract.md` | Complete — single source of truth for v0.1 scope |
| `43-control-room-product-spec.md` | Complete — operator-facing product surface |
| `44-technical-feasibility-spike.md` | Complete — all 8 stack decisions resolved |
| `45-fork-policy.md` | Complete — core divergence rules and upstream absorption |
| `46-security-claims-audit.md` | Complete — source verification; follow-up edits to docs 04 and 20 pending |
| `00-glossary.md` | Complete — single definition for all terms |
| `docs/decisions/spike-results.md` | Complete — all 8 decisions recorded |

---

## Pending Follow-Up Edits

These items are resolved at the decision level but require follow-up commits before public release:

1. `04-security-model.md` — replace lines 5–20 per `46-security-claims-audit.md` §4. Replace `HERMES_HOME`-specific claims and CVE numbers with architectural-pattern language.
2. `20-brainstorm-session-tree.md` — replace lines 42–44 per doc 46 §4.
3. Documents 12–38 — review for any "Phase 1" references that contradict doc 42. Mark them as roadmap context or update per doc 42.

---

## Current Status

> **All gaps resolved. Implementation in progress. Slice 1 (DocType scaffolding) complete per `docs/project/IMPLEMENTATION_LOG.md`.**

---

## The Friday Architecture Statement

Friday is an agentic framework that runs on a hard fork of Frappe v16 stable, with the full bench ecosystem intact, agent-native primitives built into framework core, and business automation as the first flagship use case delivered through a Friday app.

Single-site. Two-worker model. Framework Console as the product surface. Agent Core Worker as the engine. Permission first, always. Audit everything. Kanban is a view, not the workflow.
