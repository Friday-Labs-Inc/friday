# 20 — Brainstorm Session Tree

> See `00-glossary.md` for term definitions.
>
> Snapshot of the ideation flow that produced the Friday design dossier. Captures how ideas branched, evolved, and locked into the architecture. Structurally a tree by design — preserve the shape when extending, not the prose.

---

## Root

```
FRIDAY
  └─ "Agentic framework, ports Hermes Agent patterns on a hard fork
      of Frappe v16, governed for the enterprise."
```

---

## Branch 1 — Foundation

```
1. SEED IDEA
   └─ Take Hermes Agent's gateway / agent-loop pattern
      └─ Decouple from its storage and governance backend
         └─ Re-implement on a Frappe v16 fork
            └─ Inherit Frappe's enterprise primitives:
               role-based permissions, PostgreSQL, Redis,
               RQ workers, notifications, integrations

2. RESEARCH PHASE
   ├─ What is Frappe Framework?
   │  └─ Full-stack, batteries-included, Python + JS
   │     └─ DocType-centric, GPL v3, mature
   │
   ├─ How does Hermes Agent work?
   │  ├─ Three-layer: Connectors → Gateway → Agent Runtime
   │  ├─ Skills as markdown files (progressive disclosure L0/L1/L2)
   │  ├─ Sessions like OS processes
   │  ├─ Tool registry (built-in + MCP + LSP)
   │  └─ Cron + Memory + Config files (USER/SOUL/AGENTS/TOOLS.md)
   │
   └─ Security issues common to current agentic frameworks
      ├─ Permissive defaults in fresh installs
      ├─ Adapter / input-handling bugs (path traversal class)
      ├─ Memory-channel poisoning
      ├─ Prompt-injection-driven tool chains
      ├─ Token exfiltration via untrusted web content
      └─ Supply-chain exposure via shared LLM-routing dependencies
         └─ INSIGHT: governance is the gap. That is Friday's moat.
```

(Security framing follows `46-security-claims-audit.md` §4 — architectural pattern language, no unsourced CVE numbers.)

---

## Branch 2 — Architecture lock-in

```
3. PERMISSION-FIRST DESIGN
   └─ Use Frappe's role-based permission system
      └─ Agent Profile linked to a Frappe User
         └─ Roles cascade through to skill execution
            └─ Permission check at the gateway, BEFORE queueing
               └─ Every decision logged to Permission Decision Log

4. ISOLATION
   └─ Docker container per skill invocation
      ├─ Scoped credentials (short-lived API tokens)
      ├─ Network namespace + allowlist
      ├─ Resource caps via cgroups
      └─ Frappe REST API as the trust boundary

5. INTER-AGENT COMMUNICATION
   └─ Redis pub/sub + Gateway permission check
      └─ Agents never call each other directly
         └─ Delegation Request DocType tracks every cross-agent call

6. DATA LAYER DECISIONS
   ├─ PostgreSQL over MariaDB (pgvector, better JSON, FTS)
   ├─ Redis for cache, queues, real-time pub/sub
   ├─ pgvector for semantic memory
   └─ Docker for sandbox
```

---

## Branch 3 — Integrated stack

```
7. RAVEN DISCOVERED
   └─ Open-source Slack-like, built on Frappe
      └─ Channels = War Rooms (one per Agent Project)
         ├─ Message Actions → trigger Friday workflows
         ├─ Document sharing with embedded previews
         ├─ Custom emoji as status indicators
         └─ Timeline integration for audit

8. ERPNext PROJECT/TASK/ISSUE PORTED
   └─ Do not depend on ERPNext — port the DocTypes
      ├─ Agent Project (from ERPNext Project)
      ├─ Agent Task (+ assigned_to_profile, required_skills)
      └─ Agent Issue for blockers
         └─ Frappe Workflow + Kanban view replaces Hermes' fixed Kanban

9. FOUR LAYERS LOCKED
   ├─ Friday Framework Core (Frappe v16 fork)
   ├─ Raven (collaboration)
   ├─ Ported ERPNext Project/Task/Issue (orchestration)
   └─ Friday Core / agent kernel (gateway, skills, dispatcher, sandbox)

9A. HERMES KANBAN REAL-WORLD FAILURE
    └─ Asked Hermes to create profiles, board, and tasks
       ├─ Basic bounded tasks worked
       ├─ Multi-agent setup repeatedly failed
       ├─ Profiles and skills wrongly built
       ├─ Fixed columns did not match real business workflows
       └─ INSIGHT: agents should not improvise the operating model;
          they operate inside typed, validated, governable DocTypes.
```

