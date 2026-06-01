# Friday — Governed Agentic Framework on Frappe v16

> **Made in India. Built for Indian businesses. Open source under GPL v3.**

Friday is a hard fork of Frappe v16 stable that makes AI agents a first-class primitive of the framework — not an app you install on top, not a bolt-on layer, but a native part of the framework itself. Agent identity, skill dispatch, permission gating, sandboxed execution, and immutable audit logs are built into core.

The mission: every Indian SMB owner gets a governed, auditable back-office agent team that runs on their own infrastructure, without vendor lock-in, without predatory licensing, and without compromising on security.

---

## What Friday Is

**Friday is the fork.** The Friday repository starts from Frappe v16 stable and builds agent-native primitives directly into framework core. The full bench ecosystem is retained. The product surface is the Framework Console. The agent runtime is the engine.

**Agents are first-class, not bolted on.** Agent Profile, Skill, Execution Log, Permission Decision Log, and Sandbox Execution are framework primitives — they exist in every Friday site by default, the same way User and Role exist in every Frappe site.

**Permission first, always.** Every skill invocation passes through Frappe's role-based permission engine before anything executes. No exceptions. Permission decisions are logged immutably.

**Kanban is a view, not the workflow.** Business workflows are defined through Frappe Workflow. The Kanban board renders whatever states are configured. Agents operate inside governed workflows; they do not invent them.

---

## What Friday Is Not

- Not a fork of Hermes or OpenClaw (Friday re-implements their ideas on a governed enterprise substrate)
- Not a thin "AI app installed on Frappe" with no framework identity
- Not tied to a single LLM provider (provider-agnostic from day one)
- Not an ERPNext dependency (specific DocTypes are ported into Friday, not inherited)
- Not a SaaS-only product (self-hosted first; FridayLabs hosted platform is a separate future project)

---

## Architecture in One Paragraph

Friday runs on a single-site bench installation (one bench = one agent ecosystem). Gunicorn serves the Framework Console (HTTP + WebSocket). A dedicated Agent Core Worker runs the Hermes-derived agent execution loop continuously alongside it — these are two separate processes with two separate lifecycles. Agents execute skills inside Docker sandboxes with scoped credentials and network restrictions. All state — agent profiles, skills, tasks, execution logs, permission decisions — lives in PostgreSQL. Redis handles caching, job queuing, and real-time pub/sub. Raven (installed as a Friday app) provides the War Room communication layer per project.

---

## Document Index

**Start here if you are new:** read `39`, `42`, `43`, `45` in that order. Then read `01`.

### The Operational Spine (read first)

| # | Document | What it decides |
|---|---|---|
| 00 | [Glossary](./00-glossary.md) | Single definition for every term used across the dossier |
| 39 | [Framework Strategy](./39-friday-framework-strategy.md) | Why Friday is a fork, not an app. What goes in core vs apps. |
| 40 | [Gap Analysis & Resolution](./40-gap-analysis-and-resolution-plan.md) | All contradictions resolved before implementation starts |
| 41 | [Porting Strategy](./41-porting-strategy-hermes-erpnext-raven.md) | How Hermes, ERPNext DocTypes, and Raven map into Friday |
| 42 | [Phase One Authority Contract](./42-phase-one-authority-contract.md) | Single source of truth for v0.1 scope. This wins all conflicts. |
| 43 | [Control Room Product Spec](./43-control-room-product-spec.md) | The operator-facing product surface in detail |
| 44 | [Technical Feasibility Spike](./44-technical-feasibility-spike.md) | Stack decisions — all resolved |
| 45 | [Fork Policy](./45-fork-policy.md) | How Friday develops on its kernel; upstream absorption rules |
| 46 | [Security Claims Audit](./46-security-claims-audit.md) | What Friday can and cannot claim publicly about security |

### Architecture & Vision

| # | Document | Purpose |
|---|---|---|
| 01 | [Vision & Architecture](./01-vision-and-architecture.md) | System design, request flow, what makes Friday different |
| 02 | [Feature Comparison](./02-feature-comparison.md) | Hermes vs OpenClaw vs Friday — keep / replace / add |
| 03 | [Technical Stack](./03-technical-stack.md) | Frappe, PostgreSQL + pgvector, Redis, Docker — why each |
| 04 | [Security Model](./04-security-model.md) | Eight defense layers, threat model, audit trail |
| 05 | [Module Design](./05-module-design.md) | DocTypes, gateway internals, dispatcher, skill loading |
| 06 | [Phase One Scope](./06-phase-one-scope.md) | MVP scope and milestones (doc 42 wins conflicts) |
| 07 | [Legal & Branding](./07-legal-and-branding.md) | GPL v3, trademark, naming rules |
| 14 | [Integrated Architecture](./14-integrated-architecture.md) | Full integration: Frappe + Raven + ERPNext port + Friday Core |

### Implementation Guides (for AI and human contributors)

| # | Document | Purpose |
|---|---|---|
| 08 | [Agent Setup Guide](./08-agent-setup-guide.md) | Context sources, environment, conventions, authority hierarchy |
| 09 | [Agent Evaluation Guide](./09-agent-evaluation-guide.md) | REUSE / ADAPT / REWRITE decisions for every Hermes component |
| 10 | [Agent Execution Guide](./10-agent-execution-guide.md) | Slice-by-slice implementation order with micro-loop discipline |
| 11 | [Agent Validation Checklist](./11-agent-validation-checklist.md) | Concrete completion gates for each slice |

### Agent Governance & Roles

