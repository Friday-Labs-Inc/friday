# 45 — Fork Policy

> **Purpose:** Define how Friday develops on its Frappe kernel — what we change in core, what we keep stable, and how we absorb upstream Frappe patches when relevant.

---

## 1. The Architectural Decision

**Friday's kernel is a hard fork of Frappe v16 stable. The Friday repository and the kernel are one.**

The fork is not a substrate we sit on top of — it IS Friday. The community modifies its core directly to suit agentic framework requirements. Every change to the kernel is a change to Friday. There is no separate "Friday app" layer.

### Why One Repo, Why Kernel-Level Ownership

The leverage Frappe gives Friday today is real and worth using: DocTypes, ORM, permissions, workflow engine, scheduler, RQ workers, Desk, real-time pubsub, file management, REST API, bench operational tooling. Years of proven engineering.

But Friday will not stay static. As Friday matures, we anticipate infrastructure changes that **cannot be made from an external app**:

- A secondary lightweight data store (SQLite, embedded) for agent state that doesn't belong in the primary database
- A different message queue (Kafka) replacing Redis when scale demands it
- Vector storage tightly integrated with the DocType layer
- Agent-native execution primitives — sandboxed worker pools, warm container management — wired into the framework
- Custom auth flows for agent-to-agent authentication
- Trace propagation, actor context, and audit hooks integrated into every request and job cycle

These are kernel concerns. An app on top of Frappe **cannot** swap the queue layer. An app cannot introduce a parallel data store. An app cannot add framework-level execution primitives. Only modifying core can.

**Therefore the kernel must be ours. One repo. Full control.**

Today the kernel uses PostgreSQL + Redis (Frappe defaults). Tomorrow, when scale or specific workloads demand it, the community modifies the kernel — adds SQLite as a secondary store for some use case, swaps Redis for Kafka under load, integrates a new infrastructure component natively. The fork is not a substrate; it is the body of the framework.

### What Lives In The Repo

The single `Friday-Labs-Inc/friday` repository contains:

- **Frappe v16 source code** absorbed from upstream (`frappe/frappe`) at v16.18.2 as the base
- **Agent-native modifications to Frappe core**: actor context, trace propagation, audit hooks, agent-scoped auth, infrastructure adaptations
- **Friday's agent kernel modules** — Agent Profile, Skill, Execution Log, Permission Decision Log, Agent Task, etc. — built into the Frappe source tree (e.g. under `frappe/friday_core/` or appropriate module paths)
- **Friday's design docs** (`docs/`)
- **Governance and policies** (`CODEX.md`, `START_HERE.md`, `docs/contributing/AI_CONTRIBUTORS.md`)
- **Scripts**, GitHub templates, project infrastructure

There is no separate "Friday app." There is one framework, called Friday, that began as a Frappe v16 fork and continues to evolve as a unified codebase.

### Every `bench new-site` Is Automatically Agentic

Because the agent kernel is part of the framework, not an installable app:

```bash
bench new-site mybusiness.localhost
```

…produces a fully agentic site by default. No `install-app friday` step. No wrapper command. The framework itself is the agentic kernel.

### Upstream Frappe Becomes A Read-Only Resource

`frappe/frappe` is no longer a partner project for Friday — it is a reference we selectively absorb from. See §5 for the absorption workflow. The Friday community owns the kernel's future.

---

## 2. Why a Hard Fork

Agents must be first-class actors in the permission engine, job system, audit layer, and request context. That requires modifying Frappe's core — not wrapping it from outside.

Trying to treat agents as first-class citizens through app/module hooks alone would mean:

- Fragile monkey-patching of framework internals from an app.
- Agent context injected into request cycles through hacks rather than designed interfaces.
- Two competing identities (Frappe user, Friday agent) with no coherent model in the permission engine.
- A "Friday app" that modifies behavior Frappe didn't intend to expose — which is worse than an explicit fork because the surface is undocumented and fragile.

