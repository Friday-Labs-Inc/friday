# Slice 93-1 — The Durable Turn Journal (crash-safe agent turns)

**Design:** `docs/design/93-durable-turn-journal.md`
**Shipped:** 2026-07-02

## The problem, in plain English

While an agent works through one turn — call the model, run some tools, call
the model again, up to 15 rounds — all of that progress lived **only in the
memory of the worker process**. If that process died (out of memory, a
deploy, a crash), everything was gone. The recovery machinery noticed
minutes later and re-ran the whole turn **from the beginning**: every LLM
call paid for again, every tool executed again. And in one known crash
window (after the reply was written but before the inbound message was
marked handled), the user could receive the **same answer twice**.

Three real production incidents pointed at this exact gap: the streaming
audit-trail loss (#166), the background build-agents that died with a
process restart (2026-06-24), and the gateway's double-reply window.

## What shipped

Every turn now keeps a **diary** (the new `Turn Event` table). As the turn
progresses, each step is written to the database the moment it happens:

| Diary line | Written when |
|---|---|
| `turn.started` | the prompt is built (the exact messages, pinned) |
| `llm.response` | the model answers (its text + requested tool calls) |
| `tool.result` | a tool returns |
| `steer.injected` | an operator `/steer`s mid-turn |
| `turn.completed` | the final reply exists (any ending: answer, denial, gate pause, budget) |
| `reply.delivered` | the gateway wrote the outbound message |

On a retry, the runner **reads the diary and picks up from the last line**:

- turn already finished? → return the journaled reply. No LLM call. Ever.
- reply already delivered? → the gateway just closes the books. **The
  double-reply window is gone.**
- crashed mid-turn? → the conversation is rebuilt from the diary, only the
  tool calls still owed are dispatched, and the model continues from where
  it was. Replayed rounds count against the same 15-round budget.

## Who gets it

- **Chat turns** (every surface — Raven, Slack, CLI, A2A): the inbound
  message's row name is the turn's diary key; the recovery sweeper already
  retries by that name, so resume "just happens".
- **Task turns** (pipelines, delegation, cron): keyed `task::<name>`, stable
  across reconciler retries.
- **Self-review and eval turns**: journaling off (no key passed) — zero
  behavior change.

## Safety posture

Every diary write commits immediately and is savepoint-guarded: a failed
write logs and degrades (the turn just re-runs more on a crash — today's
behavior), it never breaks a turn or poisons the Postgres transaction. A
`(turn_id, seq)` unique index makes two racing resumers physically unable
to both append the same line. Diaries are purged after 7 days — they are
replay state; the permanent audit trail stays where it always was
(Execution Log, LLM Usage Log, Chat Message).

## What this does NOT do yet (disclosed)

If a crash lands in the tiny window between a tool executing and its result
reaching the diary, that **one tool call** re-runs on resume (before this
slice, the **whole turn** re-ran). Exactly-once tool effects via dispatch
idempotency keys are slice 2. Slice 3 teaches the task reconciler to resume
`runner_lost` tasks straight from the diary.

## Verification

- 17 new DB-free unit tests (`tests/test_turn_journal.py`): pure replay
  reconstruction + resume behavior of the real `run_turn` loop.
- Full DB-free suite: 1107 tests, failure set identical to main baseline.
- `bench --site friday.localhost migrate` clean; `tabTurn Event` +
  `unique_turn_seq` index verified in Postgres.
- Live-DB smoke on the real site: journal write/read round-trip, duplicate
  seq swallowed by the guard, replay reconstructed the exact pending state.

## Hermes comparison

Hermes persists the per-message transcript (SQLite WAL) and resumes at the
*session* level; a crash mid-turn loses the in-flight turn. Friday now
resumes mid-turn. Classified as an **improvement** under the
"Hermes = floor, not ceiling" stance — there is no Hermes equivalent to
port.
