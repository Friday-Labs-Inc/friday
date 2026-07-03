# Design 95, Slice 1 — the pipeline now runs through the human Creative Director

**Date:** 2026-07-03 · **Changes:** `domains/randompack_brand.py` (data only — no engine code)

## What changed, in plain English

The brand pipeline used to have an **AI** invent the brand directions and logos, with
humans only appearing at the two client gates. That was backwards. In the real studio,
the **human Creative Director creates the identity** — the logo concepts and the design
system — and the AI's job is *production*: applying his system across all the
deliverables, fast and faithfully.

The machine now runs:

```
Strategy (AI) → Naming (AI)
→ CD Creative        ← the HUMAN creates + uploads his direction options & design system
→ Gate 1 Prep (AI)   ← assembles the client presentation FROM HIS FILES
→ Gate 1 Review      ← client picks a direction (unchanged)
→ AI Production      ← the AI applies his chosen system ("their design system is LAW")
→ CD Internal Gate   ← the human approves, or loops it back for rework
→ Gate 2 Prep → Gate 2 Review → Guidelines → Delivered (all unchanged)
```

Nothing the client or RandomPack sees changed — the client gates, the portal, and the
`gate.decided` webhook all work exactly as before. The internal gate is Friday-side.

## How the human works it (no new UI)

1. When a brief reaches **CD Creative**, the war room posts a "waiting for you" note
   (the engine already announces human pauses).
2. The CD creates his direction options + design system and **uploads the files to the
   Project** (Desk or the project's chat room).
3. He fires **"Creative Ready"** on the Brand Brief. The pipeline takes it from there.
4. When it reaches **CD Internal Gate**, he reviews the AI's production package:
   **"Approve Production"** sends it toward the client; **"Request Refinement"** sends
   it back — the production stage re-runs, treating his notes as corrections.

**Operator setup (one-time):** grant the new **`Brand Creative Director`** role to the
human CD's user. No agent ever holds it — the same governance pattern as the client
gates, so the AI can neither skip his stage nor approve its own work (tested).

## In-flight projects

Briefs already mid-pipeline finish on the old states (Directions/Buildout are kept as
legacy, reachable only by documents already in them). Every new brief runs the new
machine. No data migration needed.

## The apprenticeship connection (why the AI's prompt changed)

The AI Creative Director profile is now explicitly the **apprentice seat**: "their
design system is law… never originate a new identity direction… treat every correction
as a lesson." Slice 2 adds the actual studying (observation memories + labeled gate
feedback); Slice 3 adds the confidence ledger and graduation flags.
