# Design 97 — The brand asset layer (deliver a brand, not documents about one)

**Status:** DRAFT — Q-locks open
**Track:** Domain (`domain:randompack`) + one Core slice (asset rendering)
**Origin:** the founder's verdict on the Reezort delivery, verbatim: *"i only see
bunch of pdf writen full text articles as delivered handoff — do you call this as
branding delivery or just guideline copywrite docs"*

## Plain English

He's right. The Reezort E2E delivered six branded PDFs — a brand *specification*:
palette values, voice rules, a described heron mark. A real branding delivery is a
**folder of artifacts the customer can use Monday morning**: logo files in variants,
color swatches, a favicon, type specimens, social templates, mockups. Today the
machine ends exactly where a paying customer's expectations begin. Design 96 fixed
the *packaging* (branded PDFs instead of raw markdown); nothing yet produces the
**assets**.

## Why there were no assets in the Reezort delivery

1. **The human CD stage produced a document, not artwork.** The pipeline already
   supports the real path — the CD uploads logo SVG/PNGs, flags them customer-facing,
   delivery ships them — but nothing REQUIRES artifacts, so a design-system doc alone
   passed Creative Ready.
2. **The AI production phase writes text.** Its one image all run was a decorative
   raster (MiniMax), unflagged. No step turns the locked design system into files.

## The design — two lanes, honoring "human creates, AI produces" (Design 95)

### Lane 1 — the CD's artifact gate (no new machinery)

Creative Ready gains an **artifact checklist**: the Studio Bench warns (soft gate,
Q1) when the project has no CD-uploaded logo artwork (`logo-*.svg/png`) at CD
Creative exit. The human's artwork, when present, is the canonical mark; everything
in Lane 2 derives from or defers to it. This is config/prompt + one Bench check —
it also fixes the E2E's role-play laziness structurally.

### Lane 2 — the asset production step (the build)

A new **`asset_production` phase** after the CD Internal Gate approval (the system
is LOCKED by then — assets derive from an approved system, never a draft):

1. **Logo variants as SVG-via-code.** LLMs write clean vector code for geometric
   marks (a single-stroke heron is exactly this class). The production agent
   generates `logo-primary.svg`, `logo-mark.svg`, `logo-mono.svg`, `logo-reversed.svg`
   from the locked system's mark spec — honoring its reduction rules (e.g. the 16px
   spec) — plus PNG rasters at standard sizes (SVG→PNG via the box's existing
   headless-chrome/wkhtmltopdf tooling; no new binary deps).
2. **Color + type artifacts.** `palette.css`/`palette.json` + a swatch sheet PNG;
   a type-specimen PDF from the locked typography.
3. **Favicon + app-icon set.** From the mark's reduction spec (16/32/180/512).
4. **Templates.** Social avatar/banner + a one-page letterhead as HTML→PNG/PDF
   using the palette/type tokens.
5. **The kit.** Everything lands on the project flagged `is_customer_facing=1`
   with human names ("The Reezort — Logo (SVG, primary)"), and materialize's
   delivery push ships a `Brand Kit` alongside the guidelines. The leak guard
   applies unchanged.

**Where the human stays in charge:** asset_production output routes BACK to the CD
Internal Gate (a second, short pass — approve the artifacts like the packages).
AI-generated marks are always derived from the human's system; if the CD uploaded
artwork (Lane 1), the AI produces *variants of his files*, never a competing mark.

### Pillar 3 — content hygiene (folds in finding C4)

Customer-facing documents must never enumerate internal artifact names: a
`_scrub_internal_names()` pass in materialize strips/aliases hash-named internal
`.md` references from rendered customer PDFs (C4: the Gate-2 PDF listed
`cd-refinement-notes-r1af11bf.md` etc. in its appendix).

## Open Q-locks (proposals; confirm or override)

- **Q1 — Artifact gate strength**: PROPOSED soft (Bench warns, CD can proceed) —
  the CD may legitimately deliver spec-first engagements. Hard gate = config later.
- **Q2 — SVG generation model**: PROPOSED the routed text provider writes SVG
  (it's code); gpt-image/MiniMax used only for raster explorations, never the
  canonical mark. (Vector > raster for logos; image models can't do brand-grade
  vectors.)
- **Q3 — Asset review loop**: PROPOSED reuse the CD Internal Gate (one extra
  Bench pass over the kit) instead of a new gate/state.
- **Q4 — Slice 1 scope**: PROPOSED logo variants + palette/typography artifacts +
  favicon + kit delivery; templates/mockups slice 2; C4 scrub rides slice 1.

## Slices

1. **The kit core**: asset_production phase (data, Design-75 style) + SVG logo
   variants + palette/type artifacts + favicon set + flagged kit delivery + C4
   scrub + Lane 1 Bench warning.
2. **Templates & mockups**: social set, letterhead, simple product mockups.
3. **(with Design 96 slice 4)** website starter derived from the same tokens.

## What this closes

The founder's verdict (a delivery must BE a brand) · finding C4 (internal names in
customer text) · the E2E gap where Creative Ready passed with zero artwork.
Related: Design 95 (the human's primacy + apprenticeship — asset production is a
production skill, not creative authority), Design 96 (materialize/leak-guard rails
the kit rides on).
