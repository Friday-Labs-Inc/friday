# Design 56 — Hand #2: the first Draft business skill (brand directions)

**Status: PROPOSED — decisions Q1–Q6 below need locking before any code.**

## What this is, in plain English

The first skill that produces something Draft can sell. The flow it enables:

1. Your team fills in a **Brand Brief** (the client questionnaire) in Desk.
2. Anyone tells Friday, in chat: *"Generate 3 brand directions for brief
   BB-0001."*
3. The agent reads the brief, generates three distinct creative directions,
   and saves each as a **Brand Direction** record — concept story, palette,
   typography, logo concept, tagline options.
4. Your design team opens them in Desk and refines the winner. (AI generates
   → experts refine — exactly the RandomPack pipeline.)

Every step rides the rails we already built: permission-checked dispatch,
immutable Execution Log, token/cost accounting, the dedicated worker.

## Scope (honest): 2 DocTypes + 2 skills

The agent can't see a Brief unless something hands it over — so this slice
ships a **reader** and a **writer**:

| Piece | What it is |
|---|---|
| `Brand Brief` DocType | the questionnaire as a durable record |
| `Brand Direction` DocType | one row per generated direction, linked to its brief |
| `get-brand-brief` skill | READ: returns a brief's content to the agent |
| `create-brand-direction` skill | WRITE: validates + persists one direction |

Hermes equivalent: this is Friday's analogue of Hermes' own business tools
(`feishu_doc_tool`, `discord_tool`, …) — the user-specific work layer on top
of the generic engine. Nothing here is a port; it's the product.

## Decisions to lock (Q-by-Q)

**Q1 — Input shape: a `Brand Brief` DocType (vs free-text in chat).**
*Recommendation:* DocType. Fields: business name, industry, what they do,
target audience, brand personality (vibe words), competitors, color
likes/dislikes, inspirations/references, notes, status
(Draft → Ready → Directions Generated). Durable, auditable, refinable — and
the chat command stays one line ("…for brief BB-0001").

**Q2 — Output shape: a `Brand Direction` DocType, one row per direction.**
*Recommendation:* yes. Fields: brief (Link), direction name, concept story,
personality keywords, color palette (JSON list of hex+name+role — a child
table is ceremony v0.1 doesn't need), typography (heading/body + rationale),
logo concept (a designer-ready description), tagline options, status
(Proposed → Shortlisted → Refined → Rejected). The team refines these rows
directly in Desk; track_changes on.

**Q3 — WHO generates the creative content: the agent, not the skill.**
*Recommendation:* the model generates the directions inside the ReAct loop
(already governed: usage-logged, reasoning-scrubbed, budget-capped) and calls
the skill with the finished content as arguments. The skill is a dumb,
auditable **persister** — it validates and writes, never calls an LLM. Zero
new model plumbing; intelligence stays where the governance already is.

**Q4 — Skill granularity: `create-brand-direction` called once per direction.**
*Recommendation:* singular, called 3× — smaller JSON arguments (less repair
surface), one audit row per direction, partial success possible (2 of 3
land if the model fumbles one). The loop's dedup keeps identical calls from
double-writing.

**Q5 — Governance class: low risk, NO approval gate.**
*Recommendation:* `risk_level=Low`, `requires_approval=0`. These are
internal draft artifacts for human refinement — nothing outward-facing. The
write is still permission-checked (the profile's role needs create on Brand
Direction) and fully logged. The approval gate stays reserved for skills
with external effects.

**Q6 — How the Brief gets filled: Desk form, v0.1.**
*Recommendation:* team enters it manually in Desk for now. A public web
form / client portal is a later slice (it's a surface, not a skill).

## What lands on disk (when locked)

- `doctype/brand_brief/` + `doctype/brand_direction/` (module: Friday Core —
  a future "Draft Studio" module split is a rename, not a rebuild).
- `skills/handlers_brand.py` — the two handlers, registered with the
  dispatcher like `create_note`.
- Two Skill rows (fixtures/bootstrap): parameter schemas, when-to-use text
  the loader feeds the model, risk class.
- Permission wiring: the Friday profile's role gets read on Brief, create on
  Direction; both skills added to its permitted_skills.
- Tests FIRST: handler validation/persistence units (mocked frappe), loader
  exposure, and a mocked loop test (read → create ×3 through dispatch).
- Live proof: a real brief on the bench → one chat command → 3 Brand
  Direction rows, audit-logged, cost-accounted.

## Out of scope (deliberately)

- Logo/mockup image generation (multimodal is ⬛ in v0.1) — the logo concept
  field is a *designer-ready description*, not an image.
- Client-facing forms/portal (a surface slice).
- Auto-refinement loops / curator behaviours (the learning loop, later).
