# 35 — Autopilot Mode

> See `00-glossary.md` for term definitions.
> Phase: Autopilot is out of v0.1 scope per `42-phase-one-authority-contract.md` §4 (autopilot mode, autonomous profile activation). Phase 2+.

---

## 1. Concept

Friday agents operate on a spectrum from "every step requires human approval" to "fully autonomous". Autopilot is the highest level — the agent executes a task end-to-end without per-step approval, returning a summary at completion.

Autopilot is not granted by default. It is **earned per task type** based on measured success rate, and revoked when conditions deteriorate.

---

## 2. Why confidence-gating

Three risks of premature autopilot:

1. **Quiet failures** — mistakes the supervisor does not notice until consequences manifest.
2. **Compound errors** — the agent acts on a flawed inference, then acts again on the flawed result.
3. **Trust collapse** — one bad autopilot incident destroys months of credibility.

Confidence-gating ensures autopilot is enabled only for task types Friday has proven it handles reliably, with circuit breakers when reliability drops.

---

## 3. Task Type DocType

A taxonomy for repeated task patterns.

| Field | Type | Notes |
|---|---|---|
| `task_type_code` | Data (unique) | e.g. `support.create_ticket_standard` |
| `description` | Text | What this task type covers |
| `domain` | Link → Domain | |
| `agent_role_profile` | Link → Agent Role Profile | Which profile executes |
| `signature_pattern` | Long Text | Heuristic for matching tasks to this type |
| `success_definition` | Long Text | What constitutes success |
| `total_executions` | Int | Lifetime count |
| `successful_executions` | Int | |
| `success_rate_rolling_30d` | Float | Auto-computed |
| `current_mode` | Select | Shadow / Manual / Assisted / Autopilot |
| `autopilot_threshold` | Float | Default 0.95 |
| `autopilot_min_samples` | Int | Default 50 |
| `last_anomaly_at` | Datetime | |
| `circuit_breaker_active` | Check | |

---

## 4. Execution modes

| Mode | Behaviour |
|---|---|
| **Shadow** | Agent generates the plan but does not execute. Plan posted to War Room as a proposed action. Supervisor executes manually or approves Friday to execute. Used during onboarding and for new task types. |
| **Manual** | Agent waits for supervisor to assign and approve each task individually. Default for new task types after Shadow. |
| **Assisted** | Agent executes step by step, each step posted to War Room. Supervisor can interrupt at any step. |
| **Autopilot** | Agent executes the full task autonomously. Single summary in War Room at completion. No mid-task interruptions unless the agent self-escalates. |

---

## 5. Promotion to Autopilot

A task type promotes from Assisted → Autopilot when **all** of:

1. `total_executions` ≥ `autopilot_min_samples` (default 50).
2. `success_rate_rolling_30d` ≥ `autopilot_threshold` (default 0.95).
3. No anomalies in the last 14 days.
4. Supervisor explicitly approves the promotion (one-click via War Room "Promote to Autopilot").
5. Promotion logged immutably.

Promotion is not automatic on threshold crossing. Friday surfaces the candidate; the human decides.

---

## 6. Demotion from Autopilot

Demotes Autopilot → Assisted when any of:

1. Rolling 30d success rate falls below `autopilot_threshold - 0.05` (default below 0.90), OR
2. Three or more anomalies in 7 days, OR
3. A single high-severity incident (financial loss, user complaint, regulator-relevant), OR
4. Supervisor manually demotes via War Room.

Demotion is **automatic** for the first three conditions. Friday does not wait for permission to step down — fail-safe defaults.

Demotion notice is high-priority in War Room with the triggering data.

---

## 7. Circuit breaker

A circuit breaker pauses execution entirely.

**Triggers:**
- Two consecutive failures in Autopilot.
- Detected anomaly during execution (output validation fails).
- External dependency reports degraded state.

**When tripped:**
- All pending tasks of this type pause.
- Supervisor notified.
- Manual reset required to resume.
- Reset logged with reason.

---

## 8. Anomaly detection

Continuous validation during execution.

