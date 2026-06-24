# Memory program — step 2b-2: semantic recall (the vector store + blend)

_Shipped 2026-06-23. Completes semantic memory: stores an embedding per memory in
pgvector and blends meaning-similarity into recall. Layers on 2b-1 (the embedding
layer) and 2a (keyword+recency), with the same fail-safe fallback._

## In one sentence

Friday now stores a meaning-vector for each memory and uses it so recall can
match by **meaning**, not just words — "no decorative fonts" can now surface a
memory phrased "hates serifs" — while degrading cleanly to keyword+recency
whenever embeddings aren't available.

## What it actually does (plain terms)

Each memory gets an embedding (from 2b-1) saved next to it in a pgvector table.
When an agent recalls memory, the current message is embedded too, and memories
are ranked by a blend:

- **50% semantic similarity** (how close in meaning),
- **25% keyword match** (full-text, from 2a),
- **15% recency**.

A memory that hasn't been embedded yet still appears — its semantic part counts
as zero, so it's ranked by keyword+recency. Nothing is ever excluded for lacking
a vector.

## What scenarios it now covers

| Scenario | Before (2a) | After (2b-2) |
|---|---|---|
| Query and memory mean the same but share no words | Missed | Surfaced by semantic similarity |
| A new memory is written | Keyword-only | Embedded async (after commit) for future semantic recall |
| Embeddings backend unavailable (no model installed) | n/a | Recall runs keyword+recency — **no regression** |
| A memory has no vector yet | n/a | Still recalled (semantic term = 0) |
| Backend dimension changes (local↔minimax) | n/a | Shadow table auto-recreated at the new dimension; vectors re-backfilled |
| Existing memories (pre-embeddings) | n/a | `backfill_embeddings()` queues them on demand |

## What it means for friday-core

This is the read+write completion of semantic memory:
- **Write:** the `remember` skill and the compaction fact-extractor both queue an
  async embedding job after they save a memory — the conversation turn is never
  blocked on embedding.
- **Store:** a pgvector shadow table (`tabAgent Memory Embedding`), keyed to the
  memory with `ON DELETE CASCADE`, sized to the active backend's dimension, HNSW
  cosine index.
- **Read:** `recall_block` blends the semantic term when a query embedding
  exists.

Crucially, every layer is best-effort: if pgvector is absent, the model isn't
installed, or an embed job fails, recall silently runs the keyword+recency path
from 2a. Semantic recall only ever *adds* signal.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Per-memory vector | `tabAgent Memory Embedding` (pgvector), side-channel to the ORM, created in `after_migrate` |
| Async embedding | `frappe.enqueue` (the `short` queue), after commit |
| Backfill | `bench execute …embed.backfill_embeddings` — queues vectors for existing memories on demand |
| Recall blend | one `frappe.db.sql` with a `LEFT JOIN` + pgvector `<=>` cosine, query vector bound as a `::vector` param |

## What the company can say truthfully today

- "Friday recalls memories by meaning, not just keywords — and it does the
  embeddings on-box by default, so nothing leaves the tenant."
- "It's strictly additive and fail-safe: if embeddings aren't set up, recall
  works exactly as before (keyword + recency)."
- "Verified end-to-end against real pgvector: stored a vector and recalled it
  through the live code path; 35 memory tests pass."

## Risks and limits a product head should hold

- **Embeddings aren't active until a backend is enabled.** The default is the
  local model, which needs a one-time `sentence-transformers` install; until
  then no vectors are produced and recall stays keyword+recency. The plumbing is
  ready the moment it's installed (then run `backfill_embeddings`).
- **MiniMax backend is rate-limited** (if chosen instead) — embeddings would
  throttle; the Redis cache from 2b-1 mitigates, install-local avoids it.
- **Blend weights (0.5/0.25/0.15) are a sensible default, not tuned** — revisit
  once real usage data exists.

## What this unlocks

- The memory program's "recall" half is now complete. Next steps in the program:
  schema hardening (provenance, temporal validity, confidence), the governed
  skill-proposal half of Design 79, and the recall-audit governance surface.

## Numbers for the record

- Files: `llm/after_migrate.py` (+shadow-table hook), `frappe/hooks.py`,
  `llm/embed.py` (+store/job/backfill), `llm/memory.py` (vector blend),
  `skills/handlers_memory.py` + `llm/compression.py` (async embed on write),
  `tests/test_embed.py` (+9), `tests/test_memory_recall_scored.py` (+2).
- Tests: test_embed 20/20, test_memory_recall_scored 15/15, plus compaction +
  worker + extraction suites green. Migrate clean; shadow table + HNSW index
  verified (dim 384); real pgvector store+recall verified live.
- Fail-safe: with no embeddings, recall == step 2a. No regression.
