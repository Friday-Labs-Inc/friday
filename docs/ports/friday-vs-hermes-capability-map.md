# Friday vs Hermes — Capability Map (2026-06-25)

> The high-altitude, plain-English companion to the line-by-line
> [`hermes-port-ledger.md`](hermes-port-ledger.md). The ledger answers *"is this
> component a faithful port?"* file-by-file. This map answers the question a human
> actually asks: **"what can Friday do right now, and how does that compare to
> Hermes?"** Grounded in the ledger + a code existence-check of every headline
> claim (modules/doctypes verified present on `main`, 2026-06-25), not memory.

## Bottom line

1. **The Hermes port is COMPLETE.** Every one of the 7 core components is shipped;
   what's left is *justified defers* (A2A, external memory providers, lifecycle
   hooks) and *polish* (streaming, display tiers, transcript mirror).
2. **Friday deliberately SURPASSES Hermes** wherever the Frappe foundation makes it
   cheap to: governance, durability, delegation, observability, and
   domain-as-data. These aren't in Hermes at all — they're the "Hermes = floor,
   not ceiling" upgrades.
3. **The shape is different on purpose.** Hermes is one long-running asyncio
   process holding 20+ live socket connections in memory + JSON + SQLite. Friday
   is the inverse: **every message is a `Chat Message` row, the chokepoint is a
   Frappe `after_insert` hook, and RQ workers + Redis locks do concurrency.** Most
   of Hermes's daemon machinery (pairing, channel directory, PID liveness, restart
   forensics) is *correctly absent* — the DB/Raven substrate already solves those.

---

## At a glance — the 7 core pillars

| # | Pillar | Status vs Hermes | Friday's version |
|---|--------|------------------|------------------|
| 1 | **Agent ReAct loop** | ✅ Complete + surpasses | `agent_runner/runner.py` — tool loop, empty-response retry, dedup, permission-denial break, **interrupt/steer**, on-error compress+retry, **post-turn learning loop** |
| 2 | **Connection surfaces** | ✅ Complete (multi-surface proven) | Raven + Slack adapters; surfaces are thin row-in/row-out adapters, not in-process plugins |
| 3 | **Context assembly** | ✅ Complete | `llm/prompt_builder.py` — USER.md split, date line, skills guidance, prompt caching, project isolation |
| 4 | **Context compression** | ✅ Complete | `llm/compression.py` — 50% trigger, 13-section summary prompt, on-error retry, durable `Compaction Summary` rows |
| 5 | **Gateway** | ✅ Complete (full file-by-file audit) | Row-based chokepoint + RQ workers; session manager (queue/interrupt/steer/cascade/stop-force), delivery router, slash commands |
| 6 | **Memory (3 forms)** | ✅ Complete (Mem0 deferred) | `Agent Memory` + pgvector semantic recall + Chat-Message FTS + `session_search`; blended scored recall |
| 7 | **Cron / scheduled runs** | ✅ Complete (both slices) | `Cron Job` doctype + `*/1` tick + delivery + `manage-cron-jobs` agent skill |

---

## Where Friday SURPASSES Hermes (the "floor not ceiling" upgrades)

These have **no Hermes equivalent**. They exist because Frappe gives them to us as
first-class primitives, and they're what make Friday an *enterprise governance
framework* rather than a personal agent.

