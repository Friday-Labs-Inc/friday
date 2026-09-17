# Design 95 — The Creative Director apprenticeship (human creates, AI learns, then earns it)

**Status:** LOCKED 2026-07-03 (Q1–Q3 accepted as proposed) — Slice 1 implemented
**Track:** Domain (`domain:randompack`) with one Core slice (research tooling)
**Origin:** founder's correction of the shipped pipeline + his vision, verbatim: *"the
creative director agent slowly should study and learn from human director feeds, once
its confident we can allow it to create logo and brandings."*

## Plain English

The shipped brand pipeline (Design 75 data) got the creative heart of the business
backwards. As built, an **AI** "Creative Director" generates three brand directions and
AI logo images, and the only human touchpoints are the two client gates. In the real
studio, the **human** Creative Director creates the logo and the design system — the
identity is human-made — and the AI's job is *production around it*: applying his
system across the deliverable set, at machine speed.

But the correction is not "AI never creates." It is an **apprenticeship**: the Creative
Director *agent* watches the human work — every brief that comes in, everything he
makes from it, every correction he gives the AI's production, every approve/refine at
his gate — and accumulates his taste as memory. When the evidence says it is ready, the
operator can graduate it, capability by capability: first drafting for his review,
eventually creating logos and brandings with the human moving from doer to approver.

Trust is earned with evidence, not enthusiasm — the same principle as the rest of
Friday's governance, applied to creative authority.

## The corrected pipeline

```
Intake ─▶ Strategy (AI) ─▶ Brand Writing (AI: naming + copy)
      ─▶ CD CREATIVE (HUMAN: creates direction options — logo concepts + design system;
                       uploads to the Project; the CD agent OBSERVES)
      ─▶ Client Gate 1 (client picks a direction — unchanged for RandomPack)
      ─▶ AI PRODUCTION (AI applies the human's chosen system across the deliverable set)
      ─▶ CD INTERNAL GATE (HUMAN: approve → forward · refine → loops back to AI Production)
      ─▶ Client Gate 2 (final client approval — unchanged)
      ─▶ Guidelines / Delivery (AI) ─▶ Delivered
```

What changed vs the shipped machine:

| | Shipped (Design 75 data) | Corrected |
|---|---|---|
| Directions / logo / design system | AI generates (3 directions + `generate-image` logos) | **Human CD creates**; agent observes |
| AI's creative role | Originates the identity | **Production**: applies the human's system |
| Internal QA | none — AI work goes straight to client gates | **CD Internal Gate** before anything reaches the client |
| Client gates | Gate 1 (direction) + Gate 2 (final) | unchanged — no RandomPack-side change at all |
| `generate-image` for identity work | yes | **not until graduation** (production imagery per the human's system only) |

The client-facing seam (RandomPack's `gate.decided`, the portal confirm cards, the
whole §4 contract) is untouched — the CD Internal Gate is Friday-side only.

## How the human's work enters Friday

**Files on the Project** — the primitive already exists and needs zero new UI. The CD
uploads his direction boards / logo files / design-system doc to the Project (or its
Raven channel); the AI Production phase's prompt begins: *"call `list-project-files` +
`get-project-file` and read the Creative Director's design system FIRST — follow it
exactly; never invent outside it."* Firing the `CD Creative → Client Gate 1` transition
is the human's "I'm done" signal (role-gated, like the client gates today).

## Guidelines for default work — three layers

1. **House style (all projects):** standing studio rules live in the creative profiles'
   `system_prompt` — config, not code.
2. **Per-project truth:** the human CD's uploaded files, read via existing skills.
3. **Learned taste (grows):** Agent Memory — the apprenticeship layer below.

## The study loop (what the agent learns, and from where)

Two signal sources, both cheap and honest:

- **Observation (CD Creative):** when the human's stage completes, the CD agent gets an
  *observe task*: read the brief + his uploaded artifacts, and `remember` a structured
  lesson — "given this brief (personality, category, audience), he chose {palette,
  type, logo route}; notes: …". No judgment, just pairing.
- **Labeled feedback (CD Internal Gate):** every gate decision on the AI's production
  is a labeled example — approve = positive; "refine: too corporate, warm it up" is
  exactly the correction that teaches. Recorded verbatim with the artifact refs.

Memory entries are tagged (`cd-apprentice`, dimension tags: palette / typography /
logo / layout) so the agent recalls them on future projects — and so the ledger below
can count them.

