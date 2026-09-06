# Friday Implementation Log

This file tracks setup and implementation progress for the Friday repository.
Keep entries append-only where practical: add new dated notes instead of rewriting
history, except for correcting factual mistakes.

## 2026-05-18

### Environment Setup

- Host OS confirmed as Ubuntu 26.04.
- PostgreSQL was not installed initially.
- Installed native PostgreSQL from Ubuntu packages:
  - `postgresql`
  - `postgresql-18-pgvector`
- PostgreSQL version installed: 18.3.
- PostgreSQL service is enabled and active.
- PostgreSQL cluster `18/main` is online on port `5433`.
- Port `5432` is already occupied by Docker Desktop (`com.docker.back`), so Friday setup should use PostgreSQL port `5433`.
- `pgvector` and `pg_trgm` are available to install into databases:
  - `vector` default version 0.8.1
  - `pg_trgm` default version 1.6
- The `friday.localhost` PostgreSQL database does not exist yet, so database extensions were not created yet.

### Database Auth Notes

- Existing PostgreSQL role: `postgres`.
- No password was set for the `postgres` database role during installation.
- Local socket access uses peer authentication.
- TCP access on `127.0.0.1` requires `scram-sha-256` password authentication.
- Recommended later: create a dedicated Friday database user instead of using the `postgres` superuser.

### Bench Setup Findings

- Installed Bench version observed: 5.29.1.
- `bench init` in this version does not support `--db-type`.
- Attempted command:

  ```bash
  bench init friday-bench --frappe-branch version-16 --python python3.11
  ```

- The attempt failed during Frappe editable install because current Frappe `version-16` declares:

  ```text
  requires-python = ">=3.14,<3.15"
  ```

- The failure was caused by Python 3.12+ syntax in Frappe being parsed by Python 3.11:

  ```python
  type ConfType = _dict[str, Any]
  ```

- Python 3.14 is available on the host:

  ```text
  /usr/bin/python3.14
  Python 3.14.4
  ```

- Retried Bench initialization with Python 3.14:

  ```bash
  bench init friday-bench --frappe-branch version-16 --python python3.14
  ```

- The retry passed the Python syntax requirement but failed while building Frappe's `mysqlclient==2.2.7` dependency.
- The system MySQL development package is already installed and provides the missing header:

  ```text
  libmysqlclient-dev: /usr/include/mysql/udf_registration_types.h
  ```

- Root cause found: the active Conda base environment is exporting Conda compilers:

  ```text
  CONDA_PREFIX=/home/friday/conda
  CC=/home/friday/conda/bin/x86_64-conda-linux-gnu-cc
  CXX=/home/friday/conda/bin/x86_64-conda-linux-gnu-c++
  ```

- This causes the native `mysqlclient` build to use Conda's compiler/sysroot instead of the normal Ubuntu compiler environment.
- `bench set-config` failed inside the partial bench because Frappe was not installed:

  ```text
  ModuleNotFoundError: No module named 'frappe'
  ```

- After deactivating Conda and retrying with Python 3.14, Frappe Python dependencies installed successfully, but `yarn install --check-files` failed because Node was too old:

  ```text
  error frappe-framework@: The engine "node" is incompatible with this module.
  Expected version ">=24". Got "22.22.2"
  ```

- Installed Node 24 with `nvm` and set it as the default:

  ```text
  Node.js v24.15.0
  npm 11.12.1
  yarn 1.22.22
  ```

- Bench initialization succeeded after activating Node 24:

  ```bash
  source ~/.nvm/nvm.sh
  nvm use 24
  bench init friday-bench --frappe-branch version-16 --python python3.14
  ```

- Result:

  ```text
  SUCCESS: Bench friday-bench initialized
  ```

- Verified the bench virtual environment:

  ```text
  Python 3.14.4
  Frappe 16.18.2
  ```

- `bench new-site --help` confirms this Bench version supports PostgreSQL site creation with:

  ```text
  --db-type [mariadb|postgres|sqlite]
  --db-host TEXT
  --db-port INTEGER
  --db-root-username TEXT
  --db-root-password TEXT
  --db-socket TEXT
  ```

- Non-interactive shells still need an explicit `nvm use 24` before commands that run Frappe's frontend build.

### Next Actions

