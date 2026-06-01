# Doc 50 — C1 Fix Design Lock: Agent Task Execution Route

**Status:** Design lock — decisions are final for Roo Code to implement against
**Fixes:** Finding **C1** (and folds in **M4**, **M5**; depends on **M3**) from
[doc 49 — foundations deviation audit](49-foundations-deviation-audit.md)
**Audited base:** `main` @ `0f2cdd9`
**Date:** 2026-05-30
**Author role:** architect (this doc). Implementation by Roo Code. Do **not**
deviate from a locked decision; if a decision blocks you, stop and flag it.

---

## 0. Why this doc exists

[Doc 49 finding C1](49-foundations-deviation-audit.md) found the async Agent Task
route is **dead**: the dispatcher announces an assignment with
`frappe.publish_realtime("agent_task.assigned", ...)`, but that is a *browser push*,
not a server job queue — so nothing executes the task. PR #35 stopped the resulting
`bench migrate` crash by turning the subscriber into a no-op, which left the route
permanently dormant.

This doc locks **every decision** needed to make the route work, so the
implementation has no gaps to fill with guesses. Each section is a question (`Q`),
a **Decision**, the **Why**, and (where relevant) the **Hermes** comparison required
by our porting discipline.

**Read [doc 49 §C1](49-foundations-deviation-audit.md) first** for the plain-English
problem statement. This doc assumes it.

---

## 1. The shape of the fix in one paragraph

