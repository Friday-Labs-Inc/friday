# 34 — Efficient Multi-Layer Memory

> See `00-glossary.md` for term definitions (Memory Entry, Memory Search, Domain).
> Phase: v0.1 installs pgvector but **does not run queries** per `42-phase-one-authority-contract.md` §4 ("Semantic memory / pgvector queries: installed but not used"). The full memory subsystem ships Phase 2+.

---

## 1. Memory is a tool, never auto-injected context

Per `15-openclaw-insights-friday-refinements.md` Insight 3: memory is searchable via skills, not stuffed into every prompt. Naive context-injection:

- Blows token budgets.
- Includes irrelevant content (distraction).
- Does not scale — memory grows unbounded; context does not.

Friday treats memory as a backend the agent queries deliberately, like a database.

---

## 2. Three-tier architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ HOT — Redis (in-memory)                                         │
│   - Recent execution context (last N steps)                     │
│   - Active task scratchpad                                      │
│   - Recently accessed concepts                                  │
│   - TTL: minutes to hours                                       │
│   - Size: ~50MB per active agent                                │
├─────────────────────────────────────────────────────────────────┤
│ WARM — PostgreSQL + pgvector                                    │
│   - Memory Entries (full content + embeddings)                  │
│   - Memory Concepts + Links (32)                                │
│   - Recent (last 90 days) Execution Logs                        │
│   - Indexed for fast retrieval                                  │
│   - Size: ~1–10GB per business after 1 year                     │
├─────────────────────────────────────────────────────────────────┤
│ COLD — Archive (S3 / MinIO / local disk)                        │
│   - Compressed execution logs > 90 days                         │
│   - Memory Entries flagged "archive" by curator                 │
│   - Periodic snapshots                                          │
│   - Retrievable on demand (slow path)                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Categories

Independent of tier, every Memory Entry carries a category.

| Category | Meaning | Example |
|---|---|---|
| **Episodic** | What happened | "Client X opened a support ticket on March 5." |
| **Semantic** | What is true | "Client X SLA: response within 30 days." |
| **Procedural** | How to do | Typically codified as Skills, not memory entries. |
| **Reflective** | What was learned | "Following up with Client X via chat is more effective than email." |

`memory_search` filters by category.

---

## 4. Memory Entry — full schema

| Field | Type |
|---|---|
| `entry_id` | Data (auto-named) |
| `domain` | Link → Domain |
| `category` | Select — Episodic / Semantic / Procedural / Reflective |
| `content` | Long Text |
| `embedding_vector` | pgvector column on companion table |
| `mentioned_concepts` | Child table → Memory Concept |
| `primary_concept` | Link → Memory Concept |
| `source_type` | Select — Agent Execution / Human Annotation / ERPNext Event / Wiki / External |
| `source_reference` | Data — link back to original |
| `created_by` | Link → User (agent or human) |
| `created_at` | Datetime |
| `accessed_at` | Datetime — last time returned by search |
| `access_count` | Int |
| `tier` | Select — Hot / Warm / Cold |
| `importance` | Float, 0.0–1.0 — curator-set |
| `verified` | Check — supervisor confirmed accuracy |
| `sensitive` | Check — elevated permission to read |
| `archive_at` | Date — auto-archive date if set |

---

## 5. Tier transitions

### Hot → Warm

Automatic on agent execution end. Hot tier holds only active context.

### Warm → Cold

Nightly job moves entries to cold when:

- Not accessed in 90 days, AND
- `importance` < 0.5, AND
- Not flagged `verified`.

Cold storage uses S3-compatible object storage. Each archive object is a compressed JSONL of ~1000 entries.

### Cold → Warm (restore)

When `memory_search` has an unusually low hit rate, search expands into cold:

1. Cold-tier scan with looser thresholds.
2. Matches restored to warm tier.
3. Restored entries get `accessed_at = now` and remain warm.

Cold scan is slow (10–30s) and bounded — a fallback.

---

## 6. Hot tier shape

Within Redis, organised per agent execution:

```
agent:{agent_id}:exec:{exec_id}:
  - steps: list of recent step records (last 20)
  - scratchpad: free-form key-value working memory
  - recent_concepts: set of concept IDs recently mentioned
  - cached_skill_results: result cache for current execution
```

Expires at execution end or after 1 hour idle. Long-running heartbeat sessions persist hot memory across heartbeat boundaries.

---

## 7. Write path

`memory_save(content, category, ...)`:

1. Create a Memory Entry (warm tier) in PostgreSQL.
2. Compute embedding via the embedding service.
3. Run concept extraction per `32-memory-association-neural-linking.md`.
4. Update mentioned concepts.
5. Index in pgvector.
6. Update hot memory `recent_concepts`.
7. Submit Execution Log record of the write.

