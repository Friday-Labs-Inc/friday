# Friday — Codex Implementation Brief

> **Who this is for:** Any AI coding agent (OpenAI Codex, Claude Code, Cursor, Aider, etc.) assigned to build Friday Phase 1.
>
> **What this is:** A single self-contained brief. Read this file first, then the design docs listed in §2. Do not start writing code until you have read both.

---

## 1. What You Are Building

Friday is an **agentic framework** — a system that lets AI agents do real business work (read records, draft documents, send emails) inside a Frappe v16 application, with every action **permission-checked, sandboxed, and logged**.

Think of it like this: a human employee at a company can only do certain things — they need the right role, the right access, and everything they do is recorded. Friday makes AI agents work the same way.

**The Friday repository is a hard fork of Frappe v16 stable.** You are not building a plugin on top of Frappe. You ARE building inside the Frappe codebase, adding agent-native capabilities to its core, and creating a Friday app (`friday/`) on top of it.

**Current state of the repo:** Zero code. Only design documents and project files. Your job is to write all the code.

---

## 2. Design Documents — Read These Before Writing Code

All design docs live in `docs/design/`. Read them in this order:

| Priority | File | What it tells you |
|---|---|---|
| 1 | `docs/design/42-phase-one-authority-contract.md` | **WHAT to build in Phase 1 — the law** |
| 2 | `docs/design/39-friday-framework-strategy.md` | Framework identity, fork discipline |
| 3 | `docs/design/05-module-design.md` | App layout, DocType field schemas, file structure |
| 4 | `docs/design/10-agent-execution-guide.md` | **HOW to build — 9 slices, micro-loop, rules** |
| 5 | `docs/design/11-agent-validation-checklist.md` | **Completion criteria — checkbox per slice** |
| 6 | `docs/design/06-phase-one-scope.md` | Phase 1 scope and milestones |
| 7 | `docs/design/08-agent-setup-guide.md` | Environment setup commands |
| 8 | `docs/design/04-security-model.md` | Security requirements |
| 9 | `docs/design/45-fork-policy.md` | What lives in core vs apps |
| 10 | `docs/design/14-integrated-architecture.md` | How all layers fit together |

**Rule:** If any doc conflicts with `42-phase-one-authority-contract.md`, doc 42 wins.

---

## 3. Stack Decisions (All Final — Do Not Re-Open)

| Decision | Choice | Reason |
|---|---|---|
| Frappe version | **v16 stable** | Longest support, modern features |
| Database | **PostgreSQL + pgvector** | AI memory search requires vector support |
| Chat UI (Raven) | **Required** | Friday's chat front door — bot identity, project channels, war room. Superseded the v0.1 "excluded" decision (designs 58, 73). |
| ERPNext | **Excluded this phase** | Use case, not framework requirement |
| CLI strategy | **Extend bench** — `bench friday <cmd>` | No new tools to install |
| LLM provider | **Provider-agnostic interface; Minimax as first provider** | Swap provider by changing one config value |
| Sandbox | **Docker** | Standard, isolated, proven |
| Repo strategy | **Hard fork of Frappe v16** | Friday IS the fork |

---

## 4. Environment Setup

Before writing any code, set up the local development environment.

### 4.1 System Requirements

Verified working combination (see `docs/project/IMPLEMENTATION_LOG.md` for the discovery trail):

```
Python:       3.14   (Frappe v16 version-16 branch requires >=3.14,<3.15)
Node.js:      24 LTS (frontend yarn install fails on Node 22 and older)
PostgreSQL:   15+ with pgvector (PG 18.3 confirmed working)
Redis:        7 or higher
Docker:       24 or higher (daemon running)
Git:          2.40 or higher
Bench:        5.29.1 or compatible
```

**Heads-up:** if your machine has a Conda base environment active, deactivate it before running `bench init`. Conda's compilers cause the `mysqlclient` native build to fail in subtle ways.

### 4.2 Install Bench and Initialize

```bash
pip install frappe-bench

# bench 5.x init does NOT accept --db-type; set the db type on the site instead.
bench init friday-bench --frappe-branch version-16 --python python3.14

cd friday-bench

# If PostgreSQL is on a non-default port (commonly 5433 when 5432 is held by Docker):
bench set-config -g db_host 127.0.0.1
bench set-config -g db_port 5433

# bench new-site for postgres first connects to a maintenance DB matching the root username.
# If you see "database <name> does not exist", create it once and retry:
#   sudo -u postgres createdb <root-username>
bench new-site friday.localhost --db-type postgres --admin-password admin

bench --site friday.localhost set-config developer_mode 1
```

