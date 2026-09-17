# Design 96 — The Creative Studio Harness (multi-medium models · customer-grade deliverables · the Studio Workspace)

**Status:** DRAFT — awaiting founder Q-locks
**Track:** Core (routing + materialize) with one Domain slice (studio page provisioning)
**Origin:** the Friday Labs Inc E2E (2026-07-04/05) closed the loop but exposed the last
mile — the customer received raw hash-named markdown (and even internal working notes),
no logo files, no branded PDFs; and the founder's verdict on the backend: *"completely
confusing, requires better UX/UI."* The requirements source is the human Creative
Director's own service catalog (rajiv-portfolio-lilac.vercel.app): Brand Identity, Logo
Design, Packaging, Print & Editorial, Brand Guidelines, Creative Direction, Website
Design/Dev, Motion, Animation, AI Art Direction, Presentation Design, Photography
Direction, Illustration, Audio, Video, Social Content.

## Plain English

Friday's brand pipeline now *works* — the E2E proved intake → gates → human CD → AI
production → delivery end to end. But three truths stand between "the machine works"
and "a creative studio can sell this":

1. **The machine only speaks text.** One image model (MiniMax), hard-wired into one
   skill, currently unreachable by the gpt-5.5 brand agents. A studio's work is mostly
   NOT text: logos, packaging, motion, presentations, audio. Models must be routed by
   the KIND of work (the *medium*), not just by which agent asks.
2. **Deliverables are engineer artifacts.** The customer got `brand-guidelines8e02e8.md`
   — a raw markdown file with a hash name — plus, because nothing distinguishes
   customer-facing files from internal ones, the CD's private refinement notes were
   pushed to the customer too. A paying client expects "Brand Guidelines.pdf" with
   their logo on it, actual logo files, and *only* the finished work.
3. **The backend is an ops console, not a studio.** The Project Console shows
   dispatcher telemetry and raw brief ids. The human Creative Director needs the
   opposite: a queue of what's waiting on *him*, with the work rendered in front of
   him and one-click Approve / Refine-with-notes — the notes being exactly the
   training signal Design 95's apprenticeship learns from.

## The requirements matrix (the CD's services → what the harness needs)

| Service (his catalog) | Medium | Model class | Today |
|---|---|---|---|
| Strategy, naming, copy, guidelines | text | gpt-5.5 / Claude (+D94 failover) | ✅ works |
| Logo concepts, key visuals, AI art direction | image | gpt-image / MiniMax image / Flux | ⚠️ MiniMax-only, provider-type hard-checked |
| Presentation design, brand book | doc-render | md→html→pdf (wkhtmltopdf exists) | ⚠️ internal-only, unbranded |
| Website design/dev | code/site | coding agent fed the design system | ❌ no phase |
| Motion, animation for social | video | Veo/Runway-class | ❌ none |
| Audio (jingle, sonic logo) | audio | music/TTS models | ❌ none |

Design 96 builds the *routing and delivery frame* for all six media, and implements
text/image/doc-render now; video/audio/site become plug-in providers later, not
re-architectures.

---

## Pillar 1 — Medium-based model routing

**Today** (`llm/provider.py:1126`): `get_provider_for_profile` resolves
`Agent Profile.model_provider` → `Agent Settings.default_provider` → first active row.
One TEXT provider per agent. Image gen (`skills/handlers_visual.py:114`) does its own
bespoke resolution and **hard-fails unless the profile's provider is `minimax`**
(`handlers_visual.py:125`) — which is exactly why the brand agents (now on Codex) can't
generate images. The Design 94 failover chain (`LLM Provider.fallback_provider`,
consumed at `runner.py:350–378` with a 3-hop cap + cycle guard) is provider-level and
already proven on prod.

**The design** — a routing layer ABOVE the existing resolution, composing with (not
replacing) Design 94:

1. **`Model Route` child table on Agent Settings** — rows `(medium, provider)` where
   medium ∈ {text, image, video, audio, doc-render}. One admin surface, config-as-data,
   same singleton pattern as `default_provider`.
