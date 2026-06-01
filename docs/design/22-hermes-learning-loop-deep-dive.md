# 22 — Hermes Learning Loop Deep Dive

> See `00-glossary.md` for term definitions.
> Friday Skill, Skill Draft, and Skill Version schemas live in `05-module-design.md`. This document specifies the autonomous-curator and skill-evolution subsystem on top of those DocTypes.
> Phase: Out of v0.1 scope per `42-phase-one-authority-contract.md` §4 (autonomous skill activation / learning loop). Phase 2+.

---

## 1. The Hermes mechanism

Synthesised from public Hermes documentation and the OpenClaw pattern in `15-openclaw-insights-friday-refinements.md`:

1. **Trigger.** Every N tool calls (default ~15), or end of session, or on heartbeat.
2. **Analysis.** Agent reads its own recent conversation transcript and execution log.
3. **Pattern extraction.** Identifies which skills were invoked, which succeeded, which failed, and common failure modes.
4. **Performance index.** Success rate per skill, rolling.
5. **Improvement draft.** For skills below threshold (e.g. < 80% success), the agent drafts an improvement — clearer instructions, refined `when_to_use`, corrected parameter examples.
6. **Self-rated confidence.** Agent assigns a 0..1 score.
7. **Persist.** Above the confidence threshold (default 0.75), the agent writes the patch directly via a `skill_manage` tool.
8. **Async.** Runs in the background; main conversation is not blocked.

**Strength:** skills evolve continuously without explicit curation.

**Weakness for enterprise use:** an agent silently editing its own behaviour rules is exactly the failure mode auditors flag. Friday keeps the mechanism and replaces the governance.

---

## 2. Friday's governed loop

Same core, five additions.

### Addition 1 — DocType-backed versioning

Skills are DocTypes. Every improvement creates a new Skill Version row, not an in-place edit. Old versions remain queryable. The active version is a pointer on Skill.

### Addition 2 — Mandatory supervisor approval for production

The agent never auto-promotes. Flow:

```
Agent generates improvement → Skill Draft (status=Pending Review)
  → Supervisor sees in War Room: "Support Agent suggests an update to skill X"
    → Supervisor reviews the diff with confidence + reasoning
      → Approve: Skill Draft → new Skill Version → Active
      → Reject: Skill Draft marked Rejected with reason; agent learns the reasoning
```

### Addition 3 — Cross-agent learning via Redis pub/sub

On promotion, the gateway publishes `skill.promoted`. All agents using that skill flush their local cache and pick up the new version on next invocation. Improvements propagate to a fleet immediately.

### Addition 4 — Confidence and provenance

Every improvement carries:

- Confidence (agent self-rating).
- Evidence count (how many executions informed it).
- Provenance trace (which Execution Log rows fed the analysis).

Supervisors see all of this before approving.

### Addition 5 — Rollback as first-class

Every skill change is rollback-safe. On regression:

- Supervisor clicks "Rollback" on the Skill DocType.
- Active pointer reverts to the prior version.
- Affected Execution Logs flagged for review.
- The rolled-back version is marked `Reverted` with reason.

---

## 3. DocTypes involved

### Skill — fields added beyond `05-module-design.md`

| Field | Type |
|---|---|
| `active_version` | Link → Skill Version |
| `version_count` | Int (read-only) |
| `success_rate` | Float (rolling, last N executions) |
| `last_improvement_at` | Datetime |

### Skill Version

| Field | Type |
|---|---|
| `parent_skill` | Link → Skill |
| `version_number` | Int (auto-increment per skill) |
| `description`, `when_to_use`, `instructions` | Text / Long Text |
| `parameters_schema` | JSON |
| `created_by_agent` | Link → Agent Profile (null for human-authored) |
| `confidence` | Float |
| `evidence_count` | Int |
| `provenance` | Table → Execution Log |
| `status` | Select (Active / Superseded / Reverted) |
| `promoted_at` | Datetime |
| `promoted_by` | Link → User |
| Submittable | Yes |

### Skill Draft

| Field | Type |
|---|---|
| `target_skill` | Link → Skill |
| `proposed_by_agent` | Link → Agent Profile |
| `proposed_version` | Section with the same fields as Skill Version |
| `diff_summary` | Long Text — what changed and why |
| `confidence` | Float |
| `evidence_count` | Int |
| `provenance` | Table → Execution Log |
| `status` | Select (Pending Review / Approved / Rejected) |
| `reviewed_by` | Link → User |
| `review_reason` | Text |
| `reviewed_at` | Datetime |
| Submittable | Yes |

---

## 4. The learner job

A background RQ job, `friday.skills.learner.tick`, scheduled hourly (configurable).

```python
def tick():
    candidates = frappe.db.sql("""
        SELECT s.name
        FROM `tabSkill` s
        WHERE s.status = 'Active'
          AND s.success_rate < 0.80
          AND (SELECT COUNT(*) FROM `tabExecution Log` el
               WHERE el.skill = s.name AND el.creation > NOW() - INTERVAL 24 HOUR
              ) >= 10
    """)
    for skill in candidates:
        agent = pick_qualified_proposer(skill)
        frappe.enqueue(
            'friday.skills.learner.analyse_and_propose',
            agent_profile=agent.name,
            skill_name=skill.name,
        )
```

