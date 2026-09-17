# 10 — Agent Execution Guide

> Step-by-step implementation order for Phase One. The agent follows this after `08-agent-setup-guide.md` and `09-agent-evaluation-guide.md` are complete.
>
> Phase One ships in vertical slices. Each slice is independently reviewable and deliverable. No giant end-of-phase reveal.

---

## 1. Per-step micro-loop

For **every** task below:

1. Read the relevant Friday spec sections and the corresponding `hermes-audit.md` entry.
2. Plan the change — list files to create or modify, tests to write.
3. Implement the smallest functional unit.
4. Write tests alongside implementation (not after).
5. Run tests + pre-commit + `bench migrate`.
6. Commit using conventional-commit style (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
7. Report progress in the format from `08-agent-setup-guide.md` §6.
8. Wait for human acknowledgement before starting the next slice, unless explicitly told to chain.

---

## 2. Implementation slices

Each slice corresponds roughly to a week in `06-phase-one-scope.md`. Slices build on each other; do not start a slice until the previous one is reviewed and merged.

### Slice 1 — Foundations & DocType skeletons

**Goal:** Module folders exist; DocTypes from `42-phase-one-authority-contract.md` §3 are creatable in the Framework Console.

1. Verify `08-agent-setup-guide.md` §7 checklist is green.
2. Create module folders inside the agent kernel tree per `05-module-design.md`: `gateway`, `agents`, `skills`, `tasks`, `messaging`, `approvals`, `permissions`, `memory`, `tools`, `sandbox`, `api`. Each gets an `__init__.py`.
3. Register modules in `modules.txt`.
4. Create the Phase 1 DocTypes from 42 §3:
   - `Agent Profile`, `Agent Role Profile`
   - `Skill`, `Skill Draft`, `Skill Version`
   - `Agent Project`, `Agent Task`, `Agent Task Event`
   - `Chat Message`, `Chat Platform`
   - `Execution Log` (submittable)
   - `Permission Decision Log` (submittable)
   - `Workflow Request`
5. Field schemas exactly per `05-module-design.md` §Phase 1 DocTypes.
6. Empty controllers (`{doctype}.py`).
7. `bench --site friday.localhost migrate`.
8. Verify each DocType is creatable from the Framework Console.

**Deliverable:** Migration produces every DocType; one row of each is creatable by hand.
**Tests:** `test_doctypes_exist.py` opens each meta and asserts required fields exist.

### Slice 2 — Permission engine

**Goal:** Given an Agent Profile and a Skill, a function returns `(allowed: bool, reason: str)` and submits a Permission Decision Log row.

1. `friday/permissions/matrix.py`:
   - `build_matrix(agent_profile_name) -> PermissionMatrix`
   - `check(matrix, skill_name) -> Decision`
2. `friday/permissions/cache.py`:
   - Redis cache keyed `friday:perm_matrix:{profile_name}`, TTL 60s.
   - Invalidation hook on Agent Profile or Role updates.
3. `friday/permissions/decisions.py`:
   - Persist decision to Permission Decision Log (submitted, immutable).
4. Wire invalidation hooks in `hooks.py`:
   ```python
   doc_events = {
       "Agent Profile": {"on_update": "friday.permissions.cache.invalidate_for_profile"},
       "Role":          {"on_update": "friday.permissions.cache.invalidate_all"},
   }
   ```
5. Tests:
   - Allow: profile with matching role permitted on DocType referenced by Skill.
   - Deny: profile lacks required role.
   - Status check: Skill in Draft / Retired / Archived is always denied.
   - Cache hit vs. miss.
   - **Coverage: 80% lines, 100% branches on `matrix.py`.**

**Deliverable:** `bench execute friday.permissions.matrix.check --args "['profile_a', 'create_note']"` returns a structured decision and logs it.

### Slice 3 — Skill Loader

**Goal:** Active, permitted Skills for a profile are loaded into Redis and convertible to LLM tool definitions.

1. `friday/skills/loader.py`:
   - `load_for_profile(profile_name) -> list[SkillDefinition]`.
   - Filters Skills by `status='Active'` and profile permission.
   - Caches at `friday:skills:{profile_name}` with TTL 300s.
2. `to_tool_definition(skill) -> dict` — Skill row → OpenAPI tool schema.
3. Invalidation hooks on Skill updates.
4. Tests: loader returns only Active+permitted; cache stable across calls; status change invalidates cache.

**Deliverable:** Calling the loader from `bench console` returns tool definitions ready for the LLM.

### Slice 4 — Gateway: CLI adapter and Chat Message flow

**Goal:** CLI input writes a Chat Message; the gateway sees it via real-time event; an outbound Chat Message comes back.

1. `friday/messaging/adapters/cli.py` — `friday chat --profile <name>` opens a REPL. Each input writes a Chat Message (`direction=inbound`) via REST. Subscribes for outbound on the same session.
2. `friday/gateway/session_manager.py` — subscribes to `chat_message.after_insert`. Resolves Agent Profile and hands off to the agent runner.
3. The agent runner in this slice is a stub — writes `"echo: <inbound content>"` to verify the round trip.
4. Tests: inbound creates a row; outbound appears in CLI; round-trip latency < 1s on local dev.

**Deliverable:** `friday chat` shows the echo reply.

### Slice 5 — LLM integration (single provider)

**Goal:** Replace the echo stub with a real LLM call. No tool calling yet — chat only.

1. `friday/gateway/prompt_builder.py` — system prompt = `Agent Profile.system_prompt` + recent session history.
2. `friday/agents/runner.py` v1 — calls the provider directly (no aggregator dependency). **Minimax M2 is the Phase 1 provider** per glossary and `03-technical-stack.md`; the adapter interface is wide enough to add Claude / OpenAI / OpenRouter later.
3. Provider API key stored as a Frappe `Password` field on the `LLM Provider` DocType (one row per provider, selectable per Agent Profile via `model_provider` link).
4. Tests: mock provider API; prompt assembly deterministic given inputs; reply Chat Message has correct `agent_profile` and `direction=outbound`.

**Deliverable:** `friday chat` produces a real LLM reply.

### Slice 6 — First real skill: `create_note`

**Goal:** End-to-end skill execution with permission validation.

1. Create or reuse `Note` DocType as the skill target.
2. Create a `Skill` row `create_note`: `parameters_schema={title, content}`, `required_doctypes=[Note(create)]`, `risk_level=low`, `status=Active`.
3. Create an Agent Profile `note_taker` with a role granting Note create.
4. Extend `friday/agents/runner.py` to include tool definitions in the LLM call and route tool calls to `friday/agents/dispatcher.py`.
5. `friday/agents/dispatcher.py`:
   - Call the permission engine.
   - On deny: write rejection to Execution Log; reply with error.
   - On allow: execute the skill. **In-process is acceptable for this slice only**; Slice 7 moves it into Docker.
6. Submit an Execution Log row on completion (success or failure).
7. Tests: allowed profile creates a Note; denied profile gets a clean rejection with no Note created; Execution Log has one submitted row per attempt.

**Deliverable:** `friday chat --profile note_taker` then "make a note titled X about Y" creates a Note and confirms.

### Slice 7 — Docker sandbox

**Goal:** Move skill execution from in-process to a Docker container meeting `42-phase-one-authority-contract.md` §5 minimum bar.

1. Build a Friday-worker image: Python 3.14, no host mounts, pinned dependencies.
2. `friday/sandbox/runner.py`:
   - `spawn_worker(profile, skill, params) -> result`.
   - Docker SDK for Python.
   - CPU + memory caps via `host_config`.
   - Network: bridge mode with allowlist of the Frappe API host only.
   - Pass a short-lived API token via env var.
3. Container entrypoint authenticates back to the REST API, performs the skill, exits with structured JSON.
4. Gateway captures stdout JSON, submits Execution Log, replies to the user.
5. Tests: spawn + teardown integration test; OOM kill recorded as graceful failure; network isolation enforced (attempt to reach a non-allowlisted host must fail).

**Deliverable:** Slice 6 still works end-to-end, but the skill now runs inside Docker.

### Slice 8 — Agent Task + Dispatcher + native Kanban

**Goal:** Tasks created manually are claimed by the dispatcher and executed by an agent.

1. Frappe Workflow on Agent Task: Pending → Assigned → Executing → Blocked → Review → Completed → Cancelled. Role-permissioned transitions.
2. `friday/tasks/workflow.py` — `on_update` hook for state transitions and `dispatchable` derivation.
3. `friday/tasks/dispatcher.py`:
   - Scheduled every 60s in `hooks.py`.
   - Query tasks in dispatchable states without `assigned_to_profile`.
   - Match `required_skills` against eligible Agent Profiles.
   - **Atomic claim using `SELECT ... FOR UPDATE SKIP LOCKED`** — concurrency-safe.
4. On claim → emit `agent_task.assigned` on Redis pub/sub → runner picks up.
5. Enable native Kanban view on Agent Task grouped by `workflow_state`.
6. Tests: two concurrent dispatcher invocations cannot double-claim the same task; task moves through states correctly; Kanban view loads with cards in the right columns.

**Deliverable:** Create a Task in the Framework Console; watch it move across the Kanban board as the dispatcher and agent process it.

### Slice 9 — Polish & hardening

**Goal:** Phase 1 quality bar.

1. Complete unit + integration test coverage to `08-agent-setup-guide.md` §3.5 targets.
2. Log every permission decision, execution, and dispatcher action via Frappe's logger.
3. Write `docs/install.md`, `docs/quickstart.md`, `docs/architecture.md` (linking to the design docs).
4. Add `make` (or `nox`) targets: `setup`, `test`, `lint`, `migrate`, `run-gateway`.
5. Verify LICENSE, README, AUTHORS / NOTICE, SECURITY.md.
6. One-week dogfood: Friday tracks Friday's own remaining Phase 1 work.

**Deliverable:** Public-ready repo state. Phase 2 entry can proceed.

---

## 3. Cross-slice rules

| # | Rule |
|---|---|
| 3.1 | **No skipping permission checks.** Every skill-invocation code path goes through `friday.permissions.matrix.check`. Every new skill ships with a "denied" test. |
| 3.2 | **No direct database writes bypassing Frappe.** Use `frappe.get_doc(...).insert()` / `.save()` / `.submit()`. Raw SQL is reserved for read-only analytics and pgvector queries. |
| 3.3 | **No hard-coded paths.** No `~/.hermes`, no `/tmp/whatever`, no hard-coded site names. Use `frappe.local.site`, `frappe.get_site_path()`, `tempfile`. |
| 3.4 | **No silent failures.** Any caught exception either (a) recovers cleanly and logs at WARNING+, or (b) is re-raised. Never silent `pass`. |
| 3.5 | **No breaking the migration path.** Every DocType change ships a migration patch in `patches.txt`. `bench migrate` from an empty site to current state must work unattended. |
| 3.6 | **Conventional commits** — `feat(permissions): …`, `fix(gateway): …`, `test(skills): …`, `docs(install): …`, `refactor(agents): …`. |
| 3.7 | **PR size** — each slice is one or two PRs. > 800 line diffs get split. |

---

## 4. When the agent is stuck — Blocker Report

After one full micro-loop without progress (ambiguous spec, missing information, contradiction not resolved by the audit), the agent stops and produces a Blocker Report. **It does not silently pick an option to keep moving.**

```
## Blocker

### Context
[which slice, which task]

### What I tried
[approaches attempted, why they failed]

### Conflict
[which spec sections or Hermes patterns conflict]

### Options
[concrete proposals A / B / C with tradeoffs]

### Recommendation
[the agent's preferred option, with reasoning]

### Decision needed by
[immediate / by next slice]
```

The agent waits for a human decision before proceeding.

---

## 5. Phase One exit criteria

All nine slices complete and:

- Every checkbox in `42-phase-one-authority-contract.md` §7 (Completion Gate) is green.
- All tests pass on a fresh bench provisioned per `08-agent-setup-guide.md` §2.
- The dogfood week produced no critical issues.
- A new developer can install and run Friday from the README alone.

Hand control back to the human for the open-source launch decision (Phase 2 entry).