- Create a PostgreSQL role for the Linux `friday` user so local peer authentication can create the site without storing a database root password.
- Create the Friday site using PostgreSQL on port `5433`.
- After the `friday.localhost` database exists, enable:

  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  ```

### Site Creation

- First PostgreSQL site creation attempt failed because TCP auth to `127.0.0.1:5433` requires a password.
- Set a local-development password on the `friday` PostgreSQL role.
- Second attempt failed because Frappe's PostgreSQL setup first connects to a maintenance database matching the root login name; database `friday` did not exist.
- Created maintenance database `friday` owned by role `friday`.
- Removed the partial `sites/friday.localhost` directory left by the failed attempt.
- Created site `friday.localhost` successfully using PostgreSQL:

  ```text
  db_type = postgres
  db_host = 127.0.0.1
  db_port = 5433
  ```

- Enabled required extensions in the generated site database:

  ```text
  pg_trgm 1.6
  vector 0.8.1
  ```

- Ran migration successfully:

  ```bash
  bench --site friday.localhost migrate
  ```

- Enabled developer mode for the site:

  ```text
  developer_mode = 1
  ```

### Development Server Port Conflict

- `bench start` initially failed because ports used by the generated `friday-bench` config were already occupied:

  ```text
  127.0.0.1:11000 redis_queue
  127.0.0.1:13000 redis_cache
  0.0.0.0:8000 web
  *:9000 socketio
  ```

- The conflicting processes belonged to an older running bench at `/home/friday/frappe-dev`, not the new `friday-bench`.
- To avoid killing the other bench, moved `friday-bench` to alternate local ports:

  ```text
  webserver_port = 8002
  socketio_port = 9002
  file_watcher_port = 6788
  redis_queue = redis://127.0.0.1:11002
  redis_cache = redis://127.0.0.1:13002
  redis_socketio = redis://127.0.0.1:13002
  ```

- Regenerated Redis config:

  ```bash
  bench setup redis
  ```

- Regenerated `Procfile` with Node 24 active so socketio uses `/home/friday/.nvm/versions/node/v24.15.0/bin/node`:

  ```bash
  source ~/.nvm/nvm.sh
  nvm use 24
  bench setup procfile
  ```

- Current Friday dev URL is:

  ```text
  http://friday.localhost:8002
  ```

- `bench start` succeeded after the port changes.
- Browser reached the Frappe setup wizard at:

  ```text
  http://friday.localhost:8002/desk/setup-wizard/0
  ```

- Completed first-run setup with:

  ```text
  Language = English
  Country = India
  Time Zone = Asia/Kolkata
  Currency = INR
  ```

- Desk loaded successfully at:

  ```text
  http://friday.localhost:8002/desk
  ```

- Current Desk state shows only the base Framework workspace. The Friday app has not been created or installed yet.

### Next Slice 1 Setup Actions

- Create and install the Friday app inside the bench:

  ```bash
  cd /home/friday/friday/friday-bench
  source ~/.nvm/nvm.sh
  nvm use 24
  bench new-app friday
  bench --site friday.localhost install-app friday
  ```

## 2026-05-19

### Friday Repository Becomes Source Of Truth

- The active bench kernel checkout at `/home/friday/friday/friday-bench/apps/frappe` was moved to the Friday project repository:

  ```text
  origin = https://github.com/Friday-Labs-Inc/friday.git
  ```

- Fetched Friday project branches from `origin`.
- Checked out `main` and set it to track `origin/main`.
- Current active kernel commit:

  ```text
  fa2e7c2741 Suggest Absorb Frappe v16 as Friday kernel base
  ```

- Kept the previous local `version-16` branch available as a reference:

  ```text
  version-16 e61c3950fa chore(release): Bumped to Version 16.18.2
  ```

- Ran migration successfully after switching to Friday `main`:

  ```bash
  bench --site friday.localhost migrate
  ```

- Verified installed app state:

  ```text
  frappe 16.18.2 main
  ```

- This supersedes the earlier temporary remote note that pointed at `Friday-Labs-Inc/frappe.git`. The intended project remote for ongoing Friday work is `Friday-Labs-Inc/friday.git`.

### Slice 1 Execution Started

- Pulled latest `origin/main` and received the dedicated Slice 1 instruction:

  ```text
  docs/contributing/slices/SLICE_1.md
  ```

- This instruction supersedes the earlier app-based note above. Friday Core now lives inside the kernel source tree, not in a separate `friday` app.
- Created branch:

  ```text
  slice-1/friday-core-doctypes
  ```

- Added module registration:

  ```text
  frappe/modules.txt -> Friday Core
  ```

- Added kernel module package:

  ```text
  friday/friday_core/
  ```

- Added 8 main DocTypes and 3 child-table DocTypes under `friday/friday_core/doctype/`:

  ```text
  Agent Profile
  Agent Profile Skill
  Skill
  Skill Required DocType
  Agent Project
  Agent Task
  Agent Task Skill
  Chat Message
  Chat Platform
  Execution Log
  Permission Decision Log
  ```

- Added test module:

  ```text
  friday/friday_core/tests/test_doctypes_exist.py
  ```

- Created local `Agent Supervisor` role. Frappe also creates missing roles referenced by DocType permissions during DocType installation.
- Enabled tests for the local site:

  ```bash
  bench --site friday.localhost set-config allow_tests true
  ```

- Ran migration successfully:

  ```bash
  bench --site friday.localhost migrate
  ```

- Ran Slice 1 tests successfully:

  ```bash
  bench --site friday.localhost run-tests --module friday.friday_core.tests.test_doctypes_exist
  ```

  Result:

  ```text
  Ran 2 tests in 0.113s
  OK
  ```

- Verified metadata:

  ```text
  Module Def Friday Core exists
  Execution Log -> module Friday Core, is_submittable = 1
  Permission Decision Log -> module Friday Core, is_submittable = 1
  Agent Supervisor role exists
  ```

- Created one local sanity row for each of the 8 main DocTypes through the Frappe ORM. The two audit logs submitted successfully.
- Browser Desk create/list checks are still pending human verification.

## 2026-05-27

### Environment Setup on Mac M1 (PostgreSQL-Backend)

- Successfully verified and finished `mysqlclient` package compilation using local `mariadb-connector-c` C-client headers to satisfy the required base dependency in Frappe's `pyproject.toml`.
- Swapped stock `apps/frappe` folder with the true development repository `/Users/alphaworkz/Documents/friday`, establishing `/Users/alphaworkz/Documents/friday-bench/apps/frappe` as the single clean repository clone and active environment root.
- Re-installed the true Friday development repository as an editable python package inside the virtual environment (`env/`).
- Started `postgresql@17` and `redis` services via Homebrew services and verified active status.
- Configured bench global database settings:
  ```bash
  bench set-config -g db_host 127.0.0.1
  bench set-config -g db_port 5432
  ```
- Created a PostgreSQL maintenance database matching the local user `$(whoami)`.
- Created site `friday.localhost` successfully using PostgreSQL 17, pointing to superuser `alphaworkz` via `--db-root-username` parameter:
  ```bash
  bench new-site friday.localhost --db-type postgres --db-root-username alphaworkz --admin-password admin --force
  ```
- Enabled PostgreSQL database extensions in the generated database:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  ```
- Enabled `developer_mode = 1` and `allow_tests = true` for `friday.localhost`.
- Ran database migrations:
  ```bash
  bench --site friday.localhost migrate
  ```