```python
def analyse_and_propose(agent_profile, skill_name):
    skill = frappe.get_doc('Skill', skill_name)
    logs = recent_execution_logs(skill_name, limit=50)

    # Agent runs in its own sandbox with a focused prompt:
    # "You are improving skill 'send_notification'. Current version + recent
    #  Execution Logs (successes and failures). Propose a revised version
    #  addressing the failure patterns. Output: diff_summary,
    #  proposed_version JSON, confidence."
    result = run_agent_for_skill_improvement(
        agent_profile=agent_profile,
        skill=skill,
        evidence=logs,
        token_budget=20000,
    )

    if result.confidence >= 0.5:  # generous draft threshold
        frappe.get_doc({
            'doctype': 'Skill Draft',
            'target_skill': skill_name,
            'proposed_by_agent': agent_profile,
            'proposed_version': result.version_fields,
            'diff_summary': result.diff_summary,
            'confidence': result.confidence,
            'evidence_count': len(logs),
            'provenance': [{'execution_log': log.name} for log in logs],
            'status': 'Pending Review',
        }).insert().submit()

        post_to_warroom(
            project=skill.governing_project,
            message=f"💡 Agent @{agent_profile} proposes an improvement to "
                    f"skill `{skill_name}` (confidence {result.confidence:.2f}). "
                    f"[Review →]"
        )
    else:
        log_low_confidence(agent_profile, skill_name, result)
```

---

## 5. Approval UX in War Room

```
💡 Support Agent proposes update to skill `send_followup_email`
   Confidence: 0.87 (high)
   Evidence: 23 recent executions
   Summary: "Current skill produces overly formal emails for follow-ups.
            Proposed: detect message tone from prior thread; mirror tone."

   [View Diff in Console]  [Approve]  [Reject with reason]
```

`Approve` triggers:

1. Skill Draft → Approved.
2. New Skill Version row created with the proposed content.
3. Skill's `active_version` updated to the new version.
4. Previous version → Superseded.
5. Redis pub/sub `skill.promoted` fires.
6. Agents flush local Skill cache.
7. War Room reaction 🧠 added to the draft message.

`Reject` requires a reason, fed back to the learner for calibration.

---

## 6. Confidence calibration

Tracked over time:

- Predicted confidence at draft time.
- Actual outcome (Approved / Rejected; post-deployment success rate of the new version).

Calibration data feeds a per-agent confidence-adjustment model. Agents whose self-reported confidence overestimates reality have their drafts displayed with calibration-adjusted scores in War Room.

Phase 3 enhancement. Phase 2 uses raw confidence with supervisor judgment as the only filter.

---

## 7. Rollback mechanics

Every Skill carries:

- `active_version`.
- `previous_active_version` (auto-tracked on each promotion).

Rollback:

1. Supervisor clicks "Rollback Active Version".
2. `active_version = previous_active_version`.
3. The current active version's status → `Reverted`.
4. Reason captured.
5. Redis pub/sub `skill.rolled_back` fires.
6. Affected agents flush cache.
7. War Room notified.

Rollback is always safe because every version was previously validated. Rollbacks chain — a rollback can itself be rolled back.

---

## 8. Cross-agent sharing

When a Skill is promoted, all agents using it benefit immediately. Some learnings are scope-bounded (e.g. a React Developer learns something a generic Full Stack agent shouldn't inherit).

- Skills can be scoped by Agent Role Profile (default: scoped to the proposer's profile).
- Promotion within scope is automatic; cross-scope promotion requires explicit supervisor approval.
- Supervisor sees "Promote to all Engineering Agent profiles" as a separate action when reviewing a draft.

Balances local learning vs. fleet-wide propagation.

---

## 9. Audit trail

Every step is queryable:

- Skill Draft rows — every proposal ever made.
- Skill Version rows — every version ever active.
- Execution Log rows — every execution, linked to the Skill Version it ran against.
- Permission Decision Log — every promotion approver.

For compliance: "Why did the agent act this way at time T?" resolves through a deterministic chain to specific Skill Versions.

---

## 10. Anti-patterns and their prevention

| Pattern | Prevention |
|---|---|
| Agent silently mutates its own Skill | All changes go through Skill Draft + supervisor approval; agents never write to the active Skill |
| Improvement removes safety checks | Diff review surfaces removed constraints; high-risk skills require multi-supervisor approval |
| Skill drift across versions | Version history immutable; every version persisted |
| Forgotten rollback context | Rollback reason mandatory and visible |
| Confidence inflation | Calibration data tracked; mis-calibrated agents flagged over time |
| Same draft proposed repeatedly | Dedup — if an identical diff was rejected within N days, suppress and inform the agent |

---

## 11. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | **Out of scope.** Skills are human-authored. No learner job. |
| 2 | Skill Draft DocType + manual flow; supervisor authors drafts; learner job exists but inactive |
| 3 | Active learner; agents propose drafts based on Execution Log analysis |
| 4 | Cross-agent sharing, calibration models, automated rollback heuristics |

Phase 1's proof point uses fixed skills curated by humans. Learning is Phase 2+ once the agent runtime is proven safe.

---

## 12. Dependencies

- Skill, Skill Version, Skill Draft DocTypes (`05-module-design.md`).
- Execution Log DocType (`05-module-design.md`).
- Agent Profile + Agent Role Profile (`05`, `12`).
- Frappe RQ for background jobs.
- Redis pub/sub for cache invalidation.
- Raven for War Room notifications (`16-raven-integration-strategy.md`).

---

## 13. Open engineering questions

- How to expose Skill Version to the LLM. The agent should know what version it's running against, but version-switching mid-conversation could confuse it. Likely answer: pin to active version at session start, refresh only on explicit boundary.
- Diff representation in War Room. Raw text diff is hard to skim for non-technical supervisors. Consider a structured summary ("Changed: `when_to_use`; Added: 1 parameter; Removed: 0 lines").
- Throttle. A flood of drafts on the same Skill within a short window should be coalesced.
- Evidence window. Too narrow misses patterns; too wide produces stale drafts. Default 24 hours, configurable.
