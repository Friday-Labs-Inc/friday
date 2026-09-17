# Design 62 — Agents report back (2026-06-13)

## The one-sentence version

Every agent now speaks in the War Room **as itself**, and a finished task
sends a direct "done" back to the conversation that asked for it.

## What you would have seen, before today

You watch the War Room while a project runs. Every line reads
`**[TASK-42]** — completed`. The Copywriter, the Designer — the agents
actually doing the work — never appear. It's one faceless voice. And when
a task finishes, nobody who asked for it gets told; the only signal is
that shared War Room line.

## What this PR ships

**1. Multi-agent War Room identity.** The message now leads with the
agent as speaker:

```
🤖 Copywriter
   [TASK-42] completed · 3.2s
```

A blocked agent still has a face (the blocked path used to pass
`profile: None`; now it resolves the agent from the task).

**2. Agents report back to the requester.** Tasks gain
`originating_session` + `originating_platform`. When a task reaches a
terminal state (`Completed` / `Review` / `Blocked` / `Cancelled`) AND it
knows the conversation it came from, the agent writes one outbound Chat
Message to that session — authored by the agent profile, reusing the
gateway's exact outbound shape so it lands in the requester's channel
like any other reply:

> ✅ Copywriter finished "Write naming options" (TASK-42):
> Midnight Roast, Northbound, Loomwork

Never raises — a report-back failure cannot break the task pipeline.

## Honest scope note

Every chat→work path today runs **inline** (`delegate-task`,
`plan-project`) and already reports through the parent agent's reply, so
they deliberately leave `originating_session` empty — stamping it would
double-report. RandomPack pipeline tasks have no session (their
report-back is the backend write-back). So **no task populates origin
automatically yet**, and behaviour is identical to today.

The fields + `report_back` are the **seam**: the moment any *async*
-from-chat flow lands ("queue this and tell me when done"), the requester
gets a direct reply for free — a two-line change instead of a redesign.

## Why we know it works

- **7 new** `test_report_back.py` — War Room leads with the agent;
  report-back writes a Chat Message to the right session as the agent;
  empty-origin writes nothing; non-terminal writes nothing; blocked
  reports trouble (not false success); never raises on write failure.
- All adjacent suites green: warroom (15), workflow (15), reconciler
  (12), command-center (20), randompack-surface (21).

**Live proof on `friday.localhost`:** created a task with
`originating_session=PROOF-SESSION-001`, transitioned it to Completed →
exactly one outbound Chat Message appeared in that session, authored by
`Copywriter`, with the result summary. The War Room format rendered
`🤖 Copywriter / [TASK-42] completed`.

## What's NOT in this PR

- Per-project Raven channels (still one shared War Room — design 60 Q7).
- Per-specialist Raven *bot users* (agents post as themselves in text,
  not as distinct Raven accounts — a larger Raven-identity slice).
- External-platform delivery beyond writing the Chat Message row (the
  surface adapters own delivery).

## Operator note

Run `bench --site <site> migrate` to add the two Task fields. No
provisioning command needed — the behaviour is automatic.
