# Design 69a — Delegation Foundation (2026-06-14)

## What changed

Before this PR, Friday agents worked alone. An orchestrator could call
`delegate-task` and the child agent would run **inside** the parent's process,
blocking until done. One child at a time. If the parent crashed, the child's
work vanished.

After this PR, delegation is **async and durable**. An orchestrator calls
`delegate_task(agent_profile="Researcher", instruction="...")` and gets back a
delegation ID immediately. The child becomes a real Task row in the pipeline
with `parent_task` pointing at the parent. The existing dispatcher picks it up,
the existing runner executes it, and the existing report-back delivers results.
The orchestrator can fan out five children in parallel.

Three safety gates protect the system from runaway delegation:

1. **Role gate** — only Orchestrator profiles can delegate. The LLM for a
   Specialist or Worker never even sees the delegate-task tool.
2. **Depth gate** — the parent_task chain can't go deeper than
   `Agent Settings.max_delegation_depth` (default 3, hard ceiling 8).
3. **Concurrency gate** — each orchestrator profile can have at most
   `max_concurrent_delegations` active children (default 5).

## Why

This is the milestone that turns Friday from "an agent" into "a team." Complex
jobs (multi-step research, batch classification, parallel reviews) need
fan-out. The existing pipeline already handles dispatch, execution, heartbeat,
reconciliation, and report-back — delegation composes those pieces into
tree-shaped work.

## What operators see

- **Task form** — a new "Parent Task" field (read-only) shows which task
  delegated this one. NULL for top-level tasks.
- **Agent Profile form** — a new "Max Concurrent Delegations" field (default 5)
  controls how many active children one orchestrator can have.
- **Agent Settings** — two new fields: "Max Delegation Depth" (default 3) and
  "Delegation Depth Hard Ceiling" (default 8).
- **Orchestrator prompt** — the role preamble now mentions `delegate_task` by
  name and advises running delegations in parallel when possible.

## Migration

Schema-only. The new fields have sensible defaults. No data migration needed —
existing tasks simply have `parent_task = NULL` (they were never delegated).

Run `bench --site <site> migrate` after deploying this PR.

## What ships next

- **69b** — coordination skills: `wait_for_result`, `tail_child`, cancellation
  cascade, report-back targeting the parent's session.
- **69c** — live console delegation tree visualization.