| # | Document | Purpose |
|---|---|---|
| 12 | [Agent Role Profiles](./12-refinement-agent-roles-and-features.md) | Role Profile bundles, delegation chains, escalation flows |
| 15 | [OpenClaw Insights](./15-openclaw-insights-friday-refinements.md) | Memory-as-tools, skill ceilings, heartbeat, LLM-as-policy |
| 22 | [Hermes Learning Loop](./22-hermes-learning-loop-deep-dive.md) | Governed skill evolution: draft → review → version → rollback |
| 23 | [Secrets & Credentials](./23-secrets-credentials-management.md) | Credential Profile DocType, per-agent ERPNext users, masking |
| 25 | [Domain-Specialised Profiles](./25-domain-specialized-agent-profiles.md) | React Dev, K8s Specialist, PostgreSQL DBA, and coordinator pattern |

### Infrastructure & Performance

| # | Document | Purpose |
|---|---|---|
| 24 | [Sandbox Architecture](./24-sandbox-architecture-implementation.md) | Docker hardening, warm pool, network policy, cleanup |
| 31 | [Cache Management](./31-cache-buffer-management-system.md) | Redis hot cache, pre-load, invalidation, monitoring |
| 38 | [Performance Optimization](./38-performance-optimization-bottleneck-analysis.md) | LLM latency, pgvector tuning, warm pool, SLA targets |
| 37 | [Multi-Site Inter-Agent](./37-multi-site-inter-agent-communication.md) | ACP protocol, mTLS, service discovery (Phase 2+) |

### Memory & Knowledge

| # | Document | Purpose |
|---|---|---|
| 32 | [Memory Association](./32-memory-association-neural-linking.md) | Concept graph, association strength, decay (Phase 2+) |
| 33 | [Knowledge Graph & Wiki](./33-knowledge-graph-wiki-integration.md) | Frappe Wiki as agent knowledge base (Phase 2+) |
| 34 | [Multi-Layer Memory](./34-efficient-multilayer-memory-system.md) | Hot/warm/cold tiers; episodic, semantic, procedural (Phase 2+) |

### Autonomous Operations & Business Use Cases

| # | Document | Purpose |
|---|---|---|
| 35 | [Autopilot Mode](./35-autopilot-mode-autonomous-execution.md) | Confidence-gated autonomy, circuit breaker (Phase 2+) |
| 36 | [Analytical Agents](./36-analytical-predictive-agents.md) | Trend, demand forecast, resource budget, performance insights |

### Roadmap Context (Phase 2–4 design depth)

*These documents describe future capability. Read them after fully understanding the operational spine. They do not affect v0.1 implementation.*

| # | Document | Purpose |
|---|---|---|
| 13 | [Frappe v16 Leverage](./13-frappe-v16-leverage-strategy.md) | v16 features mapped to Friday bottlenecks |
| 16 | [Raven Integration](./16-raven-integration-strategy.md) | War Room per project, channel auto-creation, Message Actions |
| 17 | [Open Source Launch](./17-open-source-launch-playbook.md) | Repo setup, license sequence, community kickoff |
| 18 | [Go-to-Market](./18-go-to-market-strategy.md) | India-first, FridayLabs SaaS, contributor revenue share |
| 19 | [Phase One Metrics](./19-phase-one-success-metrics.md) | KPIs — doc 42 wins conflicts |
| 20 | [Brainstorm Session Tree](./20-brainstorm-session-tree.md) | Visual map of ideation; useful for understanding lineage |
| 21 | [Auto-Research Strategy](./21-auto-research-integration-strategy.md) | Autonomous research agents (Phase 2+) |
| 26 | [Framework Version Mgmt](./26-dynamic-framework-version-management.md) | Skills versioned per framework version |
| 27 | [Infrastructure Sub-Agents](./27-infrastructure-specialist-subagents.md) | K8s, Terraform, Ansible, Docker Compose specialists |
| 28 | [GitHub Doc Sync](./28-github-driven-documentation-sync.md) | Auto-update framework docs from upstream releases |
| 29 | [Domain-Specific Learning](./29-domain-specific-self-learning.md) | Hermes learning loop scoped per domain |

---

## Quick Start for Engineers

**Implementing Phase 1:** Read `39 → 42 → 43 → 45` first. Then read `08 → 09 → 10 → 11` in order. Then `05` and `24`.

**Security review:** Read `04 → 23 → 24 → 46`.

**Understanding the porting decisions:** Read `41 → 09 → 02`.

**Building agent profiles or skills:** Read `12 → 15 → 22 → 25`.

**Performance tuning:** Read `31 → 34 → 38`.

---

## Decisions Log

All spike decisions are recorded at `docs/decisions/spike-results.md`:

| Decision | Choice |
|---|---|
| Frappe version | v16 stable |
| Database | PostgreSQL + pgvector |
| Raven in v0.1 | Excluded — v0.2 |
| ERPNext in v0.1 | Not relevant this phase |
| CLI strategy | Extend bench with `friday` group |
| LLM provider | Provider-agnostic, Minimax first |
| Sandbox | Docker |
| Fork strategy | Hard fork of Frappe v16 |

---

## Made in India 🇮🇳

Friday is built in India, for Indian growing businesses, by an Indian founder. We stand on the shoulders of Frappe (Mumbai), Raven (The Commit Company), and the global Hermes / OpenClaw communities — and add the governance, accessibility, and economic alignment that the next chapter requires.

**Open source. No proprietary trap doors. No per-seat licensing. No vendor lock-in. Ever.**
