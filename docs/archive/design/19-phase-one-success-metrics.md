# 19 — Phase One Success Metrics

> See `00-glossary.md` for term definitions.
> Authority: `42-phase-one-authority-contract.md`. This document's tier-1 metrics restate 42's completion gate in measurable form. Where they conflict, 42 wins.
> Companion: `11-agent-validation-checklist.md` (slice-by-slice gate).

---

## 1. North-star metric

> Friday proves the governed framework loop end-to-end: profile, skill, permission check, sandboxed execution, immutable logs, configurable task workflow, Framework Console visibility.

If this single statement is green, v0.1 succeeded. If it is not, no amount of feature breadth compensates.

The first business-automation dogfood follows the governed loop becoming green. It is sequenced behind the framework proof, not removed (per 42 §6).

---

## 2. Tier 1 — must-hit (Phase 1 fails without these)

### M1.1 — End-to-end governed framework loop

- [ ] User creates or submits work into Friday.
- [ ] Friday resolves the correct Agent Profile.
- [ ] Active Skills are loaded from governed DocTypes.
- [ ] Skill invocation is permission-checked before execution.
- [ ] Denied calls are rejected and logged.
- [ ] Permitted calls execute through the sandboxed path.
- [ ] Execution Log and Permission Decision Log rows are written.
- [ ] Agent Task moves through a configurable workflow.
- [ ] Framework Console shows the task, agent, execution, and audit trail.

### M1.2 — Zero unsafe actions

- [ ] No permission boundary violations across the dogfood week.
- [ ] No skill executed without a prior permission decision logged.
- [ ] No agent action taken outside its Agent Role Profile's scope.
- [ ] No credential leaked into logs or War Room messages.

### M1.3 — Full audit trail

- [ ] Every skill invocation has a submitted Execution Log row.
- [ ] Every permission decision has a submitted Permission Decision Log row.
- [ ] Every approval has a Workflow Request row with decision and reason.
- [ ] An external auditor can trace any agent action to: who, what, why, when, with what credentials.

### M1.4 — Validation checklist green

Every checkbox in `11-agent-validation-checklist.md` slices 1–9 is ticked and human-acknowledged. No exceptions; no "we'll fix this in Phase 2".

---

## 3. Tier 2 — should-hit (architectural soundness signals)

### M2.1 — Latency

- [ ] Permission check median: < 5ms with warm cache.
- [ ] Skill loader cold-cache load: < 100ms for an agent with 50 permitted skills.
- [ ] Gateway dispatch from inbound message to LLM call: < 200ms.
- [ ] End-to-end skill execution (CLI → sandbox → reply, excluding LLM time): median < 3s, p95 < 10s.

### M2.2 — Throughput

- [ ] Dispatcher handles 500 Tasks/minute on a single worker without backpressure.
- [ ] Permission engine handles 1000 checks/second with warm cache.
- [ ] System sustains 10 concurrent agents on a single 8-core / 16GB host.

### M2.3 — Reliability

- [ ] No silent failures across the dogfood week. Every error is in logs and a Frappe error log.
- [ ] Skill execution success rate ≥ 95% for Active Skills (excluding LLM-attributable failures).
- [ ] Docker container clean-shutdown rate ≥ 99%. No orphaned containers polluting the host.
- [ ] Dispatcher concurrency: 0 double-claims across 10,000 simulated task claims.

### M2.4 — Test coverage

- [ ] Overall coverage ≥ 70%.
- [ ] Critical modules (`permissions`, `gateway`, `sandbox`, `tasks/dispatcher`) ≥ 85%.
- [ ] No skipped or xfailed tests without a tracked issue.

---

## 4. Tier 3 — nice-to-hit (operability)

### M3.1 — Developer experience

- [ ] Time-to-first-running-agent for a new developer (cold install): < 30 minutes.
- [ ] `bench migrate` from empty to current state: < 60 seconds.
- [ ] CI green-build wall-clock: < 10 minutes.

### M3.2 — Documentation

- [ ] README install steps work verbatim on a fresh Ubuntu 22.04 VM.
- [ ] Quickstart walks a developer from clone → first running agent in < 30 minutes.
- [ ] Every public function in `permissions/` and `gateway/` has a docstring.
- [ ] Architecture diagram is current with the code — not aspirational.

