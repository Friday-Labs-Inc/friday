# Design 94 — Provider failover (a degraded provider degrades to its backup)

**Status:** Slice 1 implemented
**Track:** Core (`core` tag)
**Handoff:** routed from the RP-integration session 2026-07-03; key finding
credited there — the mechanism was already half-built and unconsumed.

## Plain English

When an agent's LLM provider goes bad mid-work — rate-limited, overloaded,
down, out of credit, or simply refusing the request — the turn today just
**fails**. The task blocks, and the reconciler later retries it… against the
**same dead provider**. If Minimax is down for an hour, every retry for an
hour hits the same wall while a perfectly healthy backup (say the Codex
subscription, Design 63b) sits idle.

This design teaches the turn to **switch to a backup provider on the spot**:
same turn, same conversation, no operator, no waiting for the reconciler.
The operator declares the chain as data — each `LLM Provider` row gets an
optional **Fallback Provider** link ("if I fail, try them") — and the ReAct
runner follows it when a call fails beyond recovery.

## The found half-mechanism (why this slice is small)

`llm/error_classifier.py` (Feature F) already labels every LLM failure with
a reason and THREE recovery hints: `retryable` (the provider's own transport
layer retries with backoff — consumed), `should_compress` (context overflow
→ compress + retry — consumed by the runner since Design 80), and
**`should_fallback`** (auth / billing / model_not_found / format_error —
"this provider fundamentally can't serve this; a different one might") —
**computed on every error and never read by anyone**. This slice wires the
missing consumer.

## Locked decisions (Q-by-Q)

**Q1 — When does failover fire?** On **any `LLMError` the runner catches
that the compress path didn't resolve**, provided a fallback is configured.
Rationale: by the time the runner sees an LLMError, the provider's transport
layer has ALREADY exhausted its same-provider retry budget
(`_post_with_recovery`, MAX_RETRIES with backoff + Retry-After) — so
"retryable" reasons (rate_limit/overloaded/server_error/timeout) are
*exhausted-retryable*, and switching is the only move left that isn't
"block and wait". `should_fallback=True` reasons switch for the classifier's
original rationale. A second context-overflow also falls through to failover
(the backup may simply have a bigger window). Empty chain = exact current
behavior — zero regression.

**Q2 — Where does the chain live?** **`LLM Provider.fallback_provider`** —
an optional Link on the provider row itself, transitive (A→B→C), consumed at
runtime with a **visited-set cycle guard and a 3-hop cap**. Chosen over an
Agent Settings global table (per-provider knowledge belongs on the provider;
"who backs up Minimax" is a property of Minimax, not of the deployment) and
over a per-profile field (config surface × profiles, and single-tenant means
few profiles share few providers anyway — [[single-tenant-not-saas]]).
Misconfigured cycles (A→B→A) are legal data; the runtime guard makes them
harmless.

**Q3 — What model does the backup run?** **Its own `default_model`** (the
runner passes `model=None` after a hop). The primary's model string is
provider-specific (`MiniMax-M2` means nothing to Codex); mapping tables are
ceremony this slice doesn't need.

**Q4 — How does this compose with the Design 93 turn journal?** A hop writes
a **`provider.failover` journal event** (`from`, `to`, `reason`) — so the
diary shows exactly which provider produced which response. On **replay**,
the event resets the rebuilt state's pinned model to None: a resumed turn
starts from the profile's PRIMARY provider again (if it's still down, the
failover re-fires naturally and is re-journaled), and a fresh model
resolution avoids replaying a foreign model string against the wrong
provider. Deliberately simple: the journal records history; it does not pin
the failover choice.

**Q5 — Audit & attribution.** `record_usage` already receives the provider
instance, so tokens/cost attribute to **whichever provider actually
served the call** — no change needed. Each hop additionally emits a
`llm.failover` Dispatcher Event (observability, Design 72) with the reason
and both provider names.

**Q6 — What about the streaming intake surface?** Deferred, disclosed. The
RP chat surface (`randompack_chat._stream`) relays live tokens; failing over
mid-stream would double-emit partial replies to the browser. Failover lands
in the blocking runner path (`run_turn`) only — which is every agent/task/
chat-gateway turn. The reconciler's cross-tick retry remains the outer
safety net for everything else, exactly as today.

## Hermes comparison (required)

Hermes' equivalent is the **provider pool + fallback** in `run_agent.py`:
multi-credential rotation per provider, `_pool_may_recover_from_rate_limit`
deciding rotate-vs-fallback, and a fallback provider for non-recoverable
failures. Friday adapts rather than ports: no credential pools (v0.1 is
single-credential per provider — the classifier's `should_rotate_credential`
was already omitted for the same reason), and the chain is **declarative
data on the provider row** instead of process config. Classified
**improvement** under [[hermes-floor-not-ceiling]]: Friday's failover is
journaled (Design 93) and audited (Dispatcher Event + usage attribution),
which Hermes' in-process rotation is not.

## Slices

1. **This slice:** `fallback_provider` field + chain resolution + runner
   failover + journal/observability events + tests.
2. Failover for the streaming intake surface (needs a token-buffering
   strategy).
3. Health-aware routing (skip a provider known-degraded for N minutes
   instead of paying a failed call to rediscover it).
