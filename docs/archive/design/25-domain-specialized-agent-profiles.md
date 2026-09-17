# 25 — Domain-Specialised Agent Profiles

> See `00-glossary.md` for term definitions.
> Refines `12-refinement-agent-roles-and-features.md`. Complements `26-dynamic-framework-version-management.md`, `27-infrastructure-specialist-subagents.md`, and `33-knowledge-graph-wiki-integration.md`.
> Phase: deferred from v0.1; phased in from Phase 2 (see §10).

---

## 1. Why specialisation

A generic Full-Stack Developer agent must **discover** which framework, which version, which conventions a codebase uses. Discovery burns tokens and time and produces averaged-quality output.

A React Developer agent **starts** with React-specific context: hooks, JSX patterns, current React 19 conventions, common pitfalls. No discovery. Focused execution. Higher-quality output.

Examples:

| Generic | Specialised |
|---|---|
| Full-Stack Developer | React, Vue, Svelte, Django, FastAPI |
| DBA | PostgreSQL, MySQL, MongoDB, ClickHouse |
| DevOps | Kubernetes, Terraform, Ansible, Docker Compose, AWS, GCP |
| Data Engineer | Airflow, dbt, Spark, Snowflake |
| Tester | Playwright E2E, pytest/jest unit, k6/Locust load |
| Writer | Technical, marketing, release notes |

---

## 2. Mechanics

A specialised Agent Role Profile differs from a generic one in four ways.

### 2.1 Narrow skill set

Only domain-relevant skills permitted. A React Developer has no `query_database` skill — that is the DBA's. Beyond permission, it is **focus**: the LLM's prompt is shorter and more coherent.

### 2.2 Domain system prompt

`domain_system_prompt` field on Agent Role Profile — a domain-specific addendum. Example for React Developer:

```
You are a React developer specialising in React 19 with TypeScript.
Conventions:
- Functional components only; class components are legacy.
- Prefer Server Components when running on Next.js 15+; mark client components with "use client".
- State: useState (local), useReducer (complex), Context API (cross-tree), Zustand or Redux Toolkit (global).
- Side effects: useEffect with explicit dependency arrays; no missing deps.
- Suspense and ErrorBoundary expected for async UI.
- Accessibility (ARIA, keyboard nav) is not optional.
- Styling: Tailwind preferred unless project uses CSS-in-JS or modules.
```

### 2.3 Knowledge bundle

Curated reference exposed via tools (per `15-openclaw-insights-friday-refinements.md` Insight 3 — memory as tool, not auto-injection). Updated as the framework evolves through `28-github-driven-documentation-sync.md`.

### 2.4 Domain-scoped learning loop

The curator (`22-hermes-learning-loop-deep-dive.md`) operates within domain scope. A React Developer's learning improves React skills; it does not pollute the broader library.

---

## 3. Schema extensions

Beyond `12-refinement-agent-roles-and-features.md`:

| Field | Type | Notes |
|---|---|---|
| `domain` | Link → Domain | The specialisation area |
| `domain_system_prompt` | Long Text | Addendum to the base system prompt |
| `knowledge_bundle` | Link → Knowledge Bundle (`33-knowledge-graph-wiki-integration.md`) | Curated reference |
| `framework_versions` | Table | Pinned framework versions (e.g. React=19, TS=5.4) |
| `parent_generic_profile` | Link → Agent Role Profile (nullable) | Fallback for adjacent work |

### Domain DocType

| Field | Type |
|---|---|
| `domain_code` | Data (unique) — e.g. `react`, `kubernetes`, `postgresql` |
| `display_name` | Data |
| `category` | Select — Frontend / Backend / Database / Infra / Data / Testing / Writing |
| `description` | Text |
| `current_stable_version` | Data |
| `documentation_sources` | Table — URLs Friday monitors per `28-github-driven-documentation-sync.md` |

---

## 4. Coordinator pattern

Specialists are too narrow for full features. A coordinator routes work.

```
Operator: "Build a React component with a PostgreSQL-backed API endpoint and Kubernetes deployment."

Coordinator Agent receives the request.
  ├─ Decomposes: UI / API / DB / Deploy
  ├─ Delegates UI    → React Developer
  ├─ Delegates API   → FastAPI Developer
  ├─ Delegates DB    → PostgreSQL DBA
  └─ Delegates infra → Kubernetes Specialist

Specialists work in parallel where possible, sequentially where dependent.
Coordinator integrates results and reports back.
```

A Coordinator profile has:

