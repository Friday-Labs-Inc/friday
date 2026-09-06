# Design 68 — Agent Role Contract (2026-06-14)

## What changed and why

Every Friday agent is now declared as one of three roles: **Orchestrator**, **Specialist**, or **Worker**. The role isn't a label — it changes how the runtime treats the agent in three concrete ways:

1. **System prompt** — the prompt builder injects a short role preamble after the GOVERNANCE block. An orchestrator is told to plan and coordinate; a specialist is told to go deep in its domain; a worker is told to execute one task precisely without expanding scope.
2. **Default approval threshold** on first insert — Orchestrator=`high`, Specialist=`medium`, Worker=`low`. Workers are most-gated because they run in bulk, unattended; a runaway worker doing 1000 wrong things is the failure mode to prevent.
3. **Default skill seed** on first insert — new Orchestrators with no permitted skills get the broad read tools (`read_record`, `list_records`, `list_project_files`) so they can survey project state without the operator having to remember which baseline to grant. Specialists and Workers stay blank.

Defaults *only* fire on creation, and *only* when the relevant field is blank. An operator who explicitly picks an approval level or a skill set always wins over the default — defaults fill the gap, never override a decision.

## Why this is a foundation, not a feature

This design is the precondition for **Design 69 (Multi-Agent Delegation)**. When `delegate_task` lands, it will be Orchestrator-only — and the runtime will know which agent is an orchestrator by reading `agent_role`, not by guessing from skill membership. Hermes leaves "can this agent delegate?" implicit in tool grants; Friday makes it explicit on the profile row, auditable, and governed.

## Operator-facing changes

- **Agent Profile form**: new `Agent Role` Select field, placed right after `Profile Name`. Default value `Specialist`.
- **Model picker hint**: when the operator picks a role, a help line appears next to `Model Provider` recommending a tier (Heavy/Standard/Light) with example models. It's a hint, never an enforcement — operators stay in control.

## Migration

A patch (`patches/v1_0/backfill_agent_role.py`) sets every existing Agent Profile with a blank `agent_role` to `Specialist`. Specialist is the gentlest role — no skill seed, no approval-threshold change from the existing `medium` default, prompt frame closest to the pre-68 shape. Existing behavior is preserved exactly.

## What does NOT ship here

- The `delegate_task` skill and sub-agent runtime — that's Design 69.
- Tier enforcement (refusing a Worker on Opus) — out of scope by Q2; suggestion, not enforcement.
- An "intelligence tier" sibling field — deferred per Q7; observe role behavior first.

## Verification

- 19 new unit tests in `test_agent_role.py` covering: field existence, default value, field order, role preamble per role, governance-before-role ordering, operator-prompt-after-role ordering, fallback to Specialist for blank/missing role, default approval per role, no-override of operator-set approval, Orchestrator skill seed, no-reseed when skills already present, no seed for Specialist/Worker, patch backfill scope.
- Existing test suite untouched.

## Where to read more

- Locked design: [`docs/design/68-agent-role-contract.md`](../design/68-agent-role-contract.md)
- Controller: `friday/friday_core/doctype/agent_profile/agent_profile.py`
- Prompt scaffolding: `friday/friday_core/llm/prompt_builder.py`
- Form: `friday/friday_core/doctype/agent_profile/agent_profile.js`
- Patch: `friday/friday_core/patches/v1_0/backfill_agent_role.py`
