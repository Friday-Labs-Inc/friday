# Design 83 — Interrupt a running turn (`/stop`) (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — Q1–Q5 all answered as the recommended path
(A throughout). Tests-first, then code. Triggered by the gateway deep audit
(`docs/ports/hermes-port-ledger.md` § Gateway deep audit) — INTERRUPT is the
headline session-manager gap, now unblocked because the command surface
(Design 82) shipped. This design also lands the `/stop` command deferred from
Design 82 (a command never ships before its action).

## The gap, in plain English

Today, once an agent turn starts running in a worker, nothing can stop it. If an
Orchestrator goes down a wrong path — wrong file, wrong plan, a loop of useless
tool calls — the operator can only wait out the 600s job timeout or the 15
ReAct-iteration cap. In Hermes you type `/stop` and the agent halts. Friday has
no equivalent: `run_turn`'s loop (`agent_runner/runner.py:176`) checks nothing
between iterations.

We want `/stop` from Raven to halt the current turn promptly and cleanly.

## What the source says (grounded, both sides)

**Hermes** runs two levels (`gateway/run.py`):
- *Cooperative* `agent.interrupt()` — sets a flag, the loop checks it at the top
  of each iteration (`conversation_loop.py:680`) AND every 0.3s during the LLM
  HTTP call (`chat_completion_helpers.py:420`), then breaks cleanly. The
  interrupting message replays as the next turn.
- *Hard* `_interrupt_and_clear_session` (`run.py:15292`) — same flag PLUS bumps a
  generation counter, discards the pending message, releases the session.
  Triggered by `/stop`. Cascades to subagents (`_active_children`).

**Friday's substrate** (confirmed in source):
- `run_turn` is one blocking `provider.chat()` per iteration — there is **no**
  0.3s poll thread. So a cooperative flag can only be observed at **iteration
  boundaries**, not mid-LLM-call. (Disclosed divergence — see Q2.)
- `frappe.cache()` is redis; arbitrary keys via `.set_value/.get_value/
  .delete_value` (`permissions/cache.py`). An interrupt flag is the natural
  cross-process channel (the turn runs in a worker; `/stop` arrives in the web
  process).
- RQ 2.6.1 has `send_stop_job_command(job_id)` — SIGTERMs the worker's horse
  process (hard kill). `Job.cancel()` only dequeues a not-yet-started job. The
  deterministic `job_id` is already on `Chat Message.job_id`
  (`gateway/service.py:118`).
- Delegated children are **separate** Task RQ jobs linked by `Task.parent_task`
  (`skills/handlers_delegate.py:132`); they do NOT share the parent's
  `session_id`, so a session-keyed flag won't touch them (see Q4).
- The session lock `friday:session_lock:{session_id}` (TTL 300s) serialises
  turns — only one turn per session runs at a time.

## Why a Q-by-Q lock

"Add an interrupt flag" hides five real decisions: what may trigger it, how hard
it kills, how we stop a *stale* flag from killing the wrong turn, whether it
cascades to subagents, and what the operator sees. Friday's queue-by-default
stance and its blocking-LLM-call shape make several of these diverge from Hermes
on purpose. Five questions.

---

## Q1 — What may trigger an interrupt?

Hermes interrupts on ANY second message by default (busy-mode "interrupt").
Friday deliberately chose **queue-by-default** (Design 80): a second message is
queued and drained, never interrupts. That divergence is already shipped.

**Option A — `/stop` only (recommended).** The single trigger is the explicit
`/stop` command. A normal follow-up message still queues (Design 80) and drains
after the turn. Interrupt is a deliberate operator act, not an accident of
typing fast. Consistent with the locked queue-by-default stance.

**Option B — also auto-interrupt on a second message (Hermes default).** Re-opens
a divergence we already closed; surprises an operator who just wanted to add a
note. Rejected.

**Recommendation: A.** `/stop` is the only interrupt trigger. (`/stop` becomes an
operator-tier command in the Design 82 table — `Friday Operator` role.)

---

## Q2 — How hard does `/stop` kill, and at what granularity?

Because the LLM call is blocking, a cooperative flag lands at the next iteration
boundary (after the current LLM round-trip + its tool calls). A truly stuck
single call (a runaway sandbox tool, a 97s LLM read) won't stop until it returns.

**Option A — Cooperative flag only, boundary granularity; hard-kill deferred
(recommended).** `/stop` sets `friday:interrupt:{session_id}`; the loop checks it
at the top of each iteration (`runner.py:176`) and returns a clean "(interrupted)"
reply. Worst case to halt = one in-flight LLM call (seconds, ≤~97s). Simple,
clean, no partial-write risk. A future `/stop force` adds the hard kill.

**Option B — Cooperative + auto-escalate to hard kill.** If the turn doesn't
honor the flag within a grace window, a watcher calls
`send_stop_job_command(job_id)` to SIGTERM the horse. More immediate, but: the
horse dies mid-statement (possible partial DB write), the session lock then sits
until its 300s TTL unless we also force-delete the key, and we need a watcher
process. Real complexity for the rare stuck-tool case.

