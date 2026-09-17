# ADR-0009 — Archive the design dossier; CONTEXT.md and ADRs replace it

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0012

## Context

`docs/design/` held 97 files — roughly 30 marked LOCKED and 12 marked BUILT or
SHIPPED — describing a governed loop that has never run end to end. The status
vocabulary recorded *decisions taken*, never *behaviour observed*, and was read
as a changelog. `docs/rollouts/` added 69 dated post-implementation records.

Two products had leaked into each other: 16 design documents and 21 rollout
records name RandomPack, inside a kernel whose own test forbids the word.

The front doors were stale in opposite directions. `START_HERE.md` tells a
newcomer "Slice 1 is built… no permission engine, no skill execution yet"
against 341 shipped files. `CODEX.md` §3 lists "Hard fork of Frappe v16" under
"Stack Decisions (All Final — Do Not Re-Open)", which #209 re-opened.
`CLAUDE.md` and `docs/agents/domain.md` instruct every agent to read `CONTEXT.md`
and `docs/adr/`, neither of which existed.

## Decision

**Archive to `docs/archive/`:** `docs/design/`, `docs/rollouts/`,
`docs/testing/`, `CODEX.md`, `START_HERE.md`, `docs/context-conversation.md`.

**Keep in place:** `docs/ports/` (promoted to the definition — ADR-0008),
`docs/decisions/spike-results.md`, `docs/agents/`, `docs/contributing/`,
`docs/project/`, `docs/runbooks/`.

**Rewrite:** `docs/architecture.md` against what the code actually does.

**`CONTEXT.md` is the front door.** Decisions go to `docs/adr/`.

Nothing is deleted. Archived material stays readable and stays in git history;
it simply stops being read as current.

## Consequences

- Status vocabulary from here: an ADR is **Accepted** (a decision we stand
  behind) or **Superseded**. Claims about behaviour need evidence — the command
  that proved it — or they are not made.
- A future reader who needs the reasoning behind an old design can still find
  it; they just will not mistake it for a description of the system.
- Contradicting an archived document is not automatically wrong, but should be
  surfaced rather than done silently, per `docs/agents/domain.md`.

## Evidence

- `docs/design` 97 files (16 name RandomPack); `docs/rollouts` 69 (21 do).
- `START_HERE.md:32` and `CODEX.md:53` contradict current reality and each other.
- `tests/test_kernel_vocabulary.py` forbids product names in kernel code but
  does not scan `docs/`.