- Ran Slice 1 tests successfully on the PostgreSQL backend:
  ```bash
  bench --site friday.localhost run-tests --module friday.friday_core.tests.test_doctypes_exist
  ```
  Result:
  ```text
  friday.friday_core.tests.test_doctypes_exist.TestDocTypesExist
      ✔  test_each_doctype_exists_with_required_fields
      ✔  test_submittable_doctypes_are_submittable

  Ran 2 tests in 0.568s
  OK
  ```

## 2026-05-27 — Slice 2: Permission engine

- Shipped the gateway pre-check engine specified in `docs/design/10-agent-execution-guide.md` §Slice 2.
- New package `friday/friday_core/permissions/` with three modules:
  - `matrix.py` — `build_matrix`, `evaluate`, `check` + `Decision` / `PermissionMatrix` dataclasses.
  - `cache.py` — Redis cache (`friday:perm_matrix:{profile}`, 60s TTL) with per-profile and broad invalidation.
  - `decisions.py` — writes immutable Permission Decision Log rows.
- `frappe/hooks.py` wired: `Agent Profile.on_update` → per-profile invalidation; `Role.on_update` → broad invalidation.
- 10 tests in `friday/friday_core/tests/test_permissions.py`, all green on PostgreSQL 17.
- Slice 1 regression: 2/2 green.
- Deliverable verified:
  ```
  bench --site friday.localhost execute \
      friday.friday_core.permissions.matrix.check \
      --args "['FRIDAY-TEST-PROFILE-A', 'friday-test-skill-active']"
  → {"allowed": true, "reason": "Allowed"}
  ```