### 4.3 Enable PostgreSQL Extensions

```sql
-- Run on the friday.localhost database
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 4.4 The Friday Kernel — Already Present

There is **no separate "Friday app" to create**. The Friday repository IS the kernel — a hard fork of Frappe v16 with agent-native modifications. See `docs/design/45-fork-policy.md` §1.

After `bench init friday-bench --frappe-branch version-16 --python python3.14`, point `apps/frappe` at the Friday kernel:

```bash
cd friday-bench/apps/frappe
git remote set-url origin https://github.com/Friday-Labs-Inc/friday.git
git fetch origin
git checkout main          # the Friday kernel branch
```

Now `apps/frappe/` IS the Friday kernel. Any `bench new-site` against this kernel produces an agentic site by default — no install-app step, no wrapper command.

Agent kernel modules (Agent Profile, Skill, Execution Log, etc.) live **inside the Frappe source tree** under a module path such as `frappe/friday_core/` or appropriate sub-modules — added in Slice 1 by extending Frappe's own modules.txt, not by creating a new app.

### 4.5 Verify Setup

```bash
bench --site friday.localhost migrate       # must run clean
bench --site friday.localhost run-tests --app friday   # zero tests = OK at start
source ~/.nvm/nvm.sh && nvm use 24          # activate Node 24 before bench start
bench start                                 # Desk loads at http://friday.localhost:8000
```

---

## 5. The Build Plan — 9 Slices

Build one slice at a time. Do not start slice N+1 until slice N is complete and all its validation checkboxes (in `docs/design/11-agent-validation-checklist.md`) are green.

After each slice: run tests, run `bench migrate`, commit with a conventional commit message.

---

### Slice 1 — Foundations & DocType Skeletons

**Goal:** App scaffolded. Eight DocTypes exist and are creatable from the Frappe Desk UI.

**What to build:**

1. Create module folders inside `friday/`: `gateway/`, `agents/`, `skills/`, `tasks/`, `messaging/`, `permissions/`. Each gets `__init__.py`.
2. Register all modules in `friday/modules.txt`.
3. Create these DocTypes (field schemas are in `docs/design/05-module-design.md` §"Core DocTypes"):
   - `Agent Profile` — in module `Agents`
   - `Skill` — in module `Skills`
   - `Agent Task` — in module `Tasks`
   - `Agent Project` — in module `Tasks`
   - `Chat Message` — in module `Messaging`
   - `Chat Platform` — in module `Messaging`
   - `Execution Log` — in module `Agents`, **is_submittable = 1**
   - `Permission Decision Log` — in module `Permissions`, **is_submittable = 1**
4. Add empty controller classes (`{doctype}.py`) for each DocType.
5. Run `bench --site friday.localhost migrate`.
6. Verify each DocType loads in the Desk without errors.

**Test to write:** `test_doctypes_exist.py` — opens each DocType meta and asserts required fields exist.

**Done when:** You can create one row of each DocType manually in the Desk.

---

### Slice 2 — Permission Engine

**Goal:** `friday.permissions.matrix.check(profile, skill)` returns `allowed=True/False` with a reason, and logs every decision to `Permission Decision Log`.

**What to build:**

1. `friday/permissions/matrix.py`
   - `build_matrix(agent_profile_name: str) -> PermissionMatrix`
   - `check(matrix, skill_name: str) -> Decision`
2. `friday/permissions/cache.py`
   - Redis key: `friday:perm_matrix:{profile_name}`, TTL 60s
   - Invalidation on Agent Profile or Role update
3. `friday/permissions/decisions.py`
   - Persist every check as a submitted `Permission Decision Log` row
4. Wire invalidation hooks in `friday/hooks.py`:
   ```python
   doc_events = {
       "Agent Profile": {"on_update": "friday.permissions.cache.invalidate_for_profile"},
       "Role": {"on_update": "friday.permissions.cache.invalidate_all"},
   }
   ```

**Tests to write:**
- Allow case: profile with matching role → allowed
- Deny case: profile missing role → denied
- Deny case: skill status != Active → always denied
- Cache hit is faster than cache miss
- Permission Decision Log row is submitted (not draft)

**Coverage target:** 80% lines, 100% branches on `matrix.check()`.

**Done when:** `bench execute friday.permissions.matrix.check --args "['profile_a', 'create_note']"` prints a decision and a row appears in Permission Decision Log.

---

### Slice 3 — Skill Loader

**Goal:** Active, permitted Skills for a given profile are loaded from the database, cached in Redis, and converted to LLM tool definitions (OpenAPI-style JSON schema).

**What to build:**

1. `friday/skills/loader.py`
   - `load_for_profile(profile_name) -> list[SkillDefinition]`
   - Only returns Skills where `status = Active` AND the profile has permission
   - Cache in Redis: `friday:skills:{profile_name}`, TTL 300s
2. `to_tool_definition(skill) -> dict` — converts a Skill row to an OpenAPI tool schema
3. Invalidation hooks on Skill `after_insert`, `on_update`, `on_trash`

**Tests to write:**
- Active + permitted → appears in list
- Active + not permitted → does NOT appear
- Draft / Retired / Archived → does NOT appear
- Cache invalidates when Skill is updated

**Done when:** Calling the loader from `bench console` returns a list of dicts you can paste into any LLM API call as tools.

---

### Slice 4 — Gateway: CLI Adapter + Chat Message Round Trip

**Goal:** `bench friday chat --profile <name>` opens a prompt. You type a message. It bounces back as an echo reply. Both messages saved to `Chat Message` DocType.

**What to build:**

1. `friday/messaging/adapters/cli.py`
   - `bench friday chat --profile <name>` opens an interactive REPL
   - Each line creates a `Chat Message` (direction=inbound) via Frappe REST
   - Polls / subscribes for outbound `Chat Message` on same session and prints it
2. `friday/gateway/session_manager.py`
   - Subscribe to Frappe real-time event `chat_message.after_insert`
   - On inbound event: resolve Agent Profile, pass to (stubbed) agent runner
   - Stub runner writes back `"echo: <content>"` as an outbound Chat Message

**Tests to write:**
- Inbound message creates a row
- Echo reply appears in CLI within 1 second
- Both messages visible in Desk

**Done when:** You type "hello" and see "echo: hello".

---

### Slice 5 — LLM Integration

**Goal:** Replace the echo stub with a real LLM response. No tool calling yet — just conversation.

**What to build:**

1. `friday/gateway/prompt_builder.py`
   - Assembles system prompt from `Agent Profile.system_prompt` + recent session messages
2. `friday/agents/runner.py` (first version)
   - Calls the LLM provider (Minimax first — provider-agnostic interface from day one)
   - Returns the model reply as a `Chat Message` (direction=outbound)
3. API key stored as a Frappe `Password` field on `Agent Profile` or in an `Agent Settings` singleton DocType — never in `.env` committed to repo
4. Implement provider interface so swapping providers changes one config value, not the code

**Tests to write (use mocks — do not call real LLM in tests):**
- Mocked provider returns reply → outbound Chat Message exists
- Prompt assembly is deterministic for same inputs (golden-file test)
- Mocked 429 → retried up to 3 times → success
- Mocked persistent 5xx → error message returned to user, no silent failure

**Done when:** `bench friday chat` produces a real LLM reply, not an echo.

---

### Slice 6 — First Real Skill: `create_note`

**Goal:** Full end-to-end governed execution. User asks the agent to create a note. LLM emits a tool call. Permission engine checks it. Skill executes. Note is created. Everything is logged.

**What to build:**

1. Create a `Skill` row named `create_note` with:
   - `parameters_schema`: `{title: string, content: string}`
   - `required_doctypes`: Note (create)
   - `risk_level`: low
   - `status`: Active
2. Create an `Agent Profile` named `note_taker` with a role that grants Note create permission
3. Extend `friday/agents/runner.py`:
   - Include tool definitions in LLM call (from Slice 3)
   - When LLM emits a tool call → route to dispatcher
4. `friday/agents/dispatcher.py`:
   - Call permission engine first (always)
   - If denied → write rejected `Execution Log` row, return error to user
   - If allowed → execute skill (in-process is OK for this slice only — Docker comes in Slice 7)
5. Submit an `Execution Log` row for every execution attempt (success or failure)

**Tests to write:**
- `note_taker` profile → Note is created → Execution Log shows `success`
- Profile without Note permission → Note is NOT created → Execution Log shows `rejected`
- Both flows produce exactly one Execution Log row

**Done when:** `bench friday chat --profile note_taker`, then type "make a note titled Test about hello world" → Note row appears in Frappe Desk.

---

### Slice 7 — Docker Sandboxing

**Goal:** Move skill execution from in-process to a Docker container. Slice 6's end-to-end flow still works, but the skill now runs inside an isolated container.

**What to build:**

1. Build `friday-worker` Docker image:
   - Python 3.11
   - No host mounts in Dockerfile
   - Entrypoint: reads JSON command from env/stdin, returns JSON on stdout
   - Non-root user
2. `friday/agents/isolation.py`
   - `spawn_worker(profile, skill, params) -> result`
   - Uses Docker SDK for Python
   - CPU + memory caps via `host_config`
   - Network: bridge mode, only Frappe API host in allowlist
   - Passes short-lived API token to container as env var (never long-lived)
3. Container flow:
   - Authenticates to Frappe REST API with the scoped token
   - Executes the skill action via API call
   - Exits with JSON result
4. Gateway captures stdout JSON, writes Execution Log, sends reply

**Tests to write:**
- Container spawns and tears down cleanly (no leftover containers)
- Memory limit enforced: allocating beyond limit → container killed → graceful failure logged
- Network isolation: container cannot reach external hosts not in allowlist
- Slice 6 `create_note` still works end-to-end

**Done when:** `create_note` works exactly as before but the skill runs inside Docker (confirm with `docker ps` during execution).

---

### Slice 8 — Agent Task + Dispatcher + Kanban

**Goal:** Tasks can be created in the Desk. The dispatcher automatically picks them up, assigns them to an agent, and the agent executes them. You can watch this happen in real time on a Kanban board.

**What to build:**

1. Define a Frappe Workflow on `Agent Task`:
   - States: Pending → Assigned → Executing → Blocked → Review → Completed / Cancelled
   - Transitions with role-based permissions
   - Mark which states are "dispatchable" (eligible for dispatcher to claim)
2. `friday/tasks/workflow.py` — hook on Agent Task `on_update` for state transitions
3. `friday/tasks/dispatcher.py`:
   - Scheduled job every 60 seconds via `hooks.py`
   - Query Tasks in dispatchable states with no `assigned_to_profile`
   - Match `required_skills` against available Agent Profiles
   - **Atomic claim** — use `SELECT ... FOR UPDATE SKIP LOCKED` so two dispatcher runs cannot claim the same task
   - Emit Frappe real-time event when task is claimed
4. Gateway picks up the real-time event → routes task to the assigned agent's runner
5. Enable native Kanban view on `Agent Task` grouped by `workflow_state`

**Tests to write:**
- Concurrency test: 100 Tasks, 5 simultaneous dispatcher runs → each task claimed exactly once, no double-claims
- State machine test: every transition is permitted or denied per the Workflow definition
- End-to-end: create a Task in Desk → dispatcher claims it → agent executes → state reaches Completed

**Done when:** Create a Task in the Desk, wait 60 seconds, watch it move across the Kanban board to Completed.

---

### Slice 9 — Polish & Hardening

**Goal:** Public-ready repo. Another developer can install Friday from the README alone.

**What to do:**

1. Audit test coverage:
   - Overall: ≥ 70% line coverage
   - Critical modules (`permissions/`, `gateway/`, `agents/isolation.py`, `tasks/dispatcher.py`): ≥ 85%
2. Add logging everywhere:
   - Every permission decision → Permission Decision Log
   - Every skill execution → Execution Log
   - Every dispatcher action → `frappe.logger()`
   - Levels: INFO for state changes, WARNING for retries, ERROR for failures
3. Write docs:
   - `docs/install.md` — full prerequisites and setup
   - `docs/quickstart.md` — first agent + skill in 10 minutes
   - `docs/architecture.md` — overview linking to design docs
4. Add `Makefile` (or `nox`) targets: `setup`, `test`, `lint`, `migrate`, `run-gateway`
5. Verify: `LICENSE` (GPL v3), `README.md`, `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
6. Set up `.github/workflows/test.yml` — runs tests on every PR
7. Dogfood: use Friday to manage Friday's own remaining work for 5+ days