---

## Branch 4 — Agent governance

```
10. AGENT ROLE PROFILES
    └─ Bundles of (roles + skills + quota + approval threshold)
       ├─ Ship 7 defaults (task_worker, data_processor, qa,
       │  supervisor, integration, dev, read_only)
       ├─ Multi-agent hierarchy via can_delegate_to / can_escalate_to
       └─ Permission inheritance with invariant: child ⊆ parent

11. DELEGATION & ESCALATION
    ├─ Delegation Request DocType (peer / downward)
    ├─ Escalation DocType (upward when stuck)
    └─ War Room as fallback escalation surface

12. SECRETS MANAGEMENT
    └─ Frappe Password field + Vault integration
       ├─ Masked in logs and War Room
       ├─ Short-lived scoped tokens to containers
       └─ Per-agent access audited
```

---

## Branch 5 — OpenClaw insights

```
13. KRENTSEL TALK (UC Berkeley, March 2026)
    ├─ Three-layer architecture confirmed
    ├─ Heartbeat session pattern (every 30 min self-check)
    ├─ Memory as TOOLS, not context injection — flip the design
    ├─ Skill ceiling: 150 max, 30k chars max, intelligent filter
    ├─ Auto-configuration via BOOTSTRAP conversation
    └─ LLM-as-policy — don't over-prescribe architecture
```

---

## Branch 6 — Specialised intelligence

```
14. DOMAIN-SPECIALISED AGENTS
    └─ Not "Full Stack Developer" generic
       └─ React Developer, Database Engineer, DevOps, Security
          (token-efficient via narrow expertise)

15. DYNAMIC FRAMEWORK VERSIONING
    └─ Skills versioned per framework version
       ├─ React 19 ≠ React 17
       └─ Latest doc injection on task assignment

16. INFRASTRUCTURE SPECIALIST SUB-AGENTS
    ├─ Kubernetes specialist
    ├─ Terraform specialist
    ├─ Docker Compose specialist
    ├─ Ansible specialist
    └─ Coordinator routes to the right specialist

17. GITHUB-DRIVEN DOC SYNC
    └─ User specifies GitHub release URLs
       └─ System fetches, parses markdown, generates skill updates
          └─ Auto-promotion through Skill Draft → Active

18. DOMAIN-SPECIFIC SELF-LEARNING
    └─ Hermes learning loop, scoped per domain
       └─ Kubernetes specialist learns K8s patterns
          └─ Cross-agent sharing of validated learnings
```

---

## Branch 7 — Autonomy and memory

```
19. AUTONOMOUS BUSINESS OPS
    └─ 6-layer architecture
       ├─ L1 Data integration (REST API to the business system)
       ├─ L2 Domain agents (Support, Research, Operations, HR, ...)
       ├─ L3 Decision rules (configurable thresholds)
       ├─ L4 Approval gates (Workflow Request)
       ├─ L5 Audit & compliance
       └─ L6 Learning loop
          └─ One platform user per agent (audit by agent identity)
             └─ System Manager Agent bootstraps other agent users

20. CACHE BUFFER MANAGEMENT
    └─ Optional, configurable per project
       ├─ Pre-load frequently-read records into Redis
       └─ TTL-based, agent queries cache first

21. MEMORY ARCHITECTURE
    ├─ Multi-layer: hot (Redis) / warm (PostgreSQL) / cold (archive)
    ├─ Semantic via pgvector + FTS hybrid
    ├─ Memory as TOOLS, not context (OpenClaw insight)
    └─ Compression for old memories (summarise, keep embedding)

22. NEURAL LINKING / MEMORY ASSOCIATION
    └─ Concepts tagged; cross-concept association tracked
       └─ "Surveillance" + "Automation" auto-link
          └─ Query one, surface related memories

23. KNOWLEDGE GRAPH / WIKI INTEGRATION
    └─ Frappe Wiki hosts curated domain knowledge
       └─ Agents query as a reasoning aid
          └─ Updated as agents learn (human approval gated)
```

---

## Branch 8 — Operations and scale

