# Design 95, Slice 3 — the confidence ledger + graduation flags

## The principle, from the design doc

"Is it ready?" must be a number you can look at, not a feeling. And:
**graduation is an operator decision, evidence-informed — never automatic.**

## What shipped

### 1. The confidence ledger (on the Studio page)

The Studio Bench (`/app/studio`) gains an **Apprentice ledger** section —
counted live from Agent Memory and Tasks, no new machinery, no model calls:

- **lessons stored** — what the apprentice has remembered from watching
- **observations** — completed observe tasks
- **gate approve rate** — approvals ÷ gate decisions (e.g. "67%"), with
  "no gates yet" honestly shown before any evidence exists
- **productions attempted** — completed production-phase tasks
- **evidence by dimension** — palette / typography / logo / layout mention
  counts across the stored lessons (deterministic keyword buckets; honest
  label: mentions, not a taxonomy)
- **per-brief trend** — each brief that reached the CD gate: how many
  refinement rounds, approved or still looping
- the **drafting flag state**, so the operator sees the current authority

### 2. The graduation flag

A new `may_draft_directions` checkbox on the Agent Profile (a Custom Field —
the domain concern stays out of the core doctype, same pattern as
`File.is_customer_facing`). The operator flips it on the Creative Director
agent's profile form. Reversible at any time.

**Flipped ON**: when a brief enters CD Creative, the apprentice gets a
*draft task* — 2–3 direction concepts (palette with hex values, typography,
logo route, layout principles) grounded in its accumulated `cd-apprentice`
memories, attached to the project as one internal markdown file. The human
CD curates, edits, or discards; he still creates the identity and still
fires Creative Ready. **The flag changes what is on his desk when he sits
down — not who holds the pen.**

The draft task uses the same sidecar isolation as the observe task: no
work-item link, so it can never advance the pipeline and never crosses the
RandomPack seam. Its file stays unflagged, so the leak guard keeps it off
the customer portal.

### 3. The recall fix (found while building — load-bearing)

Memory recall is project-scoped (Design 73, correctly — one client's facts
must not bleed into another's room). But study lessons were being tagged
with the project they were learned on, which would have made them
**invisible on every future brief** — silently defeating the whole
apprenticeship. Fixed on both channels:

- The `remember` skill gains an optional `scope` parameter: `"global"`
  stores the memory untagged, recallable everywhere. The observe prompt
  now instructs it ("these are craft lessons you must recall on FUTURE
  projects"). Guidance added to the skill schema: global is for craft,
  conventions, and taste — never one client's private facts.
- Gate memories are written with no project on purpose (the brief stays
  traceable via `source_session`).

## Deploy notes

- `bench migrate` required: the `may_draft_directions` Custom Field
  (after_migrate) and the updated `remember` skill schema (provisioner).
- The flag defaults OFF — deploying changes nothing until an operator
  decides the evidence is there.

## Tests

`test_cd_study_loop.py` grows to 20: flag-off default no-op, flag-on draft
sidecar (isolation + human-in-charge prompt pinned), dedupe, observe still
fires alongside, ensure-field idempotence, ledger math (counts, approve
rate, dimension buckets, per-brief trend, no-gates-yet). Plus the ledger
endpoint envelope (`test_studio_api.py`) and the `remember` scope="global"
behaviour (`test_memory_project_scope.py`).
