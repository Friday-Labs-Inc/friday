# Design 76 — Parallel fan-out + AND-join (Design 75 Phase 2)

**Status:** Designed 2026-06-16 via a 5-agent pass (Frappe-capability study + Phase-1-engine map + prior art → synthesis → adversarial critic). Buildable with the critic's 6 preconditions baked in. **Extends Design 75**; Phase 1 stays byte-for-byte unaffected.

## The pivot (why this exists)

Design 75 Phase 1 is **sequential-only**: each workflow state has at most one outgoing agentic transition. Real pipelines fork — the RandomPack brand pipeline's *naming* and *directions* both follow *strategy* and both feed *gate 1 prep*; a research domain scans several sources at once. Phase 1 linearised these. Phase 2 lets a domain run branches **in parallel** and **join** them — declared as bundle data, no engine code per domain.

## The hard constraint (Frappe is single-token)

The capability study is unambiguous: **Frappe Workflow is a strict single-token state machine.** A document holds exactly one state in one field; there is no native fork/join; `apply_workflow` overwrites one field with one next-state. So the work-item's branch progress **cannot** live in the Frappe state field — it lives in Friday's own Task rows. The work-item simply *sits in the fan-out state* while branches run, then advances once, exactly as a sequential phase does. This keeps the Frappe Workflow valid and the operator's mental model intact.

## 1. Data model (additive — Phase 1 data reads as sequential)

- **`Friday Workflow Transition Meta`** + `fan_out_group` (Data, blank for sequential) + `is_fan_out_branch` (Check, default 0). `wait_for_all_tasks` (already stubbed in Phase 1) becomes live. `action` becomes **not-reqd** when `is_fan_out_branch=1` (a branch never fires a Frappe transition); the controller enforces "action required unless branch", and `_unique_transition` skips branch rows.
- **`Task`** + `fan_out_group` (Data) + `is_fan_out_branch` (Check) — stamped at dispatch so the sibling-completion query is one indexed read, not N meta look-ups.
- **`phase_key` uniqueness** is the load-bearing key for the meta look-up in `advance.py`. **Already enforced** per-workflow by the Phase-1 controller (`_unique_phase_key`), so the critic's CRITICAL-1 is satisfied without a (wrongly-scoped) global DB unique index.

### How a bundle DECLARES a fan-out (pure data)
From a fan-out state `S`, the bundle defines, all sharing one `fan_out_group` slug:
- **N branch rows**: `is_fan_out_branch=1`, each its own `phase_key` + `agent_role` (the specialist), no `action`. These dispatch in parallel.
- **1 join row**: `wait_for_all_tasks=1`, `is_fan_out_branch=0`, its own `agent_role` (the aggregator), and the **real** `action` that advances `S → next`. This is the sole advance authority.

A sequential phase is just the existing single row with `fan_out_group=''`, `is_fan_out_branch=0`, `wait_for_all_tasks=0` — unchanged.

## 2. The engine (changes are localized + additive)

