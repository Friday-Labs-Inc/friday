# Verification log

Behaviour **observed running**, with the command that proved it. Nothing enters
this file on inspection alone — that is the distinction the previous
documentation set lost ([ADR-0012](../adr/0012-re-baseline-exit-criterion.md)).

One entry per verified claim. Newest first.

---

## V1 — A governed turn runs end to end

**Date:** 2026-09-17 · **Bench:** `friday-dev-frappe-1`, site `friday.localhost`
(Frappe 16.18.2, Python 3.14.7, Postgres + pgvector, raven 3.0.0, randompack_ai)
**Pillar:** 1 — the agent ReAct loop.

### What was run

A `Chat Platform` row `reledger-verify` (`dispatch_mode = sync`,
`default_agent_profile = Friday`), then one inbound `Chat Message`:

> "List the projects you can see, using your list-projects skill. Then stop."

Insert only. Everything after the insert is the system's own path:
`Chat Message.after_insert` → `gateway.service.handle_inbound` → session lock →
`agent_runner.runner.run_turn` → MiniMax → `agent_runner.dispatcher.dispatch`.

### What was observed

| Evidence | Value |
|---|---|
| Inbound message | `processed = 1` |
| Outbound reply | real data — "1. **RandomPack RP-BRIEF-0098 (PROJ-0002)** — Open, 100.0% (7/7 tasks) …" |
| LLM call | `LLM Usage Log 1ppoqbr3q0` — minimax / MiniMax-M2 / 1,812 tokens |
| Skill dispatched | `list-projects`, result `{"count": 9, "duration_ms": 11, …}` |
| **Execution Log** | `1pprhgc11s` — agent_profile `Friday`, status `success`, **docstatus 1 (submitted, immutable)**, trace `944bdcce8836ae7d`, tokens 1,812 |
| **Permission Decision Log** | `1pplrvub2e` — skill `list-projects`, decision `allowed`, **docstatus 1**, trace `944bdcce8836ae7d` |
| Agent Write Log | 0 rows on this trace — correct: `list-projects` writes nothing |
| Turn Event | journal populated (113 rows on the site) |

The permission matrix, the dispatcher chokepoint, both immutable audit rows, the
trace that ties them, LLM usage accounting and the outbound write all executed in
one pass on a real provider.

### What this does NOT prove

- **One** skill, **one** profile, **one** turn, on `sync` dispatch. The async
  worker path, the approval gate, delegation, compression and recovery are
  unverified.
- The skill was read-only, so the sandbox boundary was never approached and
  Design 99's write audit had nothing to record.
- Rows on this site predating Design 99 carry `trace_id = null`; only new rows
  are traced.

### Defect found while verifying

**The Execution Log does not link its Permission Decision Log on the success
path.** `agent_runner/dispatcher.py:240` calls `_get_latest_permission_decision`
only in the rejected branch; a successful dispatch leaves `permission_decision`
empty, and the two rows correlate by `trace_id` alone.

The audit chain holds — the trace is arguably the better key, since it spans the
whole turn rather than one call — but the Link field exists and is empty, and
[ADR-0012](../adr/0012-re-baseline-exit-criterion.md) was written assuming it
was populated. Either wire it on success or remove it; leaving a half-populated
Link field is the worse option.
