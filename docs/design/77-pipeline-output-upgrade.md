# Design 77 v2 — Pipeline output upgrade (Brand Brief → real customer deliverables)

**Status:** Designed 2026-06-17 via a 6-agent design pass (4 parallel surveys + synthesis + adversarial critique). Critic verdict `rework` because the surveyors didn't know PR #118 exists; most "critical" findings are already fixed in #118. The genuinely-new delta is small and listed below.

**Stacks on:** PR #118 (`randompack-integration`) and PR #120 (`fix/role-gate-enforcement`). PR #119 (gap batch #1) is helpful but not strictly required.

## The problem, in plain English

A customer pays for a brand identity package. After the pipeline runs, what they see on the RandomPack project page today is **4 image files** — three direction logos and a hero. Everything else (strategy text, naming candidates, voice/tone, brand guidelines) lives buried in `Task.result` JSON that the customer cannot see. So from the customer's view, they paid for "a brand" and got "a couple of logos."

This design closes that gap by making every phase save its outputs as **real attached files** on the customer's project page.

## The 5 pieces of v2

### 1. A canonical `project` field on Brand Brief

PR #118 added `rp_project` (Data — the remote RandomPack docname) and `rp_brief` (Data — the remote brief id) to Brand Brief. v2 adds a third: **`project` (Link → Project, read-only)**, the docname of the **local** Friday Project created at `project.created` time.

The fieldname **must** be `project` (not `friday_project`) so the metadata engine's `phase_dispatcher._project_of()` (at `engine/phase_dispatcher.py:103`) picks it up via the `meta.has_field("project")` check it already does today. Without this, every engine Task has `project = None` and the Project's task rollup, conversation channel routing (Design 73), and `share-deliverables` are all blind to which Project a Brief belongs to.

### 2. Wire `attach-deliverable` + `list-project-files` into every phase

These skills already exist (provisioned by `bootstrap_files.py`). They're not in the brand bundle's `PHASES.skills[]` lists or in any of the three agent profiles' `permitted_skills`, so today agents can't call them.

Concrete edits in `domains/randompack_brand.py`:
- Add `attach-deliverable` to all 7 `PHASES` skill lists.
- Add `list-project-files` to `gate1_prep`, `buildout`, `gate2_prep`, and `guidelines` (the phases that need to see what earlier phases saved).
- Add both to all three `PROFILES.permitted_skills` (Brand Strategist, Brand Copywriter, Creative Director).

### 3. `handle_project_created` writes the `project` link

