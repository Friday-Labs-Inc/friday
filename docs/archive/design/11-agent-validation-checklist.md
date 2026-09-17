# 11 — Agent Validation Checklist

> Concrete, testable criteria the agent and the human reviewer use to confirm each Phase One slice is complete and correct.
>
> This document is the gate between slices. The agent does not proceed to slice N+1 until every box in slice N is green and human-acknowledged. A box that cannot be ticked produces a Blocker Report (see `10-agent-execution-guide.md` §4) — boxes are never ticked dishonestly.

---

## How this checklist is used

1. The agent implements per `10-agent-execution-guide.md`.
2. The agent self-checks against the boxes below.
3. The agent reports outcomes in the format from `08-agent-setup-guide.md` §6, with the checklist filled in.
4. The human reviews, runs spot checks, and either acknowledges or sends back for fixes.
5. Only after acknowledgement does the next slice start.

---

## Global — applies to every slice

- [ ] All new code carries the GPL v3 file header.
- [ ] Any code adapted from Hermes carries a "this file adapts logic from..." comment and an `AUTHORS` / `NOTICE` entry.
- [ ] No new lines have hard-coded paths (`~/.hermes`, `/tmp/x`, etc.).
- [ ] No new lines bypass `frappe.permissions` or `friday.permissions.matrix`.
- [ ] No new lines silently swallow exceptions.
- [ ] `pre-commit run --all-files` passes.
- [ ] `bench --site friday.localhost migrate` runs clean on a fresh site.
- [ ] All new tests pass via `bench --site friday.localhost run-tests`.
- [ ] No secrets, API keys, or tokens are committed.
- [ ] Commit history follows conventional commits.

---

## Slice 1 — Foundations & DocType skeletons

**Structural**
- [ ] Agent kernel module folders exist per `05-module-design.md`.
- [ ] `modules.txt` lists every agent kernel module.
- [ ] Each module has `__init__.py` and a `doctype/` subfolder.

**DocTypes created** (per `42-phase-one-authority-contract.md` §3)
- [ ] Agent Profile, Agent Role Profile
- [ ] Skill, Skill Draft, Skill Version
- [ ] Agent Project, Agent Task, Agent Task Event
- [ ] Chat Message, Chat Platform
- [ ] Execution Log (`is_submittable=1`)
- [ ] Permission Decision Log (`is_submittable=1`)
- [ ] Workflow Request

**Schema conformance**
- [ ] Field names exactly match `05-module-design.md` §Phase 1 DocTypes.
- [ ] Mandatory fields marked `reqd=1`.
- [ ] Link fields point to correct target DocTypes.
- [ ] Submittable DocTypes have submit/cancel permissions configured.

**Verification**
- [ ] Each DocType is creatable from the Framework Console.
- [ ] `test_doctypes_exist.py` passes.

---

## Slice 2 — Permission Engine

**Behaviour**
- [ ] `friday.permissions.matrix.check(profile, skill)` returns a structured `Decision` (`allowed`, `reason`).
- [ ] Allow: profile with all required roles is permitted.
- [ ] Deny: missing role → denied with specific reason.
- [ ] Deny: Skill `status != Active` → denied regardless of permissions.
- [ ] Every call submits one Permission Decision Log row (not draft).

**Caching**
- [ ] Permission matrix cached in Redis at `friday:perm_matrix:{profile_name}`.
- [ ] TTL respected (60s default).
- [ ] Agent Profile update invalidates that profile's cache.
- [ ] Role update invalidates all cached matrices.

**Coverage**
- [ ] Line coverage ≥ 80% on `friday/permissions/matrix.py`.
- [ ] Branch coverage = 100% on `matrix.check()`.
- [ ] At least one test asserts the Permission Decision Log row is submitted.

**Performance**
- [ ] Cold check (no cache): < 50ms on local dev.
- [ ] Warm check (cache hit): < 5ms on local dev.

---

## Slice 3 — Skill Loader

**Behaviour**
- [ ] `load_for_profile(name)` returns only Skills with `status='Active'`.
- [ ] Returns only Skills the profile has permission to execute.
- [ ] Output is a list of dicts conforming to OpenAPI-style tool schema (name, description, parameters).
- [ ] `to_tool_definition()` produces valid JSON Schema for each Skill.

**Caching**
- [ ] Cached at `friday:skills:{profile_name}` with TTL 300s.
- [ ] Skill `after_insert`, `on_update`, `on_trash` all invalidate the cache.
- [ ] Cache miss queries DocType; cache hit does not.

**Tests**
- [ ] Active + permitted Skill appears.
- [ ] Active + unpermitted Skill does not appear.
- [ ] Draft / Retired / Archived / Experimental Skills do not appear.
- [ ] Cache invalidation test passes.

