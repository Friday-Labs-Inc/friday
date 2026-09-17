# 38 — Performance Optimisation and Bottleneck Analysis

> See `00-glossary.md` for term definitions.
> v16-attributable performance wins live in `13-frappe-v16-leverage-strategy.md` §2. This document covers Friday-side bottlenecks and mitigations.

---

## 1. Performance goals

Friday must feel responsive under realistic load:

- Single-agent task completion — p50 < 5s, p99 < 30s for simple tasks.
- Concurrent agents — 50+ agents executing in parallel on a single 8-core Friday node.
- Memory search — p50 < 200ms, p99 < 800ms.
- Skill dispatch (selection + validation) — < 100ms.
- War Room message → agent pickup — < 2s end-to-end.

Misses degrade the autonomous experience and erode supervisor trust.

---

## 2. Bottleneck categories

1. LLM provider latency (largest; often external).
2. Vector search on pgvector with poor indexing.
3. Frappe ORM overhead on hot queries.
4. Container startup for skill execution (cold start).
5. Permission gate evaluation.
6. Cross-process synchronisation for Raven War Room.

Each addressed below.

---

## 3. LLM provider latency

A single LLM call to a frontier model takes 1–8 seconds. Five serial calls feels slow.

**Parallel calls.** Independent reasoning steps run concurrently (e.g. "classify these 10 emails", "validate these 5 documents").

**Streaming.** Stream LLM responses where the agent can act on partial output. Stream final summaries to Raven in chunks.

**Smaller-model fallback.** Deterministic, simple sub-tasks (classification, extraction, validation) use a cheaper/faster model (Haiku-class). Frontier models reserved for complex reasoning. Skill DocType carries `recommended_model_tier` (Light/Standard/Heavy); dispatcher routes accordingly.

**Provider failover.** Two configured providers (e.g. Anthropic + a local OSS model). If primary times out beyond threshold, fail over to secondary.

**Batched calls.** Analytics tasks evaluating dozens of items batch into a single prompt with structured output. One call replaces ten.

---

## 4. Vector search

A naive pgvector scan over millions of rows is slow. With proper indexing, sub-second p99 is achievable.

**HNSW index**