| Capability | What it gives you | Where |
|---|---|---|
| **Always-on permission matrix + human-approval gate** | Every tool call is evaluated against a role×doctype×operation matrix and can require a human `/approve` before it runs. Hermes has no governance layer. | `permissions/matrix.py`, `agent_runner/dispatcher.py` |
| **Durable async delegation** | An orchestrator spawns sub-agents as durable `Task` rows with role/depth/concurrency gates and a `parent_task` tree — survives restarts, fully audited. Hermes sub-agents are in-memory. | `tasks/runner.py`, `tasks/report_back.py` (D68/69) |
| **Full doctype audit trail** | Every turn leaves queryable rows: `Execution Log`, `LLM Usage Log`, `Permission Decision Log`, `Dispatcher Event`, `Compaction Summary`. This *is* the substrate the eval harness reads. | `doctype/*` |
| **Metadata-driven domain engine** | A whole business domain is **DATA, not Python** — a Frappe Workflow + `Friday Workflow Transition Meta` + Agent Profiles. Add a productized pipeline without shipping code. | `engine/` (D75) |
| **Connector framework** | Generic inbound/outbound integration as governed `Connector` / `Connector Event` rows (RandomPack is connector #1). | `connectors/core.py` (D81) |
| **Project isolation + durable compaction** | Recall is scoped per-project (no cross-project bleed); folded turns persist as `Compaction Summary` rows instead of vanishing. | `llm/memory.py`, `llm/compression.py` |
| **Agentic eval harness** | Tests the agent on the *real path* (loader→matrix→run_turn→dispatch), N× for variance, scored from the audit trail. Hermes has nothing like it. | `evals/` (D91, Slice 1) |
| **Dispatcher console** | Live operational view (Pulse + Lifecycle Trace) over `observability.emit` events. | D72 |

---

## Friday-native capabilities with no Hermes line

Beyond the per-component surpasses, these are whole features Hermes simply doesn't
have, because they come from being a Frappe fork:

- **Agent role contract** (Orchestrator / Specialist / Worker) driving prompt
  scaffolding + default approval posture (D68).
- **Project + Task + Issue work objects** ported from ERPNext — agents operate on
  real governed records, and humans steer the pipeline from chat
  (`plan-project`, `project-status`, `update-task`, `pause-project`, `list-projects`).
- **MCP outward tools** — Friday reaches external MCP servers as governed skills
  (`mcp/`, D67).
- **Self-improvement review** — a post-turn, tool-restricted turn proposes durable
  memories + new skills (governed via the `Skill Proposal` doctype), D79.
- **Image generation** as a first-class skill wired to a Creative Director profile.

---

## Deliberate defers — NOT gaps

Each is a conscious v0.1 decision with a reason; none block the product.

| Deferred | Why it's deferred |
|---|---|
| **A2A (agent-to-agent protocol)** | D81e — no cross-org agent network need yet; connectors cover today's integration. |
| **External memory providers (Mem0/Supermemory)** | First-party pgvector already gives semantic recall; external plugins are layerable later. |
| **Lifecycle hooks (filesystem `handler.py`)** | D88 — Hermes loads arbitrary code from disk (a code-execution surface, HIGH severity in the v0.1 trust model) with no consumer. Eventing need already met by `observability.emit`. |
| **Progressive token streaming** | Friday writes one finished row; Raven *can* edit messages, so it's portable, but "one clean row" is fine until live-typing UX is wanted. |
| **`runtime_footer` / `display_config` tiers / generic `mirror`** | Transparency footer + per-surface display tiers + out-of-turn transcript mirroring — polish that pays off once a richer multi-surface UX is the priority. |
| **Structured session keys / auto session-reset** | Hermes rotates sessions per user/thread; single-tenant Friday uses a flat channel-id session and lets compaction handle length. Fine today. |

---

## Live verification status (this is the honest part)

Capabilities existing ≠ capabilities *working on prod*. A real-browser sweep of
production (`https://ai.randompack.com/`, one test at a time) is in flight and has
already turned up — and fixed — two bugs that **all unit tests missed**:

| Found on prod | Class | Status |
|---|---|---|
| Raven realtime dead (socketio rejected same-origin polling: browser omits `Origin`) | deploy/infra | ✅ Fixed on-box (`proxy_set_header Origin $scheme://$host`), live-verified |
| Slash commands unreachable in channels (`@Friday /help` fails the leading-`/` check) | core / Design 82 | ✅ Fixed → PR #149 (+5 tests), awaiting deploy |

Both are exactly why the eval harness (D91) exists: *unit tests verify the parts;
only the real path verifies the agent.* The sweep continues through multi-step
jobs, gate approvals, `/steer`, and `/stop force`.

---

## What this means for "RandomPack integration next"

RandomPack integration is the **capstone E2E** — it rides on every pillar above
(engine, gateway, commands, realtime, delivery). Two reasons it's *next*, not
*now*: (1) the core just shed two prod bugs, so proving it green first lets the
joint test isolate *integration* faults from *core* faults; (2) the Friday-side
Phase-1 wiring still has open pieces (`project.created → engine`,
`gate.decided → apply_workflow`, the `task_ref` write-back). Once the prod sweep
is green and those land, the RandomPack joint E2E is a clean test of just the
integration seam — which is the connectivity already proven on Legion (signed,
HMAC-verified message exchange).

---

*Maintenance: when a deferred item ships or a new pillar lands, update both this
map and the line-by-line ledger. This map is the readable index; the ledger is the
file:line proof.*
