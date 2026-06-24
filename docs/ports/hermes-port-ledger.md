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
| 5 | Gateway | diverged (by design) | **interrupt / steer / queue session manager** |
| 6 | Memory (3 forms) | 1 form adapted, 2 **MISSING** | **external providers (Mem0/etc.)**; **session_search + full-text** |
| 7 | Cron jobs | **MISSING** (infra-only scheduler) | user-schedulable recurring agent jobs + home-channel delivery |

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
5. **Interrupt / steer / queue session manager.** Hermes: `gateway/run.py:3135–3315`
   (three modes + `/steer` `/queue` + subagent-aware demotion). Friday: a new
   message on a busy session just gets `"session is busy"` (`gateway/service.py:244`).
   Port queue-mode first (prevents message loss), then interrupt (cancel the RQ
   job — `job_id` already on the row, `service.py:118`), steer last. Effort:
   queue ~0.5d, interrupt ~1d, steer ~2d.
6. **On-error compression + retry.** The `should_compress` flag is computed
   (`llm/error_classifier.py:47`) but the runner never catches `LLMError` to act
   on it. Port = a `try/except LLMError` in the loop that compresses + retries
   once. Effort: small.
7. **Cron jobs (user-scheduled agent runs).** Hermes: `cron/jobs.py`,
   `cron/scheduler.py`, `tools/cronjob_tools.py`. Friday's `*/1` ticks are
   infra-only (`tasks/dispatcher.py`, `tasks/reconciler.py`). Port = `Cron Job`
   doctype + a scheduler tick + home-channel delivery + a cron skill. Effort:
   ~3 days.

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

## How this ledger is maintained

Each row's claim is cited to `file:line` on both sides. When a gap is ported,
move it from the backlog to "faithful ports," record the Hermes source it was
ported from, and classify any divergence forced by Frappe. Re-audit when Hermes
ships major changes (the "Hermes delta review").