```sql
CREATE INDEX idx_memory_embedding ON memory_entry_embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

Tune `ef_search` at query time. Higher = better recall, slower. Start at 40, profile.

**Partial indexes per domain.** Most queries are domain-scoped per `29-domain-specific-self-learning.md`.

```sql
CREATE INDEX idx_memory_embedding_support ON memory_entry_embeddings
USING hnsw (embedding vector_cosine_ops)
WHERE domain_id = 'customer-support';
```

**Pre-filtered search.** Apply metadata filters (domain, time range, concept) before vector search where possible. PostgreSQL's planner can sometimes do this; explicit hints help.

**Cold tier bypass.** Cold tier is never scanned synchronously — only async on explicit request (`34-efficient-multilayer-memory-system.md`).

**Dimension choice.** 1536-dim embeddings — higher quality but slower than 768-dim. Profile per workload.

---

## 5. Frappe ORM overhead

`frappe.get_doc` performs role permission checks, link-field resolution, and hook firing on every call. On hot paths this adds 50–100ms.

**Bulk reads.** Replace 10 `frappe.get_doc` calls with one `frappe.get_all` or one direct SQL.

**Direct SQL for hot paths.** Where role checks are not needed (admin-context background tasks), use `frappe.db.sql` or `frappe.db.get_value` instead of full doc load.

**Caching layer.** The cache layer in `31-cache-buffer-management-system.md` intercepts hot reads before ORM.

**Hook audit.** Identify and disable unnecessary `doc_events` hooks for Friday-internal DocTypes that do not need them.

---

## 6. Container cold start

Spinning up a Docker container for skill execution takes 1–3 seconds. Every-call cold-spawn is unacceptable.

**Warm pool.** 5–20 pre-started containers in an idle pool. Grab one, run, return (or recycle).

**Per-profile pools.** Different agent profiles need different images. Pool segments per image; common images get larger pools.

**Container reuse within execution.** Within a single agent execution, the same container handles multiple skill calls if isolation requirements permit.

**Async fill.** A background job tops up the pool. Spikes grow the pool; idle drains it.

Per `42-phase-one-authority-contract.md` §5 the warm pool is **deferred to Phase 1.5**. v0.1 ships only the cold-spawn path per the §5 minimum bar.

---

## 7. Permission gate

Every skill call passes through the permission gate (`04-security-model.md`). Naive evaluation of complex matrices takes 20–50ms.

**Permission decision cache.** Redis cache of `(user_id, skill, target_doctype) → allow/deny`. TTL 5 minutes. Invalidated on role / profile changes.

**Pre-computed permission sets.** For each Agent Role Profile, compute and cache the full set of `(skill, target_doctype, action)` tuples it can perform. Skill calls become O(1) membership tests.

**Approval threshold lookup.** Threshold checks ("amount ≤ ₹50,000 → autopilot") use indexed lookups, not table scans.

---

## 8. Raven War Room throughput

When 20 agents post simultaneously, the chat backend can lag.

**Async posting.** Agents fire-and-forget War Room posts to an internal queue. A worker flushes to Raven.

**Batching.** Multiple posts within a 100ms window from the same agent batch into a single Raven message.

**Pagination.** War Room read APIs paginate efficiently. Default page size 50 messages; older messages on-demand only.

**Bot account pool.** Each Friday agent has a Frappe user, but Raven message authoring uses a small pool of "bot" identities to reduce per-account overhead. The original agent author is preserved in message metadata.

---

## 9. Benchmark suite

Standardised benchmarks ship with Friday and run in CI on every core PR. Regressions block merge.

| Benchmark | What it measures |
|---|---|
| `benchmark_simple_task.py` | 100 sequential simple record-create tasks; p50, p95, p99 latencies |
| `benchmark_concurrent_agents.py` | 50 concurrent agents, each a 5-step task; wall-clock + resource utilisation |
| `benchmark_memory_search.py` | 100K pre-loaded entries; 1000 vector searches; p50/p99 latency |
| `benchmark_war_room_throughput.py` | 500 messages/second sustained for 2 minutes; lag distribution |

---

## 10. Profiling tools

- **Python** — py-spy, cProfile + snakeviz.
- **PostgreSQL** — `auto_explain`, `pg_stat_statements`, `EXPLAIN ANALYZE` on slow queries.
- **Redis** — `SLOWLOG`, latency monitor.
- **Containers** — cAdvisor, Prometheus.
- **End-to-end traces** — OpenTelemetry instrumentation; Jaeger or Tempo backend.

Every agent execution emits a trace. Slow executions auto-flagged for review.

---

## 11. Optimisation by phase

| Phase | Scope |
|---|---|
| 1 (v0.1) | Permission decision cache (basic Redis); pgvector installed (queries Phase 2 per `34-efficient-multilayer-memory-system.md`); Frappe ORM bulk reads on hot paths; cold-spawn sandbox per `42-phase-one-authority-contract.md` §5; latency monitoring with simple histogram; standardised benchmark suite |
| 1.5 | Warm container pool per `42` §5 deferred items |
| 2 | HNSW indexes on memory tables; streaming LLM responses with War Room chunked delivery; OpenTelemetry tracing; async Raven posting; per-profile container pools |
| 3 | Parallel LLM orchestration; provider failover; pre-computed permission sets; memory-tier optimisation; cost attribution dashboard |
| 4 | ML-tuned query plans; auto-scaling pools; multi-region deployments |

---

## 12. Capacity planning

| Scale | Configuration |
|---|---|
| **Small** (≤ 50 employees, ≤ 10K monthly transactions) | 1 Friday node — 8 CPU, 16GB RAM, 100GB SSD. Handles 50 concurrent agents. LLM cost dominates (~₹15–50K/month for moderate usage) |
| **Mid** (≤ 500 employees, ≤ 100K monthly transactions) | 2–3 Friday nodes behind a load balancer. Shared PostgreSQL primary + read replica. Redis cluster. Cost scales roughly linearly with transaction volume |
| **Enterprise** (> 500 employees) | Multi-node Friday cluster. Dedicated PostgreSQL with WAL replication. Multi-region Redis. Custom optimisation per workload |

---

## 13. Cost optimisation

LLM cost is the largest variable cost. Reduce by:

1. Use Haiku / Light tier for simple sub-tasks (§3).
2. Cache LLM responses for idempotent prompts (`31-cache-buffer-management-system.md`).
3. Batch related calls.
4. Prefer smaller context — pass only relevant skill descriptions per skill ceiling (`15-openclaw-insights-friday-refinements.md`).
5. Trim memory search results to top N actually needed.
6. Use the embedding cache aggressively.

Track cost per task type. Surface in the Performance Insights Agent report (`36-analytical-predictive-agents.md`). Identify outliers.

---

## 14. SLA targets (Friday Labs hosted)

| Metric | Target | Hard SLA |
|---|---|---|
| Agent task completion p99 | < 30s | < 90s |
| Memory search p99 | < 800ms | < 2s |
| Uptime (excluding maintenance) | 99.5% | 99.0% |
| War Room post latency | < 2s | < 10s |

Self-hosted deployments are not bound by SLA, but the same targets serve as quality goals.

---

## 15. Open questions

- Ship Friday with Prometheus + Grafana pre-configured? Probably yes Phase 2 — most operators do not know what to monitor.
- Performance vs. safety overhead — hard cap: safety overhead < 10% of task time.
- Cold-start latency for the first agent of the day — < 2 seconds via warm pool (Phase 1.5).
- Optimal embedding dimension — profile both 768 and 1536 during Phase 2; choose on quality/cost trade-off.
