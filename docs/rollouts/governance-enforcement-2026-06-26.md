# Governance enforcement hardening (2026-06-26)

> First batch of the framework-robustness campaign. A parallel scout of Friday's core
> pillars surfaced real enforcement gaps; this closes the four verified, highest-impact
> ones in the governance pillar — Friday's headline. (One scout "CRITICAL", a broken
> `except` clause, was verified a FALSE POSITIVE via the AST and dropped.)

## What was wrong, and what now holds

### 1. Privilege escalation — an agent could create cron jobs owned by any profile
`skills/handlers_cron.py` built a new Cron Job with
`"agent_profile": (p.get("agent_profile") or agent_profile)`. The `p.get(...)` is
**LLM-supplied parameters** — so a prompt-injected or buggy agent could set
`agent_profile` to a higher-privileged profile and schedule recurring work running with
*that* profile's authority. This also violated the skill's own documented "Own jobs
only" boundary.
**Fix:** the owner now comes **only** from the unspoofable dispatch context. The model's
parameters can never set it.

### 2. The approval gate could double-execute a high-risk action
`approvals/workflow.py::approve()` read the request, checked `status == "Pending"`, then
called `dispatch()` (which runs the gated skill), and **only then** flipped the status.
Two concurrent `/approve` calls both passed the check and both dispatched — the gated
action (send, delete, …) ran **twice**.
**Fix:** the `Pending → Approved` transition is now an **atomic single-winner claim** (a
conditional `UPDATE … WHERE status='Pending'` + affected-row check, mirroring the task
dispatcher's `_claim_task`), done **before** dispatch. A loser raises and never executes.
`reject()` claims `Pending → Rejected` the same way, so a `/deny` racing an `/approve`
can't both win.

### 3. The gate trigger was unaudited
When a high-risk action paused for approval, only a (mutable, deletable) Workflow Request
was created — no immutable record that the agent *attempted* the action.
**Fix:** the gate now writes a **submitted (immutable) `pending_approval` Execution Log**
row at trigger time, linked to the Workflow Request. The later approval still writes its
own `success` row for the actual execution. (Adds one `Select` option to the Execution
Log `status` field — a metadata-only doctype change; `bench migrate` runs clean.)

### 4. `/approve <id>` could approve another channel's request
`gateway/commands.py::_resolve_pending_request` honored an explicit request id outright,
without checking it belonged to the channel the command came from. An operator in channel
A could `/approve <id>` a pending action from channel B (different agent / project / trust
domain) by knowing or guessing the sequential request name.
**Fix:** an explicit id is honored **only** if that request belongs to *this* channel and
is still Pending; otherwise it's treated as "nothing to approve here."

## Deliberately deferred (not in this batch)
Adding `frappe.only_for(...)` *inside* `approve()`/`reject()` (defense-in-depth for a
hypothetical future direct caller). The chat-command path is already role-gated, and an
in-function guard checks `frappe.session.user`, which doesn't match the command path's
`user`-based authorization — so it risks a regression. Worth doing later with the right
auth-context model.

## Tests
Regression tests added/updated in `test_approval.py`, `test_cron_skill.py`,
`test_gateway_commands.py`: the cron owner can't be set from params; a lost approval
claim does **not** dispatch (no double-execute); a missing request raises; reject claims
atomically; the gate trigger writes an immutable `pending_approval` log; an explicit
cross-channel `/approve` is refused. All three suites green (35 tests). `bench migrate`
clean. (`test_dispatcher.py` is a pre-existing bench-only suite — unaffected.)
