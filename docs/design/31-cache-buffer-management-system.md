# 31 — Cache Buffer Management

> See `00-glossary.md` for term definitions. Redis roles are listed there.
> Phase: not part of v0.1 per `42-phase-one-authority-contract.md` §3 (basic in-memory caching of permission matrices and Skill rows is implicit; the multi-layer cache here is Phase 2+).

---

## 1. Why a cache layer

A Friday agent answering "what is the current status of record X?" must not hit PostgreSQL every time. With dozens of agents acting in parallel and hundreds of queries per minute, naive direct queries:

- Add 30–80ms latency per query.
- Increase PostgreSQL load and lock contention.
- Risk rate-limiting or connection-pool exhaustion.

A well-designed cache layer dramatically improves responsiveness and protects ERPNext from agent-induced load.

---

## 2. Cache layers

### Layer A — Redis hot cache

For frequently-accessed reference data:

- Reference records: Contact, Project, Task, Document, User, Team.
- Friday Operations Policy thresholds.
- Active Agent Role Profile configurations.
- Permission matrices (role scope per user).
- Currency exchange rates.
- Tax templates.

TTL: 5 minutes default, configurable per data type. Invalidated on document change events.

### Layer B — Process-local cache

Within-execution memoisation:

- Same skill calling `record_get(X)` twice → second call hits process local.
- LRU cache (`functools.lru_cache` or equivalent).
- Bounded to ~10MB per execution.
- Cleared at execution end.

### Layer C — Embedding result cache

For repeated embedding queries:

- Hash query text → cached embedding vector.
- Avoids redundant embedding calls.
- Stored in Redis with 24h TTL.
- ~30–50% of embedding calls in a typical day are duplicates — significant cost saver.

### Layer D — LLM response cache (selective)

For deterministic, idempotent prompts where input fully determines output:

- Skill-internal helper prompts (e.g. "classify this incoming message as urgent / non-urgent").
- **Not** for open-ended agent reasoning — that must always be fresh.
- Hash full prompt + model + temperature → cached completion.
- TTL: 1 hour, configurable per Skill.

Skills must opt in via `cache_enabled = True` in metadata. Off by default to avoid stale reasoning.

---

## 3. Cache Policy DocType

Tuning surface for admins, no code changes.

| Field | Type |
|---|---|
| `cache_layer` | Select — Redis Hot / Process Local / Embedding / LLM Response |
| `data_type` | Data — e.g. `Contact`, `Document`, `Project` |
| `ttl_seconds` | Int |
| `max_size_mb` | Int |
| `invalidation_strategy` | Select — TTL only / Event-based / Both |
| `enabled` | Check |

---

## 4. Pre-load

On Friday startup or on a scheduled refresh (every 30 minutes):

1. Determine the "warm set" of ERPNext records each domain agent commonly references.
2. Bulk-fetch in one query per DocType.
3. Populate Redis in a single MSET pipeline.
4. Record fill time for monitoring.

The warm set is data-driven: a background job inspects Execution Logs over the last 7 days, identifies the most-accessed records per domain, and updates the warm set definition weekly.

Example warm set for Support Agent:

- All active Contacts.
- All Documents tagged for the agent's domain.
- All Teams.
- Recent Task statuses for the last 30 days.
- Operations Policy thresholds for the agent's domain.

Pre-load takes ~5–30 seconds depending on data size and primes the cache before agents need it.

---

## 5. Invalidation

Two strategies, used together.

### TTL-based

Every cached entry has an absolute expiry. Worst-case staleness = TTL value. Suitable for slow-changing data.

### Event-based

Frappe's `doc_events` hook fires on save / submit / cancel. A Friday handler:

```python
def on_doctype_change(doc, method):
    cache_key = f"frappe:{doc.doctype}:{doc.name}"
    redis_client.delete(cache_key)
    # Invalidate related list-view caches.
    redis_client.delete(f"frappe:list:{doc.doctype}")
```

Critical for data where staleness matters (quotas, current resource availability).