- **`workflow_engine._agentic_meta_for_state`** now returns `list[row]` (a one-element list is the sequential case; `None` unchanged). Rows sharing a non-blank `fan_out_group` are a fan-out; a blank/mismatched group among multiple rows logs and degrades to the first row (back-safe). **The return-type change and the `on_work_item_update` call-site refactor ship as ONE atomic commit** with a type annotation, so no caller ever dereferences `.phase_key` on a list (critic HIGH-3).
- **`workflow_engine.on_work_item_update`**: one row → `phase_dispatcher.dispatch()` (today's path, untouched). N rows → `phase_dispatcher.dispatch_fan_out()`.
- **`phase_dispatcher.dispatch_fan_out(work_item, branch_metas, join_meta)`**: cancel any stale non-terminal join task for `(work_item, join phase_key)` (back-edge safety, critic LOW-8); create N branch Tasks **Assigned** (profile resolved from each branch's `agent_role`, exactly like `dispatch()`); create the join Task **Pending** with `assigned_to_profile` **pre-set** from the join row's `agent_role` (so the cron dispatcher's `assigned_to_profile IS NULL` filter skips it — it is NOT claimed by the general queue; critic CRITICAL-2 + MEDIUM-7). Stamp `fan_out_group` + `is_fan_out_branch` on every created Task.
- **`advance.on_task_update`**: look up the meta by `phase_key`. If `is_fan_out_branch=1` → a branch finished: **do not advance the work-item.** Instead count incomplete branch siblings (`Task` where `work_item_*`, `fan_out_group`, `is_fan_out_branch=1`, state ≠ Completed). If zero, **promote the join Task** Pending → Assigned (load, guard `state=='Pending'`, save → fires the runner via `_emit_assigned_event`).
- **`advance.advance_work_item`**: when the meta has `wait_for_all_tasks=1`, **re-verify all branch siblings are Completed before `apply_workflow`** — the secondary AND-join guard (critic MEDIUM-6). The existing `work_item.get(state_field) != meta.from_state` check stays as the final idempotency shield.

## 3. The join trigger — race-safe by construction (critic CRITICAL-2)

There is exactly **one** join Task per fan-out, created once, and the work-item advances only when *it* completes. The branch-completion handler promotes that single join Task. If two branches finish near-simultaneously in separate workers and both attempt the promotion, three independent shields make it harmless:
1. the runner enqueue uses `job_id = "task:<join_task>"` → RQ de-dupes the duplicate job;
2. the runner's `executing_token` CAS gives exactly-once *effect*;
3. `advance_work_item`'s `from_state` guard no-ops a second advance.

The join transition is fired **by the join Task's resolved agent** (deterministic, role-correct — its system user holds the `agent_role` the Frappe transition gates on), via the same `acting_as(actor)` + after-commit `enqueue` path as every sequential advance. **No use of `Task.depends_on`** — the join is gated by a `fan_out_group` sibling query, honoring the Phase-1 standing rule that `depends_on` is not repurposed for fan-out coordination (critic HIGH-4, Option b).

## 4. Partial failure is surfaced, never silent (critic HIGH-5)

A branch that Blocks/Cancels would leave the join waiting forever. A **reconciler rule** (each tick) finds Pending join Tasks (`wait_for_all_tasks=1` on their meta) that have any branch sibling in `Blocked`/`Cancelled`, writes `blocked_reason='branch_task_failed:<task>'`, and emits a dispatcher event. Operator remedies: fix + re-dispatch the failed branch, or reset the work-item state to re-trigger the fan-out (which cancels the stale join). Ships **with** the feature, not as a follow-on.

## 5. Backward compatibility (the non-negotiable)

Every Phase-1 FWT Meta row has `fan_out_group=''`, `is_fan_out_branch=0`. `_agentic_meta_for_state` returns a one-element list; `on_work_item_update` calls `dispatch()` exactly as today; `advance.on_task_update` sees `is_fan_out_branch=0` and enqueues `advance_work_item` as today. The three new fields are Check/Data defaulting to `0`/`''`, so existing rows need **no data backfill** — only `bench migrate` to add columns. The brand pipeline keeps working unchanged; converting its naming/directions diamond to a real fan-out is a *separate, optional* data edit.

## 6. Scope boundary

Phase 2 ships the **AND-join only** (all branches must complete). OR-join / N-of-M (`n_of_m_threshold` on the join row) is **Phase 3** and is purely additive to this data model. Branch-result aggregation is a runner/prompt concern: the join's agent reads sibling results via `get-phase-outputs` (Phase 1.1) filtered by `fan_out_group` — no engine change.

## 7. Sequencing (additive-first; each step verifies)

1. **Schema**: add the 3 fields; `bench migrate` clean → existing rows read sequential; all Phase-1 + Phase-1.1 tests still green.
2. **Engine detection (atomic commit)**: `_agentic_meta_for_state` → `list`; `on_work_item_update` unpacks it; `dispatch_fan_out` stubbed. Phase-1 tests green. → verify: no caller reads `.phase_key` on a list (type-checked).
3. **`dispatch_fan_out`**: creates N Assigned branches + 1 Pending pre-assigned join; cancels stale join. → unit test: 2 branches + 1 join meta ⇒ 3 Tasks, branches Assigned, join Pending with the group stamped.
3b. **Reconciler rule** for blocked-branch join stall. → unit test: Block a branch ⇒ join gets `blocked_reason`.
4. **Advance guard**: branch early-return + sibling-count promotion in `on_task_update`; secondary `wait_for_all_tasks` guard in `advance_work_item`. → unit test: completing a branch does NOT advance; completing the last branch promotes the join; completing the join advances once.
5. **Integration + Legion E2E**: convert the brand pipeline's `naming`+`directions` into a real fan-out (data only) and re-run the live E2E → reaches `Delivered`, both branches ran in parallel, single advance at the join.

## The critic's non-negotiable preconditions (all folded in)
1. `phase_key` uniqueness — met by the Phase-1 controller (§1). 2. Join row declares `agent_role`; join Task created with a pre-set profile, never claimed by the general queue (§2/§3). 3. Return-type change + call-site refactor ship as one atomic, type-annotated commit (§2). 4. Secondary `wait_for_all_tasks` guard in `advance_work_item` alongside the `is_fan_out_branch` early-return (§2). 5. Reconciler rule for blocked-branch stall ships with the feature (§4). 6. Constraint-6 resolved: no `Task.depends_on` for the join — `fan_out_group` sibling query instead (§3).

## Verdict
Critic: **sound-with-fixes** — the fixes are folded above. Frappe's single-token constraint is handled by keeping branch state in Friday's Tasks (not the workflow field); the join is structurally single-owner, so it is race-safe; Phase 1 is untouched. **This is the next real architecture once signed off.**
