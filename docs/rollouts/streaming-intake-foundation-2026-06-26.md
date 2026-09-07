# Streaming intake foundation — Friday's first live front-door (2026-06-26)

> The keystone for a major new capability: a **live streaming conversation** with
> Friday that pre-fills a wizard as the customer talks. Every prior Friday surface is
> async server-to-server (Chat Message row → worker → string reply). This is the first
> **synchronous, streaming** path. Built for RandomPack's hero chat-intake, but the
> primitive is general.

## What shipped in this slice (the foundation)

1. **`on_token` streaming primitive** (`llm/provider.py`). The OpenAI-compatible
   providers already stream internally (to solve the timeout-vs-stale-watchdog problem)
   but assembled the full reply before returning. Added an optional
   `chat(..., on_token=callback)` that relays each text delta live. Fully
   backward-compatible (defaults `None`; the full response is still returned; a raising
   callback is swallowed so a UI hiccup can't abort a generation). The blocking
   providers (Anthropic, Codex) accept it for parity but don't stream.

2. **The streaming intake turn** (`conversation/intake.py`). One turn that:
   - streams a conversational reply via `on_token`,
   - persists the inbound + outbound `Chat Message` rows (session continuity — survives
     a browser refresh, no Redis-only state),
   - runs a **separate, deterministic structured-extraction pass** — a tool-less LLM
     call that reads the conversation and emits `{field, value, confidence}` wizard
     deltas — and validates them (unknown fields dropped, confidence clamped).

## Key architecture decisions

- **Lean path, not `run_turn`.** Intake takes no gated actions, so it skips the
  tool-using ReAct loop. It reuses the durable bits (transcript rows, the streaming
  provider) and nothing else. `run_turn` stays untouched for agentic flows.
- **Deltas come from a separate pass, NOT from parsing the token stream.** The pre-fill
  channel is reliable independent of how the prose streamed. Token stream = UX; the
  extraction pass = the product value.
- **Field vocabulary is injected, never hardcoded.** The consuming product owns the
  field names (RandomPack's `frontend/src/wizard/`); Friday stays semantic.
- **Reasoning scrubbing.** A live run caught MiniMax-M3 leaking `<think>…</think>` into
  the reply — the returned/persisted/extractor reply is now run through
  `llm/reasoning.strip_reasoning`. (Hiding think tokens in the LIVE stream is a
  surface-layer refinement — the SSE adapter should buffer until a think block closes.)

## Proven live (the showcase)

`bench --site <sandbox> execute friday.friday_core.conversation.intake.run_demo` on the
real MiniMax provider. From a single customer message
("We are Northwind Tools, premium hand tools for woodworkers, rugged heritage feel"):
the reply **streamed token-by-token**, and the extraction pass filled **4/4 wizard
fields** in one turn — `business_name='Northwind Tools'` (0.99), `industry='Premium
hand tools'` (0.95), `audience='Woodworkers'` (0.95), `personality='Rugged heritage'`
(0.95). That is the form pre-filling itself as the customer talks.

12 DB-free unit tests (the `on_token` primitive + the intake core: parse/validate
deltas, the extraction pass, the streamed turn, history threading, persist-failure
safety). ruff clean. No schema change in this slice.

## What's NEXT (the buildable surface — pending the RandomPack contract)

This foundation is field-agnostic and proven. The remaining slice wires it to the wire,
once `CONTRACT.md v1.1` lands:

- `surfaces/randompack/chat.py` — SSE endpoints (`chat_start` / `message` / `finalize`),
  HMAC auth reusing `connector_core` (same seam as `surfaces/randompack.py`). `message`
  streams `{type:"token"}` (via `on_token`, with live think-buffering) + `{type:"delta"}`
  events, then writes deltas back to RandomPack via the token-auth `connector_client`.
- A per-session lock (reuse `friday:session_lock:{session_id}`) since this lean path
  bypasses `_run_pipeline`'s lock.
- A `Customer Intake` Agent Profile + a `randompack-intake` Chat Platform row (pure
  data/config — the system prompt + the injected field map).
