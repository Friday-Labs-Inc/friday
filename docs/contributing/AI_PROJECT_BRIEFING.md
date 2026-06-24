# Friday — AI Project Briefing

> **Purpose.** A consolidated ground-knowledge briefing for AI coding agents
> (and human reviewers) working on the Friday codebase. It captures the
> project identity, architecture, current state, governance rules, hard
> gotchas, and live deployment topology — all in one place so a new
> session doesn't have to rediscover them.
>
> **Audience.** Any AI agent (Claude Code, Codex, Cursor, Aider, Mavis, …)
> opening a PR or reading code in `apps/frappe/` on this bench.
>
> **Sources.** Cross-referenced to `docs/design/*`, `docs/rollouts/*`,
> `docs/decisions/*`, `docs/project/*`, and the Claude Code project memory
> at `~/.claude/projects/-Users-alphaworkz-Documents-friday-bench/memory/`.
> When this briefing and a primary source disagree, **the primary source
> wins** — this is a synthesis, not the spec.

---

## 0. TL;DR (the one-paragraph version)

**Friday** = a hard fork of Frappe v16 stable that makes AI agents
first-class framework primitives. The kernel lives at
`apps/frappe/frappe/friday_core/` inside the fork (not a separate app).
Every agent action is **permission-checked → logged (immutable
submittable DocType) → sandboxed → audited**. Single chokepoint is
`frappe.friday_core.gateway.service.handle_inbound` (wired as
`Chat Message.after_insert` in `frappe/hooks.py`). A domain is **DATA**
(Domain Bundle + Frappe Workflow + Friday Workflow Transition Meta +
Agent Profiles with `discriminator_role`), not Python. Friday IS the
engine; **RandomPack** is the first domain (Track B), currently the only
connector (#1) and the first business pipeline. Two live deployments
(AWS EC2 at `https://ai.randompack.com`, Legion at
`friday.localhost:8002`); local `friday.localhost:8005` is a dev site.
PR numbering is up to **#132** on `main`. The codebase is past
"design phase" by months — it's a working v0.2+ system being hardened.

---

## 1. Identity & repo layout

### 1.1 What Friday is

| Field | Value |
|---|---|
| Repo | `https://github.com/Friday-Labs-Inc/friday.git` (PUBLIC) |
| Org | `Friday-Labs-Inc` |
| Kernel | Hard fork of Frappe v16 stable (pyproject `name = "frappe"`) |
| App layout | `apps/frappe/` is the fork + `apps/raven/` is the chat UI |
| License | GPL v3 |
| HQ | India |
| Mission | Every Indian SMB gets a back-office agent team that runs on their own infra |
| First business automation | RandomPack (branding studio) |

### 1.2 Two products under one org

- **Friday** = the engine (this fork). Generic, governed, agentic.
- **RandomPack** = the first domain (a brand studio productising Rajiv
  Ranjan's design work). Lives at `~/Documents/RandomPack/randompack-bench`,
  separate Frappe v15 bench. **RandomPack is Friday's proof, not
  Friday's definition.**

The cross-project anchor (load it when working on EITHER bench):
`~/.claude/memory/friday-labs-charter.md` — the **seam** between them is
HMAC-signed webhooks + a guarded versioned API. RandomPack owns truth &
emits signed facts; Friday consumes them & writes back through a
guarded API. **Friday never writes RandomPack's DB directly.**

### 1.3 GitHub accounts (user manages TWO)

- `rsvasanth` — personal/dev account. **Authoritative source.** All feature
  branches pushed here first.
- `iyyanarr` — company/deploy account. Frappe Cloud reads from this fork.
- The user manually syncs rsvasanth → iyyanarr to release.

### 1.4 Local dev bench (the Mac)

- Path: `/Users/alphaworkz/Documents/friday-bench/`
- `apps/frappe/` is the fork (this is where AI work happens).
- Branch convention: trunk-based, small PRs, sponsor review.
- Current branch: `main`. PRs #1–#132 merged.

### 1.5 Live deployments

| Target | Where | What's there |
|---|---|---|
| Local Mac | `friday.localhost:8005` | **Dev site** — no Orchestrator profiles; Minimax LLM Provider may be deactivated by test runs |
| Legion | `friday.localhost:8002` (user `friday`) | The E2E test box. Live demo = Northwind Coffee Brand Identity project (`Friday-proj-nwc-e2e-001`, 9/9 tasks done) |
| AWS EC2 | `https://ai.randompack.com` (Ubuntu 24.04, key `~/Downloads/friday_aws_ec2.pem`) | Production-cutover target. NGINX + Let's Encrypt + supervisor (gunicorn + node-socketio + 3 RQ workers). Login: Administrator / `307d556ab656cb940209ce0b` |
| RandomPack dev (Legion) | `randompack.localhost:8000` | The customer-facing product bench (disjoint ports from Friday) |
| RandomPack production | `https://randompack.com` (Frappe Cloud) | Live customers; integration contract unchanged |

---

## 2. Two-track development structure (the governing directive)

Set 2026-06-23. Friday is a **GENERIC platform**; tracks run in parallel.

### 2.1 Track A — Friday Core (the engine)
Generic, domain-agnostic. Holds (1) the Hermes 1:1 port and (2) the
generic platform behaviour. Everything built so far — agent loop,
memory program, compression, gateway, learning loop, cron, connector
spine — is Track A.

### 2.2 Track B — Domains / use-cases (RandomPack = FIRST, not the definition)
A domain = **DATA + a thin app on top of Core**, never code inside Core.
Embodied by Design 75: a domain = Domain Bundle + Frappe Workflow +
Friday Workflow Transition Meta + Agent Profiles with
`discriminator_role`. RandomPack is the proving ground; Friday stays
generic.

### 2.3 Ecosystem integration = 1st-class CORE pillar
Friday Core has three generic pillars: (1) agent runtime [Hermes port],
(2) governed workflow engine [Design 75], (3) **ecosystem integration**
[Design 81]. Integration covers all four modalities: chat, system
(connectors), MCP tools, A2A. **RandomPack = connector #1** (modality
`system`). Future: 81c MCP, 81d chat, 81e A2A.

### 2.4 The law (apply to every line)
**If code names a brand, "Rajiv", a gate, or a "direction," it belongs
in a domain bundle or the RandomPack app — NEVER Friday Core.** Core
must make equal sense for a law firm, a manufacturer, a hospital.

### 2.5 Tagging (apply to every PR)
Tag every work item **`core`** | **`domain:randompack`** | **`integration`**
and gate it against the law above. The Hermes-port ledger is a `core`
sub-stream.

---

## 3. Current architecture (post-Design 75 — generic engine)

### 3.1 Two processes on one site
- **Gunicorn** (web) — serves the Framework Console (Desk-based operator
  UI) and Socket.IO.
- **Dedicated `friday` RQ worker** (custom queue, configurable concurrency,
  default 1, capped at 16). Runs the governed execution loop.

### 3.2 Single chokepoint
`frappe.friday_core.gateway.service.handle_inbound` is the
`Chat Message.after_insert` hook in `frappe/hooks.py`. Every inbound
message from any surface (CLI today; Raven/Telegram/Slack/A2A later)
lands here. The flow:

```
inbound Chat Message row
  → per-session Redis lock (30s wait, 5min TTL)
  → dedup (stub today)
  → flush_batch
  → permissions.matrix.check  (deny-by-default, writes Permission Decision Log)
  → skills.loader.load_for_profile
  → agent_runner.run_turn  (full ReAct loop, bounded max-iter)
  → outbound Chat Message row
  → publish_realtime("chat.outbound", …)  (for future subscribers)
  → mark inbound.processed = 1
  → release session lock
```

Surfaces are thin adapters. They MUST NOT import `agent_runner`
directly (the unified-gateway law).

### 3.3 Domain = DATA (Design 75)

```
friday_core/engine/
  workflow_engine.py   # doc_events on_work_item_update interpreter
  phase_dispatcher.py  # resolve owner by discriminator_role, render prompt, create Task
  advance.py           # on Task complete → fire next transition (enqueue_after_commit)
  governance.py        # acting_as / set_user guard — LOAD-BEARING
```

A domain bundle declares:
- A `Domain Bundle` row tying work-item DocType → Frappe Workflow.
- `Friday Workflow Transition Meta` rows keyed by `(workflow,
  from_state, action)` carrying `phase_key`, `agent_role`, `required_skills`,
  `prompt_template` (Jinja), `wait_for_all_tasks`.
- `Agent Profile` rows with `discriminator_role` (Link→Role) — at most one
  Active profile per discriminator_role (enforced at save).
- `Skill` rows with `role_gate` (Link→Role) — replaces the hardcoded
  `_ROLE_GATED_SKILLS` dict (Design 78 closed this hole 2026-06-17).

Routing is O(1): dispatcher matches a transition's `agent_role` to the
active `Agent Profile` whose `discriminator_role` equals it. Gates =
transitions owned by a human role (no meta row → engine no-ops).

**Standing rule:** never attach a Frappe Workflow to the `Task` DocType
(Task lifecycle ≠ domain workflow).

### 3.4 Connector framework (Design 81)

```
friday_core/connectors/
  core.py    # generic HMAC verify + signed-event intake + dispatch
  client.py  # generic never-raises token-auth outbound
```

Plus `Connector` DocType (modality: system | chat | mcp | a2a) +
`Connector Event` DocType (unified audit, replaces per-adapter configs).

### 3.5 Gateway command surface (Designs 82–84)
Slash commands caught at the surface edge BEFORE a conversational row:
- `/approve` `/deny` / `/status` / `/help` — operator-tier (Friday Operator
  role), `/approve` makes the human-approval gate reachable from Raven.
- `/stop` — interrupt (Design 83), cooperative Redis flag checked at
  each ReAct boundary.
- `/steer <text>` — nudge (Design 84), coalescing Redis slot drained at
  each boundary.
- `/stop` cascade (Design 85) — cancels the whole active delegated subtree
  via `Task.originating_session` / `parent_task`.

Delivery router (Design 86): `gateway/delivery.py` — `DeliveryTarget` DSL
(`origin`/`local`/`platform:chat[:thread]`) + `DeliveryRouter.deliver()`.
Platform = outbound Chat Message; `local` = private Frappe File.

### 3.6 Memory program
- `Agent Memory` DocType + `Agent Memory Embedding` (shadow table for
  pgvector).
- Semantic recall, scored recall, embedding layer, extract-on-compaction,
  user-store split.
- 13-section structured compaction summary (Hermes parity).

### 3.7 Cron (Design 87 Slice 1)
`Cron Job` DocType with `agent_profile`, `prompt`, `schedule_kind`
(cron/interval/once), `schedule_expr`, `deliver` (DSL target).
`cron/scheduler.py` `tick()` runs every 60s, advances `next_run_at`
**before** spawning (at-most-once). **A cron run IS a Task** — inherits
heartbeat + reconciler rescue + audit row. Delivery via the Design 86
router. Slice 2 (agent-facing `manage-cron-jobs` skill) deferred.

### 3.8 LLM provider layer
- `LLM Provider` DocType — provider_type, api_key (Password), base_url,
  default_model, default_max_tokens, default_temperature, is_active,
  **image_model**, **request_timeout_seconds** (default 1800), **request_stale_seconds**
  (default 120), **auth_mode** (`api_key` | `oauth`), **oauth_* Password fields**.
- `_build_openai_client` derives base_url for the OpenAI SDK; Minimax M2
  served at `api.minimax.io/v1/chat/completions`.
- Streaming via `httpx.Timeout(read=stale, write=total)`. (Fix to a 30s
  raw-requests.post blocking call that was killing every goal-mode task.)
- OAuth flows: Anthropic Claude (manual-paste PKCE) + OpenAI Codex
  (device-code). `LLM Provider` form has Login buttons.
- **AnthropicProvider.CLAUDE_CLI_VERSION** must be bumped periodically
  (Anthropic rejects OAuth from stale CLI versions).

---

## 4. Recent shipped work (chronological)

All numbers = PRs on `main` in `Friday-Labs-Inc/friday`.

### 4.1 v0.2 program (Designs 61/62/63/63b/64/65/66/67) — ALL SHIPPED 2026-06-13
- **61a** Durable pipeline (#85): reconciler heartbeat + claim-and-set
  lease + friday queue isolation + `enqueue_after_commit` trigger.
- **61b** Pipeline observability (#87): `pipeline_health()` whitelisted
  endpoint (verdict ok/degraded/down).
- **62** Agents report back (#88): terminal tasks write Chat Message
  back to originating session, authored by agent.
- **63 + 63b** Provider model discovery + model picker UI (#89, #90):
  live `/v1/models` + curated catalog fallback.
- **63b-OAuth** Provider subscription login (#98, #99): Anthropic + Codex
  OAuth.
- **64** Setup wizard (#97): Desk web flow, requires live `list_models`
  + non-down `pipeline_health` before `setup_complete=1`.
- **65** ERPNext-grade Project module + live console (#91–#95): Project
  data model, Agent-User identity, native views (Kanban/Gantt/Dashboard),
  live console, cost/progress rollup.
- **66** Agent toolbox + deliverables (#87): `read_record`, `list_records`,
  `attach_deliverable`, `list_project_files`, anti-hallucination governance
  prompt.
- **67** MCP tools (#100): HTTP/remote MCP only, per-agent gated +
  audit-logged MCP. Surpass-Hermes.

### 4.2 v0.3 / post-v0.2 program (June 13–24)
- **68** Agent Role Contract (#101, 2026-06-14): Orchestrator/Specialist/
  Worker Select on Agent Profile drives prompt scaffolding, default
  approval threshold, Orchestrator skill seed.
- **69a** Delegation foundation (#102, 2026-06-14): durable async delegation
  with role/depth/concurrency gates, `Task.parent_task` Link, 25 tests.
- **72** Dispatcher Console (LOCKED 2026-06-14): `/desk/dispatcher-console`
  page; Pulse + Lifecycle Trace via new `Dispatcher Event` doctype +
  `emit()` helper.
- **73** Project conversation surface (Slices 1/3/5 + project-context-memory
  + share-deliverables shipped 2026-06-15/16): per-project Raven channel,
  project-aware inbound routing, deliverables-as-artifacts.
- **75** Metadata-driven generic engine (#117, 2026-06-16): Friday is
  now a generic workflow engine; a domain = DATA. Phase 1.1 added
  generic `get-phase-outputs` skill.
- **77 v2** Pipeline output upgrade (#121, 2026-06-17): Brand Brief now
  produces 9–10 file customer package instead of 4.
- **78** role_gate enforcement (2026-06-17): `Skill.role_gate` field
  load-bearing; defense-in-depth at menu-build AND call-time.
- **81** Connector framework (#127, 2026-06-24): RandomPack = connector
  #1 via generic `connectors/core.py` + `client.py`. 81c/81d/81e next.
- **82/83/84** Gateway command surface (#128, 2026-06-24): slash commands,
  approval gate, interrupt + steer. **DEPLOYED + VERIFIED LIVE on AWS**
  ai.randompack.com — 11/11 E2E via real Raven adapter.
- **85** /stop cascade (#129, 2026-06-24): cancels delegated subtree.
- **86** Delivery router (#130, 2026-06-24): `DeliveryTarget` DSL.
- **87** Cron Slice 1 (#131, 2026-06-24): `Cron Job` doctype + `*/1` tick.
- **#122** (2026-06-18): `frappe/locale.py` `value` unbound fix + image
  model field on LLM Provider.
- **#124, #123** dependency bumps (pypdf, launch-editor).
- **#126** Memory program + Hermes 1:1 port gaps landed on main.
- **#132** (2026-06-24): `memory-program` DDL rollback in `after_migrate`
  so missing pgvector is non-fatal. Caught by AWS deploy.

### 4.3 What is OPEN / next
- **Workflow Request** DocType + dispatch gate (H2 from doc 49) — approval
  subsystem is half-wired; `requires_approval` exists but nothing
  enforces it. The schema is in scope per doc 42 §3 but has 0
  occurrences in code.
- **`resource_quota` fields** on Agent Profile (M2 from doc 49) — code
  reads a field that doesn't exist; always falls back to hard-coded
  defaults (1 CPU / 256 MB / 300 s).
- **Design 76** (parallel fan-out + AND-join) — LOCKED, **PARKED by user
  2026-06-16**. Resume there for Phase 2.
- **81c** MCP → mcp modality under registry.
- **81d** Chat connectors (Slack/Telegram) + permission teeth.
- **81e** A2A (protocol TBD).
- **Design 87 Slice 2** — agent-facing `manage-cron-jobs` skill
  (create/list/pause/resume/remove/trigger).
- **Design 64 follow-ups**: OAuth flows (Anthropic/Codex already there;
  others TBD).
- **Cron Slice 2** + lifecycle hooks + `/stop force` (hard kill via RQ
  job command).

---

## 5. Standing operating rules (the discipline)

### 5.1 Workflow on this project
- **Claude writes production code directly** (no Roo Code). User said
  2026-05-30: *"i want you to code rest and refactoring which required
  to port hermes core all feat to friday."* Standing model: Claude is
  **architect + implementer + tester**. User approves and merges.
- **Lock design Q-by-Q in `docs/design/*`** before coding non-trivial
  work. Surface open questions with AskUserQuestion when reasonable
  engineers would disagree; trivial choices just make them.
- Tests-first / 80%+ coverage.
- **Migrate gate BEFORE every PR**: `bench --site friday.localhost
  migrate` must pass clean (unit tests miss patch ordering + Postgres-
  strict bugs).
- For RandomPack frontend pushes: `cd frontend && yarn build` BEFORE
  push (vite/rolldown catches things `tsc` misses).
- **Branch protection**: 1 approval required, blocks self-approval.
- Conventional commits.
- PR diff size: <800 lines.
- AI author: `fridaylabs <fridaylabs@friday-contributors.local>`. PR
  body names the sponsor.

### 5.2 Hermes comparison (required for every architectural choice)
For every option list, add a row that names the Hermes equivalent.
Acceptable answers: "same as Hermes" (best), "different because Frappe
forces X", "different because Hermes is wrong on this", "Hermes doesn't
have this concept".

### 5.3 TRUE 1:1 Hermes port rule
- READ the actual Hermes source file. Never port from a docstring,
  sibling file's description, or memory.
- Port VERBATIM (same regexes/passes/order/variants) except where a
  Frappe adaptation is genuinely required.
- **CLASSIFY + DISCLOSE every divergence** in the PR body AND a ports
  ledger: `frappe-adaptation` / `improvement` / `simplification`.
- **No silent "improve"/"trim".** Faithful first; deviate only with a
  stated reason.
- A reference Hermes clone lives at `~/Documents/reference/hermes-agent/`
  (outside the bench, read-only reference).

### 5.4 Hermes = floor, not ceiling (user stance 2026-06-12)
Deliberately SURPASS Hermes where the fork's foundations enable it:
governance (matrix/audit/approvals/cost rows vs guardrails), durability
(rows vs RAM), team-native (multi-user vs single operator), robustness
(fixed Hermes bugs in ports; survived Postgres failure classes Hermes
never faces). "More advanced" = more TRUSTWORTHY per feature, never
more features.

### 5.5 Single-tenant, not SaaS
Friday v0.1 = **one customer's Frappe site running Friday**. Not
infra hosting many customers. **Reject** any justification of the form
"we should do X because at SaaS scale Y." Enterprise = the customer
is enterprise-sized; NOT Friday hosting many enterprises.

### 5.6 ERPNext-free core
Chuck out any ERPNext coupling when porting. Frappe-only deps. The one
sanctioned exception: Project + Issue tracker modules (port, not
depend — Friday-native DocTypes, links only to Friday-native doctypes).

### 5.7 Framework altitude
**NEVER** frame Friday with ERPNext/small-business use-cases. Friday
= enterprise-level agentic system. Accessible ≠ small. Explain plainly
but never below the vision's altitude.

### 5.8 Unified gateway service
ONE gateway service handles ALL surfaces (CLI, A2A, Telegram, Slack,
Raven). Surfaces are thin adapters that read/write Chat Message rows.
**A surface MUST NOT import `agent_runner` directly.** Overrides the
Hermes-faithful in-process instinct.

### 5.9 Conversational interface (Style A)
Friday's PRIMARY interface is conversational ("talk to your agents
like coworkers" via Raven chat), NOT dashboard-driven. The Desk views
are admin/observability only — for watching/debugging, not for
work-giving. Raven is the human's home surface, so its reliability is
load-bearing-for-UX.

### 5.10 Two-layer docs in same PR as code
Every shipped change carries:
1. **In-code plain-English docstrings** on every file (module
   docstring at top; function docstring on every public fn; inline
   comments where the *why* would surprise a fresh reader). Overrides
   "minimal comments" default.
2. **Committed `docs/rollouts/<slice>-*.md` narrative** for every
   slice/phase that ships, in the SAME PR as the code. Required
   sections: In one sentence / What it actually does / What scenarios
   it now covers / What it means for friday-core / How it gets along
   with the Frappe ecosystem / What the company can say truthfully
   today / Risks and limits / What this unlocks / Numbers for the
   record. Append a one-paragraph dated entry to
   `docs/project/IMPLEMENTATION_LOG.md`.

### 5.11 Rajiv's design bar (for creative / UI work)
TWO reference systems — Draft. (austere-mono) + Rajive Studio
(warm-luxe). They diverge on surface rules but share one soul. Gate
on the **PRINCIPLE**, not on one brand's hard-nos as universal:
- Every element earns its place
- Monochrome base + AT MOST ONE accent (≤5% of elements, precision)
- Large, light-weight display type, dramatic scale, tight tracking
- Editorial layout, generous whitespace, hairline rules
- Motion (if any) is purposeful + spec'd to the millisecond

**Product brand (RESOLVED):** Draft. austere-mono is the FRONTEND
MARKETING style (randompack.com). RandomPack = $4,800/brand-scope
(charter + install.py RP-ESSENTIALS=4800, no website). Warm rajive-
studio language is NOT the product brand.

### 5.12 Permission Decision Log severity (v0.1 trust model)
**All skills in v0.1 are first-party/trusted.** When rating security
findings:
- **Missing permission/audit enforcement on the trusted path** =
  CRITICAL (breaks the governed-loop proof).
- **Sandbox containment / robustness gap** = HIGH (no untrusted-skill
  attack surface yet).
- Do NOT escalate a containment gap to CRITICAL by invoking malicious-
  skill or multi-tenant scenarios; reject those framings.

### 5.13 The 3 things that make RandomPack a system (not "run some prompts")
1. **Shared token set** (stage 5): brand + site render from one source
   of truth. Coherence trick — they can't drift apart.
2. **Two gates** = the ONLY human touchpoints. Rajiv's taste enters
   once at the direction level and propagates. ~1 hr/project = the
   economic engine.
3. **Flywheel** (Gate 1 → critic): every accept/reject trains the critic
   that pre-filters the next project's candidates → directions arrive
   already more "him" → he steers less over time. THE defensible moat.

---

## 6. Critical gotchas (load-bearing — would lose time to relearn)

### 6.1 `bench migrate` hangs at ~86% (lock contention)
`bench migrate` freezing at the same ~86% ("Updating DocTypes for
frappe") on every retry = **lock contention**, not a code bug. The
DocType sync phase runs `ALTER TABLE` (needs ACCESS EXCLUSIVE) on
tables a running worker/web process holds a lock on. The DDL waits
forever.

**Fix sequence (in order, every step required):**
1. Stop the whole stack (honcho-managed; don't kill a child alone).
2. Kill stray OS procs (migrate, schema-execs, workers).
3. **Terminate the orphaned DB backends** — `bench --site <s> execute
   frappe.db.sql --args '["SELECT pg_terminate_backend(pid) FROM
   pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"]'`.
   (The site db_user owns them all → same-role terminate is allowed.)
4. Verify `state='active'` backend count == 0.
5. `rm -f sites/<s>/locks/bench_migrate.lock`.
6. Run **exactly one** migrate.

`pkill -9` on OS processes does **NOT** release Postgres locks. The DB
backend connections survive OS kills, still pinning locks. (Cost a
24h rabbit hole 2026-06-24 on Legion — 19 orphaned backends.)

### 6.2 bench start uses honcho (cascading kill)
`bench start` runs honcho. **If ANY one managed process exits, honcho
SIGTERMs all the others and shuts the whole stack down.** Never `kill`
a honcho-managed child PID directly to restart it — you take down the
whole site. To recover: restart the whole stack (`nohup bench start`).

The local Procfile runs: redis_cache, redis_queue, web:8005,
socketio:9005, watch, schedule, worker, worker_friday.

### 6.3 run-tests pollutes the live site (deactivates Minimax)
`bench --site friday.localhost run-tests` mutates the LIVE working
site's database. Tests that commit persist their writes. Caught
2026-06-14: `test_llm_provider` left the real **Minimax** provider
`is_active=0`, blocking the live pipeline.

**How to apply:**
- Treat `bench run-tests` on `friday.localhost` as DATA-MUTATING.
  Re-check anything E2E depends on after a test run.
- Prefer a separate test site (e.g. `bench new-site test.localhost`) for
  DB-backed suites.
- When a live task blocks on "provider inactive / not found / settings
  missing" right after a test run, suspect test pollution first.

### 6.4 Mac local Redis — Frappe needs its OWN
Frappe needs its own redis on **13005** (cache/socketio) and **11005**
(queue). Start with `redis-server config/redis_cache.conf --daemonize
yes` etc. The default brew redis (6379) is NOT enough — migrate
refuses with "redis_cache is not running."

Mac local Postgres = brew `postgresql@17` cluster (port 5432, db
`_6df0169379435b18`), NOT `@14`.

### 6.5 pgvector required for the memory program
The `memory-program` after_migrate runs `CREATE TABLE ... embedding
vector(N)`. On Postgres WITHOUT pgvector this DDL fails → poisons the
whole tx (the `except Exception` logs but never `rollback()`s) → every
later query dies `InFailedSqlTransaction`, migrate aborts.

**Fix on EC2:** `sudo apt-get install -y postgresql-16-pgvector` + `sudo
-u postgres psql -d <db_name> -c "CREATE EXTENSION IF NOT EXISTS
vector;"`. (Latent code bug worth a PR: add `frappe.db.rollback()` /
savepoint in that except so missing extension is truly non-fatal.)

### 6.6 Frappe routes by Host header (NOT 127.0.0.1)
Posting to `http://127.0.0.1:8002/...` → 404 "127.0.0.1 does not exist".
Use the **hostname**: `http://friday.localhost:8002/...`. Same applies
Friday→RandomPack.

### 6.7 Raven disabled-user → blank channel + 409
Symptom: War Room shows BLANK with `409 CONFLICT` on `get_messages`,
posts intermittently fail with "You are already a member of this
channel".

**Root cause:** `raven/utils.py::get_channel_members` JOINs
`raven_user.enabled == 1` — disabled users filtered out of member
map. `track_channel_visit` takes its "not a member + Open channel →
INSERT" branch → `Raven Channel Member.before_insert` finds the
existing row → `DuplicateEntryError` → HTTP 409.

**Fix (two parts, both required):**
1. Keep human Raven Users `enabled=1`. `surfaces/bootstrap_raven._ensure_raven_user`
   sets `enabled=1` on create AND re-enables an existing disabled row.
2. Post agent messages AS THE FRIDAY BOT, not as the session user.
   `warroom/publisher._post_to_raven` and
   `conversation/project_channel._seed_welcome` use
   `frappe.get_doc("Raven Bot", "Friday").send_message(...)`.

### 6.8 AWS EC2 gotchas
- `bench` lives at `/home/ubuntu/.local/bin/bench` (pipx, NOT on PATH,
  NOT in `env/bin`). Prefix PATH before every bench command.
- EC2 uses **supervisor** (groups `friday-bench-redis`, `friday-bench-web`,
  `friday-bench-workers`), NOT the `friday-bench.service` systemd unit.
  Migrate-gate: `sudo supervisorctl stop friday-bench-web:
  friday-bench-workers:` (KEEP redis up — migrate needs it).
- `friday-bench.service` (systemd-run --user) is a **transient unit**,
  not a unit file — `systemctl --user reset-failed` erases its
  definition. Recreate with
  `systemd-run --user --unit=friday-bench --collect ...`.
- Git remote on the box is named **`upstream`** (NOT origin) →
  `git fetch upstream main && git merge --ff-only upstream/main`.
- NGINX /assets needs `chmod o+x /home/ubuntu` (asset 404 trap if
  bench under `/home/<user>` with mode 750).
- Standalone `frappe.init()` scripts mis-resolve log path on this py3.14
  build. Use `bench --site X console <<'PY'` with `exec(r'''...''')` —
  no `frappe.init` (console pre-connects).
- `set-config` gotcha: use `bench set-config -g -p <key> <int>` for
  numeric values (without `-p` it stores a STRING → breaks
  `bench setup supervisor`).
- **Two fresh-install bugs uncovered** (Legion masks both — its data
  predates them):
  1. `frappe.render_template` fails on a fresh site → `UnboundLocalError:
     'value'` at `frappe/locale.py:52`. System Settings.language = ''
     → falsy lang → crash. **FIX: set language='en'.** Code fix landed
     in PR #122.
  2. Provisioning ordering gap: after_migrate runs
     `randompack_brand.provision()` but nothing bootstraps the skills
     first → dies in `_ensure_transition_meta`. Run `cli.setup.run_setup`
     + each `bootstrap_*.provision()` BEFORE `randompack_brand.provision()`.

### 6.9 Legion persistent-start gotcha
`screen -dm`, `setsid`, `nohup` ALL die with rc=-15 when the
legion_exec SSH channel closes. tmux is NOT installed. The WORKING
method:

```bash
XDG_RUNTIME_DIR=/run/user/$(id -u) \
systemd-run --user --unit=randompack-bench --collect \
  bash -lc 'cd /home/friday/randompack-dev/randompack-bench && exec bench start'
```

Then `systemctl --user is-active randompack-bench`. Survives SSH close.

### 6.10 Postgres-strict gotchas (vs MariaDB-tolerant)
- **Number Card** → `GroupingError: column "...creation" must appear
  in GROUP BY` (default `creation desc` ordering on ungrouped
  aggregate). Fix = pass `order_by=None`.
- **`("is", "set")` filter on timestamp** → `InvalidDatetimeFormat`.
  Postgres rejects comparing a timestamp to an empty string. Use
  `Max()`/`Min()` aggregate via `frappe.qb`.
- **TIMESTAMPDIFF on Postgres** — doesn't exist; use Python-side
  cutoffs (datetime subtraction).

### 6.11 patches.txt ordering gotcha
A patch that **POPULATES a newly-added field** goes in
**`[post_model_sync]`** (NOT above it). Pre-sync runs before model
sync creates the column → fresh `bench migrate` dies with
`UndefinedColumn`. friday_core lives INSIDE frappe
(`apps/frappe/frappe/friday_core`), so its patches register in
`apps/frappe/frappe/patches.txt`, not a standalone app patches.txt.

### 6.12 Connector framework gotcha
`frappe.db.exists("Singles", {...})` emits `SELECT name FROM
tabSingles` but that table has no `name` column → SQL error poisons
the whole transaction (surfaces later as `InFailedSqlTransaction`).
Read tabSingles by raw SQL in patches. A caught SQL exception still
leaves the PG tx aborted.

### 6.13 RandomPack frontend (Doppio SPA)
- `cd frontend && yarn build` before push (NOT just `tsc`).
- Vite v8 on Frappe Cloud uses Rolldown, which is stricter than the
  dev-time loader. A straight apostrophe inside a single-quoted string
  (`'You'll sign in with this email.'`) will fail the bundler even when
  tsc passes.
- Apostrophe rule: use a curly apostrophe `'` (U+2019), reword to
  remove the apostrophe, OR switch to double quotes. The codebase
  convention is U+2019.

---

## 7. Standing E2E demo + what the product proves

### 7.1 Live demo project
**Northwind Coffee — Brand Identity** (NWC-E2E-001). 9 tasks, all
Completed. Raven channel `Friday-proj-nwc-e2e-001`. Live on Legion.

### 7.2 The governed framework loop (v0.1 proof)
> A user can create or send work into Friday. Friday resolves an
> Agent Profile, loads governed Skills from DocTypes, checks
> permissions, executes one approved skill in a sandboxed path,
> records immutable logs, updates an Agent Task through a
> configurable workflow, and shows the result in the Framework
> Console.

That loop is what Phase 1 was supposed to prove. v0.2 (Designs 61–67)
extended it. v0.3+ is the operational hardening and the actual
business pipeline (RandomPack, ERPNext PO automation eventually).

### 7.3 Recent E2E results
- **2026-06-15 Legion Northwind E2E: 17/17 PASSED.** Minimax streaming
  retry=0, deliverables md+pdf (7/7 + 28KB/100KB package), both human
  gates, reconciler recovery (retry=1), Design 72 trace visible
  (skip×17→claim→4×llm→complete).
- **2026-06-16 Legion BB-0034 E2E PASSED** (Design 75 Phase 1): full
  pipeline → Delivered in ~3 min, 7/7 tasks Completed, retry=0, both
  gates via gateway.
- **2026-06-16 Legion Aurora Coffee (BB-0042):** generate-image skill
  produced 4 real .jpg autonomously (3 direction logos + 1 hero).
- **2026-06-24 AWS ai.randompack.com E2E: 11/11 PASSED.** Real Raven
  adapter, `/help` / `/status` / non-operator `/approve` REFUSED,
  operator `/approve` flips a real Pending Workflow Request →
  Approved, `/deny <reason>` → Rejected, `/stop` cascade cancels 2
  delegated Tasks + sets interrupt flags.

---

## 8. Where to read more (load on demand)

Don't read everything at once. Load by purpose:

- **Designing a new slice**: `docs/design/42-phase-one-authority-contract.md`
  (the law) + `docs/design/10-agent-execution-guide.md` (slice
  mechanics) + `docs/design/11-agent-validation-checklist.md` (done
  criteria) + the relevant `project_design-XX-*.md` for the slice.
- **Porting Hermes**: `feedback_compare-with-hermes.md` (the
  comparison) + `feedback_true-1to1-ports.md` (the discipline) +
  `feedback_hermes-floor-not-ceiling.md` (when to surpass) +
  `~/Documents/reference/hermes-agent/` (the source).
- **Doing anything with the engine**: `docs/design/75-metadata-driven-domain-framework.md`
  + the `project_design-75-phase1.md` memory note.
- **Doing anything with the gateway**: `docs/design/47-gateway-design-decisions.md`
  + `docs/design/82-gateway-command-surface.md` +
  `project_design-82-gateway-command-surface.md`.
- **Doing anything with the connector**: `docs/design/81-connector-framework.md`
  + `project_design-81-connector-framework.md` + the rollout
  `docs/rollouts/connector-framework-81ab-2026-06-24.md`.
- **Security review**: `docs/design/04-security-model.md` (read the
  v0.1 reality callouts) + `docs/design/24-sandbox-architecture-implementation.md`
  + `docs/design/46-security-claims-audit.md` +
  `feedback_v01-skills-first-party-trust.md` (the severity model).
- **Drift between docs and code**: `docs/design/49-foundations-deviation-audit.md`
  — the **map**, not the repair. Read before believing the older
  design docs verbatim.
- **Site operations**: `friday-site-topology-2026-06.md` (live vs dev)
  + `project_migrate-needs-stack-stopped.md` (the gate) +
  `project_bench-start-honcho-gotcha.md` (don't kill children) +
  `project_run-tests-pollutes-live-site.md` (separate test site) +
  `project_ec2-deployment-2026-06-18.md` (the AWS playbook).
- **RandomPack seam**: `~/.claude/memory/friday-labs-charter.md` (the
  contract) + `docs/design/41-porting-strategy-hermes-erpnext-raven.md`
  + `docs/CONTRACT.md` in the randompack repo.
- **Doing docs / rollouts**: `feedback_high-school-readable-docs.md`
  (the two-layer rule + the 9 required rollout sections).
- **Doing the conversational UI / Raven work**: `project_interface-style-a-conversational.md`
  (Style A) + `feedback_rajiv-design-bar.md` (the design bar).

---

## 9. Standing questions for the user

The user's called-in calls that haven't been made yet:
- **C2 from doc 49** (HIGH not CRITICAL per trust model — confirmed
  by user): sandbox strict-mode (`friday_require_sandbox` default True
  in production). Build OR accept the deferral?
- **Workflow Request DocType** (H2 from doc 49): build it, or remove
  the half-wiring (`requires_approval` + `requires_approval_above_risk`
  fields are advertised but not enforced)?
- **`resource_quota_*` fields on Agent Profile** (M2): add them and
  wire `_resolve_limits`, OR delete the dead lookup and document
  the fixed defaults?
- **Conductor-only Friday Operator role on the AWS site**: only
  Administrator + bots have it. (Granted to Administrator on AWS
  per user.) For a real customer deployment, the human must be
  assigned manually.
- **USD-vs-INR currency call** for RandomPack (charter: $4,800;
  Draft. example: $700-with-website). Assume $4,800 + Draft. style
  until told otherwise.

---

## 10. What an AI session should do FIRST in this project

1. **Read this briefing** (this file).
2. **Confirm you're on `main`** (or a feature branch off it). PRs #1–
   #132 are merged; anything older than ~3 days is stale.
3. **Read the relevant `project_design-XX-*.md`** for the area you're
   touching (see §8).
4. **Read `docs/design/49-foundations-deviation-audit.md`** before
   believing any older `docs/design/04-*` or `docs/design/05-*` claim
   — those docs have AS BUILT vs PLANNED callouts now.
5. **Decide track** (`core` | `domain:randompack` | `integration`)
   before coding. Apply the §2.4 law.
6. **Lock the design Q-by-Q in `docs/design/*` before coding** non-
   trivial work (§5.1).
7. **Migrate gate**: `bench --site friday.localhost migrate` clean
   BEFORE pushing any PR (§5.1).
8. **Tag the rollout narrative** at `docs/rollouts/<slice>-*.md` in
   the SAME PR as the code (§5.10).
9. **If something feels off**: read the gotcha (§6) BEFORE debugging.
   Most things have been hit before.

---

*This briefing is a synthesis, not the spec. When in doubt, the primary
source wins — usually `docs/design/*` or the relevant
`project_design-XX-*.md` memory note.*
