# 32 — Memory Association and Neural Linking

> See `00-glossary.md` for term definitions (Memory Entry, Memory Search, Domain).
> Phase: not in v0.1 per `42-phase-one-authority-contract.md` §4. Phase 2+.

---

## 1. Why flat memory is not enough

A naive memory system stores facts independently:

- "Service X prefers async notifications."
- "Service X had an outage in March."
- "March outages were traced to dependency S's faulty release."

These three facts live as separate entries. When an agent asks about Service X, it surfaces the first two. The link to Dependency S is lost.

Real cognition links concepts. Thinking "Service X" surfaces related concepts (its outages, the dependency behind those outages, the module involved) by association strength.

This document designs an association graph that augments Friday's vector memory.

---

## 2. Memory Concept DocType

A concept is a noun that anchors memory entries: a Service, Dependency, Module, Project, Skill, Issue, Topic, Event.

| Field | Type |
|---|---|
| `concept_name` | Data |
| `concept_type` | Select — Service / Dependency / Module / Project / Skill / Issue / Topic / Event / Other |
| `linked_doctype` | Data (optional) — e.g. `Project` if anchored to a Frappe DocType |
| `linked_docname` | Data (optional) — e.g. `PROJ-001` |
| `domain` | Link → Domain (per `29-domain-specific-self-learning.md`) |
| `created_from` | Select — Manual / Auto-Extracted / Imported |
| `embedding` | Long Text — concept vector |
| `aliases` | Small Text — alternate names |

When agents process content, an extraction pass identifies concept mentions, matches to existing concepts, or creates new ones.

---

## 3. Memory Concept Link DocType

The edge in the association graph.

| Field | Type |
|---|---|
| `from_concept` | Link → Memory Concept |
| `to_concept` | Link → Memory Concept |
| `link_type` | Select — Mentioned-With / Caused-By / Resolved-By / Owns / Part-Of / Related-To / Custom |
| `strength` | Float, 0.0–1.0 |
| `decay_rate` | Float — strength decay without reinforcement |
| `evidence_count` | Int |
| `last_reinforced_at` | Datetime |
| `domain` | Link → Domain |
| `created_at` | Datetime |

A link from "Service X" to "Dependency S" with type `Caused-By` represents the example chain above.

---

## 4. Memory Entry extension

Two fields added:

- `mentioned_concepts` — child table of Memory Concept.
- `primary_concept` — Link → Memory Concept (the main subject, if any).

---

## 5. Concept extraction

When a Memory Entry is created:

1. The entry text is processed by a lightweight extraction pipeline.
2. Named entities (people, organisations, products, places) identified.
3. Each entity matched to an existing Memory Concept (by name, alias, or embedding similarity).
4. No match → new Memory Concept created with `created_from = Auto-Extracted`.
5. `mentioned_concepts` populated.
6. For each pair of mentioned concepts, a Memory Concept Link created or reinforced.

Extraction: a small LLM call (Sonnet/Haiku-class) with a focused prompt and JSON output. Avoid spaCy and similar — too brittle for the variety of Friday inputs.

---

## 6. Association strength

```
s_new = s_old * exp(-decay_rate * time_elapsed) + reinforcement
```

`reinforcement` is typically 0.1 per fresh co-occurrence, capped at 1.0. `decay_rate` defaults to 0.05/day — a link unreinforced for a month decays from 1.0 to ~0.22.

Links with strength < 0.05 are pruned nightly to keep the graph tractable.

---

## 7. Retrieval with association

`memory_search(query)` is extended:

1. Embed the query; find top K matching Memory Entries (vector search).
2. Identify primary concepts of those entries.
3. For each primary concept, walk the association graph up to depth 2 with strength > 0.3.
4. Surface reached concepts as "associated context".
5. Optionally retrieve top memory entries for each associated concept.

Result:

```json
{
  "direct_matches": [...],
  "associated_concepts": [
    {"concept": "Dependency S", "via": "Service X", "strength": 0.78, "memories": [...]}
  ]
}
```

Agent sees the surrounding knowledge web, not just direct hits.

---

## 8. Disambiguation

"John Smith" might be three different people. Friday handles this:

1. Each concept has a unique ID; never collapsed by name alone.
2. `aliases` holds variations.
3. On extraction, all concepts matching that name are pulled with their evidence; surrounding context picks the right one via a small LLM call.
4. Ambiguous → memory entry flagged for human review rather than guessed.

---

## 9. Cross-domain associations

Memory Concept Links carry a domain. Cross-domain links (e.g. `customer-support.Service S` → `infra-networking.Issue Q`) require:

- Explicit allow-list in the Domain DocType, or
- Approval workflow if not allow-listed.

Prevents accidental cross-contamination; permits intentional integration.

---

## 10. Lifecycle

**Creation** — auto-extracted from memory entries or manually created by supervisors.

**Maintenance (daily job)**
- Decay association strengths.
- Prune below-threshold links.
- Merge duplicate concepts (high concept-embedding similarity, e.g. "ACME Co." and "ACME Co").
- Flag orphan concepts (no links, no memory entries) for cleanup.

**Retirement** — concepts inactive > 180 days move to an archive table. Queryable but not in default search results.

---

## 11. DocType anchoring

When a Memory Concept has `linked_doctype` and `linked_docname` set, it is anchored to a real Frappe document. Agents move both directions:

- Memory → records: "What do you know about Project X?" pulls the Project doc AND surrounding memory.
- Records → Memory: opening Project X displays a Friday-rendered sidebar of associated memories (Phase 3 UI).

---

## 12. Concept Graph view (Phase 3)

For a chosen concept:

- Nodes sized by memory count.
- Edges weighted by strength.
- Colour-coded by domain.
- Filterable by link type.

Used by supervisors to audit "what does Friday think it knows about Project X?"

---

## 13. Worked example

Task: "Draft a follow-up message to Service X about their pending incident."

1. Memory search on "Service X pending incident".
2. Direct matches:
   - "Service X deployed Module A on March 5".
   - "Service X had an outage involving Module A in March".
3. Associated concepts via graph:
   - Module A → Dependency S (caused-by, strength 0.78).
   - Outage → "Resolution: patched release" (resolved-by, strength 0.9).
4. Agent now knows: there was an outage, it was resolved with a patch, original cause was Dependency S.
5. Drafted update acknowledges the prior issue and confirms the patched release is being rolled out.

Without association, the agent might draft a generic follow-up that ignores the incident history.

---

## 14. Performance

Storage:

- ~10K memory entries → ~5K concepts → ~50K links typical for an active SMB after a year.
- Per concept ~2KB (with embedding); per link ~500 bytes.
- Total ~50MB per business — trivial.

Latency per `memory_search`:

- Vector search on memory: 50–100ms.
- Graph walk (depth 2, strength filter): 20–50ms.
- Concept retrieval: < 10ms each.
- Total: 200–300ms. Acceptable.

---

## 15. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope. Flat memory only — vector search per `34-efficient-multilayer-memory-system.md` baseline |
| 2 | Memory Concept + Memory Concept Link DocTypes; concept extraction pipeline; association walk in `memory_search`; manual concept management UI |
| 3 | Concept Graph visualisation; ERPNext sidebar integration; concept merge/split workflows; domain-level association policies |

---

## 16. Open questions

- Embedding model for concept embeddings — same as memory entries or separate? Same in Phase 2; revisit if quality demands specialised embedding.
- Concepts that should never link (e.g. sensitive client info that must stay isolated) — "Quarantined" flag; links involving it require explicit permission.
- Graph traversal cost at very high concept counts (> 100K) — likely fine with an indexed link table; profile during Phase 2.