**Done when:** A fresh developer can follow `docs/install.md` and reach a running Friday site with no manual debugging.

---

## 6. Rules — Must Follow on Every Slice

These are not suggestions. Every PR must pass all of them.

### Never bypass permissions
Every code path that invokes a skill must call `friday.permissions.matrix.check`. Write a test for the denied case on every new skill.

### Never write raw SQL for state changes
Use `frappe.get_doc(...).insert()` / `.save()` / `.submit()`. Raw SQL is only for read-only analytics or pgvector queries.

### Never hard-code paths
No `~/.friday`, no `/tmp/something`, no literal site names. Use `frappe.local.site`, `frappe.get_site_path()`, `tempfile`.

### Never swallow exceptions silently
Every `except` block either recovers and logs at `WARNING` level or re-raises. No bare `pass` in except clauses.

### Never break the migration path
Every DocType change includes a patch in `friday/patches.txt`. `bench migrate` from an empty site to HEAD must always run clean.

### Never commit secrets
API keys, tokens, passwords go in Frappe `Password` fields (encrypted at rest). Run `git secrets` or equivalent before every commit.

### Immutability in Python logic
Create new objects/dicts instead of mutating existing ones. This prevents subtle shared-state bugs in concurrent execution.

### Commit message format
```
feat(permissions): add role-based matrix builder
fix(gateway): handle missing session id gracefully
test(skills): cover Skill loader cache invalidation
docs(install): add PostgreSQL extension setup
```

