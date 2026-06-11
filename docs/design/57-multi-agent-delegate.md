# Design 57 — Multi-agent: the `delegate-task` skill

**Status: LOCKED 2026-06-10 — all six decisions (Q1–Q6) accepted as recommended ("lock all").**

## What this is, in plain English

One agent hands a piece of work to another agent and gets the result back —
the supervisor → specialist pattern. After this lands:

> You (to Friday): *"Have the copy specialist draft taglines for BB-0001's
> shortlisted direction."*
> Friday calls `delegate-task` → a **Task row** is created (audit) → the
> specialist profile runs its own governed ReAct turn in an **isolated
> session** → its summary comes back to Friday → Friday composes the final
> answer for you.

This is the port of Hermes `tools/delegate_tool.py` onto the Task +
orchestrator objects Friday already has — finishing the half-built 🟡 row
and closing the "sub-agents" piece of the Tools gap.

## What exists vs what's missing (honest)

| Piece | State |
|---|---|
| `Task` DocType (title, description, `assigned_to_profile`, `required_skills`, `workflow_state`, `result`) | ✅ exists — the perfect delegation substrate |
| Workflow events → runner → War Room posts → failure auto-files an Issue (D6) | ✅ exists |
| **But** the existing runner is **mechanical** — it executes `required_skills` in sequence with **no model in the loop** | the gap |
| Routing (`resolve_profile`) | only platform-default — no capability matching |
| A way for one agent to *invoke* another | missing entirely |

## Hermes faithfulness

Hermes `delegate_tool`: parent spawns a child agent with an **isolated
context**; the parent's context receives **only the delegation call and the
child's concise summary** ("the parent's context only sees the delegation
call and the summary result"). Children get budget caps and the parent
waits for the result. Friday ports exactly that contract — with the Frappe
adaptation that **every delegation is a durable Task row** (audit-grade, like
everything else).

## Decisions to lock (Q-by-Q)

**Q1 — The skill: `delegate-task`, and every delegation IS a Task row.**
*Recommendation:* parameters: `title`, `instructions` (what the child must
do), `profile` (optional — the specialist to use), `required_skills`
(optional — for auto-matching when no profile is named). The handler creates
a Task row first (audit: who delegated what to whom, when), then runs the
child, then writes the child's summary onto `Task.result`.

**Q2 — Synchronous, v0.1: the parent waits for the child's summary.**
*Recommendation:* the handler runs the child **inline** — a nested
`run_turn(child_profile, fresh_session, task_framing)` — and returns the
child's reply as the tool result, so the parent can *compose* (true Hermes
parity; their delegate is wait-for-summary too). No queue hop = no
worker-deadlock risk with a single friday worker. **Async fire-and-forget
("don't wait") is deferred** — it needs the agentic execution mode wired
into the existing task runner; disclosed as the follow-up, not snuck in.

**Q3 — Context isolation, Hermes-faithful.**
*Recommendation:* the child sees ONLY the task framing (title +
instructions) in a fresh session (`task::<task-name>`), never the parent's
conversation. The parent sees ONLY the summary. Both sessions are fully
audited independently (the child's skill calls dispatch under its own
profile's permissions).

**Q4 — Depth cap: children cannot delegate (v0.1).**
*Recommendation:* the handler refuses when invoked from a `task::` session
("delegation depth limit reached — complete the task directly"). Hermes
allows nested children with progress relays; Friday defers nesting until
there's a real need. DISCLOSED divergence.

**Q5 — Auto-matching closes the orchestrator hole.**
*Recommendation:* when `profile` is omitted, pick the first **Active**
profile whose `permitted_skills` cover ALL `required_skills` (deterministic:
alphabetical). Named profile always wins. No match → actionable error fed
back to the model ("no active profile permits [x, y] — name a profile or
adjust required_skills"). This extends `routing/` with the capability
matcher the 🟡 row was missing.

**Q6 — Governance class.**
*Recommendation:* `risk_level=low`, `requires_approval=0`,
`required_doctypes`: create on Task. Rationale: delegation itself only
creates a work record and invokes another **fully governed** agent — every
action the child takes is permission-gated and audited under the child's own
profile (defence in depth). Budgets: the child inherits the standard
15-iteration loop cap; total wall-clock is bounded by the worker job timeout
(600s). A dedicated per-child timeout is a disclosed later refinement.

## What lands on disk (when locked)

- `skills/handlers_delegate.py` — the `delegate-task` handler (create Task →
  resolve profile [Q5] → depth guard [Q4] → nested `run_turn` [Q2/Q3] →
  result onto the Task row → summary back to the parent).
- `routing/resolve.py` — `match_profile_by_skills(required_skills)` (Q5).
- `skills/bootstrap_brand.py` pattern reused: `bootstrap_delegate.provision`
  (Skill row + schema + Task-create perm + profile wiring).
- Tests FIRST: depth guard, auto-match (match / no-match / named-wins),
  Task-row audit shape, child isolation (framing only), summary return,
  failure path (child error → Task Blocked → parent gets actionable text).
- Live proof: a second Agent Profile on the bench; Friday delegates a real
  subtask; Task row + both sessions' audit trails verified.

## Out of scope (deliberately)

- Async / parallel children (the agentic task-runner mode) — next slice.
- Nested delegation (Q4).
- Hermes' interrupt/list-active child controls — meaningful only with async.
- Cross-agent file/state registry (Hermes) — no shared-file workspace in v0.1.
