# Design 62 — Agents Report Back

**Status:** LOCKED 2026-06-13 (all Qs as recommended; user said "go").
Lands as **one PR** (62) — both halves are small and tightly related.

## Why this exists — the plain English

The user's words after the first hands-on test:

> *"there is only one agent in the war room — what about other agents who
> are part of the projects, why are they not reporting back in the war
> room?"*

Two gaps, one theme — **agents do work silently**:

1. **The War Room only ever hears "Friday."** Every task posts
   `**[TASK-42]** — completed` with the agent profile buried as a
   `> Profile: Copywriter` detail line. The Copywriter, the Designer —
   the agents actually *doing* the work — never appear as speakers. The
   operator watching the War Room sees a single faceless voice.

2. **Nobody who requested work gets told it's done.** A Task carries no
   link to the conversation that triggered it. When a cron-dispatched
   pipeline task finishes, the only signal is the shared War Room post —
   the human who asked "@Friday plan the Legion pipeline" never gets a
   direct "done" back in their own channel. (Delegated tasks already
   report back inline through the parent's reply; this gap is the
   **independently-dispatched** path.)

## Compare with Hermes

Hermes is single-agent and in-process: the one agent's output IS the
reply, so "reporting back" is trivial — there's nothing to report *to*.
Friday runs **many** specialist agents across a durable pipeline, so it
has to make each one's voice and each one's completion visible. This is
the team-visibility surpass-Hermes axis ([[feedback_hermes-floor-not-ceiling]]).

## Q1 — Multi-agent War Room identity

*Recommendation:* the War Room message leads with the **agent profile as
the speaker**, not the task. The profile is always passed (never `None`),
and the format becomes:

```
🤖 Copywriter
   [TASK-42] completed · 3.2s
```

`post_task_update(task_name, event, details)` gains an explicit
`agent_profile` (pulled from the task's `assigned_to_profile` when the
caller doesn't pass one), and `_format_message_text` leads with it.
The blocked path — which currently passes `profile: None` — resolves the
profile from the task row so a blocked agent still has a face.

## Q2 — Tasks carry their origin

*Recommendation:* two new Task fields:

- `originating_session` (Data) — the Chat Message `session_id` that
  triggered this task (if any).
- `originating_platform` (Data) — `raven` / `cli` / `telegram` / etc.

**Population (honest v0.1 reality):** every chat→work path today runs
**inline** — `delegate-task` and `plan-project` execute in the calling
turn and report through the parent agent's reply. So they deliberately
leave origin **empty** (stamping it would double-report — once inline,
once via report-back). RandomPack pipeline tasks also have no session
(their report-back is the `randompack_bridge` write-back). So **no task
populates origin automatically yet**, and behaviour is identical to
today.

The fields + `report_back` are the **seam**: the moment any *async*
-from-chat flow lands (a future async-delegate, "queue this and tell me
when done"), it stamps `originating_session` and the requester gets a
direct reply for free. Shipping the seam now, fully tested, means that
flow is a two-line change later instead of a redesign.

Empty origin = no chat report-back (the War Room post is the only
signal). Non-empty = the requester gets a direct reply.

## Q3 — Report-back on terminal transition

*Recommendation:* when a task reaches a **terminal** state
(`Completed`, `Blocked`, `Review`) AND has an `originating_session`, the
runner writes one outbound `Chat Message` to that session, authored by
the task's agent profile:

```
✅ Copywriter finished "Write naming options" (TASK-42):
<the result summary>
```

Reuses the gateway's exact outbound-write shape (`session_id`,
`platform`, `direction=outbound`, `agent_profile`, `content`) so the
reply lands in the requester's channel through the same machinery every
other agent reply uses, and fires `publish_realtime("chat.outbound")`
so a live surface updates. Never raises — a report-back failure must not
break the task pipeline (the War Room/bridge defensiveness pattern).

## Scope

In: the three Qs above + tests + a live-bench proof.
Out: per-project Raven channels (still one shared War Room — design 60
Q7 deferral stands); per-specialist Raven *bot users* (the agents post
*as themselves* in text, not as distinct Raven bot accounts — that's a
larger Raven-identity slice); push to external platforms beyond writing
the Chat Message row (the surface adapters own delivery).

## What lands on disk — one PR (62)

- Task DocType: `originating_session`, `originating_platform`.
- `warroom/publisher.py`: agent-as-speaker formatting.
- `tasks/report_back.py` (new): the terminal-transition report-back.
- `tasks/workflow.py`: call `report_back` from the single transition
  chokepoint (after the RandomPack bridge); pass the agent profile into
  the War Room post so blocked agents still have a face.
- Tests: War Room speaker formatting; report-back writes a Chat Message
  to the right session; empty-origin writes nothing; non-terminal writes
  nothing; blocked still reports; never-raises.
- Live proof: create a task with an `originating_session`, transition it
  to Completed, see the outbound Chat Message land in that session AND
  the War Room post lead with the agent's name.

NOT touched (deliberately, per the population note): `handlers_delegate`
and `templates` — they run inline and must not double-report.
