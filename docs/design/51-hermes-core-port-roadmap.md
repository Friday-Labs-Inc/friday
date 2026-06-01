# 51 — Hermes-Core → Friday Porting Roadmap (master plan)

> **What this doc is.** The single, ordered plan for porting **every Hermes-core
> capability** into Friday. It is the *master sequence* — it does not re-derive the
> individual contracts. For the locked details it points at:
> - [doc 48 — Hermes-port decisions](48-hermes-port-decisions.md) — Feature A (ReAct loop) is locked there; B1/B2/C/D/F were left as DRAFT and are **locked below in §4**.
> - [doc 49 — foundations deviation audit](49-foundations-deviation-audit.md) — the 14 findings (C1, C2, H1–H3, M1–M5, L1–L4) that describe where today's code is broken or missing.
> - [doc 50 — C1 task-route design lock](50-c1-task-route-design-lock.md) — the locked fix for the dead async task route.
>
> **Authority.** [doc 42 — Phase One Authority Contract](42-phase-one-authority-contract.md)
> still wins on every scope conflict. This roadmap sequences *how* we reach doc 42's
> v0.1, plus the Hermes features doc 42 leaves room for. Verified against `main @ 0f2cdd9`
> and the working tree on branch `audit/foundations-deviation`.

---

## 0. Why this doc exists, and the workflow it runs under

**The workflow changed on 2026-05-30.** The Roo Code hand-off loop is discontinued.
**This Claude now writes the production code and the refactoring directly** — `.py`,
DocType JSON, tests, and rollout docs — to port Hermes-core's features into Friday.
The user reviews the diff and merges.

Because there is no longer a separate implementer to catch my gaps, the cheap path is to
**lock the whole port order before writing any code**, so the user approves the roadmap
once instead of re-litigating priorities slice by slice. That is what this document is for.

The engineering discipline is unchanged: design-lock-first, tests-first (80%+), a Hermes
comparison for every divergence, two-layer high-school-readable docs, and the single-tenant
lens (reject "at SaaS scale…" framings).

**How to read this doc:**
- **§1** inventories every Hermes-core capability we are porting or explicitly deferring.
- **§2** is the parity matrix — each capability vs. Friday's current state.
- **§3** is the dependency-ordered slice plan (the actual build order).
- **§4** locks the design Q's for the five un-locked features (B1, B2, C, D, F) — this
  completes the DRAFT sections of doc 48.
- **§5** surfaces the handful of real forks that need the user's sign-off at approval time.
- **§6** lists what v0.1 deliberately will *not* do.

---

## 1. Hermes-core capability inventory

Grouped by concern. "Hermes ref" cites the file in the reference clone
(`~/Documents/reference/hermes-agent/`) that is the source of truth for that capability.

### 1.1 The agent loop (the thing that makes it an *agent*)

| # | Capability | Hermes ref |
|---|---|---|
| 1 | **ReAct loop** — think → act → observe, repeat until the model stops calling tools or a budget is hit | `run_agent.py::run_conversation`, `agent/conversation_loop.py` |
| 2 | **Sequential tool dispatch** with results fed back as `{role:"tool", …}` messages | `agent/tool_executor.py`, `agent/chat_completion_helpers.py` |
| 3 | **Within-turn tool-call de-duplication** — drop identical `(name, arguments)` calls before dispatch | `run_agent.py:2472 _deduplicate_tool_calls` |
| 4 | **Deterministic tool-call IDs** — stable IDs so prompt caches don't invalidate | `run_agent.py:2500 _deterministic_call_id` |
| 5 | **Iteration budget** — cap the number of think/act cycles per turn | `agent/iteration_budget.py` |

### 1.2 Provider adapters (which LLM, and how we talk to it)

| # | Capability | Hermes ref |
|---|---|---|
| 6 | **Declarative provider profile** — name, transport mode, base_url, auth type, fallback models, fixed temperature | `providers/base.py::ProviderProfile` |
| 7 | **OpenAI-compatible (`chat_completions`) transport** — the default path | `agent/chat_completion_helpers.py` (OpenAI is the default; no separate adapter file) |
| 8 | **Anthropic Messages adapter** — `tool_use`/`tool_result` block translation | `agent/anthropic_adapter.py` |
| 9 | Other native adapters (Bedrock, Gemini, Codex Responses) | `agent/{bedrock,gemini_native,codex_responses}_adapter.py` — **out of v0.1 scope** |