### M3.3 — Operability

- [ ] Health-check endpoint returns green when all subsystems are nominal.
- [ ] Frappe error log has zero unhandled exceptions after the dogfood week.
- [ ] Disk usage growth: < 1 MB/day per active agent in steady state (excluding skill outputs).
- [ ] Restart safety: the gateway can be killed and restarted mid-execution without data loss.

### M3.4 — Security posture

- [ ] No hard-coded credentials anywhere (verified by `git secrets` or `trufflehog`).
- [ ] All sensitive Friday DocType fields use Frappe `Password` type.
- [ ] Docker images built from pinned base, scanned with `trivy`, no critical CVEs.
- [ ] Dependency audit (`pip-audit`, `npm audit`) clean.

---

## 5. Anti-metrics — explicitly not measured in Phase 1

- GitHub stars, Twitter followers, blog traffic.
- LLM tokens consumed, cost per execution.
- Number of skills in the library (quality > quantity at this stage).
- Number of agents instantiated (one well-behaved agent > ten flaky ones).

These matter in Phase 2 and beyond. In Phase 1 they are noise.

---

## 6. Measurement mechanism

**Continuous (during build):**
- CI captures test coverage and latency benchmarks on every PR.
- Pre-commit hooks enforce code-quality gates.
- Dependency audit runs nightly.

**Per slice:**
- `11-agent-validation-checklist.md` green before merge.
- One approving reviewer required.

**End-of-Phase:**
- Run the governed framework loop repeatedly through the checklist.
- Once v0.1 is green, run the first business-automation dogfood as business validation.
- Operators check in daily and record interventions.
- Compile the Phase 1 Completion Report per §7.

**External review (optional):**
- An external developer (not on the build team) tries to install and run Friday from the README only. Time + friction points recorded.

---

## 7. Phase 1 Completion Report template

```markdown
# Friday Phase 1 — Completion Report

## Dates
- Build started:       ___
- Phase 1 complete:    ___
- Dogfood week:        ___ to ___

## Tier 1 — must-hit
- [ ] M1.1 End-to-end governed loop — evidence: ___
- [ ] M1.2 Zero unsafe actions       — evidence: ___
- [ ] M1.3 Full audit trail          — evidence: ___
- [ ] M1.4 Validation checklist green — link

## Tier 2 — should-hit
- [ ] M2.1 Latency       — measured: ___
- [ ] M2.2 Throughput    — measured: ___
- [ ] M2.3 Reliability   — measured: ___
- [ ] M2.4 Coverage      — measured: ___

## Tier 3 — nice-to-hit
- [ ] M3.1 DX            — measured: ___
- [ ] M3.2 Docs          — measured: ___
- [ ] M3.3 Operability   — measured: ___
- [ ] M3.4 Security      — measured: ___

## Known limitations
- [each with planned Phase 2 resolution]

## Deferred to Phase 2
- [each with issue links]

## Decision
- [ ] Phase 1 complete — proceed to open-source launch (17-open-source-launch-playbook.md).
- [ ] Phase 1 incomplete — re-scoping required: ___
```

---

## 8. Failure modes and responses

| Tier failed | Response |
|---|---|
| **M1.1** end-to-end loop | Architectural gap. Identify whether profile resolution, skill loading, permission gating, sandbox execution, task workflow, logging, or Console visibility broke. Blocks v0.1. |
| **M1.2** unsafe actions | Stop everything. Safety incident = critical bug. Root-cause, fix, restart dogfood week. |
| **M1.3** audit trail | Design failure, not coverage gap. Audit is a property of every action; if actions slipped past, the gateway/permission integration is wrong. Block launch. |
| Tier 2 | Document the gap, set a Phase 2 target. Ship Phase 1 anyway **if** Tier 1 is green and the gap is performance, not correctness. |
| Tier 3 | Ship anyway. Track as Phase 2. |

---

## 9. The honest question

At the end of Phase 1:

> Would I run my own business on this?

If the founder answers no, the launch is premature regardless of metrics. Build until the honest answer is yes.