Latency target: < 500ms end-to-end.

---

## 8. Read path

`memory_search(query, ...)`:

1. Embed the query.
2. pgvector similarity search in warm tier (top K, with metadata filters).
3. Hot tier scratchpad scanned for recent matches.
4. Concept graph walk per `32-memory-association-neural-linking.md` for associated context.
5. Merge and rank:
   - Direct vector matches (high weight).
   - Hot tier hits (high weight, very recent).
   - Associated concept results (lower weight).
6. Return top N with metadata.

Below hit threshold → optionally extend to cold tier (only on explicit agent or supervisor opt-in).

Latency target: < 300ms (warm tier only).

---

## 9. Compression

Old episodic memories compress into summary form.

Example: 50 entries about "Support Agent resolved Ticket-X with a follow-up" → one summary "In Q1 2025, Support Agent resolved 50 tickets averaging 3.2 days to completion."

Rules:

- Nightly job on entries > 30 days old in `Episodic`.
- Group by concept and time window.
- LLM-generated summary.
- Originals archived to cold; summary stays in warm.
- Summary tagged `category = Reflective`, `source_type = Compression`.

Keeps warm tier from bloating while preserving aggregate knowledge.

---

## 10. Sharing

Within a Domain, all agents share memory access. Cross-domain access is controlled per `29-domain-specific-self-learning.md`.

For Friday Labs multi-tenant:

- Each business has its own memory namespace.
- No cross-business sharing by default.
- Opt-in to an anonymised community memory pool (Phase 4).

---

## 11. Curator (Phase 2 weekly job)

1. Identify duplicate entries (high embedding similarity, same domain).
2. Propose merges to supervisors via Raven.
3. Identify low-importance, low-access entries → suggest archive.
4. Identify high-access entries lacking `verified` → suggest review.
5. Identify contradicting entries → flag for supervisor.

The curator proposes; it does not modify memory autonomously.

---

## 12. Permissions

| Level | Behaviour |
|---|---|
| **Public** within domain | Any agent in the domain can read |
| **Restricted** | Only specific Agent Role Profiles can read (e.g. salary memories visible to HR agents only) |
| **Sensitive** | Supervisor approval required per read |

Sensitive memories: encrypted at rest with per-tenant key; audited per access.

---

## 13. Forgetting

Some memories must be deleted, not archived:

- GDPR / DPDPA right-to-be-forgotten.
- Memories about ex-employees or ex-customers (retention policy expiry).
- Erroneous memories flagged by supervisor.

`memory_forget(entry_id, reason)`:

- Requires supervisor approval.
- Logs the deletion event with reason (immutable).
- Removes from warm and hot tiers.
- Marks cold archive object for purge on next maintenance.

---

## 14. Performance tuning

pgvector indexes:

- HNSW on embedding column with `M=16`, `ef_construction=64` (defaults).
- Re-index when entry count crosses 100K, 500K, 1M thresholds.
- Partial indexes per domain to keep search scope tight.

Query patterns to optimise:

- Domain-filtered vector search — index on `domain_id` + vector index; planner uses both.
- Concept-filtered — pre-fetch concept's linked entry IDs, then filter.

---

## 15. Monitoring

Tracked:

- Entries per tier.
- Read latency p50, p99.
- Write latency p50, p99.
- Cold-tier scan frequency (should be rare).
- Curator queue depth.
- Memory growth rate per business.

Alerts:

- Read p99 > 1s.
- Cold scans > 10/hour.
- Growth rate suggests bloat (> 1GB/week sustained).

---

## 16. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | pgvector installed; **no queries run** per `42-phase-one-authority-contract.md` §4. Memory Entry DocType is defined for the schema but no `memory_*` skills active |
| 2 | Memory Entry DocType active; pgvector similarity search; `memory_save`, `memory_search`, `memory_get` skills; domain scoping; basic permissions (public / restricted) |
| 3 | Hot tier (Redis); concept extraction + graph (`32-memory-association-neural-linking.md`); compression job; cold tier with S3; curator with proposal workflow |
| 4 | Sensitive memory encryption; forgetting workflow with audit; cross-tenant anonymised community pool (opt-in); advanced curation with anomaly detection |

---

## 17. Open questions

- Embedding model — provider API (OpenAI/Anthropic) vs. local (BGE, E5)? Configurable; local models for cost and privacy at scale.
- Vector dimension trade-off — 768 vs. 1536 vs. 3072? 1536 default; 768 for cost-sensitive deployments.
- Embedding-model upgrades — keep old + new for 30 days, dual-index, then drop old. Designed in Phase 3.
