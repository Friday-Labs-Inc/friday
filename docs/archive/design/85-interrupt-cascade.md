# Design 85 — `/stop` cascades to delegated work (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — Q1–Q5 all answered as the recommended path
(A throughout). Tests-first, then code. Triggered by the named follow-up from
Design 83 (interrupt) in the gateway ports ledger: "subagent cascade — children are separate Task jobs with
their own sessions."

## The gap, in plain English

`/stop` (Design 83) halts the turn for *one session*. But an Orchestrator's most
expensive work is what it **delegated**: an Orchestrator that fanned out three
Specialists and is waiting on them. Today `/stop` in that channel stops only the
Orchestrator's own turn — the three delegated Tasks keep running, each burning
tokens, with no way to stop them from chat. The operator means "stop
*everything*", and gets "stop the one thing in front of me".

## What the source says (grounded)

- A delegated child is a separate `Task` (RQ job), run as a fresh
  `task::{task.name}` session (`tasks/runner.py:477`). The Design 83 interrupt
  check lives in the shared `run_turn` loop, so a child turn **already checks its
  own interrupt flag** — we just need to *set* it.
- The tree is fully linkable with **no schema change**:
  - `Task.originating_session` = the session that spawned a root task
    (`handlers_delegate.py:138`, queried at `:94`). A chat `/stop` (session = the
    Raven channel) finds its root tasks by `originating_session == channel`.
  - `Task.parent_task` links descendants (`handlers_delegate.py:132`). Recurse to
    get the whole subtree.
  - Active = `_ACTIVE_STATES = ("Pending","Assigned","Executing","Blocked")`
    (`handlers_delegate.py:38`).
- **The catch (Q3):** when `run_turn` returns the interrupt reply, the *chat*
  path just writes it as the outbound — fine. But the *Task* path treats any
  normal return as success and marks the task **`Completed`**
  (`tasks/runner.py:530-531`). So a cascaded interrupt would falsely mark
  delegated tasks done. The interrupt has to be *distinguishable* from a normal
  finish on the Task path.
- RQ 2.6.1 has `send_stop_job_command(job_id)` (SIGTERMs the worker horse) but it
  kills mid-transaction and leaves the session lock to its 300s TTL — a hard,
  lossy primitive (Q4).

## Why a Q-by-Q lock

Cascade is easy to *start* (set flags down the tree) and easy to get *wrong*:
falsely completing interrupted tasks, killing jobs mid-write, or changing
`run_turn`'s contract without handling both call paths. Five questions.

---

## Q1 — What does `/stop` cascade to?

**Option A — the whole active delegated subtree (recommended).** `/stop` stops
the session's own turn AND every active Task reachable from it: root tasks via
`originating_session == session_id`, then their descendants via `parent_task`,
recursing while `workflow_state in _ACTIVE_STATES`. Matches the operator's "stop
everything" intent and Hermes' `/stop` (which cascades to all `_active_children`).

**Option B — session-only `/stop`, opt-in `/stop all` for the tree.** A two-verb
split. But Friday has no auto-interrupt to protect (Hermes' demotion-to-queue
guards the *default* 2nd-message interrupt, which Friday deliberately doesn't
have — queue-by-default). With no auto-interrupt, the demotion case never arises,
so the split adds a verb for no real protection. Rejected.

**Recommendation: A.** `/stop` always stops the whole active subtree.

---

## Q2 — How does the cascade reach each child?

**Option A — cooperative interrupt flags, reused from Design 83 (recommended).**
For each task in the active subtree, set its interrupt flag on the
`task::{name}` session (the same `request_interrupt` Design 83 already wrote).
Each child turn honors it at its next ReAct boundary and exits cleanly. A
*pending* child (not yet running) gets caught too — its turn clears the flag at
entry, so we also need to stop pending children from starting: mark them
directly (see Q3). No new mechanism; boundary-granular like the rest.

**Option B — RQ hard-kill each child (`send_stop_job_command`).** Immediate but
SIGTERMs mid-write and strands locks (see Q4). Rejected as the default.

**Recommendation: A.** Cooperative flags down the tree; pending children handled
via their state (Q3).

---

## Q3 — How is an interrupted child Task recorded? (the consequential one)

`run_turn` returning the interrupt reply must NOT read as success on the Task
path (today → `Completed`, `tasks/runner.py:531`).