A hard fork is the honest position: Friday **is** a new framework. It starts from proven Frappe engineering and adds the governed-agent layer. The bench ecosystem is retained because it is excellent operational infrastructure. The core is ours.

---

## 3. What We Change in Core

### First-class agent primitives (core modifications, always)

- **Actor context propagation** — agent identity flows through request context, background jobs, and workflows alongside human user context.
- **Trace ID propagation** — a consistent trace ID links: gateway event → permission check → job dispatch → sandbox execution → audit row.
- **Audit hook surface** — framework-level hooks for `Permission Decision Log` and `Execution Log` emission, fired from the permission engine and job system.
- **Agent-scoped API key authentication** — agent profiles authenticate via scoped API keys; the framework's auth layer understands agent vs human actor distinction.
- **Friday shell** — default workspace, CLI entrypoint branding, and control-room navigation registered at the framework level.

### Domain features (Friday apps, not core)

- Business-process automation
- Raven War Room integration
- pgvector memory and knowledge graph
- Auto-research agents
- Analytical and predictive agents
- Multi-site ACP
- Industry-specific skill templates

The line: **framework identity and cross-cutting execution infrastructure live in core. Domain features live in Friday apps.**

---

## 4. Branch Strategy

```
upstream/v16     ← read-only mirror of frappe/frappe v16 stable tag
upstream/v16-sec ← read-only tracking branch for upstream security releases
friday/main      ← Friday's main development branch (derived from upstream/v16)
friday/release-X.Y
```

`upstream/*` branches exist solely to make manual patch review tractable. Friday development never happens on `upstream/*`.

---

## 5. Upstream Patch Policy

Upstream Frappe patches are absorbed **manually and selectively**. There is no automatic sync.

**This is the protection a hard fork buys us.** Upstream Frappe cannot push to our fork. If Frappe drops Redis, deprecates a feature, restructures their permission engine, or releases v17 with breaking changes — none of that reaches Friday unless we choose to pull it. Our lifecycle is independent.

The price of independence: we own all maintenance of what we kept. We assess every upstream change. We cherry-pick what we want. We refuse what we don't.

| Trigger | Action |
|---|---|
| Upstream security release (CVE) | Maintainer reviews within 48 hours; if Friday is affected, cherry-pick or reimplement the fix into `friday/main` |
| Upstream bug fix we hit | Cherry-pick into `friday/main` when encountered |
| Upstream performance or architectural improvement | Reviewed quarterly; incorporated if it benefits Friday's substrate |
| Upstream feature | Incorporated only if Friday wants it and it doesn't conflict with agent-native architecture |
| Upstream major release (v17+) | Project-level decision: plan migration, stay on current, or skip |

This is intentionally lightweight. The Frappe bench ecosystem moves slowly at the core level. Most upstream activity is in ERPNext and apps, which Friday does not track.

### 5.1 Selective Absorption Workflow

The concrete day-to-day for watching upstream without being controlled by it.

**One-time setup** (on any clone of our fork):

```bash
cd <bench>/apps/frappe   # or wherever our fork lives locally
git remote add upstream https://github.com/frappe/frappe.git
git fetch upstream
```

After this, `origin` points at Friday's fork (we control), `upstream` points at frappe/frappe (read-only for us).

**Weekly / monthly: watch what upstream is doing**

```bash
git fetch upstream
git log upstream/version-16 --oneline --since="2 weeks ago"
```

Read the commit messages. No code is pulled into our fork by this — `git fetch` only updates remote-tracking references locally. Nothing on GitHub changes.

**When a specific upstream commit looks relevant** (CVE fix, bug we hit, improvement we want):

```bash
git checkout friday/main           # work on our branch
git cherry-pick <upstream-sha>     # pull only that commit in
# resolve conflicts if any
bench --site friday.localhost migrate
bench --site friday.localhost run-tests --app friday
# if clean:
git push origin friday/main
```

Tag the cherry-picked commit with `[upstream-absorb: <reason>]` in the message so the divergence registry can track origin.

