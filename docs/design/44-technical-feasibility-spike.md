# 44 — Technical Feasibility Spike

> **Purpose:** Define a timeboxed engineering investigation that resolves the open stack decisions in docs 39, 40, and 42 *before* production implementation begins. The spike is not Phase 1. It is the gate that lets Phase 1 start with grounded choices instead of guesses.

---

## 1. Why a Spike Now

Doc 40 enumerates several open technical decisions that doc 42 (Phase One Authority Contract) quietly assumes will be resolved. Starting implementation without resolving them risks:

- Choosing Frappe v16 only to discover an ecosystem dependency we need is still on v15
- Committing to PostgreSQL only to find that a critical Frappe app misbehaves
- Including Raven in v0.1 without verifying it installs cleanly alongside Friday's custom modules
- Designing around ERPNext as a hard dependency before proving its install path
- Picking a CLI strategy that fights `bench` instead of cooperating with it

The cost of a spike is days. The cost of discovering these problems mid-implementation is weeks.

---

## 2. Decisions This Spike Must Resolve

| # | Decision | Outcome |
|---|---|---|
| D1 | Frappe v15 vs v16 substrate | **v16 stable** |
| D2 | PostgreSQL vs MariaDB | **PostgreSQL + pgvector** |
| D3 | Raven inclusion in v0.1 | **Excluded — v0.2. CLI-first.** |
| D4 | ERPNext as dependency vs ported DocTypes | **Not relevant this phase** |
| D5 | CLI strategy | **Extend bench with `friday` command group** |
| D6 | LLM provider abstraction | **Provider-agnostic from day one. Minimax as primary.** |
| D7 | Sandbox backend | **Docker** |
| D8 | Friday repo: fork vs app | **Hard fork of Frappe v16 stable** |

All decisions resolved. See `docs/decisions/spike-results.md` for full rationale.

---

## 3. Timebox and Team

**Duration:** 5 working days, single engineer.

**Stretch:** 10 working days if D1 or D8 reveal genuine ambiguity.

If the spike has not produced decision records by day 10, escalate: the project has a deeper foundational ambiguity than the spike can resolve and the docs need rework before any code.

---

## 4. Spike Scope (What to Actually Build)

The spike produces a throwaway proof-of-concept. It is not Phase 1 code. It is not committed to `main` of the friday repo. It lives on a `spike/` branch and is deleted or archived after decisions are recorded.

Minimum buildable PoC:

1. Fresh bench setup
2. Frappe site created with one of the two candidate DB engines
3. ERPNext installed (or not, per D4)
4. Raven installed (or not, per D3)
5. A throwaway Friday app called `friday_spike` with:
   - One DocType called `Spike Agent Profile`
   - One DocType called `Spike Skill` with a code field
   - One whitelisted Python method that loads a Spike Skill, runs it inside a Docker container, captures result, writes a `Spike Execution Log` row
   - One simple permission check before the skill runs
6. A throwaway CLI command (`bench --site SITE friday-spike run-skill SKILL_NAME`) that drives the above end-to-end

The goal is to touch every architectural commitment in doc 42 at low resolution and learn what breaks.

---

## 5. Test Matrix per Decision

### D1 — Frappe Version

For each candidate (v15, v16):

- Does `bench init` succeed without manual workarounds?
- Does `bench new-site --db-type postgres` (if D2 candidate is PostgreSQL) succeed?
- Does ERPNext install cleanly (if D4 candidate is ERPNext-dependent)?
- Does Raven install cleanly (if D3 candidate is Raven-included)?
- Does our minimal Friday spike app install and migrate?
- Are there Python version / Node version requirements that break the operator install story?

Score: ✅ Pass / ⚠️ Pass with workaround / ❌ Blocker.

A "Pass with workaround" outcome must be documented with the exact workaround.

### D2 — Database

For each candidate (MariaDB, PostgreSQL):

- New site creation
- Frappe core migration
- ERPNext migration (if D4)
- Raven migration (if D3)
- A custom DocType create + insert + query cycle
- Simple permission check
- Frappe RQ background job
- Performance smoke test: 1000 doc inserts, simple list query

For PostgreSQL specifically, also test pgvector extension install (even though pgvector usage is deferred per doc 42 §4).

### D3 — Raven Inclusion

Two paths to test:

- **Included path:** install Raven, create one channel programmatically from the spike app, post a message from the spike app's Python code, verify message visible in Raven UI.
- **Excluded path:** verify Friday spike runs end-to-end with no Raven dependency at all.

Decision criterion: if "included path" works in under 4 hours of spike effort, Raven joins v0.1. If it takes longer, defer to v0.2 per doc 42 §3.5.

### D4 — ERPNext Dependency

Two paths to test:

- **Dependency path:** install ERPNext, use ERPNext's Project/Task/Issue DocTypes from the spike app (read + write).
- **Ported path:** create `Agent Project`, `Agent Task`, `Agent Issue` as native DocTypes in the spike app, no ERPNext install.

Decision criterion per doc 41: ported is preferred for framework independence unless dependency path has a strong Phase 1 use case. For Phase 1, default is ported.

### D5 — CLI Strategy

Three candidate approaches:

- **Extend bench:** `bench friday <command>` via Frappe command registration
- **Wrap bench:** Friday provides a `friday` script that internally calls `bench` for operations
- **New entrypoint:** Friday provides standalone `friday` CLI that does not delegate to bench

Test each: implement a simple `friday chat`-like command. Measure setup friction, discoverability, and conflict with existing bench commands.

