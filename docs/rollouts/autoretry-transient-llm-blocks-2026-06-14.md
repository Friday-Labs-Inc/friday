# Auto-retry transient LLM failures — 2026-06-14

## One sentence

When an agentic task failed on a transient LLM error (a provider timeout, a 5xx,
a rate-limit), it was parked in Blocked **forever** — the runner never recorded
*why*, so the reconciler's auto-retry sweep couldn't see it — this records the
classified reason so the loop self-heals.

## What was wrong

The FLI-001 `gate1_prep` task hit a transient Minimax **ReadTimeout** (its 2nd
ReAct call timed out, 3 retries exhausted). The runner correctly blocked it
(fail-loud), but its failure path wrote only:

```python
task.result = frappe.as_json({"status": "error", "error_type": "LLMError"})
task.workflow_state = "Blocked"
```

It never set `blocked_reason`. The reconciler's auto-retry sweep only re-Pends
tasks whose `blocked_reason` is in a transient set
(`oom`/`timeout`/`runner_lost`). With `blocked_reason = NULL`, the task was
**invisible** to it — a genuinely transient blip needed a human to notice and
manually retry.

Two deeper gaps under that:

- **The classifier's verdict was computed then discarded.** `provider.py`'s
  transport loop classifies every failure (`FailoverReason` + `retryable`) to
  drive its own backoff — but when it gave up it raised a bare
  `LLMError(message)`, throwing the structured reason away. The runner had
  nothing machine-readable to act on.
- **The reconciler hardcoded its reason list** in SQL, so the
  `TRANSIENT_BLOCKED_REASONS` constant (used by the health page) and the
  reconciler's actual filter could silently drift apart.

## The fix

End-to-end, the classified reason now flows from the provider to the reconciler:

1. **`provider.py`** — `LLMError` carries `reason` (the `FailoverReason` value,
   e.g. `"timeout"`, `"rate_limit"`, `"auth"`) and `retryable`. Both raise paths
   build it via a small `_classified_llm_error(message, classified)` helper.
   Class-level defaults keep LLMErrors raised elsewhere safe to read.
2. **`runner.py`** — the agentic failure path records
   `task.blocked_reason = getattr(exc, "reason", None)`. A non-LLM crash (a real
   bug) has no reason → stays Blocked for a human, never auto-retried.
3. **`reconciler.py`** — `TRANSIENT_BLOCKED_REASONS` gains the retryable
   transport reasons (`rate_limit`, `overloaded`, `server_error`; `timeout` was
   already there), and the retry SQL now reads the IN-list from that **one
   constant** (a SQL param) instead of a hardcoded literal, so it can't drift.
   Non-retryable reasons (`auth`, `billing`, `model_not_found`, `format_error`,
   `context_overflow`) are deliberately excluded — retrying them just spams.

The grace + `RETRY_BUDGET = 3` cap still bounds it: a persistently-failing task
gets a few shots, then stays Blocked for a human.

With this in place, `gate1_prep`'s ReadTimeout would have set
`blocked_reason = "timeout"` and **auto-retried within a tick** — no manual
unblock, no stranding.

## Verification

- `test_llm_provider` (+2): a 500 raises an `LLMError` with `reason="server_error",
  retryable=True`; a 400 with `reason="format_error", retryable=False`. 34 green.
- `test_task_failure_issue` (+2): a retryable `LLMError` sets
  `blocked_reason="timeout"`; a plain `RuntimeError` leaves it `None`.
- `test_task_reconciler`: the retry SQL param now includes the transport reasons.
- `bench migrate` clean.

## Note

Pairs with the executing-token reset fix (PR #111): together they close the
"transient failure → recover" loop — the reconciler now both *sees* the task
(this PR) and *cleanly re-dispatches* it (the token fix).
