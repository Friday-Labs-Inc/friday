# Design 69 — Multi-Agent Delegation

**Status:** Q1–Q14 LOCKED 2026-06-14. 69a implementing.
**Depends on:** Design 68 (Agent Role Contract, PR #101 — merged).
**Replaces / makes redundant:** nothing — this is net-new capability.

> An orchestrator agent must be able to break a complex job into smaller pieces, hand each piece to the right specialist or worker, watch the work as it happens, recover when something fails, and report the whole result back to the human who asked. End to end. Auditable. Durable. Cost-honest. Live.

This is the milestone PR — the one that turns Friday from "an agent" into "a team."

---

## 1. The pain in one paragraph

Today every Friday task runs as a single agent against a single prompt. An "orchestrator" agent has no way to spawn a "researcher" sub-agent to read a stack of files, or a "writer" sub-agent to draft a section, or three "classifier" workers in parallel to label a batch. The operator can wire pipelines of independent tasks through RandomPack, but the *agent itself* cannot plan and dispatch sub-work mid-run. That ceiling is what stops complex jobs — multi-step research, code review with N reviewers, batch transformation with per-row decisions, anything that wants to fan out.

## 2. What Hermes does (the floor)

Hermes ships `delegate_task` as a synchronous Python-thread spawn inside the same process:

- Parent agent calls `delegate_task(prompt, tools=…)`.
- A child thread runs a full `run_conversation()` loop with its own tool set, optional system-prompt override, optional workspace hint inheritance.
- Parent **blocks** while the child runs; progress relays back via callback.
- Configurable max depth (default 3), max concurrent children, interrupt support, timeout with diagnostic dump.
- Orchestrator mode: child gets the kanban tools but **not** the delegate tool (one-level fan-out only by convention).

**What Hermes does not do** — and what makes our version groundbreaking:

| Hermes | Friday |
|---|---|
| Thread inside parent process | Real `Task` row + durable RQ pipeline (survives parent crash) |
| Convention-gated ("orchestrator mode" if you remember to set it) | Role-contract-gated (`agent_role == "Orchestrator"` enforced at dispatch) |
| Stateless — vanishes when parent exits | Persistent — every parent→child edge is a `Task.parent_task` row, queryable forever |
| In-memory progress callback | Live console tree + War Room thread + per-task Execution Logs |
| No project linkage | Child inherits parent's `project`; cost rolls up via Design 65d |
| No cancellation cascade | Parent cancelled → all descendants cancelled by reconciler |
| Parent blocks on child | Default async (fan-out N at once); `wait_for_result` skill for sync convenience |
| Per-call audit absent | Every delegation is a governed skill call: matrix-checked, approval-gated, logged |

That's the surpass-Hermes thesis per [[hermes-floor-not-ceiling]]: deeper governance, deeper durability, deeper visibility — the foundations Friday already paid for in v0.1/v0.2 make this possible without inventing them again.

## 3. The shape — one paragraph

An Orchestrator agent calls a new skill `delegate_task(agent_profile, instruction, …)`. The dispatcher gates on `parent.agent_role == "Orchestrator"`, then inserts a new `Task` row with `parent_task = <parent>`, `project = <parent.project>`, `assigned_to_profile = <target>`, and enqueues it on the `friday` RQ queue exactly like any other Task. The child runs through the existing runner; its terminal state flows back through the existing report-back (62) into both the War Room *and* a Chat Message threaded under the parent's session. The parent agent can optionally call `wait_for_result(delegation_id, timeout)` to block until the child terminates, or `tail_child(delegation_id, lines)` to peek at progress, or just fan out 5 children and let report-back drive it. The Project Console renders the live delegation tree. Costs roll up. Cancellation cascades. The whole graph is one SQL query away.

Nothing new is invented — every piece is the existing durable-pipeline / role-contract / governance-matrix / project-rollup / live-console machinery composed into one capability.

---

## 4. Locked Qs

### Q1 — Sync vs async semantics?
**Recommendation: ASYNC by default; sync via convenience skill.**

The runtime is async — `delegate_task` returns immediately with a `delegation_id`. This unlocks fan-out: an orchestrator can dispatch 5 children in one turn and let them run in parallel through the friday queue.

Sync is a convenience: `wait_for_result(delegation_id, timeout_minutes=30)` polls the child Task's `workflow_state` until terminal, returns the result. Operators who want "do one thing, wait, continue" can chain `delegate_task → wait_for_result` in their orchestrator's prompt.

Why not sync-by-default (Hermes' shape)? Because parent blocking in an LLM loop wastes provider tokens (the parent's context is loaded but idle for every minute the child runs) and forces serialization. Async is the foundation; sync is sugar.

### Q2 — How is parent → child relationship modeled?
**Recommendation: `Task.parent_task` Link field.**

One new field on `Task`:
```
parent_task — Link → Task — read_only — indexed
```

Children are full Tasks. The relationship is a graph edge, not a subtype. Consequences come free:
- Existing Kanban shows children as cards (with a parent badge from a list view formatter).
- Existing Gantt shows them on the same timeline.
- Existing pipeline_health treats them as Tasks.
- Existing 65d rollup includes their cost.
- Recursive descendant query: `WITH RECURSIVE t AS (SELECT name FROM tabTask WHERE name = %s UNION ALL SELECT c.name FROM tabTask c JOIN t ON c.parent_task = t.name) SELECT name FROM t`.

No new DocType. No new join table. No subtype hierarchy. The relationship IS a foreign key.

### Q3 — Depth limit?
**Recommendation: configurable in Agent Settings, default 3, hard ceiling 8.**

Two knobs in `Agent Settings`:
- `max_delegation_depth` — Int, default 3. Enforced at `delegate_task` dispatch.
- `delegation_depth_hard_ceiling` — Int, default 8, not operator-editable in normal UX. The escape hatch is bench console.

At dispatch, the runtime walks `parent_task → parent_task → …` and counts; if the new child would exceed `min(max_delegation_depth, hard_ceiling)`, `delegate_task` returns an error result the orchestrator's LLM can read and react to ("Cannot delegate: would exceed max depth of 3"). No silent truncation.

### Q4 — Who can delegate to whom?
**Recommendation: Orchestrators can delegate to anyone (including other Orchestrators); Specialists and Workers cannot delegate at all.**

Enforcement: the `delegate_task` skill is gated by `parent.assigned_to_profile.agent_role == "Orchestrator"`. Two layers:

1. **Skill loading** — the loader does not include `delegate_task` in the tool list for non-Orchestrator profiles, so the LLM never sees it.
2. **Dispatcher guard** — if someone grants `delegate_task` to a non-Orchestrator profile by hand, the dispatcher refuses with `RoleContractViolation`, logged.

Why allow Orchestrator → Orchestrator? Because that's how trees grow. A top-level "Project Lead" Orchestrator can delegate a sub-project to a "Marketing Orchestrator," who in turn delegates to its own Specialists. Depth limit (Q3) bounds the recursion.

Why forbid Worker → Worker? Workers are the sharp tool — narrow, fast, unattended. Letting them spawn would break the runaway-prevention story (which is also why workers have the highest approval gate in Design 68).

### Q5 — Tool / skill inheritance?
**Recommendation: child uses its OWN `agent_profile.permitted_skills` — no inheritance, no override.**

The profile *is* the configuration. If the orchestrator could grant arbitrary skills to a child at dispatch time, the governance matrix would be bypassed (a Worker profile that's normally restricted to `read_record` could be told "also use `attach_deliverable`" by a delegating orchestrator). That's a governance hole.

Therefore: child's permitted skills come from the child's profile row, exactly as if it were a top-level task. The orchestrator chooses *who* to delegate to (by picking the right profile), not *what* the chosen agent can do.

### Q6 — Progress visibility from parent to child?
**Recommendation: three mechanisms, layered.**

1. **Live console tree** (Design 69c) — Project Console renders the delegation tree with realtime state badges. Operator sees the whole graph.
2. **`tail_child(delegation_id, lines=50)` skill** — orchestrator can read recent Execution Log rows for a delegated child, returned as text. Lets the orchestrator's LLM check on a child mid-run without polling.
3. **Report-back (existing Design 62)** — when child terminates, it writes a Chat Message to the originating session (which for delegated children = parent's session) authored by the child's profile. The parent sees "Researcher reported: done — see X" as a message in its own conversation history.

(1) is for humans, (2) is for the orchestrator LLM, (3) is the canonical "the child finished" signal. All three flow through existing wiring — nothing new at the message/event layer.

### Q7 — Failure semantics?
**Recommendation: report, don't propagate.**

Child terminates in `Blocked` or `Cancelled` → report-back fires → parent receives a Chat Message describing the terminal state, including `blocked_reason` and last `result`. Parent's LLM decides: retry with adjusted instruction, escalate to operator, mark itself blocked, ignore. The runtime does not auto-fail the parent.

Why? The runtime doesn't know what "failure" means in context. A child research task that returns "no sources found" might be a hard fail for one parent and a perfectly valid signal for another. Parent has context; runtime doesn't.

Exception — *unhandled* exceptions in the child (a crash, not a self-reported `Blocked`) still create an Issue via the existing fail-loud contract (Design 61a). That surfaces to the operator regardless of what the parent does with it.

### Q8 — Cost rollup?
**Recommendation: children inherit parent.project; existing Design 65d rollup handles the rest.**

`delegate_task` sets `child.project = parent.project`. Design 65d's `recompute_project_rollup` already sums `cost_usd` across all Tasks where `project = X`. Therefore the project's `actual_cost_usd` reflects the true total spend across the entire delegation tree — orchestrator, all children, all grandchildren — without any new code.

If the orchestrator explicitly passes a different `project` to `delegate_task`, that wins (rare; supported because tree-of-projects is a legitimate pattern). Default behavior is inheritance.

### Q9 — Cancellation cascade?
**Recommendation: yes, downward only.**

When a Task's `workflow_state` transitions to `Cancelled`, the workflow hook fires a `cancel_descendants(task_name)` pass that recursively cancels every Task with `parent_task` in the tree. Implementation: one SQL recursive CTE finds descendants; reconciler picks them up on next tick if any are mid-execution (executing children get their `executing_token` cleared and re-checked).

Cancelling a *child* does NOT cancel its parent. Parent decides: ignore, retry, escalate. (Same logic as Q7 — the runtime doesn't know what the cancellation means in parent context.)

### Q10 — Concurrency limit per orchestrator?
**Recommendation: configurable per profile, default 5.**

New field on `Agent Profile`:
```
max_concurrent_delegations — Int — default 5
```

At dispatch, the runtime counts `Task` rows where `parent_task = <parent>` AND `workflow_state IN ("Pending","Assigned","Executing","Blocked")`. If ≥ limit, `delegate_task` returns `{queued: true, reason: "concurrent-limit"}` — child Task is still inserted (so it's durable) but the dispatcher leaves it `Pending` longer; reconciler will pick it up after sibling slots free.

This prevents one runaway orchestrator from monopolizing the friday queue.

### Q11 — The skill surface?
**Recommendation: three skills.**

```python
delegate_task(
    agent_profile: str,             # target Agent Profile name (must exist + Active)
    instruction: str,               # what the child should do (becomes child.description)
    title: str | None = None,       # task title (default: first 80 chars of instruction)
    project: str | None = None,     # default: inherit parent.project
    priority: str | None = None,    # default: inherit parent.priority
    wait_for_result: bool = False,  # convenience: if True, blocks until terminal
    timeout_minutes: int = 30,      # only used when wait_for_result=True
) -> dict
# Returns: {delegation_id, child_task_name, status: "queued|executing|completed|blocked|cancelled", result?: str}

wait_for_result(
    delegation_id: str,
    timeout_minutes: int = 30,
) -> dict
# Returns: {status, result, blocked_reason?, cost_usd?, duration_ms?}

tail_child(
    delegation_id: str,
    lines: int = 50,
) -> dict
# Returns: {child_task, workflow_state, recent_logs: [{ts, kind, summary, …}]}
```

`delegation_id` == `child_task.name` (Task's own primary key). One identifier; no parallel handle universe.

Risk classification:
- `delegate_task` — risk = **medium** (spawns work; cost impact)
- `wait_for_result` — risk = **low** (read-only poll)
- `tail_child` — risk = **low** (read-only)

Per Design 68, an Orchestrator's default `requires_approval_above_risk = high`, so `delegate_task` does NOT require approval by default — but operators can set their orchestrator profile to `medium` for tighter control.

### Q12 — Console visibility (the live tree)?
**Recommendation: Project Console gets a "Delegation Tree" zone (collapsed by default).**

In the existing live Project Console (Design 65c), add a fourth zone below the project lane: a collapsible "Delegation Tree" per project. Renders the parent-task → child-task graph as an indented tree with workflow_state badges. Updates via the existing `frappe:project_activity` realtime channel (Design 65c) — no new publish channel.

Default collapsed so projects with no delegation don't waste vertical space. Click a Task in the tree → navigates to the Task form. Click a parent → highlights the subtree.

### Q13 — What does the prompt say to an Orchestrator?
**Recommendation: extend the Orchestrator role preamble in `prompt_builder._role_preamble` to mention delegation.**

Current Design 68 Orchestrator preamble:
> ORCHESTRATOR ROLE: Your job is to plan and coordinate. Break complex work into small tasks, delegate when sub-agents exist, and synthesise results. Prefer asking clarifying questions over guessing on scope.

Updated (Design 69):
> ORCHESTRATOR ROLE: Your job is to plan and coordinate. Break complex work into small tasks; use the `delegate_task` tool to assign each to the right Specialist or Worker profile by name. Run delegations in parallel when they don't depend on each other. Synthesise results once children report back. Prefer asking the human one clarifying question over guessing on scope.

That's a 5-line tweak — the rest of Design 68's frame and the GOVERNANCE block ride unchanged. We're not rewriting the prompt; we're filling in the tool name the operational frame already implied.

### Q14 — Audit trail shape?
**Recommendation: reuse existing Execution Log; add a thin delegation index view.**

Every `delegate_task` call already gets one Execution Log row via the standard skill-call pipeline (parameters logged, result logged, cost logged, approval checked). That's the audit primitive.

Add a thin convenience: a new Frappe Report named **"Delegation Graph"** that joins Task to itself on `parent_task`, with columns `project | parent | child | profile | state | cost | duration`. One-page operator view. No new persistence; pure query.

---

## 5. What ships, in three slices

This is too big for one PR. Three slices, each independently mergeable; each green CI before the next opens.

### 69a — Foundation (the durable delegation primitive)
- `Task.parent_task` Link field + migration patch (no backfill needed — pre-69 Tasks simply have it null).
- `Agent Profile.max_concurrent_delegations` Int field, default 5.
- `Agent Settings.max_delegation_depth` Int field, default 3.
- New skill `delegate_task` — registered in skill catalog, handler in `friday/friday_core/skills/handlers_delegation.py`.
- Skill loader: gates `delegate_task` visibility on `agent_role == "Orchestrator"` (Q4).
- Dispatcher guard: `RoleContractViolation` if non-Orchestrator tries to invoke (defense in depth).
- Child Task creation path: inherits `project`, sets `parent_task`, sets `assigned_to_profile = <target>`, enqueues normally.
- Depth + concurrency checks at dispatch.
- Update Orchestrator role preamble (Q13).
- Tests: depth gate, concurrency gate, role gate, project inheritance, child Task shape.

### 69b — Coordination (wait_for_result, tail_child, cancel cascade)
- New skills `wait_for_result`, `tail_child`.
- Cancellation cascade in workflow hook: when a Task moves to `Cancelled`, recursive descendants are cancelled.
- Report-back extension: child terminal state writes a Chat Message to parent's `originating_session` (already wired in Design 62 — just verify the target session is the parent's session, not the human user's).
- Delegation Graph report (Q14).
- Tests: wait timeout, tail returns logs, cascade cancels descendants, report-back targets parent session.

### 69c — Visualization (live console delegation tree)
- New Project Console zone: collapsible "Delegation Tree" (Q12).
- Snapshot endpoint extension: `console_snapshot()` returns per-project `delegation_tree` (recursive query).
- Realtime updates ride existing `frappe:project_activity` channel — no new pubsub.
- Tests: snapshot includes delegation_tree, tree renders correct nesting, click-through navigation.

---

## 6. What does NOT ship in Design 69

- **Sub-agent spawning inside the parent's Python process** — not needed; durable Task pipeline replaces it. Hermes' in-process model traded durability for latency; we're choosing durability.
- **Streaming child output token-by-token to parent's LLM call** — out of scope. Parent polls via `tail_child` or waits via `wait_for_result`. (Token streaming to *the human* via the live console is in scope via existing realtime push.)
- **MoA (mixture-of-agents) fan-out skill** — defer to a future design. Orchestrators can compose MoA manually today via N parallel `delegate_task` calls + synthesis.
- **`interrupt_child(delegation_id)` skill** — defer. `cancel_descendants` already cascades from the parent side; per-child mid-run interruption is a sharper tool we'll add once observed need is real.
- **Delegation policies (e.g. "always route X to Y")** — defer. Operators encode this in the Orchestrator's system prompt for now; turning it into a declarative policy is a v0.4+ concern.
- **Cross-site delegation (delegate to an agent on another Friday install)** — defer to a future A2A design. v0.3 is single-site.

## 7. Risks and how they're mitigated

| Risk | Mitigation |
|---|---|
| Runaway recursion (orchestrator spawns infinite children) | Hard depth ceiling (Q3); concurrency limit per orchestrator (Q10); reconciler reaps stuck children (Design 61a) |
| Cost explosion (5 parallel children × 5 grandchildren each = 25 LLM calls) | Cost rollup is honest (Q8) — operator sees the bill on the Project Console live; cancellation cascades; depth limit is the structural cap |
| Privilege escalation (orchestrator grants itself broader skills via delegation) | Q5 — child uses ITS OWN profile.permitted_skills, never inherits |
| Audit gap (delegation graph not queryable post-hoc) | Q2 — relationship is a real foreign key; Q14 — Delegation Graph report; existing Execution Log captures every skill call |
| Orchestrator gets confused by its own children's report-back messages | Report-back authored by child profile's Frappe User (Design 65a), so it appears as a distinct actor in the conversation, not as a user message |
| The friday queue gets starved by one project's tree | Q10 — concurrency cap per orchestrator; future tuning: per-project quota in Agent Settings (deferred) |

## 8. Hermes ports ledger

Per [[feedback_true-1to1-ports]]: every port classified.

| Hermes element | Friday treatment | Classification |
|---|---|---|
| `delegate_task` tool with `target` and instruction | Kept the shape, kept the name | **port** |
| Synchronous Python-thread execution | Replaced with durable RQ Task | **frappe-adaptation** (Friday has a durable pipeline; Hermes doesn't) |
| Max-depth check | Kept; same default (3) | **port** |
| Max-concurrent-children check | Moved to per-profile field | **improvement** (Hermes is global; Friday is per-orchestrator, finer-grained) |
| Toolset inheritance | Removed entirely | **improvement** (governance — child uses own profile, no skill bypass) |
| Workspace hint inheritance | Replaced with `project` inheritance | **frappe-adaptation** (workspace is Hermes-specific; project is Friday's equivalent) |
| Progress callback | Replaced with three layered mechanisms (console, tail skill, report-back) | **improvement** (durable + queryable, not in-memory callback) |
| Timeout with diagnostic dump | Kept on `wait_for_result` (timeout returns status without killing the child) | **adaptation** |
| Interrupt support | Deferred (cancel cascade covers most cases) | **simplification** (disclosed in §6) |
| Orchestrator-mode convention | Replaced with role contract (Design 68) | **improvement** (auditable on the profile row, not implicit in tool grants) |

Net: ~30% verbatim port, ~50% frappe-adaptation, ~20% deliberate improvement. Every divergence named.

## 9. Verification (the diff test)

Every changed line in the 3 slices must trace to: "an Orchestrator can call `delegate_task`, a child Task runs through the pipeline, the parent sees results, the operator sees the tree, and the books balance."

Drive-by formatting, unrelated cleanup, speculative abstraction → out.

---

## 10. Open Qs to lock with the user

Before any code lands, confirm or override:

| # | Locked recommendation |
|---|---|
| Q1 | Async runtime; sync via `wait_for_result` |
| Q2 | `Task.parent_task` Link field |
| Q3 | Configurable depth, default 3, hard ceiling 8 |
| Q4 | Orchestrators delegate to anyone; non-Orchestrators cannot delegate |
| Q5 | Child uses own profile skills — no inheritance |
| Q6 | Console + tail_child + report-back |
| Q7 | Report failure, don't propagate |
| Q8 | Children inherit parent.project; rollup is automatic |
| Q9 | Cancellation cascades downward only |
| Q10 | Per-profile concurrency cap, default 5 |
| Q11 | Three skills: delegate_task / wait_for_result / tail_child |
| Q12 | Console gets a collapsible Delegation Tree zone |
| Q13 | Orchestrator preamble extended with delegation guidance |
| Q14 | Reuse Execution Log + new Delegation Graph report |

All 14 locked — 2026-06-14.
