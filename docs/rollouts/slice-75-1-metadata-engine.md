# Slice 75-1 — The metadata-driven domain engine (Phase 1)

**Ships:** Design 75 Phase 1 — Friday becomes a generic, governed workflow
engine. A "domain" (brand identity, and later data-centre ops or research) is
now defined by **data**, not Python. The RandomPack brand pipeline is the first
domain, expressed entirely as a bundle of records.

**Status:** built, migrate-clean, and proven locally end-to-end (9 tests +
a full live rollback-safe walk). Real-LLM E2E on Legion is the final gate.

---

## What changed, in plain English

Before this slice, the RandomPack brand pipeline was **hardcoded**: a Python
list of phases (`RANDOMPACK_PIPELINE`) and a dict of skills (`TEAM_SKILLS`).
Adding a new kind of work (say, a data-centre incident pipeline) meant writing
new Python. That made Friday "the RandomPack engine," not a reusable framework.

Now the engine knows **nothing** about brands. It reads three kinds of data and
just runs them:

1. **A Frappe Workflow** on the work-item (here, the existing `Brand Brief`):
   the states a job moves through and the role-gated transitions between them.
2. **Friday Workflow Transition Meta** rows: for each *agent* transition, which
   role owns it, which skills it needs, and the prompt the agent runs.
3. **Agent Profiles** tagged with a `discriminator_role`: the team. The engine
   routes each phase to the profile whose `discriminator_role` matches the
   transition's owner — a direct lookup, no guessing.

Add a new domain by adding these records. No engine code changes.

## The pieces

| Piece | Where | What it does |
|---|---|---|
| `Domain Bundle` | doctype | Manifest: "this DocType is governed by this Workflow." One active bundle per work-item DocType. |
| `Friday Workflow Transition Meta` | doctype | The agentic config bound to one Frappe transition (role, skills, prompt, limits). |
| `engine/workflow_engine.py` | code | On a work-item save, dispatches the agent phase (if any) waiting at the current state. |
| `engine/phase_dispatcher.py` | code | Resolves the owner by `discriminator_role`, renders the prompt, creates the Task already Assigned. |
| `engine/advance.py` | code | When a phase's Task completes, advances the work-item to the next state (after commit, never inline). |
| `engine/governance.py` | code | `acting_as(user)` — the guard that makes role-gating real inside a worker. |
| `domains/randompack_brand.py` | data generator | Provisions the whole brand bundle (workflow, states, transitions, meta, team, gateway). |

## The brand pipeline (the first bundle)

`Strategy → Naming → Directions → Gate 1 Prep → [Gate 1 Review] → Buildout →
Gate 2 Prep → [Gate 2 Review] → Guidelines → Delivered`

- The seven non-gate steps are **agentic**, routed across three specialists:
  Brand Strategist, Brand Copywriter, Creative Director.
- The two `[...]` gates are **client decisions** — fired only by a gateway
  account that holds the client-reviewer role. No agent can approve its own
  work past a gate.

## Two safety rules baked in (from the design's adversarial review)

1. **Role-gating is real in the background.** Frappe lets `Administrator`
   (which is who a worker runs as) fire any transition. So before firing a
   transition the engine switches to the *acting* user — the agent's own system
   user, or the gateway. An agent's user holds only its own role, so it can
   fire only its own steps. Proven: a wrong agent firing a transition raises;
   an agent trying to open a gate raises; only the gateway opens gates.
2. **Advancing never runs inline.** When a Task completes, the work-item is
   advanced in a *separate* job after the transaction commits — so a completing
   task can never trigger a chain that rolls itself back and double-runs.

## How it was verified (no LLM spend, nothing left behind)

- `bench migrate` clean; all new columns + doctypes present.
- A live walk of a Brand Brief through every state — routing, the wrong-user
  block, both gates, and the duplicate-role guard — then rolled back. Because
  the agent runner enqueues *after commit*, the rollback meant no agent ever ran
  and no LLM was called.
- 9 committed tests (`test_engine_routing`, `test_engine_governance`),
  including the live auto-advance chain (complete a phase → the next phase is
  dispatched to the next owner).

## What's explicitly NOT in Phase 1

- **Parallel fan-out** (e.g. naming + directions at once). Phase 1 is
  sequential-only; the historical fan-out is linearised. AND-join is Phase 2.
- **Image generation** for the visual specialists — a later code-skill add-on.
- **Rewiring the RandomPack gate webhook** onto the work-item — the gateway
  path exists and is proven; wiring the live webhook to it follows once the
  E2E is green.

## Next

Real-LLM end-to-end on Legion (the acceptance gate): create a Brand Brief, let
the three specialists actually run the seven phases on Minimax, fire the two
gates through the gateway, and confirm it reaches `Delivered`.