- Broad context — knows the high-level shape of full-stack work.
- No execution skills of its own.
- Delegation rights to many specialist profiles (`can_delegate_to`).
- A skill `decompose_and_route` that uses the LLM to plan the breakdown.

LLMs excel at planning when given clear options. Coordinators provide the planning context; specialists provide execution depth.

---

## 5. Standard specialised profiles

Initial set; contributable later.

**Frontend** — `frontend.react`, `frontend.vue`, `frontend.next`, `frontend.tailwind`.
**Backend** — `backend.fastapi`, `backend.django`, `backend.frappe`, `backend.node`.
**Database** — `db.postgresql`, `db.mysql`, `db.mongodb`.
**Infra** (see `27-infrastructure-specialist-subagents.md`) — `infra.kubernetes`, `infra.terraform`, `infra.ansible`, `infra.docker-compose`.
**Cloud** — `cloud.aws`, `cloud.gcp`, `cloud.azure`.
**Testing** — `test.playwright`, `test.pytest`, `test.k6`.
**Writing** — `write.technical`, `write.marketing`, `write.release-notes`.
**Coordinators** — `coordinator.fullstack`, `coordinator.devops`, `coordinator.research` (see `21-auto-research-integration-strategy.md`).

Each ships with a tested system prompt, a starter knowledge bundle, and explicit `can_delegate_to` for coordinators.

---

## 6. Knowledge bundle lifecycle

Each specialised profile carries a Knowledge Bundle (`33-knowledge-graph-wiki-integration.md`) kept current via `28-github-driven-documentation-sync.md`.

`frontend.react` bundle contents:

- Current React major-version reference (auto-updated from React docs).
- Current TypeScript reference.
- Top 50 React patterns with examples — curated, versioned.
- Common pitfalls — community-contributed.
- Migration guides between recent versions.

Bundles are **versioned**. When React 20 ships, the bundle gets a new version; existing React 19 projects pin to the older bundle until ready to migrate.

---

## 7. Cross-specialisation contracts

Specialists must speak the same language at boundaries. Friday enforces this via **interface contracts**:

```
React Developer produces a component that calls an API.
  → Contract: OpenAPI schema, supplied by the Coordinator.
  → React Developer generates client code matching the schema.
  → FastAPI Developer implements the endpoint matching the schema.
  → Coordinator verifies both sides match.
```

Contracts live in the War Room. Mismatches surface as Agent Issues and block task completion.

---

## 8. When generic profiles are appropriate

Specialisation is not always better.

- Exploratory tasks where the framework is unknown → generic.
- Trivial tasks (e.g. count lines in a file) → generic.
- Cross-cutting concerns (project setup, README writing) → generic.
- Small teams with limited skill variety → generic may suffice.

Friday defaults to generic profiles. Operators specialise as workload demands.

---

## 9. Expected performance impact

Empirical expectation (validated in Phase 2):

- Specialised React Developer uses **30–60% fewer tokens** per task vs. generic Full-Stack.
- Task completion rate **20–40% higher**.
- Response time **2–4× faster** on framework-specific questions.

Cost: more profiles to maintain. Mitigated by the standard set (§5), auto-updating bundles, and community contributions.

---

## 10. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Generic profiles only per `12-refinement-agent-roles-and-features.md` |
| 2 | Specialised profiles for the most common stack: `frontend.react`, `backend.fastapi`, `infra.kubernetes`, `db.postgresql` |
| 3 | Full standard set (§5) |
| 4 | Community-contributed profiles via Skills Marketplace |

---

## 11. Open engineering questions

- Knowledge Bundle storage and version semantics — extend `33-knowledge-graph-wiki-integration.md`.
- Token-budget accounting per profile — empirically validate the efficiency claim.
- Coordinator decomposition: how to teach an LLM to break work down cleanly without over-specifying.
- Conflict resolution between specialists who disagree (e.g. React Dev says Server Components; Next.js Dev says client components) — escalate to architect coordinator?
- Bundle update cadence — how aggressively to pull from upstream without breaking pinned projects.

---

## 12. Open product questions

- How many specialised profiles is too many? A library of 200 niche profiles is harder to navigate than 20 well-tuned ones. Start with §5 (~25); let usage data guide expansion.
- Should specialised profiles auto-fall back to parents? A React Developer asked something React-adjacent (browser performance) probably delegates to a Frontend Generalist via `parent_generic_profile`.
- How do specialists handle deprecation? When React 19 reaches EOL, projects still pinned to it need a migration path. Mark the bundle `legacy`, require operator opt-in, surface migration prompts.
