# Memory program — step 2a: scored recall (relevance + recency)

_Shipped 2026-06-23. Second build of the memory architecture program. Replaces
newest-first "dump recent rows" recall with Postgres full-text relevance blended
with recency. The semantic (pgvector) signal is added in step 2b._

## In one sentence

When an agent recalls its memory, Friday now picks the memories most **relevant
to what's being discussed right now** (plus recent ones) — instead of just the
newest ones — so an old-but-on-topic fact no longer gets silently dropped.

## What it actually does (plain terms)

Before, recall worked like reading a notebook from the most recent page
backward until the page budget ran out. If an important note was written months
ago, it sat below the cut and the agent never saw it — even when it was exactly
what the current question needed.

Now recall ranks every memory by two things at once:
- **Relevance** — does this memory's text match what the user is asking about
  right now? (Postgres full-text search.)
- **Recency** — newer memories still get a gentle boost.

The blend is 60% relevance + 40% recency, so an old note about "Loop Coffee
hates serif fonts" surfaces the moment someone asks about Loop's brand — even
if fifty newer notes were written since.

## What scenarios it now covers

| Scenario | Before | After |
|---|---|---|
| Old but on-topic fact, many newer notes since | Dropped past the budget | Ranked to the top by relevance |
| Recent and relevant | Shown | Shown (relevance + recency both high) |
| No query / a non-Postgres site | Newest-first | **Falls back to newest-first** (unchanged, safe) |
| The full-text index is missing or the query errors | n/a | Falls back to newest-first — never breaks the turn |
| In a project room | This project's + global memories only | Same scoping, now also relevance-ranked |

## What it means for friday-core

Recall is on the hot path of **every** turn, so this is built fail-safe: the
scored path runs only on a Postgres site with a real query, and **any** problem
(missing index, SQL error, non-Postgres) falls straight back to the original
newest-first recall. The worst case is "no improvement," never "broken turn."

Paired with step 1 (which now *captures* more facts at compaction), this step
makes those facts *findable* — the write side and the read side of memory both
get better.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Relevance ranking | A Postgres `tsvector` generated column + GIN index on `tabAgent Memory` |
| Where the index comes from | An `after_migrate` hook (`ensure_memory_search_schema`) — Postgres-only, idempotent, best-effort |
| Why a side-channel column | Frappe's ORM has no `tsvector` field type, so the column lives as DDL alongside the DocType (Frappe's schema sync leaves it alone) |
| The current message | Threaded from `prompt_builder.build` into `recall_block(query=…)` so recall knows what to rank against |

## What the company can say truthfully today

- "Friday recalls the memories most relevant to the current conversation, not
  just the most recent — so it stops forgetting old-but-important facts."
  (Validated live against Postgres; 13 tests; existing memory tests still pass.)
- "It is fail-safe: recall degrades to the previous behaviour rather than ever
  breaking a conversation."
- "All ranking happens inside the tenant's own Postgres — no data leaves."

## Risks and limits a product head should hold

- **Keyword-level relevance only (for now).** Full-text matches words, not
  meaning: "no decorative fonts" won't match a memory phrased "hates serifs"
  until the **semantic (pgvector) signal in step 2b** is added. This step is the
  foundation that 2b plugs into.
- **No Redis caching yet.** The per-query result cache and embedding cache land
  with 2b (where they matter — full-text queries vary per turn, so caching pays
  off more once embeddings are involved).
- **`english` text config.** The FTS uses the English dictionary; non-English
  memories still match on exact tokens but get weaker stemming. Revisit if a
  deployment is non-English.

## What this unlocks

- Step 2b — semantic recall: add a pgvector column (MiniMax `embo-01`
  embeddings, already available) and blend a vector-similarity term into the
  same score; add the Redis embedding cache. Drop-in on top of this.
- Step 3 — schema hardening (memory_type, confidence, provenance, validity).
- The `session_search` skill (ledger gap #3) reuses the same FTS pattern on
  `Chat Message`.

## Numbers for the record

- Files: `llm/memory.py` (scored recall), `llm/prompt_builder.py` (threads the
  query), `llm/after_migrate.py` + `frappe/hooks.py` (the FTS index hook),
  `tests/test_memory_recall_scored.py` (new, 13 tests).
- Tests: 13/13 new green; existing memory + compaction suites green (no
  regression). Migrate clean on Postgres; the `memory_search` column + GIN index
  verified live; the real scored query verified to execute on Postgres.
- Default behaviour preserved everywhere the scored path doesn't apply (no
  query, non-Postgres, any error).
