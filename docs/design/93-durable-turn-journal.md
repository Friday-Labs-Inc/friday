# Design 93 — Durable Turn Journal (crash-safe agent turns)

**Status:** Slice 1 implemented
**Track:** Core (`core` tag — no domain naming anywhere)
**Motivated by:** the enterprise-capability backlog item "gateway durability",
plus three shipped incidents that all share one root cause (#166 streaming
audit loss, the 2026-06-24 background-agent deaths, the recovery sweeper's
double-reply window).

---

## Plain English

Today, while an agent is thinking through one turn — calling the model,
running tools, calling the model again, up to 15 rounds — **all of that
progress lives only in the worker process's memory**. If that process dies
(out of memory, deploy restart, crash), everything is lost. The recovery
sweeper notices after 5 minutes and re-runs the turn **from scratch**: every
LLM call is paid for again, every tool runs again, and in one known window
the user can even get the same reply twice.

This design gives every turn a **diary**. As the turn progresses, each step
is written to the database the moment it happens:

- "I started, here is the exact prompt I built" → written down
- "the model answered, and asked for these tools" → written down
- "tool X returned this result" → written down
- "the operator steered me with this note" → written down
- "here is my final reply" → written down
- "the reply was delivered to the user" → written down

If the process dies mid-turn, the retry **reads the diary and picks up from
the last line** instead of starting over. Finished work is never redone; the
user never pays twice for the same LLM call; a delivered reply is never
delivered again.

## Hermes comparison (required by feedback rule)

Hermes persists the **per-message transcript** in a SQLite session DB (WAL
checkpointing, `hermes_state.py`) and offers `/resume` at the **session**
level, plus optional workspace file checkpoints (`run_agent.py`,
`checkpoints_enabled`). But a crash **mid-turn** loses the in-flight turn —
the user re-asks. There is no intra-turn replay.

**Classification: improvement (Hermes = floor, not ceiling).** Friday's fork
foundations (a real DB, a reconciler, deterministic job ids) make intra-turn
durability cheap to add, and Friday's enterprise stance (a turn can carry
15 paid LLM calls and governed side effects) makes it worth adding. The
faithful-port rule doesn't apply — Hermes has no equivalent to port.

## Locked decisions (Q-by-Q)

**Q1 — New doctype or extend Dispatcher Event?** New doctype **`Turn Event`**.
Dispatcher Event is *observability* (informational, no `session_id`, purged at
30 days). The journal is *load-bearing correctness state* — mixing them risks
a retention purge eating replay state and couples two different write
disciplines. LLM Usage Log has `session_id` but only covers LLM calls.

**Q2 — What identifies a turn?** A deterministic `turn_id` supplied by the
caller:
- chat path: the **inbound Chat Message row name** (one inbound row = exactly
  one turn; the recovery sweeper already retries by row name, so retries
  naturally share the id),
- task path: **`task::<task name>`** (the `_claim_task` token already
  guarantees single execution; a reconciler retry re-enters with the same id
  and resumes),
- callers that pass no `turn_id` (self-review, eval harness) get **journaling
  off** — zero behavior change on those paths.

**Q3 — What events are journaled?** Six types, `seq`-ordered per turn:
`turn.started` (the built prompt messages + model + profile — the replay
base), `llm.response` (content, tool_calls, total_tokens), `tool.result`
(tool_call_id, content), `steer.injected` (the operator note),
`turn.completed` (the final reply, whatever the return path — plain reply,
denial, gate pause, budget exhaustion), `reply.delivered` (written by the
gateway after the outbound row commits). A mid-turn context-overflow
compression writes a **fresh `turn.started`** — replay uses the *last* one as
its base, so the compress-and-retry path stays correct.

**Q4 — Replay semantics.** On entry with a `turn_id`, `run_turn` loads the
journal:
- `turn.completed` present → **return the journaled reply immediately** (no
  LLM call, no tool run — idempotent short-circuit),
- journaled profile ≠ current profile → discard the journal, start fresh
  (a reconciler re-assignment must not replay another profile's prompt),
- otherwise rebuild the `messages` buffer from the last `turn.started` plus
  every later event, count consumed iterations against the same 15-cycle
  budget, dispatch any tool calls the last `llm.response` requested that have
  no `tool.result` yet, and continue the loop.

The gateway gains the mirror check: journal says `reply.delivered` → skip
`_write_outbound`, just mark the inbound processed. **This closes the known
double-reply crash window** (crash between outbound write and processed
mark).

**Q5 — Commit discipline.** Each journal write commits immediately
(`frappe.db.commit()` after insert), savepoint-guarded so a journaling
failure can never poison the Postgres transaction (the `exists()` gotcha) or
break a turn. Journaling is **best-effort by write, strictly-better by
design**: a lost journal row degrades to today's behavior (re-run more of
the turn), never to something worse.

**Q6 — Retention.** Journal rows are replay state, not the audit trail (that
stays in Execution Log / LLM Usage Log / Chat Message). Purged after 7 days
by the existing daily retention sweep.

## Residual risk, disclosed

The window "tool executed → crash → `tool.result` not yet journaled" still
re-runs **that one tool** on resume. Cross-call idempotency keys on dispatch
(already noted as deferred D.3 in runner.py) are **slice 2**. The journal
shrinks the blast radius from "the whole turn re-runs" to "at most one tool
call re-runs".

## Slices

1. **This slice:** `Turn Event` doctype + journal module + replay in
   `run_turn` + gateway/tasks wiring + delivered short-circuit + retention +
   tests.
2. Dispatch idempotency keys (exactly-once tool effects).
3. Reconciler fast-path: resume `runner_lost` tasks from the journal instead
   of re-Pending through the full dispatch cycle.