### PR size
Each slice = one or two PRs. No PR over 800 lines of diff.

---

## 7. File Header (Every New Python File)

```python
# Friday — Agentic Framework
# Copyright (C) 2024  Friday Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
```

---

## 8. When You Are Stuck

If you cannot proceed because the spec is ambiguous, a Frappe API behaves unexpectedly, or two design docs conflict, stop and produce this report instead of guessing:

```
## Blocker

### Slice and task
[e.g. Slice 2, Task 3 — Redis cache invalidation]

### What I tried
[approaches attempted and why they failed]

### The conflict or ambiguity
[which spec sections conflict, or what Frappe API does unexpectedly]

### Options
A. [option with tradeoffs]
B. [option with tradeoffs]

### My recommendation
[preferred option with reasoning]

### Urgency
[blocking this slice / can defer to next slice]
```

Do NOT silently pick an option and move on. Surface the decision and wait.

---

## 9. Phase 1 Is Complete When

- `bench install-app friday` on a fresh site runs clean.
- Control Room workspace exists and loads.
- All eight core DocTypes exist.
- A user can create or submit a task.
- Dispatcher claims a dispatchable task exactly once (atomic).
- Agent executes one approved skill through the governed path (Docker).
- Denied skill calls are logged and rejected.
- Execution and permission logs fully reconstruct what happened.
- Tests pass: permissions (100% branch), dispatcher (concurrency), end-to-end skill.
- All `docs/design/11-agent-validation-checklist.md` checkboxes are green.

When done, produce the **Phase One Completion Report** (template is at the bottom of `docs/design/11-agent-validation-checklist.md`).

---

## 10. What Comes After Phase 1

Do not build these in Phase 1. They are listed so you do not accidentally scope-creep:

- Raven chat UI (Phase 2)
- ERPNext Purchase Order automation (Phase 1 flagship — starts after the framework loop is proven)
- Autopilot / autonomous skill activation (Phase 2+)
- Semantic memory / pgvector search (Phase 2)
- Cross-site agent communication (Phase 3)
- Multi-platform adapters beyond CLI (Phase 2)

---

## 11. Quick Reference

| Thing | Where |
|---|---|
| What to build | `docs/design/42-phase-one-authority-contract.md` |
| How to build it (slices) | `docs/design/10-agent-execution-guide.md` |
| Done criteria (checkboxes) | `docs/design/11-agent-validation-checklist.md` |
| DocType field schemas | `docs/design/05-module-design.md` |
| Fork discipline | `docs/design/45-fork-policy.md` |
| Security model | `docs/design/04-security-model.md` |
| All stack decisions | `docs/decisions/spike-results.md` |
| Gap analysis (context) | `docs/design/40-gap-analysis-and-resolution-plan.md` |