### 1.3 Resilience (surviving a flaky API)

| # | Capability | Hermes ref |
|---|---|---|
| 10 | **Error classification** — a taxonomy (`FailoverReason`) + a priority-ordered classifier that returns recovery hints (retryable / compress / rotate credential / fallback) | `agent/error_classifier.py` |
| 11 | **Retry with backoff** on transient errors (429/5xx/timeout) | `agent/retry_utils.py`, `agent/rate_limit_tracker.py` |
| 12 | **Provider fallback chain** — on unrecoverable error, try the next provider | scattered in `run_agent.py` — **deferred (Feature G)** |
| 13 | **Credential pool rotation** — rotate API keys on auth/billing failure | `run_agent.py` — **deferred** (no key pool in v0.1) |

### 1.4 Context management (long conversations)

| # | Capability | Hermes ref |
|---|---|---|
| 14 | **History compression** — an auxiliary (cheap) model summarises the *middle* of the conversation; head + recent tail are protected | `agent/context_compressor.py::ContextCompressor` |
| 15 | **Compression orchestration** — feasibility probe at start, the compress call, session rotation | `agent/conversation_compression.py` |
| 16 | **"Reference only" summary preamble** — stops the model re-answering compacted questions | `agent/context_compressor.py` (`SUMMARY_PREFIX`) |
| 17 | Trajectory/sub-agent compression | root `trajectory_compressor.py` — **out of v0.1 scope** (no sub-agents yet) |

### 1.5 Governance & sandbox (Friday's reason to exist)

These are not "Hermes features" — Hermes has weaker governance. They are Friday's
**foundation findings** from doc 49, ported/fixed here so the governed loop is real.

| # | Capability | Friday source of truth |
|---|---|---|
| 18 | **Permission pre-check on every execution path** (deny-by-default + immutable log) | doc 04 Layer 2, doc 42 §3; finding C1 (task path skips it) |
| 19 | **Async task execution route** (claimed → actually runs) | doc 42 §7; finding C1; locked in **doc 50** |
| 20 | **Approval workflow** — `requires_approval` → Workflow Request → pause/resume | doc 04 Layer 6, doc 42 §3; finding H2 |
| 21 | **Scoped-credential token** — one generator, validated at the REST boundary | doc 04 Layer 4; finding H3 |
| 22 | **Mandatory Docker sandbox** + egress allowlist + read-only rootfs | doc 04 Layer 3, doc 42 §5; findings C2, L3 |
| 23 | **Per-profile resource quotas** (CPU/mem/timeout) | doc 04 quotas; finding M2 |

---

## 2. Parity matrix — Hermes capability vs. Friday today

Legend: ✅ ported & working · ⚠️ present but broken/partial · ❌ missing · ➖ deferred (not v0.1).