## The confidence ledger + graduation

"Is it ready?" must be a number you can look at, not a feeling:

- Per creative dimension: observations recorded, productions attempted, approve rate at
  the CD Internal Gate, refinement-loop count trend.
- Surfaced in Desk (a report over Agent Memory + gate outcomes — no new heavy machinery).
- **Graduation is an operator decision, evidence-informed — never automatic.** Per-
  capability flags on the CD agent's profile (e.g. `may_draft_directions`): flipped on,
  the CD Creative stage becomes *agent drafts → human curates/edits → human fires the
  transition*; the human's edits keep feeding the loop. Full creation authority is just
  the last flag, and every flag is reversible.

## Research tooling (the audit's gaps — one Core slice)

The 2026-07-03 capability audit: **no agent can reach the web** (no search skill), so
"competitive analysis" and "trend analysis" are ungrounded; image generation is
MiniMax-`image-01`-only. The seam already exists — Friday is an MCP client (Design 67),
so a search MCP server's tools become governed skills with audit for free:

- Register a search MCP (scout Brave / Tavily / Perplexity → recommend), grant to the
  Brand Strategist via the matrix → grounded competitor/trend research in Strategy.
- Multi-model `generate-image` (beyond MiniMax) stays a **named follow-up**, not in
  this design's slices — it only matters at graduation time.

## Open Q-locks (proposals; confirm or override)

- **Q1 — Handoff mechanism.** PROPOSED: project file upload (zero new UI), as above.
- **Q2 — Roles.** PROPOSED: keep TWO workflow roles even if one human (Rajiv) holds
  both today — `Brand Creative Director` (CD Creative stage + CD Internal Gate) stays
  distinct from the client-gate role, so a future hire separates cleanly. The AI
  profile keeps the name `Creative Director` (it is the apprentice of that seat) but
  its phases become production + observation until graduation.
- **Q3 — Search MCP.** PROPOSED: scout the three candidates and recommend one in the
  research slice; not blocking Slices 1–3.

## Slice 1 — findings from the real-artifact E2E (2026-07-04)

A live agent-turn E2E (a real Creative Director turn against the founder's actual
"Draft." design-system MD, 33 KB, uploaded to a test Project) surfaced two real
bugs the shape tests missed, plus one model-fit finding:

1. **The file skills were inert (fixed, PR #179).** `list-project-files` /
   `get-project-file` / `attach-deliverable` were `status="Draft"` (bootstrap_files'
   `_ensure_skill_row` default), and the skills loader hard-excludes non-Active skills —
   so the CD agent's toolset never even contained them. AND the brand profiles lacked
   the Project/File read the handlers check at runtime (the matrix ignores the ambient
   `All` role). Both gates now opened in `_ensure_file_skills` (flip Active + grant the
   `Friday File Author` role to the brand profiles). Verified via Execution Log: the tool
   now returns the full design system (`row_count: 1`, 33 KB) to the agent.

2. **Model fidelity (open — informs the CD/production phase's model choice).** With the
   plumbing fixed, MiniMax-M3 (the local CD model) *misread* the successful tool result —
   the file was returned, but the model claimed "empty" and refused. Its refusal-instinct
   is correct (it won't fabricate a design system), but its tool-result comprehension
   fumbled. **The AI Production phase demands strong instruction-following + faithful
   tool-result reading; it should run on a top-tier model (e.g. gpt-5.4 / Claude), not a
   small one.** Friday already supports per-profile model selection + Design 94 failover —
   so this is an operator/config recommendation, captured here as the standard for the
   apprentice seat.

## Slices

1. **Pipeline restructure** (domain data): new states/transitions/phases in
   `domains/randompack_brand.py` — CD Creative (human), AI Production (re-pointed CD
   agent), CD Internal Gate (human, refine-loop). MIGRATION NOTE: the machine is
   provisioned data on a live pipeline — in-flight briefs finish on the old states; the
   new machine applies from the next brief (a state-map migration only if the founder
   wants it).
2. **The study loop**: observe-task on CD Creative completion + labeled memory writes
   on every CD Internal Gate decision.
3. **Ledger + graduation flags**: the Desk report + per-capability profile flags wired
   into the CD Creative stage's dispatch.
4. **Research tooling** (Core, parallel): search-MCP scout → register → grant to the
   Strategist; strategy prompt gains a grounded-research step.