In `surfaces/randompack.py` (which PR #118 already rewrote to fire `Start Pipeline`), add **one extra `db_set`** after the local Project insert and before the `apply_workflow` call:

```python
frappe.db.set_value("Brand Brief", brief, {"project": project_doc.name})
brief_doc.reload()
with acting_as(brand_strategist_user):
    apply_workflow(brief_doc, "Start Pipeline")
```

PR #118 already does the `apply_workflow` part; v2 just adds the `project` field write so engine tasks carry the link.

### 4. Phase prompts instruct agents to save outputs as files

Each text-producing phase gets a one-sentence prompt addition: "After producing the [strategy/naming/buildout/guidelines/etc] text, call `attach-deliverable` with `project_name={{ doc.project }}` and `file_name="<name>.md"` to save it to the project."

Concrete file names:
- `gate1_prep` → `gate1-client-presentation.md`
- `buildout` → `buildout-package.md`
- `gate2_prep` → `gate2-final-review.md`
- `guidelines` → `brand-guidelines.md`

The agent's text reply still lands in `Task.result` (for the engine + `get-phase-outputs`); the file is a parallel attachment for the customer.

### 5. `_push_deliverables` queries BOTH targets, sequenced right

PR #118's bridge reads files attached to the **Brand Brief** only. v2 extends it to union-query **both** the Brand Brief (for images from `generate-image`) AND the **Friday Project** (for the new `.md` files from `attach-deliverable` + the existing `deliverable-*.md/pdf` from `materialize.py`).

**Critical sequencing fix the critic flagged:** `_push_deliverables` cannot fire on `guidelines` task completion alone — `assemble_project_package` (which writes the per-project `.md/.pdf`) only fires when `Project.status = "Completed"`. So `_push_deliverables` must fire when the Brand Brief reaches `workflow_state = "Delivered"` (which is **after** the guidelines task completes AND the project is marked Completed by the existing materialize hook). Wire the new call site in `engine/advance.py` after the final state transition, not in `on_task_transition`.

## What the customer actually sees after this ships

A RandomPack project page with **9-10 named files**:

- `direction-A-logo.jpg`, `direction-B-logo.jpg`, `direction-C-logo.jpg` — generate-image, attached to Brand Brief
- `hero-visual.jpg` — generate-image at buildout, attached to Brand Brief
- `gate1-client-presentation.md` — attach-deliverable, attached to Project
- `buildout-package.md` — attach-deliverable, attached to Project
- `gate2-final-review.md` — attach-deliverable, attached to Project
- `brand-guidelines.md` — attach-deliverable, attached to Project
- `deliverable-<task>.md` × 7 — materialize.py (already exists, just newly visible via union query)
- `deliverable-<task>.pdf` × 7 — materialize.py with wkhtmltopdf (already exists, best-effort fallback)
- Project-level `brand-package.md` + `.pdf` — assemble_project_package (already exists, fires on Project Completed)

## What the v1 critic flagged that's already fixed in #118

These items appeared as `CRITICAL` in the v2 spec critique because the critic surveyed `main` without knowing #118 was open:

| Critic finding | Status |
|---|---|
| Intake state + Start Pipeline transition missing | Fixed in #118 |
| `INITIAL_STATE` still `Strategy` | Fixed in #118 (now `Intake`) |
| `handle_project_created` still calls `instantiate_pipeline` | Fixed in #118 |
| `handle_gate_decided` uses legacy `gate1/gate2` task slugs | Fixed in #118 |
| `rp_project` and `rp_brief` Data fields missing | Added in #118 |
| `_push_deliverables` doesn't exist | Added in #118 (reads only Brand Brief — v2 extends to Project too) |

## Genuinely new gaps the critic surfaced

These ARE part of v2:

1. **`project` Link field** — neither in #118 nor in main; this is the missing piece.
2. **attach-deliverable + list-project-files not in PHASES/PROFILES** — #118 didn't touch these skill lists.
3. **Sequencing of `_push_deliverables`** — must fire when Brief reaches Delivered, not on guidelines task completion.
4. **No test for wkhtmltopdf-absent fallback** — legit gap; add to `test_deliverables.py`.
5. **No tests for `_push_deliverables`** — add to `test_randompack_surface.py` (mocked).
6. **`Start Pipeline` actor fallback** — if Brand Strategist profile has no `frappe_user`, log and stall (match `engine/advance.py:97-105` pattern).

## Wall-clock estimate (honest)

| Phase | Time |
|---|---|
| Add 3 fields to `brand_brief.json` + migrate | 30 min |
| Wire skills into PHASES + PROFILES + update prompts | 45 min |
| `handle_project_created` `db_set` of `project` field (one line + idempotency guard) | 15 min |
| Extend `_push_deliverables` union query + sequence on Brief Delivered | 60 min |
| Tests (wkhtmltopdf fallback + push-deliverables mocks) | 60 min |
| Migrate gate + local smoke test | 30 min |
| **Code total** | **≈ 4 hours** |
| Legion E2E (directions phase = 3 sequential 120s image calls ≈ 6 min) | 30 min |

## Sequencing constraints

1. **Cannot ship before PR #118 merges.** v2 depends on `rp_project`, `rp_brief`, Intake state, the rewritten `handle_project_created`, and `_push_deliverables`. Build as a stacked branch off `randompack-integration` if you want to start now; merge order is `#118 → v2`.
2. PR #119 (naming reads strategy) is recommended before v2 for output quality but not blocking.
3. PR #120 (role_gate enforcement) is independent — can land in any order.

## Open questions for the user

1. **Is the new `project` Link field on Brand Brief OK to be `read_only=1` with `no_copy=1`?** It's set only by the webhook handler; an operator should not edit it.
2. **Should `_push_deliverables` retry?** Today it never raises. If `attach_deliverable` HTTP call to RandomPack fails for one file, do we move to the next file silently, or build a small retry queue?
3. **`share-deliverables` skill scope.** It currently queries Project files with `file_name LIKE 'deliverable-%'`. Should it broaden to all Project files now that we'll have non-`deliverable-` files there (the new `*.md`)? Recommend yes.
4. **Image privacy.** `generate-image` saves images with `is_private=0` (public). All other deliverables are private. For RandomPack push, what matters is whether the bytes can be read; both work. Keep current default unless there's a reason to change.

## Implementation order (when greenlit)

1. Confirm PR #118 + PR #120 are merged.
2. Branch `feat/77-pipeline-output-upgrade` off the merged main.
3. Add `project` Link field to `brand_brief.json`; run `bench migrate`.
4. Update `domains/randompack_brand.py`: add skills to PHASES + PROFILES + prompt sentences.
5. Update `surfaces/randompack.py`: add one `db_set` line in `handle_project_created` after Project insert.
6. Update `integrations/randompack_bridge.py`: extend `_push_deliverables` union query.
7. Update `engine/advance.py`: trigger `_push_deliverables` on Brand Brief transition to `Delivered`.
8. Tests: wkhtmltopdf fallback (mock get_pdf to raise), `_push_deliverables` union query (mock both `get_all` calls), end-to-end via existing `test_randompack_surface.py` patterns.
9. Rollout doc in `docs/rollouts/`.
10. Legion E2E: fresh Halden Coffee run end-to-end, verify 9-10 files land on the RandomPack project.

## Verdict

The first critique was harsh because it surveyed the wrong baseline. The actual delta after PR #118 is **small, well-scoped, and ~4 hours of code**. The customer-visible impact is large: instead of 4 images, they see a 9-10 file deliverable package — which matches what RandomPack's marketing copy promises ("A complete brand, not a logo and a wish.").

Awaiting user sign-off on the 4 open questions, then ready to build.