- Full product-head rollout narrative: `docs/rollouts/slice-2-permission-engine.md`.
- Merged via PR #26 by `@Fridaylabsinc`.

## 2026-05-27 — Slice 3: Skill loader

- Shipped the agent's tool-menu builder specified in `docs/design/10-agent-execution-guide.md` §Slice 3.
- New package `friday/friday_core/skills/` with one module:
  - `loader.py` — `load_for_profile`, `to_tool_definition`, three invalidation hooks, `SkillDefinition` dataclass.
- Filter chain (cheapest-first, short-circuits on first miss): `Skill.status == "Active"` → `skill in profile.permitted_skills` → `permissions.matrix.evaluate(matrix, skill).allowed`. Uses `evaluate()` (pure) not `check()` (logs), so listing the menu does not write decision-log rows.
- `frappe/hooks.py` extended: `Skill.on_update` → surgical per-affected-profile flush; `Agent Profile.on_update` and `Role.on_update` events now fire both permissions and skills cache invalidation.
- 8 tests in `friday/friday_core/tests/test_skill_loader.py`, all green.
- Regression: Slice 1 → 2/2, Slice 2 → 10/10.
- Deliverable verified:
  ```
  bench --site friday.localhost execute \
      friday.friday_core.skills.loader.load_for_profile \
      --args "['FRIDAY-SLICE3-PROFILE-FULL']"
  → [{"name": "slice3-skill-active", "description": "...", "parameters_schema": {...}, ...}]
  ```
- Full product-head rollout narrative: `docs/rollouts/slice-3-skill-loader.md`.
- Shipped via PR #27.

## 2026-05-27 — Slice 4 v2: Chat flow under unified gateway (single-tenant lens)

- Shipped the first interactive surface AND laid the unified gateway every future surface plugs into. Replaces the in-process CLI approach from the closed PR #29.
- Decision contract: `docs/design/47-gateway-design-decisions.md` (new — consolidates every Q1–Q5 decision and the design for deferred subsystems).
- New packages:
  - `friday/friday_core/gateway/` — `service.py` (the chokepoint hook), `batching.py` (Q4-C stub), `recovery.py` (Q5 half-step sweeper).
  - `friday/friday_core/routing/` — `resolve.py` (Q3 stub; reads `Chat Platform.default_agent_profile`).
  - `friday/friday_core/agent_runner/` — `runner.py` (stub: tool menu + echo; Slice 5 replaces body).
  - `friday/friday_core/cli/` — `chat.py` (REPL + `handle_user_message`; direct DB read for outbound per Q2 Option A), `commands.py` (click group `friday`).
- DocType field additions (single migration, all nullable/defaulted):
  - `Chat Platform`: `dispatch_mode` (Select sync|async), `default_agent_profile` (Link), `batch_idle_ms` (Int).
  - `Chat Message`: `retry_count` (Int), `failure_reason` (Small Text).
  - `Skill`: `idempotent` (Check), `idempotency_strategy` (Select — reserved seam).
- Wiring:
  - `frappe/hooks.py`: `doc_events["Chat Message"]["after_insert"]` → gateway chokepoint; `scheduler_events["all"]` → recovery sweeper (no-op on pure-sync deployments).
  - `frappe/commands/__init__.py`: appended friday click Group to `get_commands()`.
