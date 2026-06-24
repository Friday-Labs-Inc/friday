# Design 79 — Self-improvement review (the "agent that learns" step)

_Locked 2026-06-23. Ports Hermes's post-turn background review
(`agent/background_review.py`, triggered `conversation_loop.py:4313`) into
Friday, adapted to Frappe's worker model and Friday's governance spine._

## Plain English

Today a Friday agent answers you and stops — it never reflects on the
conversation to get better. Hermes does: after a chat, on a cadence, it quietly
re-reads the conversation and asks itself *"did the user reveal a preference I
should remember? did a reusable lesson emerge?"* and saves what it learns, so
the next conversation starts smarter. This design gives Friday that loop.

Two halves:
1. **Memory review** — save durable facts/preferences about the user (faithful
   port of Hermes's memory dimension).
2. **Skill proposal** — when a how-to lesson emerges, the agent **proposes** a
   skill change that a human approves; it never edits a governed skill itself.

## Source basis (read, not summarised)

- `agent/background_review.py` — the forked, tool-restricted review agent; the
  `_MEMORY_REVIEW_PROMPT` / `_SKILL_REVIEW_PROMPT` / `_COMBINED_REVIEW_PROMPT`
  text; the daemon-thread runner; the action-summary surfacing.
- `agent/conversation_loop.py:430,463,4297,4313` — the cadence counters
  (`_turns_since_memory` / `_memory_nudge_interval`,
  `_iters_since_skill` / `_skill_nudge_interval`) and the after-turn spawn,
  gated on `final_response and not interrupted`.

## Locked decisions

| Q | Decision | Source / rationale |
|---|----------|--------------------|
| Q1 Scope | **Memory review (faithful) + governed skill-proposal (adapted).** | User, 2026-06-23. |
| Q2 Trigger | After **conversational gateway turns only**, **every N** turns. N = `Agent Settings.memory_review_interval` (Int, default **3**, `0` = off). Pipeline tasks never trigger it. | User. Hermes ties learning to the human relationship; task turns are autonomous work. |
| Q3 Surfacing | A **channel note** ("💾 Learned: …") posted as the Friday bot to the session's Raven channel **+ an Execution Log row**. | User. Mirrors Hermes's "💾 Self-improvement review" note; adds Friday's audit trail. |
| Q4 Cadence counter | **Stateless** — derive from the count of inbound `Chat Message` rows for the session; fire when `count % N == 0`. No new counter field. | Frappe-adaptation of Hermes's in-process `_turns_since_memory`. |
| Q5 Async mechanism | An **RQ job on the `friday` queue**, `enqueue_after_commit`, fired after the outbound turn is written + marked processed. Best-effort; never delays or affects the user's reply (already returned). | Frappe-adaptation of Hermes's daemon thread. Benefits from the Design-(concurrent-worker) pool just shipped. |
| Q6 Review execution | **Reuse `run_turn`** with two new optional params: `allowed_skills` (hard-restrict the toolset to the review tools) and `skip_compression=True` (a review must not compress the real session). Runs under the **original `session_id`** so the real conversation is the context; `run_turn` writes **no** Chat Messages, so the session is never polluted. | Faithful to Hermes's "restricted fork inheriting the parent runtime + the conversation snapshot." |
| Q7 Attribution | The review job sets `frappe.flags.friday_dispatch_context = {agent_profile, session_id: <original>}` so a saved memory attributes to the right agent + session + project. | Matches how `remember` already attributes (`skills/handlers_memory.py`). |
| Q8 Prompts | Port `_MEMORY_REVIEW_PROMPT` verbatim. Adapt the skill half to a **propose-don't-edit** instruction. Use the combined prompt when both halves are in scope. | true-1to1: memory prompt verbatim; skill prompt re-framed (divergence, disclosed). |
| Q9 Skill proposal | A new `propose_skill_change` skill creates a **Pending** proposal record for a human; it **never** mutates a `Skill`. (Slice 2.) | Governance: agents never self-edit governed skills ([[v01-skills-first-party-trust]]). |
| Q10 Safety | Review job is best-effort: any failure is logged + an Execution Log row, **never raised** (the user already has their reply). Tools hard-restricted via `allowed_skills`. Memory writes still pass the permission matrix. | Mirrors Hermes's swallow-and-log; honours the governed path. |

## Divergence classification (true-1to1)

- **Memory review → frappe-adaptation (faithful).** Daemon thread → RQ job;
  in-process counter → Chat Message count; otherwise the same loop, the same
  restricted-tools review, the verbatim memory prompt.
- **Skill review → diverged (governance improvement).** Hermes self-edits
  `SKILL.md`. Friday **proposes → human approves**, never auto-applies. Disclosed
  loudly: Friday agents do not mutate governed skills.
- **Output suppression / prefix-cache fork tricks → simplification (omitted).**
  Hermes's stdout redirect, suppress_status, and cached-system-prompt
  inheritance are in-process-thread concerns; an RQ job is already isolated, so
  they don't apply. Disclosed.

## Flow

```
conversational turn completes (gateway _run_pipeline, outbound written)
        │  enqueue_after_commit, if memory_review_interval>0 and inbound_count % N == 0
        ▼
friday queue → self_review.run_review(session_id, profile)         [RQ job]
        │  set dispatch context {profile, session_id}
        ▼
run_turn(profile, session_id, REVIEW_PROMPT,
         allowed_skills={remember, propose_skill_change},
         skip_compression=True)
        │  model reflects on the real conversation; calls remember / propose_skill_change
        ▼
saved? → post "💾 Learned: …" to the channel as the Friday bot + Execution Log row
none?  → silent (no note); optional debug log
```

## Slice plan

- **Slice 1 — memory-review core (this PR).** `run_turn` gains `allowed_skills`
  + `skip_compression`; new `agent_runner/self_review.py` (cadence check, the
  RQ review job, the memory prompt, surfacing); `Agent Settings.memory_review_interval`
  field; trigger wired in `gateway/service.py`; channel note + Execution Log;
  tests-first; migrate gate; rollout doc.
- **Slice 2 — governed skill-proposal.** `propose_skill_change` skill +
  bootstrap; a Pending proposal surface (reuse the approval/Workflow Request
  path); combined review prompt; tests.
- **Slice 3 — polish.** Dedup repeated learnings, "nothing to save" quieting,
  cadence tuning from live use.

## Tests-first contract (Slice 1)

1. Cadence: review enqueued only when `interval>0` and `inbound_count % interval == 0`; never on the pipeline path. (mock `frappe.enqueue`.)
2. `allowed_skills` filters the toolset in `run_turn` (a non-allowed skill is absent from the tool list).
3. `skip_compression=True` → `maybe_compress_session` is not called.
4. Review job sets the dispatch context to the original session + profile.
5. Surfacing: a successful `remember` in the review → one bot channel note + one Execution Log row; "Nothing to save" → no note.
6. Best-effort: an exception inside the review job is logged, not raised.

Default `memory_review_interval = 3`; `0` disables the whole feature (flag-off
parity with today).
