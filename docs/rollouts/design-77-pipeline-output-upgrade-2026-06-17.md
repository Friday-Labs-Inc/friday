# Rollout — Design 77 v2: pipeline output upgrade (2026-06-17)

## Plain English

A customer who paid RandomPack for a complete brand identity used to see just
**4 image files** on their project page after the pipeline ran (the direction
logos + the hero). All the actual brand work — strategy, naming, voice/tone,
brand guidelines — lived buried in `Task.result` JSON the customer could not
see. So from the customer's view, "a complete brand" looked like "a couple of
logos."

This rollout closes that gap. Every text-producing phase now also saves its
output as a real `.md` file attached to the customer's RandomPack project. By
the time the brief reaches `Delivered`, the customer sees a 9–10 file
package (images + named markdown deliverables + the materialized package).

## What changed

### Schema
A new **`project` Link field** on Brand Brief, pointing to the local Friday
`Project` doctype. The fieldname is exactly `project` (not `friday_project`)
because the metadata engine's `phase_dispatcher._project_of()` reads
`work_item.get("project")` — without this exact name, every engine Task has
`project = None` and the Project task rollup, Raven channel routing, and
share-deliverables are all blind.

### Domain bundle (`domains/randompack_brand.py`)
- **PHASES**: `attach-deliverable` added to every text-producing phase
  (strategy, naming, gate1_prep, buildout, gate2_prep, guidelines); `list-project-files`
  added to phases that read prior project state (gate1_prep, buildout,
  gate2_prep, guidelines).
- **PROFILES**: both new skills added to all three profiles' `permitted_skills`
  (Brand Strategist, Brand Copywriter, Creative Director) so the matrix admits
  them.
- **Prompts**: every text-producing phase prompt now ends with an explicit
  instruction to call `attach-deliverable` with a specific filename
  (`strategy.md`, `naming-candidates.md`, `gate1-client-presentation.md`,
  `buildout-package.md`, `gate2-final-review.md`, `brand-guidelines.md`),
  passing the full content. The agent's reply still lands in `Task.result`
  for the engine + `get-phase-outputs`; the attached file is a parallel
  customer-visible artifact.
- A side-effect quality fix: **naming phase now reads strategy via
  `get-phase-outputs`** (the pre-existing bug also fixed by PR #119 — included
  here so this PR stands alone if #119 lands later).

### Webhook handler (`surfaces/randompack.py`)
A new helper `_ensure_friday_project(rp_project, rp_brief, business_name)`
inserts a local Friday `Project` record (idempotent by `backend_ref`) and
returns its docname. `handle_project_created` calls it after the brief is
resolved, then `db_set`s the `project` field on the brief. A replay finds the
existing Project and reuses it — no duplicate rows.

### Bridge (`integrations/randompack_bridge.py`)
- `_push_deliverables` now **union-queries both targets**: files attached to
  the Brand Brief (images from `generate-image`) AND files attached to the
  linked local Friday Project (markdown deliverables from `attach-deliverable`
  + the materialized `deliverable-*.md/pdf` from `materialize.py`). Dedup is
  by `file_url` so a file linked from both is pushed once.
- A new `on_brief_state_change` hook fires `_push_deliverables` when the brief
  reaches `workflow_state = "Delivered"`. The previous trigger (in
  `_engine_writeback` on `phase == "guidelines"`) was removed — it ran before
  `assemble_project_package` had a chance to write its files. The new trigger
  guarantees everything has landed.

### Hooks (`frappe/hooks.py`)
`Brand Brief.on_update` is now a **list** with the existing engine interpreter
PLUS the new `on_brief_state_change`. The new entry never raises and is
gated on the `workflow_state` actually having changed to `Delivered` — so it's
a strict no-op for every save the engine does during the pipeline.

## What the customer actually sees after this ships

A RandomPack project page with **9–10 named files** instead of 4:

| File | Source |
|---|---|
| `direction-A-logo.jpg`, `B`, `C` (3) | generate-image → Brand Brief |
| `hero-visual.jpg` | generate-image at buildout → Brand Brief |
| `strategy.md` | attach-deliverable from strategy phase → Friday Project |
| `naming-candidates.md` | naming phase |
| `gate1-client-presentation.md` | gate1_prep |
| `buildout-package.md` | buildout |
| `gate2-final-review.md` | gate2_prep |
| `brand-guidelines.md` | guidelines (the primary customer deliverable) |
| `deliverable-<task>.md/pdf` (per phase) | materialize.py — newly visible via the union query |
| project-level brand-package.md/pdf | assemble_project_package |

## How we proved it works

- `bench --site friday.localhost run-tests --module friday.friday_core.tests.test_randompack_integration` → **14/14 green**, including 5 new tests:
  - `test_project_created_creates_local_friday_project`
  - `test_project_created_replay_reuses_existing_friday_project`
  - `test_push_deliverables_unions_brief_and_friday_project_files`
  - `test_on_brief_state_change_fires_only_on_transition_to_delivered`
  - `test_on_brief_state_change_silent_when_state_unchanged`
  - `test_on_brief_state_change_silent_for_non_delivered_state`
- `bench --site friday.localhost migrate` → clean, RandomPack bundle re-provisioned with new skills wired into PHASES + PROFILES.
- Live check on the dev bench: Brand Strategist's `permitted_skills` now
  contains `attach-deliverable` and `list-project-files`; the `gate1_prep`
  Transition Meta's `required_skills` carries the same set.

## What did NOT change

- The Design 75 metadata engine itself — `workflow_engine.py`,
  `phase_dispatcher.py`, `advance.py` are untouched.
- Image generation, generate-image's `is_private=0` default, and the
  Brand Brief schema's existing fields (rp_brief, rp_project, etc. from PR #118).
- `share-deliverables` skill scope. The spec's Q3 asked whether to broaden it
  to all Project files (not just `deliverable-*`); deferring that to a small
  follow-up so this PR stays focused.
- `_push_deliverables`' error handling — still a quiet `try/except` that logs
  and continues per file. The spec's Q2 asked whether to add a retry queue;
  deferring to a small follow-up.

## Sequencing notes

This PR is **stacked on PR #118 (`randompack-integration`)**. It depends on:
- The `rp_brief` / `rp_project` Data fields on Brand Brief (added in #118)
- The Intake state + `Start Pipeline` transition (added in #118)
- The rewritten `handle_project_created` (already fires `apply_workflow` —
  this PR just adds the project Link field write before it)
- The existing `_push_deliverables` function (from #118 — this PR extends it)

Merge order: `#118 → this`. PR #119 (gap batch #1) is independent.

## Demo impact

When the next Brand Brief flows through the engine end-to-end, the customer
sees a real brand identity package on their RandomPack project. That is what
the marketing copy promised: "A complete brand, not a logo and a wish."

## Follow-ups (out of scope)

- Broaden `share-deliverables` to all Project files (spec Q3).
- Add a retry queue to `_push_deliverables` (spec Q2).
- Test the `wkhtmltopdf`-absent fallback in `test_deliverables.py` (critic
  finding; existing fallback is correct but unverified by automated test).
