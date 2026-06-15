# Design 73 — Project context + scoped memory (Rollout)

**Date:** 2026-06-15
**Design:** [`73-project-conversation-surface.md`](../design/73-project-conversation-surface.md)
**Status:** Built + verified live.

## The bug (what you saw)

In the `proj-fli-001` channel — a room dedicated and linked to project FLI-001 — you asked Friday "@Friday hey any updates" and it replied *"which project are you asking about?"* and then listed **three different projects** (FLI-001, RP-PRJ-100, Loop Coffee "no serifs"). Friday was standing inside the FLI-001 room and didn't know it, and its memory pulled in every other client's facts.

## The fix, in plain words

1. **Friday now knows which room it's in.** When you talk in a project channel, Friday is told up front: *"This is the room for project FLI-001 — scope every answer to this project."* It resolves the project straight from the channel (no extra plumbing), so it stops asking "which project?".
2. **Memory is scoped to the project.** Each memory now carries a project tag. In the FLI-001 room, Friday recalls **only FLI-001's memories + general/global ones** — never another client's. One client's "no serifs" can't leak into another's room.
3. **Going forward, new memories self-tag.** Memories learned in a project room (and RandomPack event memories) are tagged with their project automatically.
4. **Cleaned the existing data.** Tagged the existing FLI-001 / RP-PRJ-100 memories; archived 2 leftover test-pollution memories ("Loop Coffee", which wasn't even a real project here).

## Proven live

Friday's memory recall **in the FLI-001 room** now contains exactly three FLI-001 facts (gate1 Mission Control, gate2 approved, gate1 verification note) and **nothing from RP-PRJ-100 or the test "no serifs" memory**. Verified `mentions other projects: False`.

## How it works (no new plumbing)

The session id already encodes the surface: a Raven chat session *is* the channel id, and a project room's channel links its Project (Slice 1). So `prompt_builder.build()` resolves the project from `session_id` — no need to thread a new parameter through the adapter, gateway, or `run_turn`. Task turns (`task::<name>`) resolve via the task's project too.

## Files

- `doctype/agent_memory` — new `project` Link field
- `llm/memory.py` — `project_for_session()`, project-scoped `recall_block(project=...)`, `backfill_memory_projects()`
- `llm/prompt_builder.py` — resolves the project, injects PROJECT CONTEXT framing, scopes recall
- `skills/handlers_memory.py` — the `remember` skill tags new memories with their project
- `surfaces/randompack.py` — event memories tag their project (by backend_ref)
- `tests/test_memory_project_scope.py` — 8 tests

## Known follow-ups

- Memories learned outside any project stay **global** (correct) — they show in every room. Only project-specific facts are scoped.
- The standalone DM case (no project) is unchanged: all memories recalled.
