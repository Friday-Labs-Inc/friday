# get-brand-brief: hand the agent the actual brief — 2026-06-14

## One sentence

The `get-brand-brief` tool told the agent the brief was "loaded" but handed it
**none of the content**, so agents (correctly) refused to fabricate and the
whole RandomPack pipeline produced refusals instead of work — this puts the
real brief content where the agent can see it.

## What was wrong

Found by driving the real RandomPack → Friday pipeline on the local bench (a
"Friday Labs Inc" sample). The first task (`strategy`) ran on real Minimax,
called `get-brand-brief`, and then output:

> "the tool returned only a stub: `Brand Brief BB-0008 (Friday Labs Inc) loaded`
> … with no actual content … I won't invent a strategy from a missing brief."

The agent did exactly the right thing (anti-fabrication governance, design 66).
But the brief BB-0008 was fully populated — industry, audience, personality, the
lot. The content just never reached the model.

Root cause: the dispatcher surfaces **only** the handler's `result` string to
the model (`dispatcher.py`: `content=outcome.get("result", "Done.")`). Sibling
dict keys are dropped. `get_brand_brief` put the content in sibling keys
(`industry`, `target_audience`, …) and only `"Brand Brief … loaded"` in
`result`. So the agent saw the stub and nothing else.

## The fix

Build the `result` string from the brief's actual fields, with readable labels:

```
Brand Brief BB-0008:
- Business name: Friday Labs Inc
- Industry: AI developer tools / agentic automation
- Target audience: Engineering leaders and platform teams adopting AI agents
- Brand personality: trustworthy, precise, bold, engineered
- ...
```

Empty briefs now say `(no content captured on this brief)` instead of looking
"loaded". The structured sibling keys are kept (harmless), but the content the
agent depends on now lives in `result`, where the dispatcher actually passes it.

## Why the test didn't catch it

`test_returns_content_fields` only asserted the business *name* appeared in
`result` — and the name was always in the "… loaded" string, so it passed while
every other field was missing. Strengthened to assert industry, audience, and
personality values all appear in `result`, plus a new test that an empty brief
says so. (The bug was invisible to the old mock because it never checked that
the *content* — not just the name — reached the model.)

## Verification

- `test_brand_skills` — 11 green (strengthened content assertions + empty-brief case).
- `bench migrate` clean.
- Live re-run of the FLI-001 pipeline on the bench (after restarting the worker
  so it picks up the new handler): agents now receive the brief and produce real
  strategy / naming / directions instead of refusals. (Captured in the PR.)

## Note

This is a contract gotcha worth remembering for ALL skill handlers: the model
sees `result` ONLY. Anything the model must act on goes in the `result` string,
not sibling keys. Several read-style handlers should be audited for the same
trap.