---

## Slice 4 — Gateway + CLI adapter

**CLI**
- [ ] `friday chat --profile <name>` opens an interactive prompt.
- [ ] Each user line creates a Chat Message (`direction=inbound`, `content`, `session_id` set).
- [ ] The CLI prints any outbound Chat Message on the same session.

**Gateway**
- [ ] Subscribes to `chat_message.after_insert`.
- [ ] On inbound event, resolves Agent Profile (no error on first message).
- [ ] Stub runner emits an outbound Chat Message containing `"echo: <inbound content>"`.

**Round trip**
- [ ] User types "hello" → sees "echo: hello".
- [ ] Round-trip latency < 1000ms on local dev (excluding LLM, not in this slice).
- [ ] Both messages persisted in Chat Message (verifiable in the Framework Console).

**Tests**
- [ ] Integration test simulates an inbound message and asserts an outbound reply within 2s.

---

## Slice 5 — LLM integration

**Configuration**
- [ ] `LLM Provider` DocType created with fields: `provider_name`, `provider_type`, `api_key` (Password), `base_url`, `default_model`, `default_max_tokens`, `default_temperature`, `is_active`.
- [ ] `Agent Settings` singleton created with `default_provider` (Link → LLM Provider).
- [ ] API key stored in `LLM Provider.api_key` (Password field, encrypted at rest, never committed).
- [ ] `Agent Profile.model_provider` is a Link → `LLM Provider`.
- [ ] Phase 1 default provider is Minimax per `03-technical-stack.md`.

**Prompt assembly**
- [ ] System prompt includes the Agent Profile's `system_prompt` field.
- [ ] System prompt includes the last N session messages (configurable).
- [ ] Prompt is deterministic given identical inputs (golden-file test).

**Reply flow**
- [ ] LLM reply written as Chat Message (`direction=outbound`, `agent_profile` set, `session_id` preserved).
- [ ] Stub echo is fully removed.
- [ ] Error handling: provider 429 / 5xx → graceful retry with backoff (max 3); final failure → error message to the user, never silent.

**Tests**
- [ ] Mocked provider returns a canned reply → reply Chat Message exists.
- [ ] Mocked 429 → retried → success.
- [ ] Mocked 5xx persistent → error Chat Message emitted.

---

## Slice 6 — First skill `create_note`

**Setup**
- [ ] Skill row `create_note` exists with `required_doctypes=[Note(create)]`, `risk_level=low`, `status=Active`.
- [ ] Agent Profile `note_taker` exists with a role permitting Note creation.

**Permitted flow**
- [ ] User asks the `note_taker` to create a note.
- [ ] LLM emits a tool call.
- [ ] Permission engine returns allowed.
- [ ] Skill executes (in-process for this slice — acceptable).
- [ ] A Note row is created with correct title and content.
- [ ] Execution Log row submitted with `status='success'`, `result`, `duration_ms`, `tokens_used`.
- [ ] User receives a confirmation message.

**Denied flow**
- [ ] An Agent Profile without Note-create permission attempts the same.
- [ ] Permission engine returns denied with a specific reason.
- [ ] No Note row is created.
- [ ] Execution Log row submitted with `status='rejected'`, linked to a Permission Decision Log row.
- [ ] User receives a clear denial message.

**Tests**
- [ ] Allowed flow integration test.
- [ ] Denied flow integration test.
- [ ] Both flows produce exactly one Execution Log row each.

---

## Slice 7 — Docker sandbox

**Image**
- [ ] Friday-worker Docker image builds cleanly.
- [ ] Image has Python 3.14, pinned dependencies, no host mounts in the Dockerfile.
- [ ] Image entrypoint reads a single JSON command from stdin/env, returns JSON on stdout.

**Spawn / teardown**
- [ ] `friday.sandbox.runner.spawn_worker(profile, skill, params)` returns a structured result.
- [ ] Container is destroyed after execution (`docker ps -a` shows no leftovers after 10 consecutive runs).
- [ ] CPU cap enforced (busy loop → throttle observed).
- [ ] Memory cap enforced (`[0]*N` beyond limit → container killed → graceful failure recorded).

**Network isolation**
- [ ] Container can reach the Frappe REST API.
- [ ] Container **cannot** reach an arbitrary external host (`curl https://example.com` fails).
- [ ] Allowlist is configurable per Agent Profile.

**Credentials**
- [ ] Container receives a short-lived API token (not long-lived).
- [ ] Token scope limited to the Agent Profile's permissions (server-side re-check).
- [ ] No host credentials, no `.aws/`, no SSH keys, no host `/etc/passwd` visible.

**End-to-end**
- [ ] Slice 6's `create_note` flow still works — now inside Docker.

