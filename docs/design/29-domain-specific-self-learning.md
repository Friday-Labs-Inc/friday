# 29 — Domain-Specific Self-Learning

> See `00-glossary.md` for term definitions (Domain is glossary-defined).
> Companion: `22-hermes-learning-loop-deep-dive.md` (learning loop), `32-memory-association-neural-linking.md` and `34-efficient-multilayer-memory-system.md` (memory model), `35-autopilot-mode-autonomous-execution.md` (confidence thresholds).
> Phase: v0.1 ships Domain as a string tag; the Domain DocType and the scoped learning loop are Phase 2+.

---

## 1. Why scope learning per domain

If every agent learns from every other agent's execution, knowledge contaminates across domains. A pattern that works for "send email follow-up" should not bleed into "approve records". A skill that fits a React frontend project should not surface for a Kubernetes infrastructure task.

The learning loop runs **per domain** so each domain becomes its own specialist over time.

---

## 2. Standard domains

Initial set:

- `customer-support`
- `field-ops`
- `erpnext-finance`
- `erpnext-hr`
- `erpnext-production`
- `erpnext-inventory`
- `frontend-react`
- `infra-kubernetes`
- `infra-terraform`
- `db-postgres`
- `general`

Custom domains created by supervisors with appropriate permissions.

---

## 3. Domain DocType (Phase 2)

| Field | Type |
|---|---|
| `domain_name` | Data (unique) |
| `description` | Text |
| `parent_domain` | Link → Domain — supports hierarchy (e.g. `infra-kubernetes` is a child of `infra`) |
| `enabled` | Check |
| `governance_supervisor` | Link → User — approves Skill Drafts in this domain |
| `learning_loop_active` | Check (Phase 1: all off) |
| `success_threshold_for_autopilot` | Float, default 0.95 (see `35-autopilot-mode-autonomous-execution.md`) |
| `min_samples_for_promotion` | Int, default 20 |

---

## 4. Scoped learning loop

When an Execution Log completes successfully, the curator (`22-hermes-learning-loop-deep-dive.md`) considers it for promotion:

1. Identify the execution's domain from the Agent Role Profile.
2. Cluster similar executions within that domain using embeddings of (task description + skill called + outcome).
3. If a cluster has ≥ `min_samples_for_promotion` executions with ≥ 90% success, propose a Skill Draft scoped to that domain.
4. The draft is visible only to that domain's supervisors.
5. Approval required from the domain's `governance_supervisor`.

A pattern proven in `customer-support` does not auto-propagate to `field-ops`, even if logic looks similar. Sharing requires explicit promotion (§7).

---

## 5. Memory scoping

Memory Entries (`32-memory-association-neural-linking.md`, `34-efficient-multilayer-memory-system.md`) carry a `domain` field. The `memory_search` skill defaults to filtering by the calling agent's domain. Cross-domain queries require an explicit `include_domains` parameter and may require approval based on memory sensitivity.

This blocks accidental leakage: a `customer-support` agent does not surface its private notes to an `infra-kubernetes` agent.

---

## 6. Skill resolution within domain

When the dispatcher resolves skills for a task:

1. Filter Skills tagged with the project's domain.
2. Include Skills tagged `general` (cross-domain utilities — `memory_search`, `time_query`).
3. Only if (1) and (2) return nothing, consider Skills from sibling domains under the same parent.

Tight, focused skill sets per execution — consistent with the OpenClaw skill-ceiling guidance in `15-openclaw-insights-friday-refinements.md`.

---

## 7. Cross-domain promotion

Some patterns belong everywhere (e.g. `validate ISO date format` discovered in `customer-support` is genuinely general).

Promotion flow:

1. Domain supervisor flags a Skill Version with "Propose for cross-domain promotion".
2. A meta-supervisor (default: Friday admin) reviews.
3. Promotion creates a new Skill row tagged `general` with a copy of the implementation.
4. The original domain-scoped Skill remains; it may be marked Superseded by the general version after a stability window.
5. Audit trail records the promotion source.

Promotion is never automatic. The friction is intentional and prevents contamination.

---

## 8. Domain metrics

Tracked per Domain:

- `total_executions`.
- `success_rate` (rolling 30 days).
- `avg_task_duration` (rolling 30 days).
- `unique_skill_count`.
- `skill_promotion_rate` — drafts approved / drafts created.
- `human_intervention_rate` — escalations per 100 executions.

Metrics show whether a domain is maturing (intervention rate falling, success rate rising) or regressing. Supervisors review weekly in a Raven `#domain-health` channel.

---

## 9. Domain-scoped auto-research

When an agent encounters an unknown pattern, it may trigger auto-research (`21-auto-research-integration-strategy.md`). Research results store as Memory Entries scoped to the domain — a K8s networking note does not pollute the support agent's memory.

---

## 10. Domain naming discipline

1. Domain names use kebab-case with at most two segments.
2. No more than 20 active domains in early phases — avoid fragmentation.
3. A domain must have at least one Agent Role Profile and one Skill before being created.
4. Adding a new domain requires admin approval via War Room.

Prevents domain proliferation that would defeat specialisation.

---

## 11. Multi-domain projects

Some Agent Projects span domains (e.g. "Build an internal ops dashboard" needs `frontend-react` + `erpnext-finance`). The project's `domains` field is a child table.

When an Agent Task is created in such a project, the supervisor (or System Manager Agent) assigns the task a primary domain. Skill resolution and memory access scope to that primary domain. Cross-domain skills require the task to split into sub-tasks, each with its own primary domain.

Forces clarity at task boundaries.

---

## 12. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Domain as a string tag on Skills, Agent Role Profiles, Memory Entries, and Agent Projects. No Domain DocType. No learning loop. Manual skill authoring. |
| 2 | Domain DocType; tag enforcement; memory and skill resolution filtered by domain |
| 3 | Curator scoped per domain; Skill Draft + Skill Version per domain; domain metrics dashboard; cross-domain promotion workflow |
| 4 | Nested sub-domains (e.g. `customer-support-import` vs `customer-support-local`); domain-specific evaluation harnesses; domain-level performance budgets |

---

## 13. Open questions

- `governance_supervisor`: a role (auto-backup) or a single user (clear accountability)? Likely role with primary + backup field.
- Migrating Skills between domains when boundaries shift — migration tool with audit trail in Phase 3.
- Cross-tenant domain sharing in Friday Labs (see `18-go-to-market-strategy.md`) — each tenant has private domains by default; opt-in to a shared community domain library.
