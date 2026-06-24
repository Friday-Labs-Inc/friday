# Hermes → Friday ports ledger

_Authoritative 1:1-port comparison, grounded in real source on both sides
(never docstrings or memory). Built 2026-06-23 from the Hermes architecture
talk (`Hermes_Architecture_transcript.md`) as the component index + a
source-by-source audit of `reference/hermes-agent/` vs `friday_core/`._

## Plain English

Friday is a port of the Hermes agent into Frappe. This ledger answers, for each
high-level Hermes component: **is Friday's version a faithful port, a justified
divergence, or a genuine gap?** — with the exact file on each side. It's the map
for deciding what to port next, and the audit trail that proves the harness is
really Hermes, not an approximation.

## Status legend

- **verbatim-port** — same logic, ported faithfully.
- **frappe-adapted** — changed only because Frappe forces it (DB rows vs files, etc.).
- **improved** — Friday deliberately surpasses Hermes here (named, justified).
- **simplified** — Friday does less than Hermes; behaviour is lost. Flagged.
- **MISSING** — Hermes has it, Friday does not. A true gap.

---

## Summary matrix

| # | Component | Overall status | Highest-value gap |
|---|-----------|----------------|-------------------|
| 1 | Agent ReAct loop | faithful core, **2 critical gaps** | **post-turn memory/skill review (learning step)**; interrupt handling |
| 2 | Connection surfaces | diverged (by design) | — (unified gateway is the chosen improvement) |
| 3 | Context assembly | frappe-adapted + gaps | USER.md two-store split + auto-update; date line; SKILLS_GUIDANCE; prompt caching |
| 4 | Context compression | core verbatim, edges simplified | on-error compress+retry; 13-section summary prompt; tool-result pruning |
| 5 | Gateway | diverged (by design); **session manager COMPLETE + cascade + hard-kill** | queue+slash+interrupt+steer+cascade+`/stop force` (D85/D86/D87/D83b) all done 2026-06-24; delivery DSL shipped (D86). Remaining: lifecycle hooks. Full file-by-file pass: [§ Gateway deep audit](#gateway-deep-audit-2026-06-24-file-by-file) |
| 6 | Memory (3 forms) | 1 form adapted, 2 **MISSING** | **external providers (Mem0/etc.)**; **session_search + full-text** |
| 7 | Cron jobs | **SHIPPED** (Design 87, both slices) | Slice 1: `Cron Job` doctype + `*/1` tick + delivery. Slice 2: agent-facing `manage-cron-jobs` skill (own-jobs-only, role-gated, deliver-to-channel default) |

Confirmed along the way: the transcript's claim that Hermes cron is stored as
plain JSON (`~/.hermes/cron/jobs.json`), not SQLite, is **correct in source**
(`cron/jobs.py:39,426`). A reminder of why we read source, not docs.

---

## The prioritized port backlog (true gaps only)

Ranked by value-to-effort for a single-tenant enterprise deployment.

### Tier 1 — defines the product ("an agent that learns")
1. **Post-turn memory/skill review** — the autonomous learning step.
   Hermes: `agent/conversation_loop.py:4313` → `agent/background_review.py:327–583`
   (every N turns, a forked agent restricted to memory/skill tools reviews the
   transcript and writes durable learnings). Friday: **none** — `run_turn`
   returns and stops (`agent_runner/runner.py:239`). Port = a post-turn RQ job
   that re-invokes a memory-only turn on a cadence counter. Effort: medium.
2. **USER.md two-store split + proactive auto-update.**
   Hermes: `tools/memory_tool.py:603–677` (`user` vs `memory` targets; schema
   nudges the model to write proactively). Friday: one `Agent Memory` doctype,
   explicit `remember` only (`skills/handlers_memory.py:22`). Port = `memory_type`
   field + split recall + tighter schema wording. Effort: medium.

### Tier 2 — long-lived-agent recall
3. **session_search + full-text index.** Hermes: `tools/session_search_tool.py`
   over SQLite FTS5 (`hermes_state.py:256–308`). Friday: **none** — the agent
   cannot search its own past transcripts. Port = Postgres `tsvector`+GIN on
   `Chat Message` + a `session_search` skill. Effort: high (most valuable
   long-term).
4. **External memory providers.** Hermes: `agent/memory_provider.py` (ABC) +
   `agent/memory_manager.py` (orchestration) + Mem0/Supermemory/Honcho plugins.
   Friday: **none** (fence helpers ported in `llm/memory.py:44–69`; the machinery
   that feeds them is absent). Deliberately deferred at v0.1; Mem0 is the
   lowest-friction first plugin. Effort: high, layerable.

### Tier 3 — robustness & interaction
5. **Interrupt / steer / queue session manager.** Hermes: `gateway/run.py:3090`
   (`_handle_active_session_busy_message` — three modes + `/steer` `/queue` +
   subagent-aware demotion at `run.py:3163–3173`). Friday: **QUEUE shipped
   2026-06-24 (design 80)** — a message on a busy session is left `processed=0`
   and drained FIFO when the lock releases (`gateway/service.py:234–242, 344`),
   no longer dropped/"busy"-rejected. Remaining: **interrupt** (cancel the RQ
   job — `job_id` already on the row, `service.py:118`) and **steer**. Effort:
   interrupt ~1d, steer ~2d. See the file-by-file [§ Gateway deep audit](#gateway-deep-audit-2026-06-24-file-by-file).
6. **On-error compression + retry.** The `should_compress` flag is computed
   (`llm/error_classifier.py:47`) but the runner never catches `LLMError` to act
   on it. Port = a `try/except LLMError` in the loop that compresses + retries
   once. Effort: small.
7. **Cron jobs (user-scheduled agent runs).** Hermes: `cron/jobs.py`,
   `cron/scheduler.py`, `tools/cronjob_tools.py`. **Slice 1 SHIPPED (Design 87):**
   `Cron Job` doctype + `cron/scheduler.py` (`*/1` tick, advance-before-spawn
   at-most-once, croniter/interval/once) + delivery-on-completion via the #86
   router (a cron run IS a Task, tagged `cron_job`). Repeat-limit disables (not
   deletes — Frappe audit). **Slice 2 (deferred):** the agent-facing
   `manage-cron-jobs` skill (`tools/cronjob_tools.py` equivalent) so an agent can
   schedule its own work. See `docs/design/87`.

### Tier 4 — quality / cost edges
8. **Compressor prompt: 13 named sections → 1.** Friday's `_SUMMARISER_SYSTEM`
   (`llm/compression.py:103`) is free-form; risks dropping blockers / pending
   user asks / in-progress state on long runs. Port the section template. Small.
9. **Anthropic prompt caching.** `agent/prompt_caching.py` (80 lines,
   self-contained) — **none** in Friday. No-op on MiniMax; a real cost/latency
   win on Claude. Small.
10. **Tool-result pruning before compression** (`context_compressor.py:454–807`)
    — Friday feeds full transcripts to the summariser. Small–medium.
11. **Date line in the system prompt** — Friday never tells the model today's
    date. Trivial.
12. **Misc small gaps:** `SKILLS_GUIDANCE` block; head-protection /
    last-user-message-in-tail guarantee; mid-loop compression; usage-field token
    refinement; frozen memory snapshot for prefix-cache stability.

---

## Port plans + status update (2026-06-23)

The memory program shipped today, closing several backlog items, and four
source-grounded 1:1 port plans were produced for the remaining top gaps.

**Now DONE (memory program — shipped + tested on the Mac):**
- Tier 2 #3 `session_search`/full-text — the Postgres FTS index now powers
  scored recall (relevance ranking; the AND→OR `plainto_tsquery` fix landed).
- Tier 2 #4 external/semantic recall — first-party pgvector + a local fastembed
  (ONNX, torch-free) embedding backend; semantic recall proven end-to-end
  (zero-keyword-overlap query surfaced the right memory, 0.70 vs 0.41).
- Compaction-time fact extraction (Hermes `on_pre_compress`) — durable facts are
  mined into Agent Memory before turns are folded away.

**Port plans ready to build (each grounded in real Hermes source, classified):**

| Gap | Plan summary | Effort | Top open fork |
|-----|--------------|--------|---------------|
| Tier 1 #1 learning loop (Design 79) | Validated vs `background_review.py`; 7 design gaps found (verbatim "do-NOT-capture" list, the 4-level skill hierarchy, cadence query, etc.). Slice 1 memory-review + Slice 2 governed skill-proposal. `run_turn` stubs (`allowed_skills`/`skip_compression`) already exist. | 1.5d + 2d | which model runs the review (recommend `compression_model`); separate `skill_review_interval` |
| Tier 1 #2 USER.md two-store split | Add `memory_type` (general/user_profile) field + proactive-write skill wording (verbatim) + split labelled recall blocks; injection-scan at write. Keeps pgvector path intact. | ~8h | is the split worth it vs `subject`; needs the learning loop for full proactive value |
| Tier 3 interrupt/steer/queue | DB+RQ adaptation: QUEUE (leave row `processed=0` + drain/reconciler), INTERRUPT (cancel RQ job by `job_id` + Redis interrupt flag), STEER (Redis steer-inbox polled in `run_turn`). New `Chat Message.gateway_status` field. | 0.5d + 1d + 2d | auto-interrupt vs queue-by-default; Raven command surface; RQ cancel fidelity |
| Tier 3/4 compression parity | 5 gaps: on-error compress+retry (the `should_compress` flag is computed but unused), 13-section summary prompt, tool-result pruning, last-user-in-tail guarantee, usage-token refinement. | ~3.25d | tool-row shape in `prompt_builder` (gates the pruning pass) |

**Also closed 2026-06-23 (Tier 4 quality/cost edges):**
- ✅ **On-error compress+retry** + **last-user-in-tail** (compression quick wins).
- ✅ **13-section structured compressor prompt.**
- ✅ **Date line** in the system prompt (the model now knows the current date).
- ✅ **Tool-use guidance** (SKILLS_GUIDANCE essence) on conversational turns.
- ✅ **Anthropic prompt caching** — upgraded from prefix-only to full Hermes
  `system_and_3` (system + last-3-message history caching). No longer a divergence.

**Remaining open port gaps (2 substantive + 1 minor):**
- **Interrupt + Steer** (Tier 3) — the other two of the session manager (queue done). Touches the run_turn hot loop + RQ cancellation.
- **Cron jobs** (Tier 3) — user-schedulable recurring agent runs. New doctype + scheduler tick + home-channel delivery.
- **usage-token refinement** (Tier 4, minor) — feed the provider's real token usage into the compression trigger instead of chars/4. Deferred (chars/4 fine for text).

**Recommended cross-plan build order (value ÷ effort):**
1. Compression *last-user-in-tail* (~15 lines, pure correctness) + *on-error compress+retry* (~0.5d, prevents hard fails).
2. Interrupt/steer/queue **QUEUE phase** (~0.5d) — stops the current message-loss bug.
3. Learning loop **Slice 1** (memory review) — the #1 strategic gap.
4. USER.md split + compression 13-section prompt.
5. INTERRUPT/STEER phases, governed skill-proposal, tool-result pruning, usage refinement.

## Faithful ports already in place (verified)

- ReAct loop skeleton, empty-response retry (3), tool-call dedup, deterministic
  call IDs, tool-result feedback, permission-denial break — `agent_runner/runner.py`.
- Compression trigger (50%, chars/4), before-turn check — `llm/compression.py` (verbatim).
- Memory context fence helpers (`sanitize_context`, `build_memory_context_block`)
  — `llm/memory.py:44–69` (verbatim).

## Deliberate divergences (justified — not gaps)

- **Surfaces / gateway:** unified Chat-Message-row chokepoint + RQ workers vs
  Hermes' in-process asyncio. (`feedback_unified-gateway-service`.)
- **Soul:** `Agent Profile.system_prompt` field vs `SOUL.md` file.
- **Memory store:** `Agent Memory` / `Chat Message` (Postgres) vs Markdown +
  SQLite. **Improvements on top:** project-scoped recall isolation
  (`llm/memory.py:116–133`) and durable `Compaction Summary` rows
  (`llm/compression.py:245`) — both surpass Hermes.
- **Cron substrate:** Frappe scheduler vs Hermes' own tick loop.
- **Governance:** always-on permission matrix + human-approval gate
  (`agent_runner/dispatcher.py`) — no Hermes equivalent; a deliberate surpass.

---

## Gateway deep audit (2026-06-24) — file-by-file

The summary-matrix row #5 above treated "Gateway" as one line and only audited
Hermes `gateway/run.py`'s session manager. This section is the **full pass**:
every file in Hermes `gateway/` (22 files) read in source, classified against
Friday, with the exact file on each side.

### Plain English

Hermes's gateway is a single long-running Python process that holds open live
connections to 20+ chat platforms, keeps all session state in memory + JSON +
SQLite, and is its own process manager. Friday's gateway is the opposite shape
by deliberate design (`feedback_unified-gateway-service`): **every message is a
`Chat Message` row, the chokepoint is a Frappe `after_insert` hook, and RQ
workers + Redis locks do the concurrency**. So most of Hermes's gateway files
fall into one of four buckets — and only a handful are real gaps.

### The four buckets

1. **Ported / has a Friday equivalent** — same job, Frappe-shaped.
2. **True gap** — Hermes has it, Friday needs it, Friday doesn't have it.
3. **Made irrelevant by the Frappe/Raven substrate** — the problem doesn't
   exist in a row-based, DB-authenticated world. Justified divergence, not a gap.
4. **Infra-only** — process-manager concerns that honcho / systemd / bench own.

### Full classification table

| Hermes file (≈LOC) | What it does | Friday equivalent | Status | Bucket |
|---|---|---|---|---|
| `run.py` _message dispatch_ (`run.py:6708` `_handle_message`) | The chokepoint every inbound message flows through | `gateway/service.py:126` `handle_inbound` (`Chat Message.after_insert`) | **frappe-adapted** — in-process asyncio → DB-row hook + RQ | 1 |
| `run.py` _QUEUE mode_ (`run.py:3090`, `:3197–3203`) | Busy-session message left for next turn | `service.py:234–242` (leave `processed=0`) + `:344` `_drain_next_in_session` (design 80) | **ported 2026-06-24** — FIFO drain + orphan sweeper backstop | 1 |
| `run.py` _INTERRUPT mode_ (`run.py:3210–3215`, hard: `:15292`) | Cancel a running turn, replay msg next | **none** — `run_turn` loop (`agent_runner/runner.py:176`) has no cancel check | **MISSING** | 2 |
| `run.py` _STEER mode_ (`run.py:3183–3191`) | Inject text into a turn between tool calls | **none** — no steer inbox, no mid-loop poll | **MISSING** | 2 |
| `run.py` _slash dispatch_ (`run.py:7026–7792`) | `/stop /status /approve /deny /new /queue /steer …` | **none** — `cli/chat.py` + `raven_adapter.py` pass text verbatim; zero slash parsing | **MISSING** | 2 |
| `run.py` _busy-ack debounce_ (`run.py:3225`) | One "I'm busy" ack per session / 30s | n/a — Friday queues silently, no ack | irrelevant (no busy reject) | 3 |
| `session.py` `SessionStore` (`session.py:668`) | session_key → session_id, transcript | `Chat Message.session_id` (Data) + rows; `routing/resolve.py:44` | **frappe-adapted** | 1 |
| `session.py` `build_session_key` (`session.py:600`) | Structured key `agent:main:{platform}:{chat_type}:{chat_id}` | `session_id` = Raven channel id / CLI uuid (flat) | **simplified** — no per-user/thread isolation key (single-tenant: fine today) | 1 |
| `session.py` reset policy / `suspend`/`resume` (`:973`,`:988`) | idle/daily auto-reset, crash-resume | **none** — sessions never auto-reset; compaction handles length | **simplified** (deliberate — DB rows don't need session rotation) | 1 |
| `session_context.py` (179) | `ContextVar` session vars (concurrent-safe) | Frappe `frappe.local` per-request + separate worker procs | **frappe-adapted** (process isolation replaces ContextVar) | 1 |
| `stream_consumer.py` (1318) | Progressive token streaming → edit one msg | **none** — Friday writes ONE finished outbound row | **MISSING** (Raven supports edits; low priority — see note) | 2 |
| `config.py` (1920) | Gateway/platform config loading | `Chat Platform` doctype + `config_json` + `bootstrap_raven.py` | **frappe-adapted** | 1 |
| `delivery.py` (372) | Multi-target delivery DSL (`platform:chat:thread`), 4k truncation, local sink | **ported (Design 86)** — `gateway/delivery.py`: DSL + router; platform→outbound `Chat Message` row, local→private File, 4k truncation | **ported** (free targeting incl.; thread ignored) | 1 |
| `platform_registry.py` (260) | Code-side plugin self-registration of adapters | `Connector` / `Chat Platform` doctypes (data-driven, design 81) | **frappe-adapted** — but `standalone_sender_fn` (out-of-process send) pattern still relevant for worker delivery | 1 |
| `platforms/base.py` `MessageEvent`/`SendResult` (4241) | Normalized inbound/outbound contract | the `Chat Message` row IS the normalized contract | **frappe-adapted**; `validate_media_delivery_path` (`base.py:972`) is security-critical to port if Friday adds file delivery | 1 |
| `hooks.py` `HookRegistry` (210) | Agent-lifecycle hooks (agent:start/step/end, command:*) | **none** — Frappe `doc_events` are DocType lifecycle, not agent lifecycle | **MISSING** (extension point) | 2 |
| `mirror.py` (168) | Write outbound-sent msg into the right session transcript | partial — `share-deliverables` skill writes rows, but no generic mirror w/ session disambiguation | **MISSING** (mostly) | 2 |
| `slash_access.py` (229) | Two-axis perms: may-talk vs may-run-commands | **none** — no command tier (and no commands yet) | **MISSING** (blocked on slash dispatch) | 2 |
| `runtime_footer.py` (150) | `model · context% · cwd` footer on final msg | **none** | **MISSING** (low priority, transparency) | 2 |
| `display_config.py` (240) | Per-surface display tiers (streaming on/off, tool progress) | **none** — all surfaces treated identically | **MISSING** (matters when 2nd surface lands) | 2 |
| `pairing.py` (450) | DM code-pairing to authorize new users | Frappe user auth + Raven channel membership / @mention gate (`raven_adapter.py:46`) | **irrelevant** — DB-authenticated users, no pairing needed | 3 |
| `channel_directory.py` (357) | Discovery cache: name → chat_id per platform | `Raven Channel` rows; resolve via `frappe.get_value` | **irrelevant** — the DB *is* the directory | 3 |
| `whatsapp_identity.py` (155) | Canonical WhatsApp JID/LID alias resolution | n/a until a WhatsApp adapter exists | **irrelevant** (platform-specific) | 3 |
| `sticker_cache.py` (124) | Telegram sticker description cache | n/a until a Telegram adapter exists | **irrelevant** (platform-specific) | 3 |
| `status.py` (971) | PID-file + flock single-instance liveness | honcho / `systemd --user` / `bench` | **infra-only** | 4 |
| `restart.py` (20) | Exit-75 graceful-restart drain protocol | systemd `Restart=` | **infra-only** | 4 |
| `shutdown_forensics.py` (462) | SIGTERM post-mortem snapshot | infra layer | **infra-only** (the `check_systemd_timing_alignment` idea could help deploy tooling) | 4 |
| `memory_monitor.py` (230) | RSS/GC/thread daemon logger | Frappe infra / Prometheus | **infra-only** | 4 |

### What this means — the real gateway gap list

Stripping out buckets 3 and 4 (correctly absent) and bucket 1 (done), the
**true gateway gaps**, ranked for a single-tenant Raven-first deployment:

**Tier A — session-manager completion (the headline gap)**
1. ~~**INTERRUPT**~~ — **SHIPPED 2026-06-24 (Design 83).** Cooperative Redis
   flag `friday:interrupt:{session_id}`, set by the operator-tier `/stop`
   command, checked at each ReAct boundary in `run_turn` (`runner.py`), cleared
   at entry (session lock makes a generation counter unnecessary). Boundary-
   granular (Friday's blocking LLM call can't be aborted mid-flight) — disclosed
   divergence from Hermes' 0.3s poll. **Subagent cascade SHIPPED (Design 85):**
   `/stop` now stops the whole active delegated subtree (roots via
   `Task.originating_session`, descendants via `parent_task`) — `run_turn` raises
   `TurnInterrupted` so an interrupted child is marked Cancelled, not Completed.
   **Hard kill SHIPPED (Design 83b):** `/stop force` SIGTERMs the in-flight RQ
   job(s) via `send_stop_job_command` (chat turn via `Chat Message.job_id` +
   cascade subtree), marks delegated Tasks `ForceKilled` with audit fields;
   reconciler auto-heal left untouched (operator-initiated only). See
   `docs/design/83`, `docs/design/85`.
2. ~~**STEER**~~ — **SHIPPED 2026-06-24 (Design 84).** `/steer <text>` pushes a
   coalescing Redis slot `friday:steer:{session_id}`, drained at each ReAct
   boundary and appended to the last tool result as "User guidance: {text}"
   (Hermes-faithful framing, `conversation_loop.py:754`); clear-at-entry; a
   missed steer is dropped (disclosed divergence from Hermes' `pending_steer`).
   See `docs/design/84`. **The three-mode session manager is now complete**
   (queue ✅80, interrupt ✅83, steer ✅84). _Resolved fork: Friday chose
   queue-by-default — interrupt/steer are opt-in `/stop` `/steer` commands, never
   the default reaction to a second message._

**Tier B — the command surface (unlocks A)**
3. **Slash-command dispatch** — there is *no* command parser on any inbound path
   today. INTERRUPT/STEER, `/approve`/`/deny` (the approval gate already exists
   in `agent_runner/dispatcher.py` but can't be driven from chat), and `/status`
   all need this. Port target: a parse step in the surface adapters (or in
   `handle_inbound`) that peels `/cmd …` before the row reaches `run_turn`.
4. **`slash_access.py` two-axis perms** — may-talk vs may-run-commands. Blocked
   on #3; Frappe roles are the natural substrate. Build with #3.

**Tier C — delivery & extensibility (needed as surfaces/cron grow)**
5. ~~**`delivery.py` multi-target + truncation**~~ — **SHIPPED (Design 86).**
   `gateway/delivery.py`: the `DeliveryTarget` DSL (`origin`/`local`/
   `platform:chat[:thread]`) + `DeliveryRouter.deliver()`. Platform delivery =
   an outbound `Chat Message` row (Frappe adaptation of `adapter.send`); `local`
   sink = a private Frappe File; 4k truncation with full output saved to a File.
   Full faithful port incl. free targeting — governance lives at the skill layer,
   not the router (user-accepted divergence). Ships ahead of its first consumer
   (cron, gap #7). `thread_id` parsed but ignored on Raven. See `docs/design/86`.
6. **`hooks.py` lifecycle HookRegistry** — agent:start/step/end extension point.
   No equivalent; Frappe signals could back it. Low urgency until plugins want
   to hook the agent loop.
7. **`mirror.py` transcript mirroring** — when an agent posts outside its own
   turn (cron, `share-deliverables`), write that into the session transcript so
   context stays complete. Partly covered ad-hoc; needs the disambiguation logic.

**Tier D — polish (defer)**
8. **`stream_consumer.py` progressive streaming** — Raven *can* edit messages,
   so token-streaming is portable, but Friday's "one finished row" is fine for
   now. Defer unless live-typing UX is wanted.
9. **`runtime_footer.py`** + **`display_config.py`** — transparency footer +
   per-surface display tiers. Build `display_config` when the **second** surface
   (Slack/Telegram) lands; until then there's nothing to tier.

### Recommended gateway build order

1. ~~**Slash dispatch (#3)**~~ — **SHIPPED (Design 82).** Prerequisite for the
   rest; `gateway/commands.py` + the operator-role gate.
2. ~~**INTERRUPT (#1)**~~ — **SHIPPED (Design 83).** `/stop` + the Redis flag.
3. **slash_access (#4)** — partly covered: commands already gate on the
   `Friday Operator` role (Design 82, Q4). The DM-vs-group scope split is the
   remaining piece.
4. ~~**STEER (#2)**~~ — **SHIPPED (Design 84).** The session manager is complete.
5. **delivery DSL (#5)** — sequence with the Cron-jobs port (row #7); they share
   the home-channel delivery target.
6. Defer C-hooks / mirror / streaming / footer / display tiers until a concrete
   driver (a plugin, a 2nd surface, a cron job) makes each pay for itself.

### Divergences confirmed correct (do NOT port)

`pairing.py`, `channel_directory.py`, `whatsapp_identity.py`, `sticker_cache.py`
(buckets 3) and `status.py`, `restart.py`, `shutdown_forensics.py`,
`memory_monitor.py` (bucket 4) are **deliberately absent**. They solve problems
that the Frappe/Raven substrate (DB-authenticated users, Raven Channel rows,
honcho/systemd process management) already solves. Porting them would be
re-introducing a daemon's accidental complexity into a row-based system. This is
the unified-gateway divergence (`feedback_unified-gateway-service`) working as
intended.

---

## How this ledger is maintained

Each row's claim is cited to `file:line` on both sides. When a gap is ported,
move it from the backlog to "faithful ports," record the Hermes source it was
ported from, and classify any divergence forced by Frappe. Re-audit when Hermes
ships major changes (the "Hermes delta review").