Decision criterion per doc 39 §6: "bench remains available and documented; `friday` CLI entrypoint or bench plugin commands exist for agent-specific workflows." The spike must determine which form of `friday` command works best.

### D6 — LLM Provider

Implement one skill that uses Anthropic Claude. Then write a thin provider interface. Confirm:

- The interface cleanly supports tool/function calling
- Provider keys live in Frappe Password fields
- Streaming works
- Error handling and timeout are reasonable

No second provider needs to be implemented in the spike. The interface design is the deliverable.

### D7 — Sandbox

Implement skill execution in a Docker container with:

- Non-root user
- Resource limits (cpu, memory)
- Timeout
- No host mounts
- Structured result capture

Test: a skill that tries to escape (mounts /, opens network, forks bombs). All should be contained or rejected by the sandbox configuration.

Doc 42 §5 minimum bar applies. Hardened sandbox (warm pool, egress allowlist, etc.) is explicitly out of scope for the spike.

### D8 — Fork Strategy

**Decided: Friday is a hard fork of Frappe v16 stable. This is not a spike question.**

The Friday repository starts from the Frappe v16 stable tag. Agent-native primitives — actor context propagation, trace ID propagation, audit hooks, agent-scoped auth — are built directly into core. The bench ecosystem is fully retained. There is no app-only path.

The spike still validates the five technical requirements to confirm that the planned core modifications are sufficient and correctly scoped:

- Actor context propagation across request → background job → sandbox
- Trace ID propagation from gateway → execution → audit
- Friday Control Room workspace as default landing
- Permission check before background job dispatch
- Bench command extension via `friday` namespace

The question is not "do we fork?" — that is answered. The question is "where exactly in core do these changes land, and are there surprises?" See `45-fork-policy.md` for the operating discipline.

---

## 6. Deliverables

The spike produces three artifacts:

### 6.1 Decision Record (`docs/decisions/spike-results.md`)

A document with one section per decision (D1–D8). Each section contains:

- Decision: chosen option
- Date: when the decision was made
- Rationale: why this option
- Evidence: what the spike showed (logs, screenshots, benchmarks)
- Reversibility: how hard would it be to change later
- Risks: what could still go wrong

### 6.2 Updated Phase 1 Authority Contract

If the spike resolves D3 (Raven), D4 (ERPNext), or D8 (fork strategy) in ways that change doc 42's assumptions, doc 42 must be updated. The spike author proposes edits; the project owner approves.

### 6.3 Spike Branch Archive

The throwaway PoC code stays on `spike/feasibility-{date}` branch in the friday repo. It is not merged. It is referenced by the decision record for reproducibility.

---

## 7. Risks During the Spike

| Risk | Mitigation |
|---|---|
| Spike goes over timebox | Hard stop at day 10; escalate doc-level ambiguity |
| Spike PoC code accidentally ships to main | Spike work happens only on `spike/` branch; PR review gate prevents merge |
| Spike biases toward shiny choices (v16, PostgreSQL) over boring choices (v15, MariaDB) | Default to boring unless spike produces specific evidence that shiny is better |
| Engineer running spike treats it as Phase 1 implementation | Restate scope at kickoff; PoC code is throwaway |
| Spike reveals foundational issue that breaks doc 42 | Pause and rework the contract before continuing |

---

## 8. Out of Scope for the Spike

The spike does NOT:

- Build production-grade DocTypes
- Build the Control Room (per doc 43)
- Implement learning loops, memory, autopilot, multi-site
- Build the first business-automation flagship (that's a Phase 1 deliverable on top of v0.1)
- Make any choice that doc 42 has already locked
- Touch the `main` branch of the friday repo

The spike is exploration, not commitment.

---

## 9. Success Criteria

The spike succeeds when:

- All 8 decisions have recorded outcomes (whether default or alternative)
- Each outcome has rationale and evidence
- Doc 42 reflects any changes the spike caused
- The engineer running the spike can confidently start Phase 1 implementation knowing the stack
- A second engineer could read the decision record and rebuild the same setup without re-running the spike

---

## 10. After the Spike

Once the spike concludes:

1. Decision record committed and reviewed.
2. Doc 42 updated if needed.
3. Doc 45 (Fork Policy) referenced if D8 chose the fork path.
4. Spike branch archived (tag + remove from active branches).
5. Phase 1 implementation kickoff using doc 42 + doc 11 (Validation Checklist) as the operational plan.
6. The first real Phase 1 commit lands on `main` with confidence about every foundational choice.

---

## 11. Open Questions

1. Should the spike include a hosted/Frappe Cloud test target, or local bench only? Lean: local bench for the spike; Frappe Cloud compatibility verified separately if it becomes a deployment target.
2. Who runs the spike — Vasanth, a hired engineer, or a coding agent (Claude Code / Cursor)? Decision is project-owner's. The spike's content is the same either way.
3. Does the spike include a basic LLM cost measurement to inform doc 18's GTM pricing? Optional but useful: log tokens per skill call, multiply by current provider rates, log per-skill cost.

---

## 12. Summary

The spike turns doc 42's assumptions into evidence. Five working days, eight decisions, one decision record, possibly one fork commitment.

Doing the spike is much cheaper than discovering its outcomes during Phase 1 implementation.

---

**Recommendation:** run the spike *before* writing any non-trivial Phase 1 code. The spike's decision record becomes a permanent reference for every Friday engineer who joins later.
