# 21 — Auto-Research Integration Strategy

> See `00-glossary.md` for term definitions.
> Phase: Auto-research is out of v0.1 scope per `42-phase-one-authority-contract.md`. Phase 2 capability.

---

## 1. Definition

An autonomous research agent:

1. Takes an open-ended question or topic.
2. Decomposes it into sub-questions.
3. Gathers information from multiple sources (web search, internal documents, knowledge base).
4. Synthesises findings into structured analysis.
5. Produces a citable report.
6. Iterates on follow-up requests.

Distinct from a chat session that searches. The research agent runs autonomously over minutes to hours, persists intermediate state, and produces a substantive deliverable.

---

## 2. Friday use cases

| Domain | Application |
|---|---|
| DevOps | New dependency — maintenance status, security advisories, alternatives |
| Sales | Pre-meeting research on a prospect — company profile, recent news, decision-makers |
| HR | Compensation benchmarking — market rates, comparable roles |
| Legal | Regulatory landscape before a new business activity |
| Engineering | Library/framework evaluation — compare options, read changelogs, summarise tradeoffs |
| Strategy | Competitive analysis |
| Compliance | Regulatory change tracking — monitor sources, flag changes, summarise impact |

Each is a real workflow currently taking humans 2–8 hours. Auto-research compresses it to minutes.

---

## 3. Architecture

### 3.1 Research Project DocType

A research engagement is a first-class object.

| Field | Type | Notes |
|---|---|---|
| `topic` | Long Text | The research question or brief |
| `requested_by` | Link → User | Originator |
| `assigned_to_profile` | Link → Agent Profile | Research-capable profile |
| `status` | Select | Pending / Decomposing / Researching / Synthesising / Review / Completed |
| `depth` | Select | Shallow (15 min) / Medium (1 hour) / Deep (4+ hours) |
| `max_token_budget` | Int | Cap on total LLM tokens |
| `sources_allowed` | Table | Web / Internal Wiki / ERPNext / Past Research |
| `sub_questions` | Table | Decomposed questions |
| `findings` | Table | Each finding with source citation |
| `final_report` | Link → File (markdown) | Output |
| `parent_task` | Link → Agent Task | If kicked off from a task |
| Submittable | Yes | |

### 3.2 Research Sub-Question DocType

| Field | Type |
|---|---|
| `parent_project` | Link → Research Project |
| `question` | Text |
| `status` | Select (Pending / Researching / Answered / Inconclusive) |
| `answer` | Long Text |
| `confidence` | Select (Low / Medium / High) |
| `sources` | Table → Research Source |

### 3.3 Research Source DocType

Citations for traceability.

| Field | Type |
|---|---|
| `url` | URL (nullable) |
| `internal_doctype` | Link (nullable) |
| `internal_name` | Data (nullable) |
| `excerpt` | Long Text |
| `accessed_at` | Datetime |
| `reliability_score` | Float (0..1, learned over time) |

### 3.4 Research-agent skills

| Skill | Purpose |
|---|---|
| `research_decompose(topic)` | Generates sub-questions |
| `web_search(query)` | Searches the web; returns ranked results |
| `web_fetch(url)` | Fetches and parses a page |
| `wiki_query(topic)` | Queries Frappe Wiki / knowledge graph (see `33-knowledge-graph-wiki-integration.md`) |
| `memory_search(query)` | Searches past Research Projects and findings |
| `research_synthesise(sub_questions)` | Combines answers into structured findings |
| `research_report(findings, format)` | Renders final markdown / PDF deliverable |
| `research_cite(claim, source)` | Adds citation; every claim must carry at least one source |

---

## 4. Research loop

