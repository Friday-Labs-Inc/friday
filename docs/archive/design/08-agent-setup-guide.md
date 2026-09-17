# 08 — Agent Setup Guide

> Prepare any agentic coding framework (Claude Code, OpenClaw, Cursor, Aider, etc.) with the context, sources, and environment needed to implement Friday Phase One.
>
> This document is framework-agnostic. The instructions assume an agent capable of reading remote repositories, understanding multi-file specifications, writing code, and executing shell commands in a sandboxed development environment.
>
> Companion docs: `09-agent-evaluation-guide.md` (criteria for reusing Hermes code), `10-agent-execution-guide.md` (the build sequence), `11-agent-validation-checklist.md` (gate before merge).

---

## 1. Context sources

The agent loads sources in this order.

### 1.1 Friday specification — primary, authoritative

| Document | Purpose |
|---|---|
| `00-glossary.md` | Every Friday term resolves here first |
| `00-README.md`, `01-vision-and-architecture.md` | Intent and system design |
| `02-feature-comparison.md` | Capability map Hermes / OpenClaw → Friday |
| `03-technical-stack.md` | Stack and rationale |
| `04-security-model.md` | Permission and isolation requirements |
| `05-module-design.md` | Module layout and DocType fields |
| `06-phase-one-scope.md` | Build plan, milestones, risks |
| `07-legal-and-branding.md` | License headers and naming |
| `14-integrated-architecture.md` | Runtime architecture and request flow |
| `39-friday-framework-strategy.md` | Framework-not-app identity and fork discipline |
| `41-porting-strategy-hermes-erpnext-raven.md` | Verdict per Hermes / ERPNext / Raven piece |
| `42-phase-one-authority-contract.md` | v0.1 scope authority |
| `45-fork-policy.md` | One-repo kernel model and upstream-absorption workflow |
| `46-security-claims-audit.md` | Verifiability rules for competitor security claims |

If anything in any other source contradicts the Friday specs, the specs win. If two Friday docs conflict, the authority hierarchy in §4 resolves it.

### 1.2 Hermes Agent — reference, selective

- Repository: `https://github.com/NousResearch/hermes-agent`
- Branch: `main`
- License: verified on first access.

Hermes is a reference implementation, not code to copy verbatim. Reuse criteria are in `09-agent-evaluation-guide.md`. The verdict per piece is in `41-porting-strategy-hermes-erpnext-raven.md` and `14-integrated-architecture.md` §10.

Hermes paths worth studying:

| Path | Studied for |
|---|---|
| `gateway/run.py` | GatewayRunner lifecycle, session caching |
| `agent/run_agent.py` | AIAgent loop, tool execution, retries |
| `agent/prompt_builder.py` | System prompt assembly |
| `skills/` | Skill manifest format, progressive disclosure |
| `gateway/platforms/` | Platform adapter pattern |
| `agent/tools/` | Tool registry, MCP integration |
| `hermes_cli/commands.py` | Slash command resolution |
| `gateway/builtin_hooks/` | Lifecycle hooks |
| `kanban/` (if present) | Multi-agent dispatcher |
| `AGENTS.md`, `SECURITY.md` | Design rules and security boundaries |

### 1.3 Frappe Framework documentation

- Main docs: `https://docs.frappe.io/framework`
- DocTypes: `https://docs.frappe.io/framework/user/en/basics/doctypes`
- Permissions: `https://docs.frappe.io/framework/user/en/permissions`
- Hooks: `https://docs.frappe.io/framework/user/en/python-api/hooks`
- Background jobs: `https://docs.frappe.io/framework/user/en/background_jobs`
- Workflow: `https://docs.frappe.io/framework/user/en/workflows`
- DeepWiki (deep code reference): `https://deepwiki.com/frappe/frappe`

### 1.4 OpenClaw — anti-pattern reference

- Repository: `https://github.com/openclaw/openclaw`
- Used only as a contrast case for default-permissive security posture. No code is copied.

---

## 2. Development environment

### 2.1 System prerequisites

```
Python:     3.14   (Frappe v16's version-16 branch requires >=3.14,<3.15)
Node.js:    24 LTS (Frappe v16 frontend requires Node >=24; older versions fail yarn install)
PostgreSQL: 15+    with pgvector ≥ 0.8.2 (PG 18 confirmed working)
Redis:      7+
Docker:     24+    with running daemon
Git:        2.40+
```

Verified working combination (`docs/project/IMPLEMENTATION_LOG.md`, 2026-05-18):

- Python 3.14.4
- Node 24.15.0 / npm 11.12.1 / yarn 1.22.22
- PostgreSQL 18.3 with pgvector 0.8.1 and pg_trgm 1.6
- Frappe 16.18.2 / Bench 5.29.1

### 2.2 bench setup

```bash
pip install frappe-bench

# bench 5.x init does NOT accept --db-type; the db type is set on the site.
bench init friday-bench --frappe-branch version-16 --python python3.14
cd friday-bench

# If PostgreSQL is on a non-default port (e.g. 5433 because Docker holds 5432):
bench set-config -g db_host 127.0.0.1
bench set-config -g db_port 5433

bench new-site friday.localhost --db-type postgres --admin-password [secure]
bench --site friday.localhost set-config developer_mode 1
```

Gotchas captured in IMPLEMENTATION_LOG:

- Deactivate any active Conda base environment before `bench init` — Conda's compilers break the `mysqlclient` native build.
- `bench new-site --db-type postgres` first connects to a maintenance database named after the root login. Create it manually (`createdb <rolename>`) if missing.
- Activate Node 24 in every shell before `bench start` or any frontend command: `source ~/.nvm/nvm.sh && nvm use 24`.

### 2.3 PostgreSQL extensions

```sql
-- On the Friday site database, as superuser:
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fuzzy search
```

### 2.4 Friday framework scaffold

The Friday repository is the Frappe v16 fork — there is no separate "app on top of Frappe" layer. Agent kernel modules live inside the Frappe source tree per `45-fork-policy.md`. `bench` remains the operational CLI; the `friday` command group adds agent-specific operations.

```
friday/                                  ← repo root = the fork
├── frappe/                              ← Frappe v16 source tree
│   └── friday_core/                     ← agent kernel modules (see 05-module-design.md)
├── LICENSE                              ← GPL v3
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── AUTHORS
├── CHANGELOG.md
├── pyproject.toml
├── .pre-commit-config.yaml
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   └── design/
└── tests/
```

Conceptual paths. Implementation may evolve internal package layout; the rule is that the repo IS the fork and Friday Core is part of it, not installed on top.

---

## 3. Code conventions

### 3.1 Python

- Python 3.14, type-hinted where reasonable.
- `black` (line length 100), `ruff`, `mypy` (strict on `permissions/` and `gateway/`).
- Google-style docstrings on every public function.
- DocType controllers inherit from `frappe.model.document.Document`.

### 3.2 File headers

```python
# Copyright (c) [year] Friday Labs and contributors
# Licensed under GNU GPL v3 or later. See LICENSE.
```

### 3.3 Naming

- DocType names: Title Case with spaces (`Agent Profile`, `Skill`).
- Python class names: PascalCase (`AgentProfile`, `Skill`).
- DocType folder names: snake_case (`agent_profile/`, `skill/`).
- Field names: snake_case (`assigned_roles`, `risk_level`).

### 3.4 Module boundaries

- No cross-module imports except through each module's explicit `__init__.py` interface.
- Permission checks always go through `friday.permissions.matrix`. Never inline.
- Database access always through Frappe ORM (`frappe.db`, `frappe.get_doc`). Raw SQL is permitted only for pgvector queries, via parameterised `frappe.db.sql`.

### 3.5 Testing

- Every module has a `tests/` subdirectory.
- `pytest` with `frappe.tests.utils.FrappeTestCase`.
- Permission engine: 80% line coverage minimum.
- Gateway and dispatcher: integration tests required.

---

## 4. Authority hierarchy

On any conflict, resolve in this order:

1. `42-phase-one-authority-contract.md` (v0.1 scope).
2. `39-friday-framework-strategy.md` and `45-fork-policy.md` (identity and fork rules).
3. `41-porting-strategy-hermes-erpnext-raven.md` and `14-integrated-architecture.md` (composition and verdict per piece).
4. Other Friday specs (`01`–`07`, `40`, `46`).
5. Frappe Framework conventions (DocType API, hooks, permissions).
6. Hermes patterns (architectural guidance only).
7. General Python and web best practice.

The agent never silently chooses a pattern that contradicts a Friday spec. If specs are ambiguous, the agent flags it for human review.

---

## 5. Permitted tooling

| Tool | Use for |
|---|---|
| `bench` | Site, app, migration, build operations |
| `bench execute` | Running Python in site context for testing |
| `bench console` | Interactive Python in site context |
| Git | All version control |
| Docker | Building and running sandbox containers |
| `pytest` | All test execution |
| `pre-commit` | Run before every commit |
| `psql` | Direct PostgreSQL inspection (read-only preferred) |
| `redis-cli` | Inspecting cache and pub/sub |

The agent may **not**:

- Disable security features to make development easier.
- Skip permission checks "temporarily".
- Hard-code credentials anywhere, including in tests (use `.env.test` patterns).
- Push to a public remote without explicit human approval.
- Modify Frappe Framework source outside the documented core-divergence path; every divergence is recorded in `docs/core-divergences.md`.

---

## 6. Progress-reporting format

```
## Milestone: [name]

### Completed
- [done items with file paths]

### In Progress
- [current work]

### Blockers / Questions for Human
- [explicit questions; unresolved ambiguities]

### Next Steps
- [planned next actions]

### Decisions Made
- [significant decisions taken with rationale]
```

The human stays in the loop on every significant decision without constant micro-management.

---

## 7. Definition of "ready to start"

Setup is complete when:

- [ ] Friday spec documents listed in §1.1 are loaded in the agent's context.
- [ ] `42` is loaded and understood as the v0.1 scope authority.
- [ ] `39` and `45` are loaded and understood as identity and fork rules.
- [ ] `14` is loaded and understood as the integrated runtime architecture.
- [ ] Hermes repository is accessible (read-only).
- [ ] bench is provisioned with PostgreSQL + pgvector and Redis.
- [ ] Friday framework shell is scaffolded with LICENSE, README, bench-aware setup, `friday` command group, Framework Console workspace, and agent kernel module structure.
- [ ] Pre-commit hooks are installed and pass on the empty repo.
- [ ] Initial commit is made on `friday/main`.
- [ ] The agent produces a written summary of Phase One's goal in its own words.

When every checkbox is green, proceed to `09-agent-evaluation-guide.md`.