The cron dispatcher (`tasks.dispatcher.tick`, already wired to run every 60s) stays
the single source of task assignment. When it assigns a task, instead of
`publish_realtime`, it **enqueues a Frappe RQ job** (`frappe.enqueue`, exactly like
the gateway's `run_pipeline_for_row`). The job loads the task, takes a per-task lock,
checks idempotency, and executes each required skill **through the shared
`agent_runner.dispatcher.dispatch`** — the same chokepoint the chat path uses — so the
task route inherits permission checks and immutable Execution / Permission Decision
logs for free. The duplicate emit in the workflow hook and the no-op
`register_task_runner` are deleted.

---

## 2. Hermes comparison (porting discipline)

| Aspect | Hermes | Friday (this design) | Why we diverge |
|--------|--------|----------------------|----------------|
| Background work | In-process `threading.Thread` tracked in `_background_tasks` dict (`cli.py:3269-3271`); in-memory `_enqueue(QueueEvent)` stream (`mcp_serve.py:312-321`) | Durable **Agent Task** DocType rows, cron-claimed, executed by **Frappe RQ** workers | Friday tasks must survive process restart, be claimed exactly once across multiple workers, and leave an immutable audit trail. Hermes's threads are ephemeral and single-process. |
| Trigger | Direct in-process call / thread spawn | `frappe.enqueue` after DB commit | Frappe gives us RQ + cron for free; we use the platform's native async primitive. |
| Precedent we mirror | — | Friday's **own** gateway async path: `gateway.service.run_pipeline_for_row` (`gateway/service.py:112`) | Consistency within Friday beats inventing a second async idiom. We are [unified-gateway / one-idiom](49-foundations-deviation-audit.md) by preference. |

**Conclusion:** this is a *justified divergence* from Hermes, faithful to Frappe and
to Friday's existing gateway pattern.

---

## 3. Locked decisions

### Q1 — What replaces the dead `frappe.realtime.on` subscription?

**Decision.** Frappe RQ via `frappe.enqueue`. Not `publish_realtime` (browser-only),
not a `doc_events` `on_update` handler (would run inside the save transaction and
couple execution to every field save), not a new poller (the dispatcher cron already
polls).

**Why.** `frappe.enqueue` is the server-side async primitive; the gateway already uses
it. The #35 docstring (`tasks/runner.py:62-72`) listed three options — this picks the
RQ-from-dispatcher one, which is the least coupled and reuses the existing cron.

---

### Q2 — Who enqueues, and where exactly?

**Decision.** The cron dispatcher. In `tasks/dispatcher.py::_claim_and_dispatch`,
**replace** the `frappe.publish_realtime(...)` block (currently `dispatcher.py:107-116`)
with:

```python
frappe.enqueue(
    "frappe.friday_core.tasks.runner.run_assigned_task",
    queue="long",
    timeout=1800,
    enqueue_after_commit=True,
    task_name=task_doc.name,
    profile_name=chosen_profile,
)
```

**Why.** The dispatcher is the only component that claims (`FOR UPDATE SKIP LOCKED`)
and assigns. It is the natural and single place to trigger execution.
`enqueue_after_commit=True` mirrors the old `publish_realtime(after_commit=True)` intent
— the job must not start until the assignment row is committed, or the worker would
load a stale/uncommitted task.

---

### Q3 — The dispatcher must also set `workflow_state = "Assigned"`

**Decision.** In `_claim_and_dispatch`, set **both** `assigned_to_profile` *and*
`workflow_state = "Assigned"` before saving. Today it sets only `assigned_to_profile`
(the docstring claims it transitions to Assigned, but the code does not).

**Why.** The idempotency guard (Q6) keys off `workflow_state`. The state machine must
be truthful: a claimed task is "Assigned," not still "Pending." Saving with
`workflow_state="Assigned"` also lets the existing workflow hook record correct
timestamps.

---

### Q4 — Delete the duplicate emit in the workflow hook

**Decision.** Remove `tasks/workflow.py::_emit_assigned_event` (lines 118-140) **and**
its call site in `_watch_transition` (lines 92-95). The workflow hook keeps only its
derived-field, timestamp, cancellation, and War Room duties.

**Why.** Two emit sites = two job enqueues = double execution risk. The dispatcher (Q2)
owns dispatch. Leaving a second trigger in the doc-event would re-introduce the very
kind of hidden coupling that caused C1.

---

### Q5 — The RQ job entrypoint

**Decision.** Rename `on_agent_task_assigned(message: dict)` to
`run_assigned_task(task_name: str, profile_name: str)` — direct kwargs, no pub/sub
message dict (we control the enqueue args now). Keep its existing OOM / timeout / error
handling and War Room posts. Its body becomes:

```python
def run_assigned_task(task_name: str, profile_name: str) -> None:
    if not task_name or not profile_name:
        _logger.error("run_assigned_task called with missing args: %r %r", task_name, profile_name)
        return
    # idempotency + lock: see Q6
    ...
    try:
        _run_task(task_name, profile_name)
    except SandboxOutOfMemory: ...
    except SandboxTimeout: ...
    except Exception: ...
```

**Why.** Mirrors the gateway's `run_pipeline_for_row(row_name)` shape: a thin RQ
entrypoint that loads by name. The message-dict indirection only existed to fit the
(fictional) pub/sub contract; with `enqueue` we pass typed kwargs directly.

---

### Q6 — Idempotency and concurrency (mirror the gateway)

**Decision.** At the top of `run_assigned_task`, before `_run_task`:

1. **Per-task Redis lock** — mirror `gateway/service.py:165`:
   ```python
   lock = frappe.cache().lock(f"friday:task:{task_name}", timeout=1800, blocking_timeout=0)
   if not lock.acquire(blocking=False):
       _logger.info("Task %s already running on another worker — skipping", task_name)
       return
   ```
2. **State guard** — reload the task; if `workflow_state` not in `{"Pending", "Assigned"}`,
   it has already started or finished: log and return (idempotent skip). This mirrors the
   gateway's `if doc.processed: return`.
3. Release the lock in a `finally`.

**Why.** RQ can deliver a job more than once (retries, double-enqueue). The dispatcher's
`FOR UPDATE SKIP LOCKED` only guards the *claim*, not the *execution*. Without this, a
re-delivered job would run the same task twice. The gateway already solved this exact
problem for chat turns; we copy it.

---

### Q7 — Execute skills **through the shared dispatcher** (the central decision)

> **This is the decision most worth the architect's review.** It changes the task path
> from "call the sandbox directly" to "go through the same chokepoint as chat."

**Decision.** `tasks/runner.py::_execute_skill_in_sandbox` is **deleted**. In
`_run_task`, each required skill is executed via
`agent_runner.dispatcher.dispatch(...)` by synthesizing a tool-call:

```python
from frappe.friday_core.agent_runner.dispatcher import dispatch
...
for skill_name in skills:
    tool_call = {
        "id": f"{task.name}:{skill_name}",
        "name": skill_name,
        "arguments": frappe.as_json(_parse_task_parameters(task, skill_name)),
    }
    result = dispatch(
        tool_call=tool_call,
        agent_profile=profile_name,
        session_id=task.name,   # the task is the "session" for audit linkage
        tokens_used=None,
    )
    if not result.success:
        _block_task(task, ...)   # adapt _block_task to DispatchResult, see Q8
        return
```

**Why.**
- **Permission enforcement.** Today the task path calls `sandbox.execute()` directly and
  **never calls `permissions.matrix.check`** — so task skills run with *zero* permission
  enforcement and write *no* Permission Decision Log. That is a latent security hole, not
  just a dead route. Routing through `dispatch` closes it: every task skill is now checked
  deny-by-default and logged immutably, identical to chat.
- **One audit trail.** `dispatch` writes the Execution Log row (with the sandbox result),
  so tasks and chat share one audit schema.
- **Kills M4.** The direct `sandbox.execute(..., api_key=token)` call (a latent `TypeError`
  — `execute()` has no `api_key` parameter) disappears entirely.
- **One sandbox path.** `dispatch` already calls `_execute_sandboxed`, so tasks inherit the
  C2 sandbox-or-fallback behavior (and any future strict mode) with no duplicate logic.

**Dependency — M3 must land with this.** `dispatch` resolves handlers from the chat path's
`_SKILL_HANDLERS`, which today registers the test name `"slice6-create-note"`
(`agent_runner/dispatcher.py:449`) instead of `"create_note"`. Before/with this change,
**M3** must converge on `"create_note"` and a single registry, or `dispatch` will report
"unknown skill." Track M3 as a prerequisite sub-task of this slice.

---

### Q8 — Adapt `_run_task` result handling to `DispatchResult`

**Decision.** Since skills now return `DispatchResult` (not `SandboxResult`),
`_build_result_envelope` and `_block_task` change to read `DispatchResult` fields
(`success`, `content`, `execution_log_name`). The task `result` JSON stores, per skill:
`{"skill", "success", "content", "execution_log_name"}`. State transitions are unchanged:
all-success → `Review`; any failure → `Blocked`.

**Why.** Keep the envelope but source it from the unified dispatch result. Linking each
skill to its `execution_log_name` ties the task record to the immutable audit rows.

---

### Q9 — Fix M5 (dead `agent_role_profile` read) in the same change

**Decision.** In `tasks/dispatcher.py::_load_permitted_skills`, delete the
`if not skills and profile.agent_role_profile:` branch (lines 175-187). Keep only the
`permitted_skills` table read.

**Why.** `agent_role_profile` is not a field on Agent Profile (`agent_profile.json` has no
such field), so the branch raises `AttributeError` for any profile with an empty
`permitted_skills`. Per [doc 49 §3](49-foundations-deviation-audit.md), Agent Role Profile
is intentionally not built (we use native Frappe roles). This is a leftover from the stale
doc-05 assumption. It's in the file we're already editing, so fix it here.

---

### Q10 — Delete the no-op runner registration (L2)

**Decision.** Delete `tasks/runner.py::register_task_runner` (the `pass` stub) **and** its
`after_migrate` entry in `hooks.py` (`hooks.py:344`).

**Why.** Once enqueue is wired (Q2), the stub and its migrate hook are pure dead wiring.
Removing them prevents a future reader from thinking a subscription exists.

---

### Q11 — Keep War Room posts; keep the cron schedule

**Decision.** No change to the `_post_warroom` calls in `_run_task` (executing / completed /
blocked) or to `scheduler_events["cron"]` for `dispatcher.tick` (`hooks.py:264`).

**Why.** Both already degrade gracefully and are unaffected by the trigger change.

---

## 4. Tests — close the gap that *caused* C1

C1 shipped because tests asserted *"the event was published,"* not *"the task executed."*
The new tests **must assert execution and enforcement**, not emission.

**Required new/changed tests:**

1. **End-to-end execution** (`tests/test_task_runner.py`, new or rewritten): create a
   `Pending` Agent Task with one `create_note` skill and a profile permitted for it; run
   `dispatcher.tick()` with `frappe.enqueue` patched to call the job **inline**. Assert:
   - task ends in `Review`;
   - a **Note** row was created;
   - an **Execution Log** row exists with `status="success"`;
   - a **Permission Decision Log** row exists (proves enforcement now runs);
   - `assigned_to_profile` and `workflow_state` transitions are correct.
2. **Permission denial path**: profile *not* permitted for the skill → task ends `Blocked`,
   Execution Log `status="rejected"`, Permission Decision Log `allowed=0`. (Impossible to
   test before this fix, because the task path never checked permissions.)
3. **Idempotency**: invoke `run_assigned_task` twice for the same task → second call is a
   no-op (lock or state guard); exactly one Execution Log row.
4. **No eligible profile**: task with an unmatchable skill stays `Pending`, no exception
   (also covers Q9 / M5 — a profile with empty `permitted_skills` must not crash matching).
5. **Delete** the assertions that the now-removed `publish_realtime` fires
   (`tests/test_task_dispatcher.py:129`, `tests/test_task_workflow.py:162`). Replace with
   "asserts `frappe.enqueue` called once with the expected kwargs."

**Verify clause for the whole slice:** `bench run-tests --module ...tasks` green; a manually
created Agent Task reaches `Review` and produces a Note + Execution Log + Permission Decision
Log; `grep -rn "publish_realtime(\"agent_task" friday_core` returns zero; `grep -rn
"agent_role_profile" friday_core/tasks` returns zero.

---

## 5. Files Roo Code will touch

| File | Change |
|------|--------|
| `tasks/dispatcher.py` | Q2 (enqueue), Q3 (set Assigned), Q9 (delete agent_role_profile branch) |
| `tasks/workflow.py` | Q4 (delete `_emit_assigned_event` + call site) |
| `tasks/runner.py` | Q5 (rename entrypoint), Q6 (lock + idempotency), Q7 (route via `dispatch`), Q8 (DispatchResult), Q10 (delete `register_task_runner`) |
| `agent_runner/dispatcher.py` | **M3 prerequisite** — register handler as `"create_note"`, converge registry |
| `hooks.py` | Q10 (remove `after_migrate` register entry) |
| `tests/test_task_runner.py`, `tests/test_task_dispatcher.py`, `tests/test_task_workflow.py` | §4 |

**Explicitly out of scope** (do not touch in this slice): C2 sandbox strict mode, H1 ReAct
loop, H2 approvals, H3 credential token. Routing through `dispatch` (Q7) means tasks
*inherit* C2's current behavior — that's intended; the strict-mode fix is a separate slice.

---

## 6. The one decision to confirm before coding — **CONFIRMED**

**Q7 (route through the shared dispatcher) is the load-bearing choice.** It is the
foundation-correct fix — it gives tasks real permission enforcement and a unified audit
trail, it dissolves **M4** (the latent `api_key` kwarg `TypeError`) and **M5**, and it
depends on **M3** landing first (converge the handler to `"create_note"` + a single
registry). The cheaper alternative (keep the direct `sandbox.execute` call, just fix the
`api_key` kwarg and add enqueue) would turn the route on but leave task skills *unenforced
and unlogged* — re-creating a quieter version of the drift we're fixing.

**Decision (architect-confirmed 2026-05-30): Q7 = route through `dispatch`.** This is final
for the C1 slice. Roo Code implements Q7/Q8 as written and treats **M3 as a hard prerequisite
sub-task** of this slice (do M3 first, or in the same change). Do not fall back to the
minimal enqueue-only variant.
