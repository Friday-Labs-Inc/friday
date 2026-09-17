# 09 — Agent Evaluation Guide

> Define the criteria the implementing agent uses to decide whether each Hermes Agent component is **reusable as-is**, **adaptable to Frappe**, or **must be rewritten from scratch** for Friday.
>
> This is the evaluation framework. The canonical verdict-per-piece tables live in `14-integrated-architecture.md` §10 and `41-porting-strategy-hermes-erpnext-raven.md`. This doc explains the questions behind those verdicts.

---

## 1. Three verdicts

- **REUSE** — Friday uses the code with minimal changes: license headers, import paths, input/output rewiring to Frappe equivalents.
- **ADAPT** — The design and structure are valuable, but the implementation is rewritten on Frappe primitives (DocTypes, permissions, hooks, RQ workers, Socket.io) instead of Hermes' own (markdown files, JSON state, SQLite, custom dispatcher).
- **REWRITE** — Hermes' implementation does not map to Friday's architecture. The feature is designed and built from scratch; Hermes is reference for *what* the feature does, not *how*.

---

## 2. Decision questions

Applied in order to every Hermes component.

### Q1 — Does it touch persistent state?

- No (pure logic, prompt assembly, parsing, formatting) → likely **REUSE**.
- Yes → continue to Q2.

### Q2 — Does the state map cleanly to a DocType?

- Yes → **ADAPT**. Replace file/SQLite reads with `frappe.get_doc` / `frappe.get_all`; replace writes with DocType save/submit.
- No (e.g. ephemeral conversation buffer) → keep in Redis; **ADAPT** or **REUSE**.

### Q3 — Does it bypass or weaken permission boundaries?

- Yes (Hermes' permissive defaults, direct file access, unscoped shell exec) → **REWRITE**. Friday requires gateway-level permission validation, no exceptions.
- No → continue.

### Q4 — Does it depend on Hermes-specific runtime conventions?

Examples: `HERMES_HOME`, `~/.hermes/`, `profile_override`, Hermes' own session format, Hermes' SQLite schema.

- Yes → **ADAPT**. Replace conventions with Frappe site context (`frappe.local.site`), Frappe sessions, Frappe DocTypes.
- No → likely **REUSE**.

### Q5 — Is there a Frappe-native primitive that already does this?

Examples: Frappe Workflow vs. Hermes' approval routing; Frappe Scheduler vs. Hermes' cron; Frappe Socket.io vs. Hermes' WebSocket dispatcher; Frappe Kanban view vs. Hermes' Kanban dashboard.

- Yes → **REWRITE** on the Frappe primitive. Document the mapping.
- No → consider **ADAPT**.

### Q6 — Does the component carry a publicly-documented security risk class?

This is architectural-pattern reasoning per `46-security-claims-audit.md` — not unsourced CVE numbers. Patterns include adapter-level input handling bugs, supply-chain exposure via shared LLM-routing dependencies, and memory-channel poisoning.

- Yes → **REWRITE**. Learn from the mitigation; do not inherit the implementation.
- No → continue with the prior verdict.

---

## 3. Worked examples

The full verdict table is in `14-integrated-architecture.md` §10. The three examples below show how Q1–Q6 produce a verdict.

### Agent loop (`AIAgent.run_conversation`)

- Q1: Yes — touches conversation state.
- Q2: Conversation buffer maps cleanly to Redis + a DocType for persistence.
- Q3: The loop itself is permission-agnostic; permission checks are inserted around it.
- Q4: Uses Hermes `profile_override` and session format — needs rewire.
- Q5: No direct Frappe equivalent.

**Verdict: ADAPT.** Keep the loop structure (perceive → plan → tool call → execute → result → repeat); replace state plumbing with Frappe + Redis.

### Tool registry / Skill loading

- Q1: Yes — loads from disk on every dispatch.
- Q4: Loads from `~/.hermes/skills/` and bundled `.hub/`.
- Q5: Friday's Skill DocType replaces the entire file-based loader.

**Verdict: REWRITE.** Reference Hermes' progressive disclosure model (L0/L1/L2); build the loader against Frappe DocTypes from scratch.

### Skill management tool (`skill_manage`)

- Q3: In Hermes, skills are files the agent can write directly — self-mutation bypasses any review.
- Q5: Friday gates skill changes via DocType permissions; agents produce Skill Draft rows, humans approve.

**Verdict: REWRITE.** Direct skill mutation is replaced by a DocType-based draft/review workflow.

---

## 4. Anti-patterns the agent rejects on sight

Regardless of how convenient or well-written, the agent refuses to import Hermes patterns that contradict Friday's design:

| Pattern | Why rejected |
|---|---|
| Permissive-by-default permission posture | Violates Friday's permission-first principle |
| Skills as files the agent can write directly | Bypasses approval workflow |
| Session state in flat files outside the database | Breaks audit trail |
| Running tools in the host process by default | Breaks sandboxing |
| Hard-coded `~/.hermes/` paths | Breaks Frappe multi-tenant sites |
| LLM-routing-aggregator dependency as default | Supply-chain risk pattern; Friday uses direct provider SDKs |
| Markdown-only skill discovery | Breaks DocType-based Skill governance |

Encountering one of these and being tempted to import it is a stop-and-flag moment, not a judgement call.

---

## 5. License compliance

For every component marked REUSE or ADAPT:

- [ ] Confirm the original Hermes file's license header.
- [ ] Verify it is GPL v3, AGPL v3, or compatible.
- [ ] Preserve attribution in the Friday file's header:
  ```python
  # This file adapts logic from NousResearch/hermes-agent (GPL v3).
  # Original source: [path in Hermes repo]
  # See AUTHORS / NOTICE for full attribution.
  ```
- [ ] Record the original path in the project's `AUTHORS` / `NOTICE` file.

No REUSE or ADAPT happens without recorded attribution. License compliance is a blocker, not a polish item.

---

## 6. Spec vs. Hermes

If a Hermes implementation contradicts a Friday spec, the **spec wins** — always.

The agent does not "improve" Friday to match Hermes. The agent may propose a spec amendment in writing — describing what Hermes does, why it might be better, and the tradeoff. Humans decide.

---

## 7. Output of the evaluation phase

When evaluation is complete, the agent has produced:

1. `docs/hermes-audit.md` — verdict per component with reasoning, in the format below.
2. `AUTHORS` / `NOTICE` populated with attribution for every REUSE/ADAPT entry.
3. A prioritised list of Phase-1-bound components, carried forward to `10-agent-execution-guide.md`.
4. A list of flagged conflicts and proposed resolutions for human review.

```markdown
### [Component Name]
- **Hermes source:** [path or paths]
- **Verdict:** REUSE / ADAPT / REWRITE
- **Reasoning:** [which Q1–Q6 outcomes drove the verdict]
- **Mapping to Friday:** [Friday module / DocType / file that owns this]
- **License notes:** [attribution requirements]
- **Phase:** 1 / 2 / 3+
```

Once the four artefacts exist and are reviewed, proceed to `10-agent-execution-guide.md`.