---

## 6. Read path

```
frappe_get("Contact", "CONT-001")
1. Process-local cache hit? → return.
2. Redis hot cache hit?     → populate process-local, return.
3. Fetch from PostgreSQL via Frappe ORM.
4. Populate Redis (with TTL) and process-local.
5. Return.
```

Implemented in a single helper `friday.cache.get_doc(doctype, name)` used by all skills.

---

## 7. Write path

On agent-driven modification:

1. Write to ERPNext via Frappe ORM (always).
2. On success, invalidate Redis cache for that record and related list caches.
3. The `doc_events` handler also fires — belt-and-suspenders invalidation.

No write-through caching. Writes always go to PostgreSQL first.

---

## 8. Memory budget

Total Redis budget: configurable, default 2GB per Friday instance.

Per-layer allocation:

- Hot cache: 70% (~1.4GB).
- Embedding cache: 20% (~400MB).
- LLM response cache: 10% (~200MB).

Over budget → `maxmemory-policy allkeys-lru`.

---

## 9. Stampede prevention

Many agents requesting the same uncached key simultaneously cause a thundering herd on PostgreSQL.

Per-key lock pattern:

```python
def get_doc(doctype, name):
    cache_key = f"frappe:{doctype}:{name}"
    cached = redis.get(cache_key)
    if cached:
        return cached

    lock_key = f"lock:{cache_key}"
    with redis_lock(lock_key, timeout=5):
        # Re-check after lock acquired.
        cached = redis.get(cache_key)
        if cached:
            return cached

        doc = frappe.get_doc(doctype, name)
        redis.setex(cache_key, ttl, serialize(doc))
        return doc
```

One process fetches; others wait briefly and read from cache.

---

## 10. Monitoring

| Metric | Target |
|---|---|
| Hit rate per layer | > 85% for hot cache |
| Avg latency hit vs. miss | Tracked |
| Evictions per minute | Tracked |
| Top miss keys | Candidates for pre-load addition |
| Memory utilisation | Tracked |

**Alerts**
- Hit rate < 70% for 15 min → page on-call.
- Memory > 90% for 5 min → page on-call.
- Eviction-rate spike → investigate stampede or pre-load misconfiguration.

---

## 11. Cache bypass

Some operations must always read fresh:

- Resource/quota checks during task submission (race conditions).
- Account balance during a financial action.
- Bank statement reconciliation source data.

Skills mark these reads with `bypass_cache=True`. The helper skips cache and reads directly from PostgreSQL.

---

## 12. Warm-up on deployment

1. Application starts.
2. Pre-load runs as a background task (non-blocking).
3. Health check returns `degraded` until fill completes.
4. Agents starting before fill receive uncached reads (slower but correct).
5. Health check returns `healthy` when fill completes (~30 seconds).

---

## 13. Multi-tenant (Phase 4)

In Friday Labs hosted, each tenant has its own Redis namespace prefix. Cache keys include tenant ID: `tenant:{tid}:frappe:{doctype}:{name}`. No cross-tenant cache sharing.

---

## 14. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Permission matrix cache + Skill row cache in Redis (basic, implicit in `04-security-model.md` and `05-module-design.md`) |
| 2 | Redis hot cache for top 10 ERPNext DocTypes; event-based invalidation via `doc_events`; pre-load on startup; basic monitoring |
| 3 | Process-local cache; embedding cache; Cache Policy DocType; stampede prevention; full dashboard |
| 4 | LLM response cache for selected skills; per-tenant namespacing; warm-set learning from usage patterns |

---

## 15. Open questions

- Redis vs. KeyDB vs. DragonflyDB. Stick with Redis for ecosystem familiarity; revisit if memory or performance becomes a bottleneck.
- Serialisation format: JSON or msgpack. Lean msgpack for size and speed; profile during Phase 2.
- Cross-instance cache coherence in multi-node deployments — Redis pub/sub invalidation channel. Phase 3+ when multi-node ships.
