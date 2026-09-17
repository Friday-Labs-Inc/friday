# Design 89 — `session_search` (agent searches its own past conversations)

> **Status:** Built 2026-06-24. Closes the last high-value PARTIAL gap from the
> ports-ledger re-audit (Tier 2 #3). Port of Hermes `tools/session_search_tool.py`
> (SQLite FTS5) to Friday's Postgres `Chat Message` table.

## Plain English

A long-lived agent answers thousands of messages and forgets them. Hermes lets an
agent look back over its own transcripts; Friday couldn't. This adds it: a
full-text search over the agent's past `Chat Message` rows, so it can answer
"what did we decide about X?" from real history instead of guessing.

The memory full-text machinery already existed (`llm/after_migrate.ensure_memory_search_schema`
+ `llm/memory._recall_scored`). This applies the **same proven pattern** to Chat
Message — so it's a small, faithful mirror, not new invention.

## Decisions

**D1 — Index Chat Message, not a new store.** Add a generated `content_search`
tsvector column + GIN index on `tabChat Message` via `after_migrate`
(`ensure_chatmessage_search_schema`), mirroring `ensure_memory_search_schema`
verbatim: Postgres-only, idempotent, **savepoint-protected** (a failed DDL rolls
back instead of poisoning migrate — the PR #132 lesson). Friday's transcript IS
the Chat Message table, so there's nothing else to index.

**D2 — Search scope = the calling agent's own messages.** The query filters
`agent_profile = {caller}`. An agent can never read another agent's transcripts.
This is the governance-safe default (and matches how `_recall_scored` scopes
memory to the profile). A future cross-agent/admin search would be a separate,
explicitly-gated skill.

**D3 — Ranking mirrors `_recall_scored`.** `ts_rank_cd(content_search, …)` with
the proven `replace(plainto_tsquery('english', q)::text, '&', '|')::tsquery`
AND→OR fix. Unlike *recall* (which returns all rows ranked), *search* adds a
`content_search @@ tsquery` filter so it returns only actual matches.

**D4 — Graceful fallback.** Non-Postgres, or the FTS column not yet present →
fall back to a `content LIKE %q%` recency scan. The skill always returns
something useful; it never raises on a missing index.

**D5 — Skill shape.** `risk_level=low`, `requires_approval=0`, **no role gate** —
reading your own past messages needs no special privilege. Params: `query`
(required) + `limit` (default 10, cap 50). Declares `Chat Message` READ.
Provisioned via `after_migrate` (`bootstrap_session_search.provision`), registered
in the dispatcher like the other handlers.

## Divergence from Hermes (disclosed)

- **frappe-adapted:** SQLite FTS5 (`hermes_state.py`) → Postgres tsvector+GIN. The
  query semantics (rank by relevance, return matches) are the same.
- **simplified:** Hermes' tool can search across session boundaries with richer
  filters (date ranges, session ids). Friday v1 is keyword + caller-scope +
  limit. Date/session filters are a trivial follow-up if wanted.

## Tests

`tests/test_session_search.py` (mock-based): query required; the FTS SQL is scoped
to the caller (`m.agent_profile = %(profile)s`) and uses the `@@` match filter;
empty results handled; non-Postgres falls back to LIKE; the DDL rolls back to its
savepoint on failure and no-ops on non-Postgres.

**Migrate gate:** run by the coordinator before merge (the FTS column is a real
schema change).