**Option C — Hard kill only.** `send_stop_job_command` immediately. Brutal: no
clean reply, partial state, lock-TTL deadlock for the next queued message.
Rejected.

**Recommendation: A.** Cooperative flag, boundary granularity, for v1. Hard kill
(`/stop force` → `send_stop_job_command` + force-release the lock key) is a named
follow-up, built only if the stuck-tool case proves real. Disclose the
boundary-granularity divergence from Hermes in the ports ledger.

---

## Q3 — How do we stop a stale/mis-targeted flag from killing the wrong turn?

If `/stop` sets a flag and no turn is running, or the flag outlives its turn, the
*next* turn must not be insta-killed. Hermes solves this with a monotonic
generation counter.

**Option A — Clear-at-entry, lean on the session lock (recommended).**
`run_turn` deletes `friday:interrupt:{session_id}` once at entry, before the
loop. Because the session lock guarantees one turn per session at a time, only a
flag set *during* this turn survives to be observed. Plus a short TTL (e.g. 120s)
on the flag as a belt-and-braces backstop. Simpler than a counter; correct under
the one-turn-per-session invariant the lock already enforces.

**Option B — Generation counter (Hermes-style).** A per-session counter bumped
each turn; the flag carries the generation it targets; the loop honors it only
on a match. Fully race-proof, but more moving parts than Friday needs given the
lock. Defer.

**Recommendation: A.** Clear-at-entry + TTL. Accept the tiny race (operator
`/stop`s in the millisecond between entry-clear and the next turn's first check —
they just `/stop` again).

---

## Q4 — Does `/stop` cascade to delegated subagents?

A runaway is often the *children*. But Friday's children are independent Task RQ
jobs with their own sessions — a session-keyed flag never reaches them. Hermes
cascades `/stop` to `_active_children` and *demotes* a default interrupt to queue
when subagents are active (to protect them).

**Option A — Session-scoped only for v1; cascade deferred (recommended).**
`/stop` halts the current session's turn. Active child Tasks keep running. We
name the gap loudly: a follow-up (`/stop all` or a recursive cascade walking
`Task.parent_task` + `send_stop_job_command("task:{child}")`) lands with the
delegation-aware interrupt work. Keeps v1 a clean single-session mechanism.

**Option B — Cascade now.** Walk `parent_task` from the session's task, set
interrupt flags / send stop-job to every active descendant. More complete, but
children run on the Task heartbeat substrate (different from chat turns), and
this doubles the surface area of a 1-day port. Defer.

**Recommendation: A.** Session-scoped v1. Record the cascade as the next
interrupt increment in the ledger.

---

## Q5 — What does the operator see?

Two things happen: the `/stop` command itself (Design 82 audit + reply) and the
interrupted turn's own outbound.

**Option A — Two clean messages (recommended).** `/stop` replies immediately
"🛑 Stopping the current turn." (its Design 82 `is_command` rows). The interrupted
turn, when it bails at the next boundary, writes a short outbound
"(interrupted by operator)" — a normal conversational row, so the transcript
shows the turn ended deliberately. The turn's already-executed tool calls stay
(they were governed + audited + committed); only the loop stops. No rollback.

**Option B — Silent stop.** The turn just ends, no marker. Cheaper, but the
transcript looks like the agent trailed off; an operator reviewing later can't
tell `/stop` happened. Rejected for auditability.

**Recommendation: A.** Two messages; no rollback of completed tool work.

---

## Summary of what lands once Q1–Q5 are answered (recommended path)

- **`/stop` command** in the Design 82 table (`gateway/commands.py`),
  operator-tier (`Friday Operator`). Its handler sets
  `friday:interrupt:{session_id}=1` with a 120s TTL and replies
  "🛑 Stopping the current turn."
- **Interrupt module** `gateway/interrupt.py` (or in `commands.py`): tiny helpers
  `request_interrupt(session_id)`, `is_interrupt_requested(session_id)`,
  `clear_interrupt(session_id)` over `frappe.cache()`.
- **Runner hook** in `agent_runner/runner.py`: clear the flag once at entry (Q3);
  at the top of each ReAct iteration check it and, if set, clear it and return
  `_INTERRUPTED_REPLY` ("(interrupted by operator)"). Independent of `heartbeat`
  (the gateway path doesn't pass one).
- Cooperative, boundary-granular, session-scoped (Q2/Q4). Hard kill + subagent
  cascade are named follow-ups, not v1.

**Tests-first** (before any runner edit):
1. `is_interrupt_requested` false by default; true after `request_interrupt`;
   false after `clear_interrupt`. (flag helpers)
2. `run_turn` clears any pre-existing flag at entry, then runs normally (a stale
   flag from before the turn does NOT stop it). (Q3)
3. With the flag set mid-loop (patched to be set after iteration 1), `run_turn`
   returns the interrupted reply and does NOT make a further `provider.chat`
   call. (the core behavior)
4. `/stop` dispatch sets the session's interrupt flag and replies with the
   stopping message; refused without `Friday Operator` (Q1 + Design 82 Q4).
5. A normal second message still queues (Design 80) — `/stop` is the only
   interrupt path; a plain message never sets the flag. (Q1 regression guard)

Nothing is built until Q1–Q5 are confirmed.
