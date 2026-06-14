# Design 68 — Agent Role Contract

**Status:** Locked 2026-06-14. Implementing now.

## The pain

Per-agent model selection already works (Agent Profile has `model_provider` + `model_name`), but every agent is shaped the same way regardless of what it's *for*. An "orchestrator" that plans and delegates needs a different prompt frame, different default skills, and a different model tier than a "worker" that runs one narrow task. Today the operator has to wire all that by hand on every profile — and there's no contract telling the runtime which is which.

This design adds a **role contract** so the system knows whether an agent is an Orchestrator, a Specialist, or a Worker. The role then drives prompt framing, default skills, default approval thresholds, and a model tier hint in the form. It's also the **precondition for multi-agent delegation** (Design 69, planned) — `delegate_task` will be Orchestrator-only.

## Why not just "tag" agents

A free-text tag would let operators write "orchestrator" with whatever meaning they want; the runtime couldn't enforce anything. A Select field with three values is a *contract*: code can branch on it, defaults flow from it, tests can pin it.

## Hermes comparison

Hermes has no explicit role field — every agent run is one config. Sub-agent spawning (`delegate_task`) is gated by the *tool* being present, not by a role. Friday's choice to make the role explicit is a **surpass-Hermes** move ([[hermes-floor-not-ceiling]]): governance requires that "this agent can delegate" be a property of the agent, auditable on its profile row, not an accident of which skills were granted. Same with model tier — Hermes leaves it entirely to the operator; Friday surfaces a recommendation so a cheap orchestrator running on Haiku gets a visible warning instead of silent under-performance.

## Locked Qs

### Q1 — Three roles enough?
**Locked: Yes. Orchestrator | Specialist | Worker.** Three is enough to span the design space without paralysis. Mapping:

- **Orchestrator** — plans, delegates, surveys. Broad read access. Heavy reasoning model.
- **Specialist** — one domain (research, code review, ops). Standard model. Default if unspecified.
- **Worker** — one narrow task per run (classify, transform, format). Cheap fast model. Most-gated.

### Q2 — Role binds or suggests a model tier?
**Locked: Suggests.** The form shows a recommended tier next to `model_provider` when the operator picks a role. If they pick a model below the recommendation, the form shows a yellow hint — no error, no enforcement. Reason: operators may want a cheap orchestrator during testing, or a heavy worker for a hard one-off; the system shouldn't second-guess them.

Tier mapping (operator-visible):

| Role | Tier | Examples |
|---|---|---|
| Orchestrator | Heavy | claude-opus-4-8, claude-sonnet-4-6, gpt-5 |
| Specialist | Standard | claude-haiku-4-5, gpt-4o, gemini-2.5-pro |
| Worker | Light | minimax-m2, claude-haiku-3-5, gemini-2.5-flash |

The tier name is informational — the actual model is still chosen by the operator from the `LLM Provider` row.

### Q3 — Roles change the system prompt?
**Locked: Yes.** `prompt_builder._build_system_prompt` prepends a role preamble (3–5 lines) after the existing GOVERNANCE block. The preamble is short and operational — it tells the agent how to frame its work, not what to think.

```
ORCHESTRATOR ROLE: Your job is to plan and coordinate. Break complex work into
small tasks, delegate when sub-agents exist, and synthesize results. Prefer
asking clarifying questions over guessing on scope.
```

```
SPECIALIST ROLE: You are a domain expert. Go deep in your area; ask for help
when a question falls outside it. Cite the records and files you used.
```

```
WORKER ROLE: Execute one task precisely. Do not expand scope. If the request
is ambiguous, ask one clarifying question; otherwise complete and report.
```

The operator's `system_prompt` still rides after the frame verbatim — the role preamble doesn't override their voice, it composes with it.

### Q4 — Role drives default skills?
**Locked: Yes for Orchestrators only.** When a new Agent Profile is created with `agent_role = Orchestrator` AND `permitted_skills` is empty, seed it with the broad read tools: `read_record`, `list_records`, `list_project_files`. Reason: an orchestrator that can't read project state can't plan. Specialists and Workers keep the existing "operator picks everything" behavior — too many use cases to seed sensibly.

Editing an existing profile never reseeds skills (only on first insert with the field empty).

### Q5 — Role drives default approval threshold?
**Locked: Yes.** Sensible defaults on first insert when `requires_approval_above_risk` is unset:

| Role | Default approval-above |
|---|---|
| Orchestrator | `high` (trusted to plan; only the riskiest tools need a human) |
| Specialist | `medium` (default of the current system, no change) |
| Worker | `low` (narrow tools, most predictable, but most-gated by default) |

This may look inverted ("workers are most gated?") — it's deliberate. Workers run unattended, in bulk, at speed; a runaway worker doing 1000 wrong things is the failure mode to prevent. Orchestrators are typically supervised and synthesize before acting.

### Q6 — Existing profiles on migration?
**Locked: Specialist.** A patch in `friday_core/patches/v1_0/backfill_agent_role.py` sets `agent_role = "Specialist"` on every existing Agent Profile that has the field blank. No behavior change for existing profiles (Specialist's prompt frame is the gentlest, default approval is the existing `medium`, no auto-skill seeding).

### Q7 — "Intelligence tier" sibling field?
**Locked: Deferred.** Get the role contract right and observe operator behavior before adding a second axis. The role's tier hint covers the immediate UX need.

### Q8 — One orchestrator per project?
**Locked: Unlimited.** No cap. Operators decide. Multi-orchestrator setups (e.g. one orchestrator per product line in the same Frappe site) are legitimate. Code that needs to find "the orchestrator" should query by `agent_role = "Orchestrator"` and disambiguate by project, not by uniqueness.

## What ships in this PR

- `agent_profile.json`: new `agent_role` Select field (Orchestrator | Specialist | Worker, default Specialist), placed after `profile_name`.
- `agent_profile.py`: `before_insert` hook fills role defaults (approval threshold; orchestrator skill seed).
- `llm/prompt_builder.py`: `_build_system_prompt` prepends role preamble after the governance block.
- `agent_profile.js`: on `agent_role` change, show recommended-tier hint next to `model_provider`.
- `patches/v1_0/backfill_agent_role.py`: backfill existing profiles to Specialist (registered in `frappe/patches.txt`).
- `tests/test_agent_role.py`: full coverage — field exists, default, prompt scaffolding per role, default approval per role, orchestrator skill seed, no reseed on existing.
- `docs/rollouts/design-68-agent-role-contract-2026-06-14.md`: rollout narrative.

## What does NOT ship

- `delegate_task` skill and sub-agent runtime — that's **Design 69 (Multi-Agent Delegation)**, which builds on this contract.
- Tier enforcement (refuse a Worker on Opus) — out of scope per Q2.
- The "intelligence tier" sibling field — deferred per Q7.

## Verification (the diff test)

Every changed line traces to: "the operator picks a role, the runtime treats orchestrators/specialists/workers differently."