2. **`get_provider_for_medium(profile_name, medium)`** in `llm/provider.py`:
   per-profile medium override (optional field, later) → Agent Settings Model Route row
   → fall through to today's `get_provider_for_profile` (text = unchanged, zero
   regression). Returned providers pass `_attach_row_identity` (`provider.py:1164`) so
   **the D94 failover chain works per-medium for free**.
3. **`Skill.medium` field** (Select, default text) — classification, carried through
   `SkillDefinition` for observability and future loader hints. Routing itself happens
   at handler-execution time via `get_provider_for_medium`.
4. **`generate-image` becomes the first consumer**: `_minimax_credentials` is replaced
   by `get_provider_for_medium(profile, "image")` + a provider-type dispatch for the
   image API surface (MiniMax `/v1/image_generation` today; `openai` gpt-image next).
   Image APIs differ too much (sync vs poll, payload shapes) for the `LLMProvider` ABC
   — a function-level dispatch per provider_type, mirroring `_build_provider`'s
   if-chain, is the right shape. `LLM Provider.image_model` (already exists,
   `llm_provider.json:96`) stays as the per-provider image model name.
5. **`render-document` — the new doc-render skill**: exposes the existing
   `materialize._render_pdf` machinery (`deliverables/materialize.py:153`,
   md→html→`frappe.utils.pdf.get_pdf`) as an agent-callable skill with a
   `brand_context` (Pillar 2). Video/audio get Model Route rows the day a provider
   lands — the frame is medium-agnostic.

## Pillar 2 — The customer materialize layer (finding #18)

**Today**: `materialize.py` renders per-task/project PDFs — but **unbranded** (bare
sans-serif div, no logo), **hash-named** (the slug at `materialize.py:204` is the
Frappe DOCNAME — that's where `…8e02e8` comes from), **internal-only** (`is_private=1`,
never in the customer push). Meanwhile `_push_deliverables`
(`randompack_bridge.py:134–179`) pushes **every File on the brief + project** — which
in the E2E meant the customer received the CD's internal refinement notes and both
package drafts. There is no customer-facing concept anywhere.

**The design**:

1. **`is_customer_facing` flag on File** (custom field, default 0) — the single,
   minimal boundary between working files and deliverables. Set automatically by the
   customer-materialize step; settable by the CD in Desk (so his final logo SVG/PNG
   uploads flow to the customer); exposed as an optional param on `attach-deliverable`.