| Capability | Friday current state | doc 49 finding | Locked where | Slice |
|---|---|---|---|---|
| ReAct loop (#1) | ⚠️ **single-dispatch** — `runner.py::run_turn` calls the LLM once, dispatches the *first* tool call, returns. No observe→re-prompt. (lines 91-92: "single-dispatch; multi-step loop is Slice 8") | **H1** | doc 48 §1 (locked) | **S3** |
| Sequential dispatch + tool-result feedback (#2) | ❌ no feedback loop (consequence of H1) | H1 | doc 48 §1 | S3 |
| Within-turn dedup (#3) | ❌ missing | — | **§4 (D)** | S5 |
| Deterministic call IDs (#4) | ❌ missing | — | §4 (D) | S5 |
| Provider abstraction (#6) | ✅ `LLMProvider` ABC + `get_provider_for_profile()` (Slice 5) | — | n/a (built) | — |
| OpenAI-compat transport (#7) | ⚠️ **partial** — `MinimaxProvider` already speaks OpenAI `chat_completions`; no generic OpenAI adapter | — | **§4 (B1)** | S6 |
| Anthropic adapter (#8) | ❌ missing | — | **§4 (B2)** | S7 |
| Error classification (#10) | ⚠️ **inline only** — `MinimaxProvider.chat` hard-codes 429/5xx/timeout retry; no taxonomy, no reuse | — | **§4 (F)** | S4 |
| Retry/backoff (#11) | ✅ inline in `MinimaxProvider` (3× exponential) — to be lifted into F | — | §4 (F) | S4 |
| Provider fallback (#12) | ➖ deferred (Feature G) | — | doc 48 deferrals | — |
| Credential rotation (#13) | ➖ deferred (no key pool in v0.1) | — | — | — |
| History compression (#14–16) | ❌ missing entirely | — | **§4 (C)** | S8 |
| Permission pre-check, chat path (#18) | ✅ `dispatcher.dispatch` runs `matrix.check` + writes Permission Decision Log | — | doc 04 Layer 2 | — |
| Permission pre-check, task path (#18) | ⚠️ **CRITICAL** — task route is dead, so it never reaches the check | **C1** | doc 50 (locked) | **S2** |
| Async task route (#19) | ⚠️ dead — `publish_realtime` to a topic nobody subscribes to | C1 | doc 50 | S2 |
| Handler registry (prereq for C1) | ⚠️ handler under test name `slice6-create-note`; two registries | **M3** | doc 50 §6 | **S1** |
| Task/ chat signature agreement | ⚠️ task path passes `api_key=` to a function with no such param (latent `TypeError`, masked by C1) | **M4** | dissolved by C1 (doc 50) | S2 |
| Task dispatcher field read | ⚠️ reads `profile.agent_role_profile` (does not exist) → latent `AttributeError` | **M5** | dissolved by C1 (doc 50) | S2 |
| Approval workflow (#20) | ⚠️ flag exists, nothing enforces it; Workflow Request DocType not built | **H2** | this doc §3 (S10) | S10 |
| Scoped-credential token (#21) | ⚠️ stub nobody validates; two generators | **H3** | this doc §3 (S9) | S9 |
| Mandatory Docker (#22) | ⚠️ advisory — silent in-process fallback if Docker absent | **C2** | this doc §3 (S12) | S12 |
| Egress allowlist / mount (#22) | ⚠️ logically inverted; host-fs bind-mount | **L3** | this doc §3 (S12) | S12 |
| Resource quotas (#23) | ⚠️ reads a field that doesn't exist → always defaults | **M2** | this doc §3 (S11) | S11 |
| Stale docs 04 + 05 | ✅ **fixed this session** (commit `2fe9ec1`) | **M1** | done | S0 ✅ |
| Rollout docs for Slices 6–9 + War Room | ❌ missing | **L1** | this doc §3 (S13) | S13 |
| Dead `after_migrate` wiring | ⚠️ no-op handler re-registered every migrate | **L2** | this doc §3 (S13) | S13 |
| Execution Log field drift | ⚠️ `duration_ms` in result JSON, not its column | **L4** | this doc §3 (S13) | S13 |

**Reading the matrix:** the agent is currently a **one-shot tool caller** (H1), the
governed task route is **dead** (C1), and the resilience/context features Hermes relies on
(F, C) **don't exist yet**. Everything else is either built (provider abstraction, chat-path
governance) or a known foundation gap with a finding ID.

---

## 3. The sequenced slice plan (build order)

Ordering rule, in priority order: **(1) unblock the CRITICAL** (C1), **(2) deliver the
headline agent value** (ReAct loop), **(3) make it resilient** (F, D), **(4) widen provider
choice** (B1, B2), **(5) handle long conversations** (C), **(6) close the remaining HIGH
security gaps and clean up** (H3, H2, M2, C2/L3, L*). Within that, respect hard dependencies
and do the already-locked, well-understood slices first.

> **User-prioritised insert (2026-06-01):** the **Project / Issue Tracker port** — slice
> **S2.5**, design locked in [doc 53](53-project-issue-tracker-port.md) — is sequenced right
> after the task-route foundation (S2). It is the *operating model* agents work inside (generic
> `Project`/`Task`/`Issue` + Frappe `ToDo`; an agent is just one stakeholder `User`) and the one
> sanctioned ERPNext port (port the design, don't depend on ERPNext). Being a different subsystem
> from the LLM features, it can also run **in parallel** with S3–S8. Full build order: doc 53 §10.

> **The ordering of the security-foundation block (S9–S12) vs. the feature block (S3–S8)
> is the one real fork — see §5 Fork 1.** The sequence below is my recommendation; the user
> may want HIGH security items pulled ahead of features.

| Slice | What | Why now | Severity | Depends on | Done = (verify) | Locked in |
|---|---|---|---|---|---|---|
| **S0** | M1 — reconcile stale docs 04 + 05 | root cause of drift | MED | — | ✅ committed `2fe9ec1` | — |
| **S1** | M3 — converge skill handler to `create_note`, single registry | hard prereq for C1 | MED | — | one registry; handler name is `create_note`; `grep slice6-create-note` → 0 hits; existing skill tests pass | doc 50 §6 |
| **S2** | **C1** — route async tasks through `dispatch` via RQ | dead CRITICAL path | **CRIT** | S1 | task enqueues to `long` queue; runs `matrix.check`; writes Execution + Permission Decision logs; M4/M5 gone (`grep api_key=`, `agent_role_profile` → 0 hits); new task-route tests assert *execution + enforcement* | doc 50 |
| **S2.5** | **Project/Issue Tracker port** — generic `Project`/`Task`/`Issue` (+ Frappe `ToDo`); rename `Agent Project/Task`→`Project/Task`; assignee→`User`; add `Issue` + `depends_on` | the operating model agents work *inside*; **user-prioritised** | HIGH | S2 (rename Task after its route is stable) | `Project`/`Task`/`Issue` exist; `assigned_to` is a `User`; Blocked/OOM/timeout auto-raises a `Failure` Issue; unfinished `depends_on` auto-raises `Dependency-Wait` + parks task; tracker tests pass | **doc 53** |
| **S3** | **A** — ReAct loop in `runner.run_turn` | headline agent feature | HIGH (H1) | S2 (shared dispatch path stable) | `run_turn` loops ≤15 iterations; tool errors fed back; permission denial breaks loop; one inbound + one outbound Chat Message per turn; the 9 tests in `tests/test_react_loop.py` pass | doc 48 §1 |
| **S4** | **F** — error classifier (`llm/error_classifier.py`) | A's error feedback + B's retry both consume it | MED | — (pairs with S3) | trimmed `FailoverReason` enum + `classify_api_error`; `MinimaxProvider` retry uses it; classifier unit tests per reason | **§4 (F)** |
| **S5** | **D** — within-turn dedup + deterministic IDs | small; slots into A's loop | LOW | S3 | duplicate `(name,args)` calls dropped before dispatch; IDs stable across re-serialisation; dedup tests | **§4 (D)** |
| **S6** | **B1** — OpenAI adapter | low-risk (Minimax already OpenAI-compat); most common provider | MED | S4 | `OpenAIProvider(LLMProvider)` returns canonical `LLMResponse`; selectable via `LLM Provider` row; round-trips a tool call; adapter tests | **§4 (B1)** |
| **S7** | **B2** — Anthropic adapter | the other dominant API; A expects `tool_result` normalisation | MED | S4, S6 | `AnthropicProvider` translates messages ↔ Anthropic blocks; tool_use/tool_result normalised to canonical; adapter tests | **§4 (B2)** |
| **S8** | **C** — history compression | long-conversation support; biggest feature, lowest v0.1 urgency | MED | S6 (aux provider), S4 | over-threshold history summarised by aux model; head+tail protected; "reference-only" preamble; compaction is auditable; compression tests | **§4 (C)** |
| **S9** | H3 — one scoped-credential token generator, validated at REST boundary | HIGH security correctness | HIGH | — | one generator; REST boundary validates; `grep` finds no second generator; token round-trip + reject tests | this doc §3 |
| **S10** | H2 — approval → Workflow Request (DocType + matrix branch + pause/resume) | HIGH; gate before any `requires_approval` skill activates | HIGH | S2 (dispatch path) | Workflow Request DocType exists; matrix creates one when `requires_approval`; execution pauses; approve/reject resumes; approval-flow tests | this doc §3 |
| **S11** | M2 — add `resource_quota` field, wire to sandbox | MED; quotas currently un-settable | MED | — | field on Agent Profile; sandbox reads it; per-profile cap honoured; quota test | this doc §3 |
| **S12** | C2 + L3 — make Docker mandatory; fix inverted egress allowlist + drop host-fs mount | HIGH/LOW; **Phase 1.5 hardening — accepted for v0.1** while skills are first-party | HIGH/LOW | — | Docker absence is a hard reject (configurable); egress map correct; no host bind-mount; sandbox tests | this doc §3; memory [[v01-skills-first-party-trust]] |
| **S13** | L1/L2/L4 — rollout docs for Slices 6–9 + War Room; remove dead `after_migrate`; fix Execution Log `duration_ms` column | LOW cleanup | LOW | — | rollout docs committed; dead handler removed; `duration_ms` in its column; logging test | this doc §3 |

**Dependency graph (the edges that actually constrain order):**
- `S1 (M3) → S2 (C1)` — doc 50 makes M3 a hard prerequisite.
- `S2 (C1)` dissolves M4 + M5 (same diff).
- `S3 (A) → S5 (D)` — dedup lives inside the loop.
- `S4 (F) → S6 (B1), S7 (B2)` — adapters use the classifier for retry.
- `S6 (B1) → S7 (B2)` — share an OpenAI-compatible base before adding the Anthropic shape.
- `S6 (B1) → S8 (C)` — compression needs a working aux provider.
- `S2 (C1) → S10 (H2)` — approval hangs off the stable dispatch path.
- `S2 (C1) → S2.5 (tracker)` — rename `Task` only after its route is stable; the tracker then runs parallel to S3–S8 (different subsystem). Design: doc 53.

Everything else (S9, S11, S12, S13) is independent and can move earlier if the user
re-prioritises (see §5 Fork 1).

---

## 4. Design locks for the un-locked features (completes doc 48 §§2–6)

Each feature below gives the **Hermes comparison**, my **recommended lock**, and any
**flagged fork** that needs sign-off. Where I write "LOCK", that is my recommendation pending
the user's approval of this roadmap; genuine forks are pulled up into §5.

### 4.B1 — OpenAI provider adapter (doc 48 §2)

**Hermes:** OpenAI is the *default* transport — `chat_completions` shape, no dedicated
adapter file; provider specifics live in the declarative `ProviderProfile` (`providers/base.py`).

**Friday today:** `MinimaxProvider` *already* speaks OpenAI `chat_completions` (it posts the
OpenAI message/tool shape and parses an OpenAI-style response). So B1 is mostly *generalising
what exists*, not new protocol work.

- **B1.1 — Shape.** LOCK: extract the shared OpenAI-compatible request/response logic into a
  base (`_OpenAICompatibleProvider`) and make both `OpenAIProvider` and `MinimaxProvider`
  thin subclasses that differ only in default base_url / endpoint path / auth header. Rationale:
  kills duplication, matches Hermes's "one transport, many profiles" model.
- **B1.2 — Endpoint.** LOCK: `OpenAIProvider` → `https://api.openai.com/v1/chat/completions`,
  `Authorization: Bearer`. Overridable via the `LLM Provider` row's `base_url` (so Azure/OpenRouter
  work without code).
- **B1.3 — Return contract.** LOCK: return the existing `LLMResponse` TypedDict unchanged
  (`content`, `finish_reason`, `usage`, `tool_calls`). The runner stays provider-agnostic.
- **B1.4 — Retry.** LOCK: delegate to Feature F (S4) once it lands; until then reuse the
  inline 429/5xx/timeout backoff. (This is why F precedes B in the sequence.)
- **Tests:** plain-text round-trip; tool-call round-trip; 401 → `LLMAuthError`; 429 → retry.

### 4.B2 — Anthropic provider adapter (doc 48 §3)

**Hermes:** `agent/anthropic_adapter.py` — translates to/from the Messages API (`/v1/messages`,
`x-api-key` + `anthropic-version` headers, `system` as a top-level param, tool calls as
`tool_use` / `tool_result` content blocks).

**Friday today:** none. Doc 48 §1 already commits the runner to the OpenAI-canonical tool
shape and says *"provider adapters normalise Anthropic's `tool_result` block format into this
shape before the runner sees it."* B2 is where that normalisation gets written.

- **B2.1 — Request translation.** LOCK: map canonical messages → Anthropic: hoist the
  `system` message to the top-level `system` param; convert assistant `tool_calls` →
  `tool_use` blocks; convert `{role:"tool"}` messages → `tool_result` blocks.
- **B2.2 — Response translation.** LOCK: map Anthropic `content` blocks → `LLMResponse`:
  text blocks → `content`; `tool_use` blocks → `tool_calls` in OpenAI shape (`{id, name,
  arguments-as-JSON-string}`). This is the normalisation the runner depends on.
- **B2.3 — Headers/version.** LOCK: `anthropic-version` pinned as a module constant; key from
  the `LLM Provider` row (`Password` field), same as Minimax.
- **B2.4 — Out of scope for B2:** prompt caching, extended thinking, the 1M-context beta,
  vision. (Hermes has all four; none are v0.1.)
- **Tests:** system-hoist correctness; tool_use → canonical tool_calls; `{role:"tool"}` →
  tool_result; a full chat↔tool↔chat round-trip through the runner on a mocked Anthropic API.

### 4.C — Conversation history compression (doc 48 §4)

**Hermes:** an auxiliary (cheap) model summarises the **middle** of the conversation while
**head** (system prompt / first turn) and **tail** (recent turns, token-budgeted) are
protected; the summary carries a "REFERENCE ONLY" preamble so the model doesn't re-answer
compacted questions; failures have a cooldown; tool outputs are pruned in a cheap pre-pass
(`agent/context_compressor.py` + `agent/conversation_compression.py`).

**Friday today:** none — and a structural difference: Friday's history is **Chat Message
DocType rows keyed by `session_id`**, not Hermes's in-process SQLite session. So "rotate the
session" becomes a DocType operation.

- **C.1 — Trigger.** LOCK: compress when the estimated token count of the assembled prompt
  (computed in `prompt_builder`) exceeds a fraction of the model's context window
  (start at 0.6, a module constant). Cheap char/4 estimate, matching Hermes.
- **C.2 — Strategy.** LOCK: protect head (system prompt) + tail (most recent N turns by token
  budget); summarise the middle via the profile's aux model; prepend the "reference-only"
  preamble (port `SUMMARY_PREFIX` near-verbatim — it's load-bearing safety text).
- **C.3 — Storage (the fork → §5 Fork 3).** RECOMMEND: persist a **`Compaction Summary`
  DocType row** (session_id, summary text, the range of Chat Messages it replaces, created-at)
  and mark the superseded Chat Messages with a `compacted = 1` flag; `prompt_builder` then
  assembles `[system] + [latest summary] + [uncompacted tail]`. Rationale: durable, auditable,
  and consistent with Friday's "every meaningful event is a DocType row" principle — superior
  to Hermes's ephemeral session rotation for a governed system.
- **C.4 — Aux model.** LOCK: reuse `get_provider_for_profile` with an optional
  `Agent Settings.compression_model` override; if no aux model resolves, **skip with a logged
  warning** (do *not* silently drop turns) — mirrors Hermes's feasibility-probe warning.
- **Tests:** trigger fires only over threshold; head+tail preserved; summary row created +
  messages flagged; prompt_builder uses the summary; no-aux-model → warn-and-skip.

### 4.D — Within-turn tool-call de-duplication + deterministic IDs (doc 48 §5)

**Hermes:** `_deduplicate_tool_calls` (run_agent.py:2472) keeps only the first of each unique
`(name, arguments)` pair within one turn; `_deterministic_call_id` (2500) derives a stable id
from tool content so prompt caches don't invalidate.

**Friday today:** none. Note doc 48 titled this "per-tool idempotency" — but Hermes-core's
actual mechanism is *within-turn dedup*, **not** a cross-turn idempotency key. We match Hermes:
no persistent idempotency store in v0.1.

- **D.1 — Dedup.** LOCK: in the ReAct loop (S3), before dispatching a turn's tool calls, drop
  any whose `(name, arguments)` exactly matches an earlier call **in the same turn**; keep the
  first; log each drop. Port `_deduplicate_tool_calls` semantics verbatim.
- **D.2 — Deterministic IDs.** LOCK: when the provider response omits a tool-call id, derive
  one deterministically from `(name, arguments, index)` so identical calls don't get random
  ids. Port `_deterministic_call_id`.
- **D.3 — Scope.** LOCK: within-turn only. Cross-turn idempotency (re-running the same skill
  in a later turn) is **explicitly deferred** — it needs a persistence design we don't need yet.
- **Tests:** two identical calls in one turn → one dispatch; different args → both dispatch;
  missing id → deterministic id; same content → same id across re-serialisation.

### 4.F — LLM error classification (doc 48 §6)

**Hermes:** `agent/error_classifier.py` — a large `FailoverReason` enum + a priority-ordered
`classify_api_error()` returning a `ClassifiedError` with recovery hints (`retryable`,
`should_compress`, `should_rotate_credential`, `should_fallback`). It carries deep
provider-specific exotica (Anthropic thinking-signature, llama.cpp grammar, OpenRouter policy
blocks, multimodal tool content, SSL-alert disambiguation).

**Friday today:** inline only — `MinimaxProvider.chat` hard-codes 429/5xx/timeout handling.
Feature F centralises this so every adapter and the loop share one classifier.

- **F.1 — Taxonomy (trimmed).** LOCK: port a v0.1-relevant subset of `FailoverReason`:
  `auth`, `billing`, `rate_limit`, `overloaded`, `server_error`, `timeout`,
  `context_overflow`, `model_not_found`, `format_error`, `unknown`. **Drop** the
  provider-exotica reasons until the providers/scenarios that need them exist (add them with
  their provider).
- **F.2 — Result + hints.** LOCK: port `ClassifiedError(reason, status_code, retryable,
  should_compress, should_fallback, message)`. **Omit `should_rotate_credential`** (no key
  pool in v0.1).
- **F.3 — v0.1 hint semantics.** LOCK: `retryable` → the provider's backoff loop retries;
  `should_compress` → surfaced to the loop, which (once Feature C lands) triggers compression,
  else feeds the error back; `should_fallback` → **no provider chain in v0.1 (Feature G
  deferred), so it maps to "surface a clean error to the user"**, not silent failover.
- **F.4 — Wiring.** LOCK: `classify_api_error` lives in `llm/error_classifier.py`;
  `MinimaxProvider` (and B1/B2) call it instead of inline status-code checks; the ReAct loop
  uses it to decide feed-back-vs-abort on an LLM error.
- **Tests:** one unit test per `FailoverReason` mapping (status code + message → reason +
  hints); the previously-inline Minimax 429/5xx/timeout cases now route through the classifier.

---

## 5. Open decisions for the user (the real forks)

These are the choices where reasonable engineers would disagree. Everything else above is a
recommended lock I'll proceed with on approval. **Please decide these at review time.**

**Fork 1 — Sequence: features-first or security-first?**
My recommendation runs the feature block (S3–S8: ReAct loop, resilience, providers,
compression) *before* the remaining HIGH security items (S9 H3, S10 H2). Rationale: H2 and H3
are HIGH *by spec* but not *active holes on the chat path* in v0.1 — no skill carries
`requires_approval` yet (H2), and H3 is a defence-in-depth correctness issue at the REST
boundary, not an open door. C1 (the one CRITICAL with an *active* enforcement hole) is already
pulled to the front as S2. **Alternative:** pull H3 + H2 ahead of the features if you want
every HIGH closed before adding capability. (C1 stays first either way.)

**Fork 2 — Which providers does v0.1 actually need?**
I've planned B1 (OpenAI) **and** B2 (Anthropic). If the customer only uses one LLM, we can
drop or defer the other and save a slice. Minimax already works regardless. **Which providers
should v0.1 ship?**

**Fork 3 — Compression storage model (§4 C.3).**
I recommend a durable `Compaction Summary` DocType + a `compacted` flag on Chat Message
(auditable, DocType-native). The lighter alternative is summarise-on-read in `prompt_builder`
with nothing persisted (less code, no audit trail of what was compacted). **Durable row, or
compute-on-read?**

**Fork 4 — Is S8 (compression) in v0.1 at all?**
For a single-tenant customer with mostly short conversations, compression may be Phase 1.5.
It's the biggest feature and the lowest immediate urgency. **Ship C in v0.1, or defer it?**

---

## 6. What v0.1 will NOT do (deferrals, carried from doc 48 + doc 42)

- **Feature E — parallel tool dispatch.** Sequential is the v0.1 contract (doc 48 §1).
- **Feature G — provider fallback chain.** A single provider per profile; errors surface
  cleanly (see §4 F.3).
- **Feature H — tool auto-registration.** Explicit skill registry stays.
- **Credential pool rotation.** One key per provider row.
- **Sub-agent / trajectory compression** (`trajectory_compressor.py`). No sub-agents yet.
- **Cross-turn skill idempotency.** Within-turn dedup only (§4 D.3).
- **Inter-agent communication, streaming, vision, prompt caching, extended thinking.**
  Per doc 42 and doc 04's v0.1-reality callouts.

---

## 7. Immediate next step on approval

On the user's go-ahead, the first code slice is **S1 (M3 — handler convergence)**, the hard
prerequisite for the CRITICAL **S2 (C1)**, which is already fully locked in doc 50. S1 is
small and well-scoped; it gets us to the first green, governed task run quickly. If the user
prefers to start with the headline value instead, **S3 (Feature A — ReAct loop)** is equally
ready (locked in doc 48 §1) and can lead — note only that S2 stabilises the shared dispatch
path A leans on.

Each slice ships as its own reviewable diff: design already locked → code + tests-first →
two-layer rollout doc → user reviews and merges.
