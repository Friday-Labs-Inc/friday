# Rollout — Architect-doc gap batch #1 (2026-06-17)

## Plain English

A workflow comparison of Friday's orchestration stack against the AI-Agents-Architect
reference doc surfaced ten gaps. This first batch ships **two small fixes** that
the adversarial design review marked safe to ship immediately, plus a **design-lock
note** for a third fix that needs a decision from the user before code lands.

The two shipped fixes are both invisible to anyone watching the UI but
visibly improve agent output quality:

1. **The naming agent now reads the strategy phase's positioning before writing names.**
   Without this, every name candidate was a generic industry pun because the
   naming agent only ever saw the brief, not what the strategist actually decided.
   Pre-existing quality bug; one-line fix.

2. **Tool definitions sent to the LLM now include both the description and the
   `when to use` guidance.** Previously the loader's `to_tool_definition()` did an
   OR fallback that silently dropped `when_to_use` whenever `description` was set
   — half the per-skill metadata the operator carefully wrote in Desk was never
   reaching the model. Now they're concatenated under a `When to use:` header so
   the model gets the trigger conditions alongside the one-liner.

The design-lock note is for the `role_gate` field — see
`docs/design/78-role-gate-semantics.md` for the four questions the user needs
to answer before code touches that path.

## Why we're shipping batch #1 separately

The pipeline output upgrade (Design 77, in progress) requires more design work
based on a critic verdict of "rework". These two fixes are independent of that
design and fix real quality bugs today; holding them for the bigger redesign
would mean shipping low-quality agent output to the investor demo for no reason.

## What changed (the diff in human terms)

### Naming phase reads strategy
`domains/randompack_brand.py` (the bundle):
- `PHASES[naming].skills` now lists `get-phase-outputs` in addition to `get-brand-brief`
- The naming phase prompt is rewritten so the agent calls `get-phase-outputs` FIRST,
  reads the strategy phase's positioning + insight + differentiating idea, then
  produces names that reflect that positioning. Each name's rationale must tie
  back to the positioning, not generic industry vibes.

The `Brand Copywriter` profile already had `get-phase-outputs` permitted (it
was added during Phase 1.1 for the gate1_prep phase). So the only real change is
the per-phase skill allow-list and the prompt itself.

### Tool definition quality
`skills/loader.py` — `to_tool_definition()`:
- Previously: `description = (skill.description or skill.when_to_use or "").strip()`
  — this returned ONE of the two fields, whichever was set first.
- Now: both fields are read separately. If both are set, the returned description
  is `"{description}\n\nWhen to use: {when_to_use}"`. If only one is set, it's
  used directly without the header. If both are empty, the description is empty.

The LLM now sees the trigger guidance the operator wrote, which the architect
doc calls out as a tool-definition best practice for better tool selection.

## What did NOT change

- The `role_gate` Skill field still uses the hardcoded `_ROLE_GATED_SKILLS` dict
  in `loader.py`. This is the **critical security gap** the comparison found —
  but the fix has a type-mismatch landmine (the field is `Link → Role` while the
  current comparison would need to be against `profile.agent_role` which is a
  `Select`). Fixing it without a decision would silently break in production the
  moment any operator populates the field. Design 78 documents the four
  questions; code waits for the user's answer.
- Memory importance scoring, supervisor synthesis, plan-and-execute,
  console memory inspection, chat-turn LLM cost linking, reasoning-trace capture,
  and per-turn tool cap are all in the gap plan as later branches.

## How we proved it works

- `bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_skill_loader` →
  10/10 green, including two new tests (`test_tool_description_merges_when_to_use`
  and `test_tool_description_falls_back_to_either`) that lock both behaviors.
- `bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_engine_routing` →
  4/4 green after resetting the polluted local workflow (dev bench had stale
  Intake state from an earlier integration branch — unrelated to this work).
- `bench --site friday.localhost migrate` → clean, RandomPack bundle re-provisioned
  with the updated naming-phase skill list.

## Demo impact

The next Brand Brief that flows through the engine will produce noticeably
better-grounded name candidates (each rationale references the positioning,
not just the industry). The change is visible in the naming Task's `result`
JSON and in the gate1_prep client-facing summary.

## What's next

- The user decides on `role_gate` semantics (Design 78) → small code branch
  follows.
- Design 77 (pipeline output upgrade) returns to design phase after a rework
  per the critic's verdict; the next critic-driven pass will resolve the four
  critical findings (skill wiring, attachment target conflation, push-deliverables
  scope, naming phase quality — the last is now fixed by this batch).