2. **`materialize_for_customer(brief)`** — a new step in the Delivered flow (before
   `_push_deliverables`): takes each customer deliverable, renders a **branded PDF**
   (`_render_pdf` grows a `brand_context` — palette/typography from the chosen
   direction + the CD's logo file injected into the HTML header), and names it for
   humans: `"Friday Labs Inc — Brand Guidelines.pdf"` (project title + phase title, not
   docname slugs — a one-argument change at `materialize.py:86/89/111/114` plus a title
   map).
3. **`_push_deliverables` filters on `is_customer_facing=1`** — internal notes and
   drafts never cross the seam again. (Also folds in the queued #6/#13 bridge fixes:
   push the gate presentation BEFORE `request_gate_open`, and update the phase→RP-task
   maps to the Design-95 vocabulary so gates open and tasks advance without operator
   nudges.)
4. **Asset bundles**: the CD's uploaded logo/asset files (flagged customer-facing)
   ship alongside the rendered PDFs — real SVG/PNG in the customer's hands, per
   Design 95's "the human creates the identity" (until the apprentice graduates).
5. **Website phase — scoped, deferred**: pure pipeline data (one STATES/TRANSITIONS/
   PHASES entry) feeding the design-system MD to a coding agent ("feed this entire
   document to any AI coding tool" — the CD's own docs are literally written for this).
   Its own design when picked up; the engine needs no changes.

## Pillar 3 — The Studio Workspace ("The Bench")

**Today**: the human CD's work queue is invisible. The only notification is a Raven
war-room post (`workflow_engine.py:118` — no Desk badge, no email, no queue view), and
acting requires finding the Brand Brief form and knowing which workflow button to
press. The founder's verdict on the console is correct — it's engineer telemetry.

**The design** — a custom Desk Page at `/desk/studio`, the codebase's proven
rich-UI pattern (project-console/dispatcher-console: Page JSON + JS with
`frappe.ui.make_app_page()` + whitelisted snapshot endpoints):

1. **The Bench (queue-first)**: every Brand Brief at `CD Creative` or
   `CD Internal Gate` (the two CD_ROLE states, `randompack_brand.py:112/119`) as a
   card: brand name, state, days waiting, and the thing to review — the production
   package rendered (md→html in a modal), with refine-round versions side by side
   (File rows ordered by creation).
2. **One-click actions**: Approve Production / Request Refinement (with a notes box) /
   Creative Ready — wired to the already-whitelisted
   `frappe.model.workflow.apply_workflow` (`frappe/model/workflow.py:119`), firing as
   the signed-in CD (who holds `Brand Creative Director`; perms already provisioned at
   `randompack_brand.py:784`).
3. **Notes ARE the training signal**: the refine-notes box writes a
   `cd-refinement-notes-r<N>.md` File to the project (exactly what the E2E did by
   hand) *and* — when Design 95 Slice 2 lands — an Agent Memory entry tagged
   `cd-apprentice`. The Studio page is Slice 2's data-entry surface.
4. **Brand cards, not brief ids**: cards carry the brand's own palette chip + mark
   once a direction exists — the studio sees brands, not `RP-BRIEF-0239`.
5. **The workspace obeys the CD's own design bar**: mono base, ≤1 accent, large light
   type, every element earns its place. The console page CSS-variable idiom keeps it
   theme-native.
6. Console polish rides along: human project titles (company name, not
   `RandomPack RP-BRIEF-0239`), and the misleading red **DOWN** health badge
   reconciled with the worker-up indicator.

## Open Q-locks (proposals; confirm or override)

- **Q1 — Model Route home**: Agent Settings child table (PROPOSED — one admin surface)
  vs. standalone doctype. Per-profile medium overrides deferred until needed.
- **Q2 — First image provider besides MiniMax**: PROPOSED gpt-image via the existing
  `openai`-type provider row (the box already runs Codex/OpenAI auth); Flux/SD later.
- **Q3 — Customer-facing boundary**: `is_customer_facing` File flag (PROPOSED —
  minimal-complete) vs. a Deliverable registry doctype (more curation, more moving
  parts — revisit if the flag proves too blunt).
- **Q4 — Studio page scope for slice 1**: Bench + actions + rendered previews
  (PROPOSED); brand-card visual polish + realtime badges in a follow-up.

## Slices

1. **Medium routing + multi-provider image** (Core): Model Route + medium resolution +
   `generate-image` decoupled from MiniMax + `Skill.medium`. Brand agents on gpt-5.5
   can finally produce visuals.
2. **Customer materialize** (Core+bridge): `is_customer_facing`, branded PDF with
   `brand_context`, human names, filtered push — folds in the queued #6/#13 bridge
   fixes. *The fastest path from "works" to "sellable."*
3. **The Studio Workspace** (Domain/console): the Bench page + actions + previews +
   refine-notes capture (feeds Design 95 Slice 2).
4. **Website phase** (Domain, own design doc when picked up); video/audio providers as
   they land (frame ready via Model Route).

## E2E findings this design closes or advances

#18 asset/presentation layer (Pillars 1–2) · #6 + #13 bridge push/vocab (Slice 2) ·
the internal-files-leaked-to-customer exposure (Pillar 2, `is_customer_facing`) ·
the image-gen capability gap from the 2026-07-03 audit (Pillar 1) · the founder's
console UX verdict (Pillar 3). Related: Design 94 (failover the routing composes
with), Design 95 (the human CD the Studio serves, and whose notes feed Slice 2).
