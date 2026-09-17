# Design 84 — Steer a running turn (`/steer <text>`) (Q-by-Q lock)

**Status:** LOCKED 2026-06-24 — Q1–Q5 all answered as the recommended path
(A throughout). Tests-first, then code. Triggered by the gateway deep audit
(`docs/ports/hermes-port-ledger.md` § Gateway deep audit) — STEER is the last of
the three session-manager modes (queue ✅ design 80, interrupt ✅ design 83,
steer = this). Lands the `/steer` command deferred from Design 82.

## The gap, in plain English

`/stop` (Design 83) halts a running turn. But often you don't want to halt it —
you want to *nudge* it: "use the staging DB, not prod", "keep it under 200
words", "also check the error log". Steer injects that guidance into the running
turn **without restarting it**: the agent sees the nudge on its next think/act
cycle and adapts. Friday has no way to do this today — `run_turn`'s loop
(`agent_runner/runner.py`) only ever sees the original message.

## What the source says (grounded, both sides)

**Hermes** (`run_agent.py:1863` `steer()`, `conversation_loop.py:736-784` drain):
- `steer(text)` stashes `_pending_steer`. Multiple steers **coalesce** —
  concatenated with newlines (`run_agent.py:1895`).
- The loop drains it **before the API call** and appends it to the **last tool
  result's content** with the marker `"\n\nUser guidance: {text}"`
  (`conversation_loop.py:754`). The model reads the steer as part of the tool
  output on its next iteration — deliberately framed as "more context on what
  just happened", NOT a new user demand. This framing is the subtle, proven bit.
- If there's no tool message yet (first iteration), the steer stays pending for
  the next batch (`:775-784`).
- A steer landing after the final assistant turn is **not dropped** — returned as
  `result["pending_steer"]` (`:4281`) so the gateway can replay it.
- `steer()` returns False on empty text (ignored).

**Friday's substrate** (already proven by the interrupt port, Design 83):
- A Redis key per session via `frappe.cache()` is the cross-process channel
  (`/steer` arrives in the web process; the turn runs in a worker).
- The boundary check point already exists — Design 83 added an interrupt check at
  the top of each ReAct iteration (`runner.py`). Steer drains at the same point.
- `run_turn` clears its session's interrupt flag at entry; steer mirrors that.
- The session lock serialises turns (one per session), so no generation counter.

## Why a Q-by-Q lock

"Inject text into the loop" hides five decisions: what triggers it, HOW the text
enters the conversation (the framing choice above), how multiple steers combine,
what happens to a steer that misses its turn, and the operator UX. The injection
shape (Q2) genuinely changes model behavior. Five questions.

---

## Q1 — What triggers a steer?

Like `/stop`, this must respect Friday's queue-by-default stance (Design 80): a
plain follow-up message queues, it does not steer.

**Option A — `/steer <text>` only (recommended).** The single trigger is the
explicit command. A plain message still queues and drains next turn. Consistent
with `/stop` (Design 83, Q1) and the queue-by-default divergence.

**Option B — auto-steer on a second message (a Hermes busy-mode).** Reopens the
queue-by-default divergence; surprises an operator who just wanted to add a note.
Rejected.

**Recommendation: A.** `/steer <text>` is the only trigger; operator-tier
(`Friday Operator`), like the other write commands.

---

## Q2 — How does the steer text enter the running conversation?

This is the consequential one — it changes how the model treats the nudge.

**Option A — Append to the last tool result, Hermes-faithful (recommended).**
At the boundary, if the last message is a tool result (`role:"tool"`), append
`"\n\nUser guidance: {text}"` to its content. The model reads the steer as part
of the tool output — "here's more context on what just happened" — which is the
proven Hermes framing (`conversation_loop.py:754`). Fallback: when there's no
tool result yet (iteration 0 edge), append a new `user` message with the same
marker. Preserves the subtle behavior the faithful-port rule protects
(`feedback_true-1to1-ports`).

**Option B — Always a separate `user` message.** Simpler code (no role check),
valid on MiniMax's OpenAI wire. But the model reads it as a brand-new user demand
mid-task, not as guidance on the in-flight work — a behavioral divergence from
Hermes for no real Frappe reason. Rejected as the default.

