# 13 — Frappe v16 Leverage Strategy

> See `00-glossary.md` for term definitions.
> See `39-friday-framework-strategy.md` and `45-fork-policy.md` — Friday is a hard fork of Frappe v16 stable. v15 is not a target; v16 is the baseline.
>
> This document maps v16's capabilities to specific Friday design choices so the framework takes maximum advantage of what v16 already provides.

---

## 1. v16 capabilities used by Friday

| Area | v16 capability | Friday use |
|---|---|---|
| Performance | Caffeine cache, leaner request lifecycle, ~30% server-load reduction | Lower dispatcher latency, faster permission checks, more agents per host |
| Workspace | Redesigned workspace with embeddable views and persistent sidebar | Framework Console + War Room layouts |
| Workflow | State transition **actions** that fire automatically | Skill triggers on Agent Task state changes with no custom hooks |
| Permissions | Faster matrix resolution; field-level masking | Hot-path permission check; PII/credential redaction in audit |
| UI | Scrollable child tables with sticky columns; unlimited list columns | Kanban + Execution Log UX |
| Background jobs | RQ retry observability; per-job tracing IDs | Agent execution observability |
| Naming | UUID-based DocType naming | Globally unique agent IDs across sites |
| API | REST improvements; type-safer signatures | Cleaner agent ↔ Frappe REST contract |
| Real-time | Improved Socket.io handling, lower overhead | Faster War Room and Kanban updates |
| Dev tools | Automated linting, simplified app deps | Smoother Friday CI/CD |
| Evaluations | Eval expressions for dynamic fields, date/time expressions | Smarter Skill parameter validation |

---

## 2. Performance budget on v16

Friday's hot paths and where v16 helps:

| Hot path | v16 win |
|---|---|
| Permission check on every skill invocation | Faster matrix resolution → tighter latency budget |
| Skill loader cache warm-up | Lower DB round-trip cost |
| Dispatcher tick (scan dispatchable tasks) | Caffeine cache + leaner SQL |
| Real-time event publishing (War Room, Kanban) | Lower Socket.io overhead |
| Concurrent agent runs per site | ~30% less server load → ~30% more concurrent agents per host |

**Target on v16:** gateway sustains ~1000 skill executions per minute on a single 8-core / 16 GB host.

Performance specifics live in `38-performance-optimization-bottleneck-analysis.md`; this table is the v16-attributable contribution.

---

## 3. Workflow state transition actions

Side effects on Agent Task state changes are declared in the Workflow definition, not in scattered `on_update` hooks:

```yaml
# v16 workflow action declaration (conceptual)
workflow: Agent Task
states:
  - name: Pending
    transitions:
      - to: Assigned
        actions:
          - call: friday.dispatcher.notify_assigned_agent
  - name: Assigned
    transitions:
      - to: Executing
        actions:
          - call: friday.gateway.spawn_runner
      - to: Blocked
        actions:
          - call: friday.escalation.start
  - name: Blocked
    transitions:
      - to: Review
        actions:
          - call: friday.workroom.post_blocker_to_warroom
```

The workflow is the source of truth for what fires when. Auditable, editable without redeploy.

---

## 4. Field-level permission masking

Per-field masking by role eliminates a class of accidental disclosure: an operator reading an Execution Log row no longer sees raw secrets even if they hold read access.

| DocType | Field | Masked from |
|---|---|---|
| Agent Profile | API token, LLM provider key | Any role except `Friday Admin` |
| Execution Log | `parameters.password`, `parameters.secret_*` | Always masked unless explicitly unmasked |
| Chat Message | Content matching credit-card / SSN regex | Roles without `PII Reader` |
| Workflow Request | Justification containing secrets | Re-masked after read |

---

## 5. UUID naming for agent kernel DocTypes

Friday uses UUID naming on:

- Agent Profile
- Agent Task
- Execution Log
- Permission Decision Log

Rationale: multi-site agent-to-agent communication (`37-multi-site-inter-agent-communication.md`) needs globally unique identifiers; cross-site delegation references avoid collisions without prefixing; audit logs exported from multiple sites concatenate cleanly.

---

## 6. Real-time for War Room and Kanban

v16's Socket.io path gives:

- Per-event latency target < 50ms (skill completion → War Room message visible).
- More concurrent subscribers per site without server saturation.
- Better reconnection semantics for flaky clients.

The Kanban view inherits the same improvements; Task state changes propagate in near-real-time.

---

## 7. Background-job observability

v16's RQ surfaces job-level retry observability, queue-depth and processing-rate metrics, and per-job tracing IDs.

Friday's use:

- Surfaces RQ metrics in the Framework Console for execution monitoring.
- Uses tracing IDs to correlate gateway request → RQ job → sandbox container → result.
- Alerts when queue depth or retry rate exceeds thresholds.

---

## 8. Workspace as War Room shell

The v16 workspace with embeddable views composes the War Room as a single page:

```
[ War Room for Project X ]
┌─────────────────────────────────────────────────────────┐
│ Pinned project brief (Raven message)                    │
├──────────────────────┬──────────────────────────────────┤
│ Kanban view          │ Active Raven channel             │
│ (Agent Task by state)│ (embedded chat)                  │
├──────────────────────┴──────────────────────────────────┤
│ Agent status panel (Vue component)                      │
├─────────────────────────────────────────────────────────┤
│ Recent Execution Logs (filterable list view)            │
└─────────────────────────────────────────────────────────┘
```

No custom shell. The workspace primitive handles layout, persistence, and per-user customisation.

---

## 9. Eval expressions for dynamic Skill parameters

v16 allows eval expressions on DocType fields for visibility, defaults, and validation. Friday Skills use this for runtime-dependent parameter schemas:

```
# Skill: send_notification
parameters_schema = {
  "note_id":     {"type": "Link", "options": "Note"},
  "include_pdf": {"type": "Check",
                  "default": "eval: frappe.db.get_single_value('Friday Settings', 'attach_pdf_default')"},
  "send_to":     {"type": "Data", "depends_on": "eval: doc.note_id != null"}
}
```

The LLM-facing schema stays minimal; runtime resolution handles the rest.

---

## 10. What v16 does not solve

v16 is an excellent foundation. It is not a substitute for Friday's agent kernel.

- v16 does not introduce native vector search → pgvector remains.
- v16 does not change the agent-loop architecture → the Hermes-derived runtime stays custom.
- v16 does not provide LLM provider abstractions → Friday owns this layer (`03-technical-stack.md`).
- v16 does not eliminate Docker sandboxing → `04-security-model.md` stands.
- v16 does not solve multi-site coordination → `37-multi-site-inter-agent-communication.md` stands.

---

## 11. v16 absorption policy

Friday is the fork. v16 upstream releases (security patches, bug fixes, capability improvements) are absorbed manually per `45-fork-policy.md` §5. The headline capabilities above are baseline; future v16 minor releases are evaluated for selective absorption when they reach Friday's main branch.
