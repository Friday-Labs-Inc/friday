# Slice 94-1 — Provider failover (a sick provider hands over to its backup)

**Design:** `docs/design/94-provider-failover.md`
**Shipped:** 2026-07-03

## The problem, in plain English

When the LLM provider an agent runs on goes bad mid-work — rate-limited,
overloaded, down, out of credit, or just refusing the request — the turn
failed. The task blocked, and the retry machinery later tried again…
**against the same broken provider.** If Minimax was down for an hour, every
retry for an hour hit the same wall, while a perfectly healthy backup (the
Codex subscription, say) sat idle one config field away.

Funny detail: half the machinery already existed. Friday's error classifier
has labeled every LLM failure with a "**should_fallback**" verdict since
Feature F — and nothing ever read it. This slice wires the missing consumer.

## What shipped

Each `LLM Provider` row gets one new optional field: **Fallback Provider** —
"if I fail, try them." Chains are allowed (Minimax → Codex → Claude), capped
at 3 hops, and loops (A→B→A) are guarded at runtime.

When a model call fails beyond the provider's own built-in retries, the turn
now **switches to the backup on the spot** — same turn, same conversation,
no operator, no waiting:

- the backup answers with **its own default model** (model names don't
  carry across providers — `MiniMax-M2` means nothing to Codex);
- the switch is written to the turn's **diary** (Design 93), so the record
  shows exactly which provider produced which answer, and a crashed-then-
  resumed turn re-resolves cleanly;
- a **`llm.failover`** event lands in the Dispatcher Event trail, and token
  cost attributes to whichever provider actually served the call;
- leave the field empty → nothing changes. All providers exhausted → the
  turn blocks exactly as before, and the reconciler stays the outer safety
  net.

## Who gets it

Every turn through the blocking runner path: chat via the gateway, pipeline
tasks, delegation, cron. **Deliberately not yet:** the streaming intake chat
on randompack.com (a mid-stream switch would show the customer two half
replies — needs a buffering strategy; slice 2).

## Hermes comparison

Hermes rotates a credential pool and falls back between providers inside
`run_agent.py` (process config). Friday adapts: no credential pools (one
credential per provider in v0.1), chain declared as data on the provider
row, and — the improvement — every hop is journaled and audited, which
Hermes' in-process rotation is not.

## Verification

- 9 new DB-free tests: rescue by backup, backup uses its own model, hop
  journaled + replay unpins the model, transitive chain, cycle guard, hop
  cap, no-chain regression, usage attribution, chain resolution edge cases.
- Full DB-free suite: 1134 tests, failure set identical to main baseline.
- `bench --site friday.localhost migrate` clean; `fallback_provider` column
  verified in Postgres.
- Suggested prod config after deploy: Minimax → Codex (both live on the
  box; one Desk field).