**When upstream does something we explicitly reject** (e.g. drops Redis, removes a feature Friday depends on):

```bash
# Do nothing. Our fork is unaffected.
# Optionally: open an issue at Friday-Labs-Inc/friday documenting the decision
# so future contributors know we deliberately diverged from this upstream change.
```

**When upstream releases a new minor version** (e.g. v16.1, v16.2):

1. Read their changelog.
2. List the changes that matter to Friday.
3. Cherry-pick each in its own commit, test in isolation.
4. If a change is too entangled to cherry-pick safely, defer or reimplement.

**When upstream releases a new major version** (v17+):

Project-level decision under §5 table. Not a routine task.

### 5.2 What Independence Looks Like In Practice

A concrete scenario, for clarity.

> *Upstream Frappe announces in their v17 plan: "We are dropping Redis. Background jobs will move to a Postgres-backed queue."*

Friday's response:

1. **Read the announcement.** Decide whether Redis matters to Friday's roadmap.
2. **If we keep Redis:** do nothing. Our fork still uses Redis. The upstream v17 commits never reach us. Our v16 fork lives on.
3. **If we follow:** plan it as a major version migration of our own fork. Cherry-pick or rewrite the queue layer. Test heavily. Ship as Friday vX.Y when ready.
4. **The decision is ours, not theirs.**

This is the architectural promise of a hard fork. Anyone evaluating Friday — sponsor, contributor, downstream user — can rely on it.

---

## 6. Divergence Registry

The repo maintains `docs/core-divergences.md` — a living record of every place Friday's fork differs from the Frappe v16 base.

Each entry:

```
## Divergence: <short name>

- **File(s):** path/to/file.py:42-67
- **Date:** YYYY-MM-DD
- **Why:** what agent-native behavior this enables
- **Upstream conflict risk:** Low / Medium / High
- **Tests:** which tests cover this divergence
```

Entries are added when a divergence lands. Reviewed quarterly for candidates to retire (upstream added an equivalent, or the feature was removed).

---

## 7. Patch Discipline

Every core modification:

1. **Tagged in git.** Commit prefix `[friday-core]` with a reference to the divergence registry entry.
2. **Marked in code.** A comment `# friday-core: <name>` on or near the changed lines.
3. **Tested.** A test asserts the Friday-specific behavior; if upstream later changes the surrounding code, the test fails loudly.
4. **Reviewed.** No core modification merges without project owner approval.

---

## 8. What Stays Untouched

These areas of Frappe core are not modified in Friday unless a critical security or correctness reason forces it:

- DocType engine internals
- ORM internals
- Database adapter code
- Setup / install / migration logic
- Frontend Desk JS internals beyond workspace customization

If a Friday feature seems to require touching these, redesign the feature first.

---

## 9. Compatibility Promise

Existing Frappe apps installed on a Friday site should continue to work unless they directly conflict with a Friday core divergence. Friday documents breaking changes to Frappe's public APIs and provides migration guidance per release.

This promise is practical, not absolute. Friday is a new framework. If a Frappe app relies on an internal that Friday needs to change for agent-native reasons, Friday's framework needs win. The promise covers public APIs and expected behavior, not implementation internals.

---

## 10. Naming and Attribution

- The framework is called **Friday** in all user-facing material.
- Documentation and the README acknowledge: "Friday is derived from Frappe Framework (https://github.com/frappe/frappe), distributed under GPL v3."
- The Frappe NOTICE file is preserved and extended in Friday's repo.
- Frappe Technologies and The Commit Company are credited as the upstream authors.

GPL v3 requires this. Good faith requires it too.

---

## 11. Summary

Friday forks Frappe v16 stable and develops the agentic framework directly in core. The bench ecosystem is kept intact. Agent-native primitives — actor context, trace propagation, audit hooks, sandboxed execution — are built into the framework, not bolted on. Upstream Frappe patches are applied manually when Friday needs them. The fork is the starting point, not a last resort.
