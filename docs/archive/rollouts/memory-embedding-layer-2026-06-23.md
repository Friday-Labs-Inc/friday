# Memory program — step 2b-1: the embedding layer

_Shipped 2026-06-23. The first half of semantic recall: turning memory text into
vectors. The vector store + recall blend (2b-2) plugs in on top._

## In one sentence

Friday can now turn a piece of text into an "embedding" (a vector that captures
its meaning) — computed **on-box by default** so nothing leaves the tenant —
with a Redis cache so the same text is never embedded twice.

## What it actually does (plain terms)

To recall memories by *meaning* (not just matching words), each memory's text
gets converted into a list of numbers — an embedding — and similar meanings end
up with similar numbers. This module produces those embeddings.

It has a pluggable backend:
- **local (default):** a small model running inside the bench. No rate limit,
  no data leaves the tenant, free — matching the governance stance.
- **minimax (optional):** MiniMax's `embo-01`, over the provider you already
  configure. Useful, but it sends text out and is rate-limited.

Pick with a site-config key (`friday_embedding_backend`); blank = local.

## Why this shape (what the live probe taught us)

We tested MiniMax's embeddings against the real API before building. Two facts
changed the plan: (1) its request/response shape is MiniMax-native (`texts` in,
`vectors` out — **not** the OpenAI shape an earlier assumption used), and (2) it
rate-limits aggressively (RPM). Both pushed toward **local-by-default**, which
also keeps embeddings on-box — consistent with "nothing leaves the tenant." The
verified MiniMax shape is encoded for when the minimax backend is chosen.

## What scenarios it now covers

| Scenario | Behaviour |
|---|---|
| Same text embedded again | Served from the Redis cache — no recompute |
| Local model not installed | Returns None (logged) → recall falls back to keyword+recency |
| MiniMax rate-limited / errors | Returns None (logged) → recall falls back |
| Empty text | Returns None |
| Backend switched via site config | Cache is backend-scoped, so no stale cross-backend vectors |

## What it means for friday-core

This is purely additive infrastructure — it touches no conversation path yet.
The load-bearing property: `get_embedding` **never raises**. Embeddings are an
enhancement; if they're unavailable for any reason, memory recall keeps working
exactly as step 2a (keyword + recency). Semantic recall is layered on top in
2b-2, behind the same fail-safe.

## How it gets along with the Frappe ecosystem

| Friday concept | Frappe reality |
|---|---|
| Backend selection | `frappe.conf` site-config key (`friday_embedding_backend`) — no migration |
| Embedding cache | `frappe.cache()` (Redis) — the performance tier the stack already runs |
| MiniMax provider | Read from the existing `LLM Provider` row (`get_password` for the key) |
| Local model | `fastembed` (ONNX, torch-free) preferred — `BAAI/bge-small-en-v1.5`, 384-dim; falls back to `sentence-transformers` if that's what's installed. Lazily imported. |

## Risks and limits a product head should hold

- **Local embeddings need a one-time install to activate.** Run
  `./env/bin/pip install fastembed` (ONNX, torch-free — works on Python 3.14
  where torch has no wheels). First use downloads the ~90MB ONNX model and
  caches it. Until installed, the local backend returns None → recall stays on
  keyword+recency (no breakage). **PROVEN on the Mac (2026-06-23):** a
  zero-keyword-overlap query ("which typeface should we steer clear of")
  surfaced "avoid serif fonts" #1 on semantic similarity alone (0.70 vs 0.41 for
  unrelated memories). **Dependency caveat:** fastembed bumps
  `click`/`filelock`/`pyjwt` past frappe's pins — `bench` still runs, but for a
  clean prod install pin a fastembed build compatible with `click~=8.3.1` or
  isolate the embedding step.
- **MiniMax backend is rate-limited.** If chosen, heavy/backfill embedding needs
  throttling — the cache helps, but it's not a substitute for the local path.
- **No vectors are stored or used yet.** This step only *generates* embeddings.
  Storing them (pgvector) and blending them into recall is 2b-2.

## What this unlocks

- 2b-2: a pgvector column on `Agent Memory` sized to the active backend's
  dimension, the write-path that embeds new memories (async), a backfill, and
  the vector-similarity term blended into the recall score from 2a.

## Numbers for the record

- Files: `llm/embed.py` (new), `tests/test_embed.py` (new, 11 tests).
- Tests: 11/11 green. No schema change → no migration. No conversation-path
  change. MiniMax request/response shape verified live before coding.
