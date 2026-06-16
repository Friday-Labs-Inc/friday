# Design 73, Slice 3 — Inbound routing: the project's own orchestrator (Rollout)

**Date:** 2026-06-16
**Design:** [`73-project-conversation-surface.md`](../design/73-project-conversation-surface.md)
**Status:** Built + verified live (Legion, real Northwind Coffee data) — including the full `@mention → reply` round-trip with a real Minimax call (2026-06-16).

## What this is, in plain words

Friday is meant to be used like you'd message a coworker. Until now, when you talked to Friday inside a *project's* chat room, two things were missing:

1. **It didn't know whose room it was.** Every message went to one catch-all agent, no matter which project's channel you typed in.
2. **It didn't know where the project stood.** The agent had to ask "which project?" and couldn't tell you what was done or delivered.

Slice 3 fixes both. Now a message in a project's room goes to **that project's lead agent**, and that agent starts every turn already knowing the project's **status, open tasks, and deliverables**.

## The surprise

We expected to *build* the whole inbound path (you type → it routes → an agent replies). It turned out that path was already wired end-to-end (it came in with the gateway + CLI surface). What was missing was only the *project-awareness*. So this slice is small and surgical, not a rebuild — see the design doc's "Slice 3" section for the full finding.

## What changed

- **The room picks the agent.** A message in a project channel now resolves to that project's **Project Lead** (`Project.project_lead_profile`), as long as that agent is Active. Anything else — a non-project channel, a DM, a project with no lead, or a lead that's been suspended/retired — falls back to the platform's default agent, exactly as before. *(One new branch in `routing/resolve.py`; the Raven adapter now passes the channel id through.)*
- **The agent walks in informed.** Every turn in a project room now opens with a fresh **status snapshot**: the project's status and % complete, its open tasks (by state), and the deliverable files produced so far. *(New `llm/project_context.py`; the prompt builder injects it, upgrading the old name-only "you're in project X" line.)*
- **No new tables or fields.** Both changes only *read* existing data, so there's nothing to migrate.

## Proven live (Legion, real "Northwind Coffee — Brand Identity" project)

Ran the new code against the real Northwind project (the 17/17 E2E project), **commit-free** — every probe rolled back, leaving the project untouched:

- **Snapshot:** produced `Status: Open (100% complete, 9/9 tasks done)`, `Open tasks: none` (all 9 finished — correctly excluded), and listed the **real deliverable files** (the brand-identity package PDF/MD + per-task artifacts, capped at 8 with "+3 more").
- **Routing — all three paths on real data:**
  - no lead set → routed to the platform default (`Friday`) ✓
  - lead set to `Copywriter` → routed to `Copywriter` ✓ (the project's room now reaches the project's agent)
  - lead `Copywriter` suspended → fell back to `Friday` ✓ (never routes to a dead agent)
- **Restore confirmed:** Northwind's lead back to `None`, Copywriter back to `Active` — zero persistent change.
- **Prompt injection:** `build()` for the Northwind channel placed the snapshot as a system message, right after the frame and before recalled memory.

**Full round-trip (real Minimax call, reply posted back):** with Northwind's lead set to `Copywriter` and dispatch flipped to sync, posting a human `@Friday` message in the channel drove the entire chain — routed to **Copywriter** (the project lead, *not* the default `Friday`), a governed `run_turn` with the snapshot in-prompt, and a reply posted back into the channel as the bot. The agent answered straight *from the snapshot*, unprompted: *"the Northwind Coffee brand identity work is complete — all 9 tasks finished, and multiple deliverables generated including the brand identity PDF and Markdown files."* Lead + dispatch were restored afterward; the demo messages remain visible in the channel.

## How to see it

Set any project's **Project Lead** to an Active agent, then talk to Friday in that project's channel (@mention it) — the project's own lead answers, and it already knows the project's status. The snapshot rides on every turn.

## Tests

- `tests/test_resolve.py` — 6 mock-based tests (routing branches; no DB writes).
- `tests/test_project_context.py` — 7 commit-free tests (snapshot content; `build()` injection).
- 39 existing tests still green (prompt-builder, raven-adapter, memory-project-scope, chat-flow's resolve tests). Migrate clean.

## Files

- `friday_core/routing/resolve.py` — project-aware resolution (the new branch + `_project_lead_for` helper)
- `friday_core/surfaces/raven_adapter.py` — pass `chat_id=doc.channel_id` into resolution
- `friday_core/llm/project_context.py` *(new)* — `project_snapshot_block()`
- `friday_core/llm/prompt_builder.py` — inject the snapshot
- `friday_core/tests/test_resolve.py`, `friday_core/tests/test_project_context.py` *(new)*

## Known follow-ups

- **Full round-trip — DONE** (2026-06-16, Legion/Northwind): `@Friday` in the channel → routed to the project lead → governed turn with the snapshot → real Minimax reply posted back, accurately reflecting "9/9 done + deliverables." Verified via sync dispatch in a console (no stack restart). A smoke test through the *async worker* path on the next Legion deploy would close the last gap.
- **Project Lead role isn't constrained to Orchestrator.** Any Active agent can lead; if a non-orchestrator lead later calls `delegate-task`, the existing role gate handles it. Revisit if we want to enforce Orchestrator-only leads.
- **Snapshot cost** is a few extra indexed reads per turn (bounded: 20 open tasks, 8 deliverables). Fine at single-tenant scale; revisit if turns get hot.