**Tests**
- [ ] Spawn + teardown integration test.
- [ ] Memory cap enforcement test.
- [ ] Network allowlist deny-case test.

---

## Slice 8 — Tasks, Dispatcher, Kanban

**Workflow**
- [ ] Frappe Workflow on Agent Task: Pending, Assigned, Executing, Blocked, Review, Completed, Cancelled.
- [ ] Transitions are role-permissioned.

**Dispatcher**
- [ ] Runs every 60s via `hooks.py`.
- [ ] Queries unassigned Tasks in dispatchable states.
- [ ] Matches Tasks to Agent Profiles by `required_skills ⊆ permitted_skills`.
- [ ] Atomic claim via `SELECT ... FOR UPDATE SKIP LOCKED` — concurrent dispatcher runs cannot double-claim (proven by test).
- [ ] Emits `agent_task.assigned` on Redis pub/sub when a Task is claimed.

**Agent pickup**
- [ ] On the real-time event, the gateway routes the Task to the assigned profile's runner.
- [ ] Runner executes the task (skill calls go through Docker as in Slice 7).
- [ ] Task state transitions: Assigned → Executing → Completed (or Blocked / Review on failure).
- [ ] Result stored on the Task DocType.

**Kanban**
- [ ] Native Kanban view on Agent Task grouped by `workflow_state`.
- [ ] Live updates — state changes reflect in the Kanban view in real time.

**Tests**
- [ ] Concurrency: 100 Tasks, 5 concurrent dispatcher runs, each Task claimed exactly once.
- [ ] State machine: every transition is permitted or denied per the Workflow definition.
- [ ] End-to-end: create Task → dispatcher claims → agent executes → state reaches Completed.

---

## Slice 9 — Polish & hardening

**Tests**
- [ ] Overall line coverage ≥ 70% on the agent kernel tree.
- [ ] Critical modules (`permissions`, `gateway`, `sandbox`, `tasks/dispatcher`) ≥ 85%.
- [ ] No `xfail` or skipped tests without a tracked issue.

**Logging**
- [ ] All permission decisions logged to Permission Decision Log.
- [ ] All skill executions logged to Execution Log.
- [ ] All dispatcher actions logged via `frappe.logger`.
- [ ] Levels appropriate: INFO for state changes, WARNING for retries, ERROR for failures.

**Documentation**
- [ ] `README.md` — concise overview, install, quickstart.
- [ ] `docs/install.md` — full prerequisites and setup.
- [ ] `docs/quickstart.md` — first agent + skill in 10 minutes.
- [ ] `docs/architecture.md` — high-level, links to the design docs.
- [ ] `docs/hermes-audit.md` — kept current.
- [ ] `SECURITY.md` — private vulnerability reporting.
- [ ] `CONTRIBUTING.md` — DCO, conventional commits, PR process.
- [ ] `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.

**Repo hygiene**
- [ ] `LICENSE` is unmodified GPL v3 text.
- [ ] `AUTHORS` / `NOTICE` includes all Hermes attributions.
- [ ] `.github/ISSUE_TEMPLATE/` (bug, feature, security).
- [ ] `.github/PULL_REQUEST_TEMPLATE.md`.
- [ ] `.pre-commit-config.yaml` runs on every commit.
- [ ] CI workflow runs tests on PR.

**Dogfood**
- [ ] Friday has tracked at least 20 of its own remaining tasks in its own Kanban for 5+ days.
- [ ] No critical bugs found during dogfood remain unfixed.

**Performance**
- [ ] Permission check median latency < 5ms with warm cache.
- [ ] End-to-end skill execution (CLI → Docker → reply) median < 3s excluding LLM time.
- [ ] Dispatcher handles 500 Tasks/minute on a single worker.

---

## Phase One Completion Report

When every box above is green:

```markdown
# Phase One Completion Report

## Slices completed
- [ ] 1 — Foundations
- [ ] 2 — Permission Engine
- [ ] 3 — Skill Loader
- [ ] 4 — Gateway + CLI
- [ ] 5 — LLM Integration
- [ ] 6 — First Skill
- [ ] 7 — Docker Sandbox
- [ ] 8 — Tasks, Dispatcher, Kanban
- [ ] 9 — Polish

## Metrics
- Total commits: ___
- Total tests:   ___
- Coverage:      ___%
- Open issues:   ___
- Hermes audit:  ___ REUSE, ___ ADAPT, ___ REWRITE

## Known limitations
- [each, with link to the Phase 2 issue]

## Recommendation
Ready / Not ready for open-source launch (Phase 2).

## Decisions awaiting human
- [open spec amendments or scope changes proposed during build]
```

The human reviews the report and decides on the Phase 2 launch.
