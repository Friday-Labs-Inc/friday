# Release the executing_token on every non-Executing state — 2026-06-14

## One sentence

A task that was reset from Blocked back to Pending for retry could sit forever
un-dispatched, because the reset cleared the state but left the runner's stale
claim token behind — this makes releasing that token an automatic, derived
invariant so no reset path can strand a task again.

## What was wrong

`executing_token` is the runner's **claim** on a task row. It's stamped when a
task goes Assigned → Executing (an atomic raw-SQL update), and the dispatcher
will only claim a Pending row whose token is empty:
`... AND COALESCE(executing_token, '') = ''`.

The trap: when a task is moved back to Pending for a retry, the state changes
but the token has to be cleared **separately**. If any caller forgets, the row
is Pending but the dispatcher's claim guard skips it — the task is stranded.

Observed live: task `478ircteq9` (FLI-001 `gate1_prep`) blocked on a transient
LLM timeout, was reset to Pending, and then sat `dispatchable=0`,
`executing_token='f0173bca820f90cc'` for 20+ minutes, never re-dispatched —
while healthy waiting tasks had `dispatchable=1, executing_token=NULL`.

## Why it happened

`dispatchable` is already a **derived** field: the Task `on_update` hook
(`tasks/workflow.py`) recomputes it from `workflow_state` every save. But
`executing_token` was **not** derived — every reset path had to remember to
clear it by hand. The reconciler's auto-retry path does remember
(`task.executing_token = None`), but:

- a manual/operator reset via `db.set_value` bypasses the hook entirely, and
- the failure→Blocked path never set `blocked_reason`, so the reconciler's
  auto-retry never even ran (separate issue, tracked elsewhere) — leaving manual
  resets as the only recovery, which then hit this trap.

## The fix

Make `executing_token` a **derived invariant** in the same hook that derives
`dispatchable`: **the token is valid only while the task is Executing; release
it on every other state.**

```python
release_token = doc.workflow_state != "Executing"
if release_token:
    doc.executing_token = None
# ... persisted in the same db_set that writes dispatchable ...
```

Two deliberate properties:

1. **Only ever cleared, and only when not Executing.** While Executing, the hook
   does not touch the token — the runner's atomic raw-SQL claim owns it, and
   writing a stale in-memory value would clobber a live claim.
2. **One enforcement point.** The failure→Blocked path, the reconciler
   reset→Pending path, and any future or manual reset that goes through
   `doc.save()` now all release the token automatically. No caller has to
   remember. (A reset done via raw `db.set_value` still bypasses the hook — that
   remains an anti-pattern; the supported path is a document save.)

## Verification

- New tests in `test_task_workflow.py`: every non-Executing state releases the
  token; Executing **preserves** it (no clobber); and the reported
  retry-reset case (Blocked→Pending) ends up `executing_token=NULL` **and**
  `dispatchable=1`. 18 tests green.
- No regressions: `test_task_dispatcher` (15), `test_task_reconciler` (12),
  `test_dispatcher` (17) all green.
- `bench migrate` clean.
- **Adversarial review (independent):** verdict SAFE TO SHIP — confirmed the
  runner loads the doc post-claim with state=Executing (token preserved), the
  heartbeat uses `db.set_value` (bypasses the hook), and no audit consumer reads
  the token on terminal states. (Noted the reconciler's now-dead
  `executing_token IS NULL` guard as a follow-up cleanup.)

## Related (found in the same investigation, fixed separately)

- The failure→Blocked path doesn't set `blocked_reason`, so a transient
  `LLMError` (e.g. the ReadTimeout that blocked `gate1_prep`) is never
  auto-retried by the reconciler — it needs `blocked_reason='timeout'`.
- `warroom/publisher.py` calls `raven.api.send_message`, which doesn't exist in
  Raven 2.8.12 (the function is `raven.api.raven_message.send_message`) — every
  War Room post throws.