**Recommendation: A.** Append-to-last-tool-result with the `User guidance:`
marker; user-message fallback only at the no-tool-yet edge. Disclose the
fallback in the ports ledger.

---

## Q3 — How do multiple steers combine?

An operator may fire several nudges during one long turn.

**Option A — Single slot, coalescing, drained at each boundary (recommended).**
`/steer` does a read-modify-write: `existing + "\n" + new` (Hermes' newline
concat, `run_agent.py:1895`). The boundary reads the slot, injects it, and clears
it. Sequential steers across boundaries each land; steers within one boundary
window coalesce. Matches Hermes; reuses the Design 83 key pattern
(`friday:steer:{session_id}` holding text, not a flag).

**Option B — Redis list (FIFO), inject each separately.** More faithful to a
"queue of nudges" but needs raw redis list ops (not the site-namespaced
`set_value` wrapper the interrupt flag uses) and injects N messages per boundary.
More surface for negligible gain single-tenant. Defer.

**Recommendation: A.** Single coalescing slot, read-and-clear at each boundary.

---

## Q4 — What happens to a steer that misses its turn?

A `/steer` can arrive after the agent's final reply (no boundary left to consume
it). Hermes preserves it as `pending_steer`; Friday clears flags at entry.

**Option A — Clear-at-entry; a missed steer is dropped (recommended).**
`run_turn` clears `friday:steer:{session_id}` at entry (parallel to the
interrupt flag, Design 83 Q3), so a steer from a prior turn never leaks into the
next one. A steer landing after the turn ends is dropped — the operator simply
sends it as a normal message (which the next turn reads as input anyway). Simple,
consistent with interrupt. Disclosed divergence from Hermes' `pending_steer`
preservation.

**Option B — Preserve a leftover steer into the next turn.** Faithful to Hermes,
but replaying stashed text as next-turn context is real complexity (where does it
go in the prompt? does it duplicate a normal message the operator also sent?).
Defer until there's a concrete need.

**Recommendation: A.** Clear-at-entry; missed steer dropped. Note the divergence.

---

## Q5 — Operator UX + empty input

**Option A (recommended).** `/steer <text>` (operator-tier) replies
"↪ Steering the current turn." (its Design 82 `is_command` audit rows). `/steer`
with no text is rejected with a usage hint ("usage: /steer <guidance>"). A
`/steer` issued when nothing is running sets the slot, which the next turn clears
at entry — effectively a no-op, matching Q4 (operator resends as a normal
message). No new-turn message is created for the steer text itself; it rides into
the running turn per Q2.

**Recommendation: A.**

---

## Summary of what lands once Q1–Q5 are answered (recommended path)

- **`/steer <text>` command** in the Design 82 table (`gateway/commands.py`),
  operator-tier. Handler coalesces into `friday:steer:{session_id}` and replies
  "↪ Steering the current turn."; empty text → usage hint.
- **Steer helpers** in `gateway/interrupt.py` (or a sibling `steer.py`):
  `push_steer(session_id, text)` (coalescing), `drain_steer(session_id)` (read +
  clear, returns text or None), `clear_steer(session_id)`. Best-effort reads
  (a cache hiccup never breaks the turn — Design 83 posture).
- **Runner hook** in `agent_runner/runner.py`, at the existing boundary (right
  after the interrupt check): drain the steer; if present, append
  `"\n\nUser guidance: {text}"` to the last tool result (or a user message at the
  no-tool-yet edge), then let the loop's `provider.chat` see it this iteration.
  Clear the steer slot at entry (Q4).

**Tests-first** (before the runner edit):
1. `push_steer` coalesces (two pushes → newline-joined); `drain_steer` returns
   the text then clears (second drain → None). (helpers)
2. `run_turn` clears the steer slot at entry (a stale steer does not inject).
   (Q4)
3. With a steer pending at a mid-loop boundary, `run_turn` appends
   `User guidance: <text>` to the **last tool result** before the next
   `provider.chat`, and the turn continues (not interrupted). (Q2 core)
4. No-tool-yet edge: a steer at iteration 0 injects as a `user` message. (Q2
   fallback)
5. `/steer hello` dispatch pushes the steer + replies; `/steer` with no text is
   rejected; both operator-gated. (Q1 + Q5 + Design 82 Q4)

Nothing is built until Q1–Q5 are confirmed.
