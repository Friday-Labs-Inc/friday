# Memory — USER.md two-store split (about-the-user vs notes)

_Shipped 2026-06-23. Design 80, Tier 1 #2. Ports Hermes' USER.md/MEMORY.md split.
Additive, no behaviour change for existing memories._

## In one sentence

Memories are now tagged as either "about the user" or "the agent's own notes,"
the agent is prompted to save user facts proactively, and recall labels them so
the model treats a user preference differently from a stray note.

## What it actually does (plain terms)

Hermes keeps two memory stores: USER.md (who the user is — role, preferences,
working style, pet peeves) and MEMORY.md (the agent's own notes — decisions,
conventions, learnings). Friday had one undifferentiated store, and the
`remember` skill only fired when explicitly told.

Now:
- Every memory carries a `memory_type`: `user_profile` or `general` (default).
- The `remember` skill's guidance is rewritten to **save proactively** — when
  the user corrects you, reveals a preference, makes a durable decision — and to
  pick the right `memory_type`.
- At recall, `user_profile` facts are labelled **"[about the user]"** so the
  model reads them as facts about the person it's working with, not as one of
  its own notes.

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| "I prefer short replies" | maybe saved as a generic note | saved as `user_profile`, recalled as "[about the user]" |
| A project decision | generic note | `general` note (unchanged behaviour) |
| Existing memories (pre-split) | n/a | default to `general` — no change |
| The agent deciding when to save | reactive ("when you learn something") | proactive (corrections/preferences/decisions, don't wait to be asked) |

## What it means for friday-core

This sharpens what the agent volunteers to remember and how it's recalled —
which compounds with the learning loop shipped today (the post-turn review now
has a clear `user_profile` target) and with scored/semantic recall (user facts
surface, clearly labelled). It's purely additive: the new field defaults to
`general`, so every existing memory and code path is unchanged, and the pgvector
embedding path is untouched (it joins on row name, not type).

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| The two stores | a single `memory_type` Select field on `Agent Memory` (no second table) |
| Proactive-save guidance | the `remember` Skill row's `when_to_use` + a `memory_type` parameter |
| Recall labelling | `_format_block` tags `user_profile` rows "[about the user]"; both recall paths (scored + recency) now select `memory_type` |

## Faithfulness + disclosed divergences

- **frappe-adaptation:** Hermes' two files → one `memory_type` field; Hermes'
  per-file char budgets → not ported (the DB has no file-size limit; recall is
  token-budgeted as one ranked block). The proactive-write guidance is a
  faithful port of Hermes' tool-schema norms, adapted to the `remember` skill.
- **Simplification (disclosed):** Friday recalls one ranked block with
  user-facts labelled, rather than Hermes' two separate prompt blocks with
  independent budgets. Relevance ranking already floats user facts up for
  user-related queries; a per-type budget split is a later polish item if needed.

## Risks and limits a product head should hold

- **No write-side dedup** — the agent (or the learning-loop review) could save a
  near-duplicate user fact; recall de-prioritises duplicates but a write-side
  dedup/merge is a later step.
- **Injection-scan at write** (Hermes scans memory entries) is not added here —
  low priority while writes come from first-party governed skills; a candidate
  follow-up given the `v01-skills-first-party-trust` stance.
- **Per-type recall budgets** deferred (see Simplification above).

## What this unlocks

- A clean `user_profile` target for the learning loop's reviews.
- A future per-type recall budget / injection-scan if usage warrants.

## Numbers for the record

- Files: `doctype/agent_memory/agent_memory.json` (+`memory_type` field),
  `skills/bootstrap_memory.py` (proactive wording + `memory_type` param),
  `skills/handlers_memory.py` (validate + store), `llm/memory.py` (label +
  select `memory_type` in both recall paths), `tests/test_memory_type.py` (new, 8).
- Tests: test_memory_type 8/8; regressions green (recall_scored 16/16,
  project_scope 7/7, embed 23/23). Migrate clean (1 new field, defaults general).