```
24. SANDBOX ARCHITECTURE
    └─ Container lifecycle: spawn, scope, execute, teardown
       ├─ Pre-warmed pool to amortise startup (Phase 1.5 per 42 §5)
       ├─ Network namespace + allowlist
       └─ Cleanup verification

25. AUTOPILOT MODE
    └─ Confidence-gated autonomous execution
       ├─ Build confidence through observed runs
       ├─ Above threshold (95% success): autopilot for that task type
       ├─ Exception → pause + escalate to War Room
       └─ Always-on monitoring and rollback

26. ANALYTICAL & PREDICTIVE AGENTS
    └─ Beyond operational agents
       ├─ Forecast demand
       ├─ Optimise supply chain
       └─ Need ML models, real-time data, optimisation algorithms

27. MULTI-SITE INTER-AGENT COMMUNICATION
    └─ Agent-to-Agent Protocol extended cross-site
       ├─ Service discovery (DNS / registry)
       ├─ WebSocket / Redis Streams transport
       ├─ Mutual TLS authentication
       └─ Cross-site permission verification

28. PERFORMANCE OPTIMISATION
    ├─ pgvector indexes (IVFFlat, HNSW)
    ├─ Permission cache tuning
    ├─ Container pool to amortise Docker startup
    ├─ Batched LLM calls
    └─ Distributed tracing across gateway → RQ → container
```

---

## Branch 9 — Sustainability

```
29. OPEN-SOURCE LAUNCH PLAYBOOK
    ├─ Repo hygiene (LICENSE, CONTRIBUTING, SECURITY, CoC)
    ├─ CI/CD pipelines
    ├─ Documentation site
    ├─ Launch sequence (T-30, T-14, T-7, T-0)
    └─ T+90 success criteria

30. GO-TO-MARKET — INDIA-FIRST
    ├─ Target: Indian SMBs on ERPNext
    ├─ Positioning vs UiPath, LangChain, OpenClaw, vanilla ERPNext
    ├─ Phasing: build → quiet release → public launch → growth
    └─ Mission: open-source, governed, India-first

31. FRIDAY LABS (separate project, Phase 4)
    └─ Hosted / managed Friday
       ├─ Subscription tiers
       ├─ Indian-hosted infrastructure
       └─ One-click export to self-hosted

32. CONTRIBUTOR REVENUE SHARE
    └─ Friday Labs net revenue distributed:
       ├─ 40% operations + reserves
       ├─ 30% core maintainers
       ├─ 20% broader contributors
       └─ 10% community fund
          └─ Distribution by contribution score
             └─ Public, auditable, annually reviewed
```

---

## Branch 10 — Deferred

```
33. FUTURE USE CASES (parked; not Phase 1)
    ├─ Campus surveillance / vision-based monitoring
    ├─ Wiki + LLM knowledge segregation
    ├─ Software development workflow automation
    ├─ Healthcare patient intake
    ├─ Legal contract review
    └─ Customer service ticket triage

34. PHASE 1 BUSINESS VALIDATION
    └─ Business-process workflow, end-to-end, one week, zero unsafe actions
       └─ Runs after the governed framework loop is proven (per 42 §6).
```

---

## Cross-cutting invariants

```
DECISION INVARIANTS
├─ Permission-first (every action gated through Frappe roles)
├─ Audit by default (every decision a submittable DocType)
├─ No external vector DB (pgvector inside Postgres)
├─ Dual-storage Skills (DocType authoritative for governance, file for portability)
├─ Human-in-the-loop at critical junctures (approvals, escalations, skill changes)
├─ Kanban is a view, not the workflow
├─ Agents may propose operating-model changes; validation/approval activates them
├─ GPL v3 — AGPL re-evaluated once before public launch (07-legal-and-branding.md)
└─ One repo IS the fork (45-fork-policy.md)

OPEN ENGINEERING QUESTIONS (Phase 1 spikes)
├─ Skill DocType ↔ file sync conflict resolution
├─ Skill cache: file-vs-DocType source of truth on hot path
├─ War Room channel archive / retention semantics
├─ Concurrent Raven message + Execution Log writes
├─ Fine-grained Message Action permissions in Raven
├─ Agent Role Profile vs Frappe Role Profile inheritance
└─ ERPNext port: which fields to drop, which to keep
```

---

## How to use this tree

1. **Onboarding:** read root-to-leaf to follow how each major decision was reached.
2. **Architecture review:** any new feature proposal attaches to a branch and respects the decision invariants.
3. **Visualisation:** indentation maps to a tree; rendered as Mermaid, D2, or a force-directed graph by parsing structure.
4. **Roadmap input:** Phase 1 = Branches 2, 3, 4, plus Tier 1 in `19-phase-one-success-metrics.md`. Branches 5–10 are Phase 2+.

---

## Snapshot date

Reflects the brainstorm session through May 2026. Future ideation extends rather than rewrites this tree.