**Option A — typed signal + `Cancelled` state (recommended).** `run_turn` raises
a dedicated `TurnInterrupted` exception instead of returning a sentinel string on
interrupt. Both call paths handle it explicitly:
- *Chat pipeline* (`gateway/service._run_pipeline`): catch it, write a clean
  "(interrupted by operator)" outbound (not the generic "(agent error)").
- *Task path* (`_run_task_agentic`): catch it, mark the child
  `workflow_state = "Cancelled"` with `blocked_reason = "interrupted"` — never
  `Completed`. Pending (not-yet-started) children in the subtree are set
  `Cancelled` directly by the cascade (they have no turn to interrupt).

Clean, unambiguous, and the typed exception can't be mistaken for a real reply.

**Option B — sentinel-string compare.** Keep the string return; the Task path
does `if summary == _INTERRUPTED_REPLY: mark Cancelled`. No contract change, but
fragile (a model could emit that exact text) and leaves the chat pipeline writing
the sentinel as a normal reply. Rejected.

**Recommendation: A.** Typed `TurnInterrupted`; child → `Cancelled` /
`interrupted`; pending children cancelled directly. Disclose the `run_turn`
contract change (string-return → may raise `TurnInterrupted`) in the ledger.

---

## Q4 — Hard kill (`/stop force`) — now or deferred?

The cooperative cascade (Q2) lands each node at its next ReAct boundary — within
~one LLM call (≤~97s worst case). The only thing it can't stop fast is a single
node wedged inside one long tool call (e.g. an infinite sandbox run).

**Option A — defer hard kill (recommended).** Ship cooperative cascade only.
`send_stop_job_command` SIGTERMs the worker horse mid-transaction (risking a
half-written turn) and leaves the session lock to expire on its 300s TTL — real
correctness cost for a narrow benefit. Revisit if a wedged-tool case actually
bites; the job timeout (600s) is the existing backstop.

**Option B — ship `/stop force` now.** Adds `send_stop_job_command(job_id)` per
node (chat job via `Chat Message.job_id`; task jobs via `job_name=task:{name}`) +
force-delete the session lock keys. More power, more failure surface, before
there's a proven need. Defer.

**Recommendation: A.** Cooperative cascade only; hard kill stays a named,
deferred follow-up.

---

## Q5 — `/stop` reply / UX

**Option A (recommended).** `/stop` reports the breadth: "🛑 Stopping this turn
and N delegated task(s)." (N = active subtree size). Zero delegated tasks → "🛑
Stopping the current turn." So the operator sees that the cascade reached the
fan-out, not just the visible turn.

**Recommendation: A.**

---

## Summary of what lands once Q1–Q5 are answered (recommended path)

- **`run_turn` raises `TurnInterrupted`** on interrupt instead of returning a
  string sentinel (Q3). New small exception type in `agent_runner`.
- **Chat pipeline** catches it → clean "(interrupted by operator)" outbound.
- **Task path** (`_run_task_agentic`) catches it → child `Cancelled` /
  `blocked_reason="interrupted"`.
- **Cascade helper** in `gateway/interrupt.py` (or a sibling): given a session_id,
  collect the active subtree (`originating_session` roots + `parent_task`
  descendants, `_ACTIVE_STATES`), set the interrupt flag on each running node's
  `task::` session, and set pending children directly to `Cancelled`. Recurses;
  no schema change.
- **`/stop` command** (`gateway/commands._cmd_stop`) calls the cascade and reports
  the count (Q5).

**Tests-first:**
1. `run_turn` raises `TurnInterrupted` (not returns) when the flag is set;
   chat pipeline writes "(interrupted by operator)"; Task path marks `Cancelled`
   / `interrupted` (never `Completed`). (Q3 — the core)
2. Cascade collects the active subtree: a root task (by `originating_session`) +
   its `parent_task` child, both active; a `Completed` sibling is excluded. (Q1)
3. Cascade sets the interrupt flag on each running node's `task::` session and
   `Cancelled`s a `Pending` child directly. (Q2 + Q3)
4. `/stop` with a 2-task fan-out replies "…and 2 delegated task(s)"; with none,
   the plain message. (Q5)
5. Regression: `/stop` on a session with no delegation still stops just the one
   turn (Design 83 behavior intact).

Nothing is built until Q1–Q5 are confirmed.
