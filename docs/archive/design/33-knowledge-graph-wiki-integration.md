# 33 — Knowledge Graph and Wiki Integration

> See `00-glossary.md` for term definitions.
> Companion: `32-memory-association-neural-linking.md` (concepts and links), `34-efficient-multilayer-memory-system.md` (memory tiers).
> Phase: not in v0.1 per `42-phase-one-authority-contract.md` §4 (wiki / knowledge graph excluded). Phase 2+.

---

## 1. Vision

Friday agents do not only store memories — they build structured, human-readable knowledge bases. The Frappe Wiki app becomes Friday's collaborative knowledge layer where agents and humans curate domain knowledge that survives across agent versions and team changes.

---

## 2. Why Frappe Wiki

Frappe Wiki is an existing, mature open-source app from the Frappe ecosystem:

- Hierarchical pages with markdown.
- Versioning and rollback.
- Comments and discussion.
- Permissions tied to Frappe roles.
- Already integrated with Frappe's auth, audit, and search.

Reused, not reinvented.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Friday Knowledge Graph (semantic layer)                 │
│   - Memory Concepts (32)                                │
│   - Memory Concept Links                                │
│   - Memory Entries (vector store)                       │
└────────────┬────────────────────────────────────────────┘
             │ surfaces / curates / links to
┌────────────▼────────────────────────────────────────────┐
│ Frappe Wiki (human-readable layer)                      │
│   - Domain pages: /customer-support, /infra-k8s      │
│   - Process pages: "How we handle escalations"          │
│   - Reference pages: "Service S onboarding history"     │
│   - Decision logs: "Why we chose tool X"                │
└─────────────────────────────────────────────────────────┘
```

The wiki is the narrative human-readable layer. The knowledge graph is the structured agent-queryable layer. They link to each other.

---

## 4. Wiki Page Friday Metadata

Fields added to (or linked from) Wiki Page:

- `friday_indexed` — Check.
- `last_indexed_at` — Datetime.
- `linked_concepts` — child table of Memory Concept.
- `domain` — Link → Domain.
- `agent_can_edit` — Check.
- `agent_edit_requires_approval` — Check.

---

## 5. Sync pipeline

Scheduled `friday.wiki.sync_pages` every 15 minutes:

1. Query Wiki Pages modified since `last_indexed_at`.
2. Per page:
   - Extract text content (strip markdown formatting).
   - Chunk to ~1000-token windows with overlap.
   - Embed each chunk via the configured embedding model.
   - Insert chunks into pgvector with metadata: `wiki_page_id`, `domain`, `linked_concepts`.
   - Run concept extraction (`32-memory-association-neural-linking.md`) on the full page; update `linked_concepts`.
3. Update `last_indexed_at`.

---

## 6. `wiki_search` skill

```
wiki_search(query, domain=None)
```

1. Embed query.
2. pgvector similarity search filtered by `domain` if specified.
3. Return top N matching chunks: wiki page title, chunk text, page URL, last-modified date.

Sits alongside `memory_search`. Memory search returns episodic memories; wiki search returns curated knowledge.

---

## 7. Agent-authored edits

Agents propose wiki edits via two skills. **Disabled by default in early phases**; enabled with approval gates from Phase 2 onward.

### New page

`wiki_propose_new_page(title, domain, content_draft)`:

1. Creates a draft Wiki Page with status `Pending Review`.
2. Author = the calling agent's Frappe user.
3. Posts in the domain's War Room.
4. Domain supervisor approves (publishes) or rejects with feedback.
5. On approval, the page goes live with: "Drafted by Friday agent {X} on {date}, approved by {supervisor}."

### Existing page edit

`wiki_propose_edit(page_id, change_summary, new_content)`:

1. Creates a Wiki Page Revision in `Pending Review`.
2. Posts a diff to Raven.
3. Supervisor approves or rejects.
4. On approval, revision is published; on rejection, archived with reason.

---

## 8. Concept anchoring

Every Memory Concept can carry a `canonical_wiki_page` link:

- The wiki page for Project X is the reference on Project X.
- Memory entries about Project X surface this page in their context.
- Wiki page updates invalidate downstream caches.

Hierarchy:

- **Wiki page** — authoritative, curated, narrative.
- **Memory Entries** — raw observations, episodic.
- **Concept** — the bridge.

---

## 9. Auto-generated stubs

When a Memory Concept crosses a maturity threshold (20+ Memory Entries, multiple link types) but lacks a canonical wiki page, Friday proposes a stub:

1. Agent or curator detects the threshold cross.
2. Composes a stub page summarising what memory says about the concept.
3. Submits as `Pending Review`.
4. Supervisor accepts (publishes), modifies, or rejects.

Bootstraps the wiki from accumulated memory rather than expecting humans to write everything from scratch.

---

## 10. Cross-linking inside wiki

Wiki pages use `[[Concept Name]]` syntax. On render or index:

1. Each `[[X]]` resolves to a concept lookup.
2. Concept exists → link to its canonical wiki page (or back-fill if missing).
3. Concept does not exist → create a stub Memory Concept (no wiki page yet).
4. Link recorded in Memory Concept Link with type `References-In-Wiki`.

Over time the wiki becomes a deeply connected graph mirroring the concept graph.

---

## 11. Permissions

Wiki pages inherit Frappe role permissions. Friday additionally checks domain alignment:

- `customer-support` agent reads pages in its domain freely.
- Pages in other domains: only if `cross_domain_read = True` in its profile.
- Edits only on pages tagged with its domain.

Supervisors override for special cases via the standard Frappe permission system.

---

## 12. Unified `friday_search`

A unified skill `friday_search(query)` combines:

- Memory Entries (vector match).
- Wiki pages (vector match).
- ERPNext documents (Frappe full-text search).
- Skill library (skill descriptions).

Returns ranked results across all four sources with type tags. Agents request source filters when needed. The agent's "ask anything" interface.

---

## 13. Wiki as onboarding material

When a new Agent Profile is created, its training context includes:

1. The domain's root wiki page (curated index).
2. The top 10 most-linked pages in that domain.
3. Recent decision-log entries.

New agents inherit organisational knowledge, not just raw skills.

---

## 14. Wiki for human supervisors

Supervisors use the wiki to:

- Document operational policies that agents must respect.
- Record decisions and rationale (decision logs).
- Write postmortems for incidents.
- Maintain runbooks.

Friday's agents read this content as authoritative guidance.

---

## 15. Decision log pattern

Wiki structure: `/decisions/{YYYY-MM-DD}-{slug}.md`.

Each entry records:

- **Context** — what situation prompted the decision.
- **Options considered** — what alternatives existed.
- **Decision** — what was chosen.
- **Rationale** — why.
- **Date and stakeholders**.

Agents read these when facing similar situations and respect the documented rationale.

Skill `decision_log_search(situation_description)` returns relevant past decisions.

---

## 16. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §4 |
| 2 | Wiki app installed; manual wiki authoring (humans write); `wiki_search` with pgvector indexing; Wiki Page Friday Metadata; 15-min sync pipeline |
| 3 | Agent-authored edits with approval gates; concept anchoring; auto-generated stubs |
| 4 | Unified `friday_search`; decision-log skill; `[[concept]]` cross-linking; external wiki migrations (Confluence, Notion, GitBook) |

---

## 17. Open questions

- Wiki page count at scale — full-text + vector search performance on 10K+ pages. Standard PostgreSQL + pgvector handles this; profile in Phase 3.
- Multi-language wiki content — Frappe Wiki has basic i18n. Phase 4 adds language metadata to chunks.
- External wiki migration — adapters per source; not a Phase 2 priority.
