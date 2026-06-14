# War Room: post via Raven's in-process send_message — 2026-06-14

## One sentence

Every War Room post silently failed — the publisher called a Raven API method
that doesn't exist, over HTTP with a session cookie a background worker doesn't
have — so the `FRIDAY_WAR_ROOM` channel never showed any task activity; this
posts in-process via the real function instead.

## What was wrong

`warroom/publisher.py._post_to_raven` posted task updates to Raven with:

```python
endpoint = frappe.utils.get_url() + "/api/method/raven.api.send_message"
requests.post(endpoint, json={...}, headers={"Cookie": f"sid={frappe.session.sid}"})
```

Two independent breakages:

1. **Wrong method.** `raven.api.send_message` does not exist in Raven 2.x. The
   `raven/api/` directory has no `__init__.py`, so it's a namespace package with
   no `send_message` symbol at that level. Frappe's RPC dispatcher raised
   *"module 'raven.api' has no attribute 'send_message'"* on every call — seen
   as 7 Error-Log entries during a single agentic run. The function actually
   lives at `raven.api.raven_message.send_message`.
2. **No session in a worker.** The post fires from the task-transition hook,
   which runs in a background worker / scheduled job — there is no HTTP session,
   so `frappe.session.sid` is empty and the call would 403 even with the right
   path.

`requests.post` doesn't raise on a 4xx/5xx, and `post_task_update` swallows
errors by design, so the failures were **silent**: the channel simply stayed
empty while the rest of the pipeline ran fine.

## The fix

Drop the HTTP round-trip entirely and call the real function in-process:

```python
from raven.api.raven_message import send_message

send_message(channel_id=channel_id, text=payload["text"])
```

- **Correct function**, `channel_id` + `text` only. `send_message` sets
  `message_type="Text"` internally, so the old `message_type` /
  `hide_in_message_history` keys (which aren't in its signature) are dropped.
- **In-process** — no endpoint, no session cookie, no network. It inserts a
  `Raven Message` in the **current transaction** (it does no commit of its own),
  so a War Room post inside a task save commits/rolls back atomically with the
  task. Raven's own Message hooks fire the realtime push, so the channel updates
  live.
- Graceful degradation is unchanged: `_is_raven_installed()` short-circuits when
  Raven is absent, and `post_task_update` still logs-and-degrades on any error.

This lights up the War Room for **all** task transitions (the publisher is
already wired into the `on_state_change` hook), plus the surface-level
`_warroom` posts.

## Verification

- New `TestPostToRavenInProcess`: asserts `_post_to_raven` calls
  `raven.api.raven_message.send_message(channel_id=…, text=…)` with exactly the
  two real params, and a regression guard that the body no longer does
  `requests.post`. `test_warroom` 17 green.
- `bench migrate` clean.
- Live proof on the bench: an in-process `send_message` to the War Room channel
  inserted a `Raven Message` (channel count 4 → 5), confirming the post path
  works end to end.

## Note

The previous HTTP-with-cookie pattern is an anti-pattern for any
backend→whitelisted-method call inside Frappe — there's no session in a worker.
Other surfaces that call Raven (or any Frappe RPC) the same way should be
audited for the same trap.
