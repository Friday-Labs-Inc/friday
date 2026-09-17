# Memory program — step 1: extract facts before compaction

_Shipped 2026-06-23. First build of the memory architecture program (the
Postgres-vector + Redis-cache plan; Design 80 writeup pending). Ports Hermes'
`on_pre_compress` hook, adapted to write governed `Agent Memory` rows._

## In one sentence

When a long conversation gets summarized to save space, Friday now **mines the
old turns for durable facts first** and saves them to memory — so knowledge the
agent never explicitly chose to "remember" isn't quietly lost when the raw
turns are folded into a summary.

## What it actually does (plain terms)

A long chat eventually won't fit in the model's window, so Friday compacts the
old middle of the conversation into a short summary and keeps only the recent
turns verbatim. That summary is lossy — anything not captured in it is gone.

Before this change, that meant a preference the user mentioned in passing
("we always go sans-serif", "the deadline moved to April"), if it wasn't
explicitly saved via the `remember` tool, vanished the moment compaction ran.

Now, right before those old turns are folded away, a cheap model pass reads them
and pulls out durable facts — who the user is, their preferences, decisions,
standing instructions — and writes each as a governed `Agent Memory` row. The
knowledge survives the compaction.

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| User states a preference mid-chat, agent never calls `remember` | Lost at next compaction | Captured as an `Agent Memory` row before the fold |
| A decision is made over several turns | Only as much as the lossy summary kept | Extracted as a durable fact |
| The same fact is already in memory | n/a | Skipped (light dedup — exact match) |
| The extractor model errors or is unreachable | n/a | Logged; compaction proceeds normally (best-effort) |
| The model returns junk / "nothing to save" | n/a | Parsed to zero facts; nothing written |
| A model returns 50 facts | n/a | Capped at 10 |

## What it means for friday-core

Compaction used to be a one-way *loss* of any knowledge the agent didn't
explicitly save. Now compaction is also a *capture* point — the moment we're
about to discard raw turns is exactly when we harvest what was worth keeping.
This is the first concrete step of the memory program: turning Friday's memory
from "only what the agent explicitly saved" toward "the agent learns from the
conversation."

It is purely additive and best-effort: the extraction can never break
compaction, and compaction can never break the turn. A module flag
(`EXTRACT_FACTS_ON_COMPACTION`, default on) disables it entirely if needed.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Extracted fact | A normal `Agent Memory` DocType row — auditable, archivable, visible in Desk |
| The extractor | The same auxiliary provider compaction already uses (`_resolve_aux_provider`) |
| Attribution | `agent_profile` + `source_session` + `project` (via `project_for_session`) — same as the `remember` skill |
| Governance | Memory rows are governed records; the write is system machinery (like the Compaction Summary insert it sits beside) |

## What the company can say truthfully today

- "Friday no longer loses durable knowledge when it compacts long
  conversations — it extracts facts to governed memory before discarding raw
  turns." (Covered by 13 tests; the existing 24 compaction tests still pass.)
- "The capability is best-effort and bounded — it can never break a
  conversation, and it is capped and de-duplicated."
- "Every extracted fact is a normal, auditable memory record — nothing leaves
  the tenant."

## Risks and limits a product head should hold

- **Dedup is exact-match only.** Near-duplicates and contradictions are NOT yet
  reconciled — that's the conflict-resolution write-gate, a later step. Until
  then memory can accumulate slightly-overlapping facts.
- **No provenance/temporal fields yet.** Extracted facts use today's `Agent
  Memory` schema; `source_type`, `confidence`, and `valid_from/to` arrive in the
  schema-hardening step.
- **Recall is still "dump recent rows."** This step *writes* better memory; it
  does not yet *retrieve* better. The hybrid-retrieval foundation (pgvector +
  keyword + recency) is the next, higher-leverage step.
- **Extraction quality depends on the aux model.** A weak model will under- or
  over-extract; tunable later via the prompt and the cap.

## What this unlocks

- Step 2 — hybrid retrieval (pgvector + full-text + recency, Redis-cached): with
  more facts now being captured, good retrieval is the next multiplier.
- Step 3 — schema hardening (memory_type, confidence, provenance, validity).
- Step 4 — the post-turn learning loop (Design 79), which this complements:
  compaction-time capture + turn-time review = two paths to the same governed
  memory.

## Numbers for the record

- Files: `llm/compression.py` (extraction added), `tests/test_memory_extract_on_compact.py`
  (new, 13 tests), `tests/test_compression.py` (patched the integration class to
  account for the new step).
- Tests: 13/13 new green; 24/24 existing compaction green (no regression).
- No schema change → no migration. Default-on, flag-guarded, best-effort.
