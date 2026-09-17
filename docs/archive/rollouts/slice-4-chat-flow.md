# Slice 4 Rollout — The Chat Flow (v2: unified gateway, single-tenant lens)

> **Slice:** 4 of 9 — see `docs/design/10-agent-execution-guide.md`
> **Design contract:** `docs/design/47-gateway-design-decisions.md`
> **PR:** (this PR — supersedes the closed PR #29)
> **Author:** `fridaylabs` / sponsor `@Fridaylabsinc`
> **Audience:** Anyone — engineer, product owner, or a high schooler.

---

## In one sentence

**Friday now talks — and every surface that ever talks to Friday from now on (CLI today; Telegram, Slack, Raven, A2A in later slices) flows through one and only one place.**

---

## What it actually does (in plain terms)

Until now Friday had a gatekeeper (Slice 2) and a tool menu (Slice 3), but no surface to actually use them. Slice 4 builds the first surface — a CLI — *and* lays the unified gateway that every future surface will plug into.

You run the chat:

    $ bench --site friday.localhost friday chat --profile "My Agent"
    Friday chat — profile 'My Agent', session b7a4-…
    Type 'exit', 'quit', or press Ctrl+D to leave.

    > hello

…and you get a reply. For Slice 4 the agent itself is a placeholder — it lists the tools the agent has access to (proving Slice 3 is connected) and echoes your message. Slice 5 swaps the placeholder for a real LLM call **without touching anything in this slice.**

Every line you type and every reply you get is recorded as a `Chat Message` row in Postgres, tagged with session ID, platform, direction, timestamp, and sender. The audit trail is automatic.

---

## What scenarios it now covers

| Scenario | Outcome |
|---|---|
| You type a line in the REPL | One inbound `Chat Message` row written. |
| Inbound row hits Frappe `after_insert` hook | Gateway runs synchronously (CLI's platform has `dispatch_mode=sync`). |
| Gateway runs the stub agent | One outbound `Chat Message` row written. |
| Both rows for the same turn | Share the same `session_id` (UUID per REPL invocation). |
| CLI reads outbound row right after inbound `insert()` returns | Prints the reply. Zero polling, zero socket.io. |
| Inbound row has no `agent_profile` set | Gateway writes a clean system-error outbound. No crash. |
| Gateway writes an outbound row | Hook fires again — gateway sees `direction=outbound` and returns. **No infinite loop.** |
| Two inbound for the same session within milliseconds | Second one waits up to 30s for the Redis session lock; if timeout, writes "session busy" outbound. |
| Profile doesn't exist | CLI exits with code 1 before opening a session. |
| Turn raises an exception in the gateway | Logged to Frappe Error Log; user sees `(agent error: TypeName)`; loop continues. |
| First-ever CLI invocation on a fresh site | `cli` Chat Platform record auto-created with `dispatch_mode=sync`. Zero manual setup. |
| Agent has skills permitted | Reply says `"You have N tool(s) available: a, b, c."` followed by `echo: <your line>`. |
| Agent has no skills permitted | Reply says `"You have 0 tool(s) available: (none)."` |

All proven by 15 tests in `frappe/friday_core/tests/test_chat_flow.py` (chat flow + routing helper + recovery sweeper).

---

## What it means for friday-core

**Before Slice 4:** friday-core had a gatekeeper and a menu, but nothing called either of them in a user-driven flow.

**After Slice 4 v2:** friday-core has its first **end-to-end loop via a unified architecture**:

- A user action triggers an inbound `Chat Message` row.
- A single gateway function runs in response — same code regardless of which surface produced the row.
- Permissions, audit, session locking, recovery — all happen in one place.
- The reply is recorded as an outbound row.
- The surface reads and displays it.

**Three new claims that are now true:**

1. **"Every user message is recorded."** Verified by `test_handle_user_message_writes_inbound_row`.
2. **"Every agent reply is recorded."** Verified by `test_handle_user_message_gateway_writes_outbound_row`.
3. **"The reply path is identical for every surface, present and future."** When Telegram lands, the only new code is a webhook adapter that writes inbound rows — the agent path doesn't change.

This is the moment Friday becomes demonstrable AND extensible. You can hand someone a terminal today; you can hand someone a Telegram bot in three slices, plugged into the same gateway.

---

## How friday-core gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| The gateway chokepoint | A function (`friday_core.gateway.service.handle_inbound`) registered as `doc_events["Chat Message"]["after_insert"]` |
| Inbound / outbound rows | `Chat Message` DocType. Queryable in Desk, REST API, reports. |
| `cli` platform identity | A `Chat Platform` row (auto-created on first use). Future Telegram / Slack / Raven sit in the same table. |
| `dispatch_mode` per platform | A Select field on `Chat Platform`. CLI=sync. Future webhooks=async. Per-platform — no global flag. |
| Default agent fallback | `Chat Platform.default_agent_profile` Link. CLI leaves it null (uses `--profile`). |
| Session lock | `frappe.cache().lock(...)` — redis-py's built-in distributed Lock, runs on Frappe's existing Redis. |
| Outbound delivery to future async surfaces | `publish_realtime("chat.outbound", ...)` — Frappe's standard pub/sub fired by the gateway. CLI doesn't subscribe; future surfaces will. |
| The `friday chat` command | A click Group registered alongside Frappe's bench subcommands via `frappe/commands/__init__.py:get_commands()`. |
| Recovery sweeper | `scheduler_events["all"]` runs every minute — no-op on pure-sync (CLI-only) deployments. |
| Error handling | `frappe.log_error(...)` → standard Frappe Error Log. |

Frappe-native end to end. An admin doing audit work can query Chat Messages in Frappe Desk's report builder.

---

## How this compares with Hermes (per project memory rule)

| Decision | Hermes does | Friday does | Justification |
|---|---|---|---|
| CLI ↔ agent | Direct in-process call (`cli.py:11773` calls `AIAgent.run_conversation`) | Through unified gateway (CLI writes inbound row; doc_events fires gateway; sync mode runs in-line) | **Different — strategic.** Hermes specials-cases its CLI; we don't. Friday's unified gateway pays for itself the day the second surface (Telegram) lands. |
| Process model | One async daemon | Frappe multi-process (gunicorn + RQ + bench) | **Forced by Frappe.** |
| Message coordination | `MessageEvent` Python dataclass | `Chat Message` DocType row | **Forced by multi-process; bonus: free audit trail.** |
| Session lock | `threading.Lock` in `SessionStore` | Redis lock (`frappe.cache().lock(...)`) | **Forced by multi-process.** |
| Dispatch mode | All async (every platform is an asyncio task) | Per-platform `dispatch_mode` field — sync for CLI, async for webhooks | **Different — Frappe's bench-command model can't sit in an event loop.** |
| Streaming | `GatewayStreamConsumer` sync→async queue + edit-message | Not in Slice 4 — same pattern when streaming lands | **Same intent, deferred.** |
| Batching | None (Hermes is single-user per session) | Documented but stubbed (`flush_batch()` is pass-through) | **Friday-only; deferred per single-tenant scope.** |
| Dedup | Adapter-side `_quick_key` | Documented; helper lands with first webhook adapter | **Same pattern, deferred.** |
| Recovery from crash | Per-tool retry inside `run_conversation` | Cross-process sweeper (no-op on pure-sync deployments today) | **Forced by multi-process.** |

The biggest divergence is the "unified gateway for the CLI" choice. Under the strict comparison rule that's a divergence from Hermes, but it's justified by Friday's multi-surface scope (per project memory `feedback-unified-gateway-service`). All other divergences are forced by Frappe's architecture, not chosen.

---

## What's deliberately deferred (with documented design)

Per `docs/design/47-gateway-design-decisions.md` §8 these subsystems are NOT in Slice 4 but their designs are committed for when their actual users land:

| Subsystem | Activates in | Source of truth |
|---|---|---|
| Q4-C batching (queue + timer + `messages: list` signature) | First bursty surface (Telegram / A2A real use) | Design doc §4 Q4-C |
| Q4-D adapter-side dedup helper | First webhook adapter | Design doc §4 Q4-D |
| Q5 per-tool idempotency cache + key derivation | First real tool (Slice 6) | Design doc §4 Q5 |
| CLI socket.io subscriber | Only if a real out-of-band-delivery use case appears | Design doc §4 Q2 |
| Streaming delivery (send-then-edit pattern) | First streaming-capable surface | Design doc §6 |
| Per-RQ-worker agent cache | Slice 8 RQ-worker model | Design doc §6 |

**Each deferred piece is documented in the design doc so the slice that activates it can move fast — not a rebuild from scratch.**

---

## What the project can say truthfully today

- **"You can have a conversation with a Friday agent."** Run `bench --site friday.localhost friday chat --profile X` and try it.
- **"Every message is audited."** Two immutable Chat Message rows per turn, queryable in Frappe Desk.
- **"The reply path exercises the same permission machinery as a real action."** Verified by the stub calling `load_for_profile()`.
- **"Round-trip latency is well under a second on local dev."** Verified by `test_round_trip_under_one_second`.
- **"Adding Telegram (or Slack, or Raven, or A2A) requires only a webhook adapter — no gateway change."** Architectural property; verified the day we ship the first one.

---

## Risks and limits a product head should hold

- **No real intelligence yet.** Slice 4 ships a stub. Slice 5 wires the LLM.
- **No skill execution yet.** Reply mentions tools but cannot call them. Slice 6.
- **Single-user, single-session, single-process** in practice (sync CLI is the only surface). Async surfaces — and the multi-process safety the locks/recovery exist for — are real but unused infrastructure today. Correct dead code; activates with first webhook.
- **No streaming.** Replies arrive as one row, one event. Hermes's progressive-edit pattern is deferred.
- **REPL UX is plain.** No prompt history, completion, syntax highlighting. Add `prompt_toolkit` polish when we want it.
- **Latency baseline ~10ms** before the agent runs (DB roundtrip + doc_events + publish_realtime). Hermes is <1ms because it's in-process. Acceptable; LLM call latency dwarfs it.

---

## What this unlocks

- **Slice 5 (LLM integration)** replaces the body of `agent_runner.run_turn` with a real OpenAI / Anthropic call. The CLI, the gateway, the audit-row writer, and all 15 tests keep working unchanged.
- **Slice 6 (first real skill)** takes a tool call the LLM emits and routes it through the per-skill `permissions.check` → execution → return. The Q5 reserved Skill fields (`idempotent`, `idempotency_strategy`) get activated here.
- **Slice 7+ (Docker sandbox, A2A, platform adapters)** each adds a new file or two; **none of them changes the gateway**. They write inbound Chat Message rows on their respective platforms, the gateway picks them up.
- **First demoable loop:** after Slice 5 → user types a request → LLM picks a tool from the menu → gatekeeper approves → action runs (mocked). That's the moment friday-core stops being plumbing and starts being a product.

---

## Numbers for the record

- **10 files added/modified:**
  - `frappe/friday_core/gateway/` — 4 new files (init, service, batching, recovery)
  - `frappe/friday_core/routing/` — 2 new files (init, resolve)
  - `frappe/friday_core/agent_runner/` — 2 new files (init, runner)
  - `frappe/friday_core/cli/` — 3 new files (init, chat, commands)
  - `frappe/friday_core/tests/test_chat_flow.py` — new test file
  - `frappe/friday_core/doctype/{chat_platform,chat_message,skill}.json` — 6 field additions across 3 DocTypes
  - `frappe/hooks.py` — added `Chat Message.after_insert` hook + scheduler entry for sweeper
  - `frappe/commands/__init__.py` — registered the `friday` click Group
  - `docs/design/47-gateway-design-decisions.md` — new design contract
  - `docs/rollouts/slice-4-chat-flow.md` — this file
  - `docs/project/IMPLEMENTATION_LOG.md` — Slice 4 v2 entry
- **15/15 chat-flow tests green** (chat flow + routing + recovery sweeper)
- **Regression:** Slice 1 → 2/2, Slice 2 → 10/10, Slice 3 → 8/8. **Total: 35/35.**
- **Deliverable verified:**
  ```
  $ bench --site friday.localhost friday --help
  (lists chat subcommand)

  $ bench --site friday.localhost friday chat --help
  (shows --profile option)

  $ bench --site friday.localhost execute \
      frappe.friday_core.cli.chat.handle_user_message \
      --args "['FRIDAY-SLICE4V2-PROFILE-TOOLS', 'demo-1', 'hello via unified gateway']"
  → "You have 1 tool(s) available: slice4v2-skill.\necho: hello via unified gateway"
  ```
- **Scope under single-tenant lens** (project memory `feedback-single-tenant-not-saas`): ~400 LOC fewer than the ambitious v1 would have written. Deferred subsystems (batching, dedup, per-tool idempotency framework) are documented for the slice that genuinely needs them.