- Architectural choice (per `feedback-unified-gateway-service` and `feedback-single-tenant-not-saas`): unified gateway for all surfaces (CLI today; Telegram, Slack, Raven, A2A later); sized for one tenant. Subsystems with no v0.1 user (batching, dedup, per-tool idempotency framework) are documented in the design doc and stubbed in code — they activate when the slice that introduces their real user lands.
- 15 tests in `friday/friday_core/tests/test_chat_flow.py` (chat flow + routing helper + recovery sweeper), all green.
- Regression: Slice 1 → 2/2, Slice 2 → 10/10, Slice 3 → 8/8. **Total: 35/35.**
- Deliverable verified:
  ```
  bench --site friday.localhost friday chat --help     # lists --profile
  bench --site friday.localhost execute \
      friday.friday_core.cli.chat.handle_user_message \
      --args "['FRIDAY-SLICE4V2-PROFILE-TOOLS', 'demo-1', 'hello via unified gateway']"
  → "You have 1 tool(s) available: slice4v2-skill.\necho: hello via unified gateway"
  ```
- Full product-head rollout narrative: `docs/rollouts/slice-4-chat-flow.md`.
- Supersedes and closes PR #29 (the v1 in-process CLI shape, which special-cased the CLI in a way the unified-gateway rule rules out).

## 2026-05-27 — Slice 5: LLM integration (Minimax M2, single-tenant)

- Shipped real LLM integration. Replaces the Slice 4 echo stub. End-to-end loop: CLI → gateway → prompt builder → provider adapter → Minimax M2 → outbound Chat Message row → CLI prints. Same gateway path for every surface (Slice 4 contract unchanged).
- Decision contract appended: `docs/design/47-gateway-design-decisions.md` §11 (10 dated decisions Q11.1–Q11.10).
- New packages and DocTypes:
  - `friday/friday_core/llm/` — `provider.py` (LLMProvider ABC + MinimaxProvider), `prompt_builder.py` (system prompt + history + tools), `__init__.py` (public exports), `after_migrate.py` (ensures Agent Settings singleton row exists on fresh sites).
  - `friday/friday_core/doctype/llm_provider/` — per-row provider config (provider_name, provider_type, api_key (Password), base_url, default_model, default_max_tokens, default_temperature, is_active).
  - `friday/friday_core/doctype/agent_settings/` — singleton holding default_provider Link.
- Schema change: `Agent Profile.model_provider` is now `Link → LLM Provider` (was incorrectly `Link → DocType`).
- Wiring in Frappe core: `frappe/hooks.py` `after_migrate` list now includes `friday.friday_core.llm.after_migrate.ensure_agent_settings`.
- Audit findings (all fixed in commit on slice-5/llm-integration before merge):
  - Class name typo `MinimixProvider` → `MinimaxProvider` (bulk rename across 4 files).
  - Inactive linked provider silently fell through to defaults; now raises `LLMError` (Q11.3).
  - Error logs no longer leak API response data or raw exception messages (Q11.6).
  - `_get_api_key` no longer swallows exceptions (propagates so operators see the real cause).
  - N+1 query in `_load_history` replaced with single `fields=` query.
  - `default_max_tokens` / `default_temperature` now wired through to the Minimax payload.
  - Canonical Minimax base URL set to `https://api.minimax.io` (matches Hermes; override via DocType field for regional endpoints).
- Tests:
  - `test_llm_provider.py` — 25 tests (ABC, MinimaxProvider construction, HTTP mocking incl. 401/429/500/timeout/connection error, provider resolution chain incl. strict-on-inactive).
  - `test_prompt_builder.py` — 20 tests (system prompt assembly, history loading, role alternation, truncation, model resolution).
  - `test_chat_flow.py` — 15 tests, updated to mock `MinimaxProvider.chat` instead of using the echo stub.
- Regression: Slice 1 → 2/2, Slice 2 → 10/10, Slice 3 → 8/8, Slice 4 → 15/15.
- **Total: 80/80 tests green.**
- Spec deviation: API key location moved from singleton-with-Password-per-kind to per-row-Password on `LLM Provider`. Rationale in Q11.2 (multi-account flexibility, rotation property preserved).
- Full product-head rollout narrative: `docs/rollouts/slice-5-llm-integration.md`.

## Log Maintenance

- Add a new dated section whenever setup, implementation, validation, or a blocker changes.
- Every shipped slice/phase also gets a narrative doc at `docs/rollouts/slice-N-<name>.md` (product-head perspective). The IMPLEMENTATION_LOG is the timeline; the rollout doc is the story.
- Record exact commands only when they affect future reproducibility.
- Record blockers with the observed error, root cause, and next action.
- Do not place secrets, passwords, API keys, or tokens in this file.
