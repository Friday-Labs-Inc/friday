# Design 95, Slice 2 — the study loop (the apprentice starts learning)

## The founder's vision, in one sentence

"The creative director agent slowly should study and learn from human director
feeds, once its confident we can allow it to create logo and brandings."

Slice 1 restructured the pipeline so the human creates and the AI produces.
This slice adds the LEARNING: from now on, every brand that passes through the
studio teaches the apprentice something, automatically.

## The two signals (both were already happening — now they're captured)

### 1. Watching him create — the observe task

When the human Creative Director fires **Creative Ready**, the apprentice
agent gets a side-study task: read the brief and everything the human uploaded
(the design system, direction boards, logos), then store 1–3 structured
lessons with the `remember` skill — *"given this personality/industry/audience,
he chose this palette / typeface / logo route."* Pairing only; no judgment,
no advice, no production.

The observe task is deliberately a **sidecar**: it carries no work-item link,
so the engine can never mistake it for a pipeline phase (nothing advances when
it completes) and the RandomPack bridge never sees it (nothing crosses the
customer seam). Tests pin both isolation properties.

### 2. Learning from his corrections — labeled gate memories

Every decision at the **CD Internal Gate** becomes a labeled example, written
directly to Agent Memory (no model call — cheap, instant, verbatim):

- **Approve Production** → *"Gate APPROVE — Friday Labs Inc (Robotics & AI):
  approved as-is after 2 refinement round(s). Package: …"*
- **Request Refinement** → *"Gate REFINE — round 1: 'Mark is too heavy; thin
  the strokes.' (full notes: cd-refinement-notes-r1.md; package: …)"* — quoting
  the notes file the Studio Bench saves before the transition fires. A gate
  fired outside the Studio (raw Desk form, no notes) still records the label.

## How the lessons come back

Memories carry `subject="cd-apprentice"` and the brief's project, and are
embedded for semantic recall — so on the NEXT brief, the agent's existing
memory recall surfaces them, and the Slice-3 confidence ledger can count them
("observations recorded, approve rate, refinement trend") when it lands.

## Plumbing

- New `domains/randompack_study.py`, wired as a third Brand Brief `on_update`
  handler (after the engine and the bridge). Failure-isolated: a study outage
  can never break a workflow save.
- The Creative Director profile gains the `remember` skill (provisioner —
  idempotent, applies on migrate).
- Lockstep tests assert the watched states/transitions against the actual
  `randompack_brand` machine.

## Deploy notes

- `bench migrate` recommended path: the provisioner (after_migrate) grants
  `remember` to the Creative Director profile. No schema changes.
- The loop activates on the next brief that reaches the CD states — nothing
  retroactive, nothing to configure.

## What this slice does NOT do (later slices)

No confidence scores, no graduation flags, no report — that is Slice 3.
No autonomy change whatsoever: the apprentice still only produces; it just
finally remembers what it watched.

## Tests

`tests/test_cd_study_loop.py` (12 DB-free): lockstep ×3 (states/transitions
real, profile has the skills, observe key is not an engine phase), observe
task shape + **no-work_item isolation** + dedupe + missing-profile logging,
approve/refine memory content (tag, project, session, notes quote, round
number), no-notes fallback, unwatched-transition and no-change no-ops,
failure isolation.
