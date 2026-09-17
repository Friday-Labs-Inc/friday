# Hermes → Friday port ledger v2

**Target:** Hermes `v2026.9.14` = `7a963716b81b`. **Friday:** `develop` @ 2026-09-17.
**Supersedes** `hermes-port-ledger.md` (kept for lineage; its file map no longer resolves).
**Scope rule:** Hermes' own narrow waist only — [ADR-0008](../adr/0008-track-hermes-narrow-waist.md).

## Plain English

Friday ported the *shape* of Hermes and very little of its *hardening*. Every
pillar the June ledger marked COMPLETE has a working skeleton and is missing the
recovery, cost-control and safety machinery built around it. The June verdict
was not dishonest — it compared against a Hermes that was 10,000 commits
younger, by reading code rather than running it.

Scale, non-test: Hermes waist ≈ **338,000** LOC · Friday kernel **27,642**.
Roughly 12:1. Parity is not the goal; knowing the delta is.

## Verification status of this document

- Rows marked ✅ were verified in source by the author of this file.
- All other rows come from three parallel source audits (agent loop, gateway,
  core tools) and are **unverified individually**. Treat them as leads with
  citations, not as facts, until each is confirmed. That distinction is the
  whole point of this restructuring.
- One audit claimed 14 blocking `SyntaxError`s from Python-2 `except A, B:`.
  **False.** The bench runs **Python 3.14.7**, where [PEP 758](https://peps.python.org/pep-0758/)
  makes unparenthesised multiple exception types legal, and `pyproject.toml`
  declares `target-version = "py314"`. Verified: `py_compile` on `llm/provider.py`
  inside the container exits 0, and a governed turn ran through it
  ([verification-log](verification-log.md) V1). The audit used host Python 3.13.

---

## The June ledger's claims, tested

| June claim | Status now |
|---|---|
| "Agent ReAct loop — **COMPLETE**" | **False.** Hermes' loop is 18 phases across ~20 `turn_*.py` siblings; Friday implements ~8. Never ported: truncation recovery, stop gates, tool guardrails, parallel tools, outer-loop error handling, turn finalisation, iteration refund, preflight gates. |
| "Context assembly — **COMPLETE**, prompt caching shipped" | **Shipped but cannot hit.** `prompt_builder.py:134-148` appends a live project snapshot and a *query-ranked* memory block as `system` messages; `provider.py:983` joins all system messages into the marked string. Memory re-ranks per turn, so the cached prefix changes every call. Hermes' own `AGENTS.md` names this the top message-flow anti-pattern. |
| "Context compression — **COMPLETE**; tool-result pruning **moot**, Friday never persists tool rows" | **Inverted.** Because tool rows are never persisted, the entire tool trace is dropped from context at every turn boundary. That is a far larger loss than the pruning it was used to strike from the backlog. |
| "Interrupt / steer — **SHIPPED**" | **Boundary-only subset.** Interrupt cannot stop a turn inside an LLM call or a tool batch. Steer uses Hermes' *superseded* bare-marker shape, which Hermes replaced because models refused it as prompt injection. |
| "Gateway — **COMPLETE**, 22 files audited" | Hermes `gateway/` is now **159 files**. ~30 in-scope modules did not exist in June, including durable delivery, turn leasing and two-axis authz. |

---

## Consolidated backlog — MISSING, ranked

**Tier A — correctness, security, or silent loss**

| # | Gap | Hermes ref | Why | Effort |
|---|---|---|---|---|
| A1 ✅ | **`_load_history` loads the OLDEST 20 rows**, not the newest — `order_by="creation asc"` + `limit`. Compaction fires only at 50% of window, so the uncompacted tail routinely exceeds 20 and the model goes blind to the recent conversation, including the previous turn. | — (Friday bug) | Silently degrades every long-running channel | **0.5 d** |
| A2 ✅ | **Session lock TTL 300 s < job timeout 600 s** (`service.py:67` vs `:82`). A 5–10 minute turn loses its lock *while still running*; the drain or sweeper can start a second worker on the same transcript. | `turn_lease.py:98` | Live concurrency bug | **1 d** |
| A3 | **Untrusted tool-output wrapping** — a result containing `[System: …]` is fed to the model verbatim. | `tool_dispatch_helpers.py:487-520` | The one hole where the permission matrix, approvals, sandbox and execution log give **zero** protection: the payload arrives in the *result*, after every gate | **1–2 d** |
| A4 | **Durable delivery ledger.** A failed Raven/Slack post is logged and never retried; the human never sees the reply. | `delivery_ledger.py:154` | Content is durable; *delivery* has no guarantee | **4–5 d** |
| A5 | **Inbound dedup** — the call site is a commented-out stub (`service.py:226`); Slack retries on any non-200. | `routing/dedup.py` (stubbed) | Duplicate turn = duplicate spend + duplicate side effects | **1 d** |
| A6 | **Compaction lock + failure cooldown.** No mutex: two workers on one session both pay the aux model and both write a summary; a failing aux model retries every turn forever. | `hermes_state_compression.py:451,314` | Correctness and cost | **2 d** |
| A7 | **Length-truncation recovery.** `finish_reason` is populated and never read — truncated replies are delivered as complete, truncated tool calls dispatched with guessed args. | `turn_truncation.py:350` | Silent wrong answers, the worst class for a governed system | **3 d** |

**Tier B — cost**

| # | Gap | Effort |
|---|---|---|
| B1 | **Make prompt caching hit** — move memory + project snapshot below the breakpoint (into the user turn). Pure ordering change; today ~75% of input tokens are re-billed every turn. | 2–3 d |
| B2 | **Per-model context window.** One hard-coded 128 k for every model: a 32 k model overflows before compressing, a 1 M model compresses 8× early. | 2–3 d |
| B3 | **Bill auxiliary calls** — `compression.py:386,471` never call `record_usage`. Compaction spend is invisible. | 0.5 d |
| B4 | **Tool guardrails** — nothing stops 15 iterations of the same failing call; no per-turn cap on `delegate-task`. | 2–3 d |
| B5 | **Jittered backoff** — an RQ pool retries in lockstep into an already-throttled provider. | 0.5 d |
| B6 | **Per-provider failover cooldown** — `_visited_providers` is per-turn, so the next turn re-attacks the sick primary. | 1 d |

**Tier C — the user cannot tell a slow turn from a dead one**

| # | Gap | Effort |
|---|---|---|
| C1 | **Busy-ack with 30 s debounce** — a second message today gets no feedback at all. | 0.5 d |
| C2 | **Session stall notice** — Friday tells the *operator* a pipeline is unhealthy, never the *user in the channel*. | 1 d |
| C3 | **Progressive streaming to chat** — both halves exist separately (`provider._consume_stream`'s `on_token`, `chat_spine.ThinkFilter`); the throttled edit loop does not. Needs C5. | 5–6 d |
| C4 | **Message timestamps in the prompt** — the agent has no temporal awareness. | 0.5 d |
| C5 ✅ | **A real adapter contract.** `Chat Platform.adapter_module` is written by 5 call sites and **read by none**; outbound dispatch is three hardcoded hooks. The doctype looks like a registry and isn't one. Blocks A4, C3 and the next surface. | 3–4 d |

**Tier D — the waist's missing tools** (each needs the sandbox prerequisite below)

`terminal` · `process_manage` · `patch` · `search_files` · `vision_analyze`
(Friday generates images and cannot see one) · `browser_*` · `text_to_speech` ·
and `skills_list`/`skill_view` — Friday has **no procedural-knowledge layer**;
`Skill.instructions` is a field nothing reads.

> **Terminology trap:** a Hermes *skill* is a `SKILL.md` document (58 ship
> bundled); a Friday `Skill` is a *tool definition*. Same word, different thing.

**The prerequisite that gates Tier D** ✅ — `dispatcher.py:452` routes
**in-process** for any skill with no sandbox handler, and `:468` falls back
in-process when Docker is down. Documented, deliberate, and correct while
`create_note` is the only sandboxed skill. The moment a terminal or file tool
lands it is arbitrary shell execution as the Frappe worker, inside the bench,
with database access. **Deny-by-default first, then the tools.**

---

## What Friday has that Hermes does not

Not consolation — these are the reasons the fork exists, and they must survive
every port above.

1. **Governance inside tool dispatch.** Permission matrix → immutable decision
   log → approval gate that pauses the turn → `acting_as(agent_user)` →
   submitted Execution Log. Hermes has no per-agent×skill matrix and no durable
   approval record. Hermes' own `file_safety.py` says it is "NOT a security
   boundary"; Friday's is.
2. **Durable turn journal with replay.** `Turn Event` reconstructs loop state
   *including pending tool calls* and re-dispatches them. A crashed Hermes turn
   re-runs from scratch and re-pays for every LLM call.
3. **The queue is durable by construction.** Hermes needs 294 lines of atomic
   JSON + directory fsync because its 32-deep FIFO is in memory and drops
   message 33. Friday's queue is rows: unbounded, crash-proof, self-healing.
4. **Delegation as durable Task rows** — survives worker death, auditable, cost
   rolled up, three governance gates. Hermes' children are in-memory futures.
5. **Cascade interrupt + attributed force-kill** across a delegation subtree.
   Hermes *demotes* interrupt to queue when subagents run, because it cannot do
   this.
6. **Auditable compaction** — `Compaction Summary` with from/to/count/model and
   change tracking; originals never rewritten.
7. **Project-scoped, relevance-ranked memory recall** with cross-project
   anti-bleed. Hermes delegates ranking to providers; one Hermes home is one user.
8. **`@`-references gated by the DocPerm matrix** — the same matrix skill
   dispatch uses.
9. **An opinionated health verdict** that fails loud and audits a *governance*
   condition (a second ungoverned engine on the same records).
10. **Cross-channel approval scoping** — an explicit `/approve <id>` is honoured
    only if it belongs to this session. Hermes patched the same IDOR class
    reactively, twice.
11. **Friday is also an MCP *server*** — external callers routed through the real
    dispatcher, inheriting one profile's permissions, every call logged.
12. **Strict inactive-provider semantics** — deactivating a provider is a hard
    stop, not a silent reroute.

---

## Other Friday defects surfaced (unverified — leads)

- No alternation repair, and two generators of `assistant; assistant` pairs
  (`delivery.py:197`, `mirror.py:80`). Strict-alternation providers will reject.
- `prompt_builder` fails *open* on a history read error; Hermes fails closed —
  "empty history is valid data; a failed canonical read is not".
- Raw exception text reaches chat (`commands.py:175`, `:246`).
- Memory egress is unredacted — a secret in an Agent Memory row reaches the
  provider verbatim.
- `@`-reference expansion has no token budget.
- Hard-coded `CLAUDE_CLI_VERSION = "1.0.108"` (`provider.py:840`) vs Hermes'
  live detection — OAuth rejection is a matter of time.
- Flat 120 s read timeout kills any genuine reasoning model mid-think, then
  misclassifies it as a retryable provider fault.