**Output validation** — after each skill call, validate the output against expected schema/range:
- Numeric outputs within expected bounds.
- Required fields present.
- Status fields show valid transitions.
- No NULL/empty where unexpected.

**Pre-submit validation** — before document submission to ERPNext:
- Tax calculations match expected formulas.
- Account postings balance.
- Dates within reasonable range.
- Quantities match upstream documents.

**Cross-reference validation:**
- Created document references resolve correctly.
- Sums match across linked documents.
- No orphaned references.

Failed validation → task pauses, supervisor notified, optional revert.

---

## 9. Per-task override

Even in Autopilot mode, individual tasks can be marked:

- `force_supervisor_review = True` — this specific task requires approval.
- `confidence_override` — agent self-reports lower confidence; drops to Assisted.

Used when:

- Task references unusually large amounts (above per-task threshold).
- Task involves a new entity (first-time contact, first-time partner).
- Task is in a sensitive time window (end-of-month close, audit period).

---

## 10. Friday Operations Policy

Autopilot configuration lives in `Friday Operations Policy`.

| Field | Type |
|---|---|
| `business` | Link → Company |
| `default_autopilot_threshold` | Float |
| `default_min_samples` | Int |
| `task_type_overrides` | Child table — per-task-type config |
| `autopilot_value_thresholds` | Child table — monetary thresholds per domain (e.g. "ops: autopilot only for amounts ≤ ₹50,000") |
| `autopilot_time_windows` | Child table — restrict autopilot to certain hours (e.g. "no autopilot 22:00–06:00 IST") |
| `autopilot_blackout_dates` | Child table — disable around key dates (e.g. "no autopilot during financial year close, March 25 – April 5") |

Supervisors tune this without code changes.

---

## 11. Onboarding trajectory

| Period | Mode mix |
|---|---|
| Week 1 | All task types in Shadow. Agents propose; humans execute |
| Week 2 | High-frequency, low-risk task types move to Assisted. Humans see every step |
| Month 2 | Task types with high success start showing as Autopilot candidates. Supervisor promotes one at a time |
| Month 3+ | Mature: 60–80% routine task types in Autopilot, 20–40% Assisted, 5–10% Manual/Shadow (genuinely complex or rare) |

---

## 12. Confidence reporting

Each execution reports a confidence score (0.0–1.0) at completion.

Composition:

- Skill call success vs. failure (high weight).
- Validation pass rate.
- Memory search hit rate (low hits → uncertain context).
- LLM self-reported confidence (lowest weight; calibration uncertain).
- Anomaly detection results.

Confidence appears in War Room summaries. Below-threshold confidence escalates regardless of mode.

---

## 13. Audit trail

Every Autopilot execution writes an immutable Execution Log row:

- Task ID, agent profile, execution timestamps.
- Skills invoked with inputs and outputs.
- Documents created/modified.
- Validation results.
- Confidence score.
- Final summary.

Retained for the legal-minimum period (typically 7–10 years for financial actions). Supervisors can replay any execution to understand exactly what happened.

---

## 14. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §4. Task Type DocType, Shadow / Manual / Assisted modes, success tracking, anomaly detection, audit log may ship as scaffolding |
| 2 | Autopilot mode; promotion workflow with supervisor approval; automatic demotion + circuit breaker; Friday Operations Policy with value thresholds, time windows, blackouts; confidence reporting in War Room |
| 3 | Cross-business benchmarking ("similar businesses promote these task types to autopilot"); ML-based anomaly detection beyond rule-based validation; per-task confidence calibration based on historical accuracy; auto-promotion suggestions with risk scoring |

---

## 15. Open questions

- Confidence calibration — how to validate an agent's self-reported 0.95 against actual accuracy. Calibration model compares predicted vs. actual outcomes in Phase 3.
- Autopilot during agent version transitions — when an agent's underlying model upgrades, success metrics reset. Trust must be re-earned after model changes.
- Multi-step task autopilot — if step 3 of 7 fails, revert steps 1–2? Defined per task type via a `rollback_strategy` field in the Task Type DocType (Phase 2).