```
1. Operator creates Research Project with topic and depth.
2. Research Agent picks up the project → status = Decomposing.
3. Calls research_decompose → 5–15 sub-questions.
4. For each sub-question (parallel, capped at concurrency limit):
   a. Determine best source(s) to consult.
   b. Use web_search / web_fetch / wiki_query / memory_search.
   c. Synthesise an answer with citations.
   d. Mark Answered or Inconclusive.
   e. Persist to Research Sub-Question DocType.
5. Status → Synthesising.
6. Calls research_synthesise → coherent narrative across answers.
7. Calls research_report → renders final markdown.
8. Status → Review.
9. Requested_by sees the report in War Room with quick actions:
   [Accept]  [Ask Follow-up]  [Re-do with focus on X]
10. Final status → Completed.
```

**Token budget:** at each step the agent compares cumulative tokens against `max_token_budget`. At 80% used, it switches to "wrap-up mode" and produces a best-effort report even with unresolved sub-questions.

---

## 5. Quality controls

Auto-research is high-leverage but produces confident garbage if unchecked.

| Risk | Mitigation |
|---|---|
| Hallucinated facts | Every claim in the final report cites a Research Source row; `research_cite` enforces this |
| Stale information | Web sources tagged with access timestamp; report flags claims based on sources older than N days |
| Source quality | Reliability score tracked per domain; low-reliability sources flagged in citations |
| Confirmation bias | Decompose step generates counter-questions ("what would falsify this?") |
| Token waste | Token budget hard-capped; over-budget research auto-stops and produces partial report |
| Prompt injection from web content | `web_fetch` output is sanitised; web text is data, never instructions |

---

## 6. Memory integration

Every completed Research Project persists into long-term memory:

- The final report becomes a Memory Entry with `kind='research_report'`.
- Findings indexed for `memory_search` retrieval.
- Future research on related topics surfaces prior work as input.
- Reliability scores update based on whether downstream actions succeeded.

Over time, Friday accumulates institutional research knowledge.

---

## 7. War Room integration

Research Projects post live updates:

- 🔍 Project started.
- 📋 Sub-questions decomposed (N total).
- ✓ Sub-questions answered (5 of 12).
- 📊 Synthesising findings.
- 📄 Report ready — view in DM or in the Framework Console.

Reviewer comments in War Room become input for follow-up research projects.

---

## 8. Permission model

Auto-research agents have powerful capabilities (web fetch, document read). Constraints:

- Web fetch limited to an allowlist by default; allowlist configurable per Research Project.
- `wiki_query` respects Wiki page permissions.
- `memory_search` returns only memories the agent's role can see.
- Research reports inherit permissions from the most restrictive source consulted (high-water mark).
- A Research Project marked `confidential` produces a report visible only to requesting role + supervisor.

---

## 9. Source tiers

| Tier | Examples | Required role |
|---|---|---|
| Public web | News, blogs, docs | Default for research agents |
| Internal Wiki | Frappe Wiki pages | Wiki Reader |
| Business records | Contact, Project, Document records | Standard data role |
| Past research | Memory Entries | Memory Reader |
| External APIs | Crunchbase, LinkedIn (if integrated) | Specific API role |

A research agent consults only the tiers its role permits.

---

## 10. Cost tracking

Every Research Project tracks LLM tokens (split by sub-question), external API calls (web search, fetch), elapsed time, and estimated cost in INR (or configured currency). Feeds the cost-tracking system in Phase 2.

---

## 11. Phasing

| Phase | Capability |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §4 |
| 2 | Basic loop: decompose → web_search → synthesise → report; web sources only |
| 3 | Internal sources (Wiki, ERPNext, memory); follow-up iterations |
| 4 | Adaptive depth, learned reliability scores, cost optimisation |

---

## 12. Dependencies

- `web_search` and `web_fetch` skills (Phase 2).
- Frappe Wiki integration (`33-knowledge-graph-wiki-integration.md`).
- Memory module with pgvector (Phase 2 per `14-integrated-architecture.md` §11).
- Research-capable Agent Role Profile extending `12-refinement-agent-roles-and-features.md`.
- LLM provider with ≥ 128K context and structured-output support.

---

## 13. Attribution

The auto-research pattern is widely explored in the open-source community. Friday's implementation is its own; the common pattern (decompose → search → synthesise → cite) is reimplemented on Frappe primitives.
