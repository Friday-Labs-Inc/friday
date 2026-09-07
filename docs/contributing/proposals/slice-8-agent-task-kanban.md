# Proposal: Slice 8 — Agent Task + Dispatcher + Native Kanban

## Status

- **Author:** `fridaylabs`
- **Sponsor:** `iamfriday86`
- **Created At:** 2026-05-28
- **Status:** Draft
- **Audit required before merge:** Security review of atomic task claim, workflow state transitions, and Kanban permission wiring.

---

## 1. Problem & Context

Slice 7 shipped Docker-isolated skill execution — the `create_note` skill now runs inside an ephemeral container with scoped credentials, resource caps, and network allowlisting. Execution is still **synchronous and chat-driven**: a user types a message → the LLM analyzes → emits a tool call → the dispatcher executes → the result is returned in the chat stream.

Slice 8 introduces the **asynchronous task queue**: tasks are created manually in the Framework Console, claimed by a scheduled dispatcher, and executed by an agent without blocking any user's chat session. This is the foundation for the Kanban view, task persistence across restarts, the multi-step ReAct loop, and eventually A2A / inter-agent task handoff.

Three concrete gaps are addressed:

1. **No task lifecycle beyond the chat session.** Chat-driven skills die when the session closes. Agent Tasks survive — they track state across dispatcher cycles, agent restarts, and manual interventions.
2. **No CLI-to-dispatcher separation.** The CLI currently routes through the chat gateway (synchronous). Tasks created in the console have no route to an agent. The dispatcher bridges this gap.
3. **No native Frappe Kanban view for tasks.** Agents managed in spreadsheets or custom tables. The `Agent Task` DocType Kanban view makes task state visible and transitionable without a custom UI.

**Reference architecture:** [`docs/design/10-agent-execution-guide.md`](docs/design/10-agent-execution-guide.md) §Slice 8, [`05-module-design.md`](docs/design/05-module-design.md) §Phase 1 DocTypes (`Agent Task`), [`docs/design/14-integrated-architecture.md`](docs/design/14-integrated-architecture.md) for request flow and runtime architecture.

---

## 2. Proposed Changes & Architecture

### 2.1 Frappe Workflow on `Agent Task`

The state machine for an `Agent Task` DocType row:

```
Pending → Assigned → Executing → Blocked → Review → Completed
                                                          ↓
                                                      Cancelled
```

Transitions are role-gated. The `dispatchable` field is a **derived checkbox** — it is True only when the current `workflow_state` is in the dispatchable set (below). It is never manually edited; `friday.tasks.workflow.on_state_change` recomputes it on every row update.

| From | To | Roles permitted | dispatchable |
|------|----|-----------------|-------------|
| Pending | Assigned | Agent Supervisor | yes |
| Assigned | Executing | Agent Supervisor, assigned Profile | yes |
| Assigned | Cancelled | Agent Supervisor | no |
| Executing | Blocked | assigned Profile | no |
| Executing | Review | assigned Profile | no |
| Blocked | Executing | assigned Profile | no |
| Review | Completed | Agent Supervisor | no |
| Review | Blocked | assigned Profile | no |
| Review | Cancelled | Agent Supervisor | no |

The `dispatchable` set = `{Pending, Assigned}`. The dispatcher will only claim tasks where `dispatchable=1` AND `assigned_to_profile IS NULL`.

**Blocked** and **Review** are not dispatchable — the agent must complete the task or a human must intervene before the task can be re-claimed or closed.

### 2.2 Workflow Hook (`friday/tasks/workflow.py`)

Lives in the new `friday/tasks/` module. registered as the `on_update` hook on `Agent Task` in `hooks.py`:

```python
doc_events = {
    "Agent Task": {
        "on_update": "friday.tasks.workflow.on_state_change",
    },
}
```

**`on_state_change` responsibilities:**

1. Derive `dispatchable` from current `workflow_state`.
2. Set `started_at` when transitioning `Assigned → Executing`.
3. Set `completed_at` when transitioning into `Completed` or `Cancelled`.
4. Clear `assigned_to_profile` when transitioning `Assigned → Cancelled`.
5. Emit `agent_task.assigned` on Redis pub/sub when transitioning `Pending → Assigned` (the runner picks this up outside the save transaction to avoid holding a DB lock).

```python
# friday/tasks/workflow.py

DISPATCHABLE_STATES = {"Pending", "Assigned"}

def on_state_change(doc: "Agent Task", method: str) -> None:
    """Recompute dispatchable; record timestamps; emit Redis event."""

    # 1. dispatchable is a derived field — never trust a stale value
    doc.dispatchable = doc.workflow_state in DISPATCHABLE_STATES

    # 2. started_at
    if doc.has_value_changed("workflow_state"):
        if doc.workflow_state == "Executing" and doc.started_at is None:
            doc.started_at = frappe.utils.now_datetime()

        if doc.workflow_state in ("Completed", "Cancelled") and doc.completed_at is None:
            doc.completed_at = frappe.utils.now_datetime()

        # 3. Redis pub/sub — outside the save transaction
        if doc.workflow_state == "Assigned" and doc.has_value_changed("assigned_to_profile"):
            _emit_assigned_event(doc.name, doc.assigned_to_profile)

    doc.save(ignore_permissions=True)
```

### 2.3 New `friday/tasks/` Module

Created as part of Slice 8 to own all task-lifecycle code:

```
friday/friday_core/tasks/
├── __init__.py
├── workflow.py        # on_state_change hook
├── dispatcher.py      # Scheduled task claim + dispatch
└── runner.py          # Task-execution runner (picks up assigned tasks via Redis)
```

The `agent_task_assigned` Redis pub/sub message format:

```json
{
  "task_name": "AT-000042",
  "assigned_to_profile": "note_taker",
  "workflow_state": "Assigned"
}
```

The runner subscribes to this channel and processes task execution asynchronously.

### 2.4 Task Dispatcher (`friday/tasks/dispatcher.py`)

Registered in `hooks.py` as a cron scheduler event, firing every 60 seconds:

```python
scheduler_events = {
    "cron": {
        "*/1 * * * *": ["friday.tasks.dispatcher.tick"],
    },
}
```

**`tick()` — one dispatcher cycle:**

```python
def tick() -> None:
    """Called every 60s. Claims and dispatches one or more dispatchable tasks."""

    # Find tasks that are dispatchable and unclaimed.
    # Use SELECT ... FOR UPDATE SKIP LOCKED to avoid double-claim
    # when two dispatcher instances run concurrently.
    tasks = _fetch_dispatchable_tasks(limit=5)

    for task_doc in tasks:
        _claim_andDispatch(task_doc)
```

**Atomic claim query (`_fetch_dispatchable_tasks`):**

```sql
SELECT name, assigned_to_profile, required_skills
FROM `tabAgent Task`
WHERE dispatchable = 1
  AND assigned_to_profile IS NULL
  AND workflow_state = 'Pending'
ORDER BY
  priority = 'urgent'   DESC,
  priority = 'high'     DESC,
  priority = 'normal'   DESC,
  priority = 'low'      DESC,
  creation              ASC
LIMIT 5
FOR UPDATE SKIP LOCKED
```

The `ORDER BY` priority trick (sorting boolean DESC) achieves strict priority ordering without a CASE expression. `FOR UPDATE SKIP LOCKED` ensures that if two dispatcher workers fire simultaneously, neither waits — the second worker simply skips already-locked rows.

**`_claim_and_dispatch`:**

```python
def _claim_and_dispatch(task_doc: "Agent Task") -> None:
    """Atomically assign the task to the best-fit profile, transition state,
    emit Redis event, and hand off to the runner."""

    # 1. Match required_skills against eligible Agent Profiles
    eligible = _match_profiles(task_doc)

    if not eligible:
        # No profile can handle this task — leave it Pending; log it.
        frappe.logger("friday.tasks.dispatcher").warning(
            "No eligible profile for task %s (required_skills=%s)",
            task_doc.name,
            [r.skill for r in task_doc.required_skills],
        )
        return

    # 2. Pick the first eligible profile (round-robin by creation is fine for Phase 1;
    #    Phase 2 can add load-balancing by tokens-per-hour or current load)
    chosen_profile = eligible[0]

    # 3. Assign and transition
    task_doc.assigned_to_profile = chosen_profile
    task_doc.transition("Assigned")          # Frappe Workflow action
    task_doc.save(ignore_permissions=True)

    # 4. Emit Redis event — consumed by runner.py OUTSIDE this transaction
    frappe.publish_realtime(
        event="agent_task.assigned",
        message={
            "task_name": task_doc.name,
            "assigned_to_profile": chosen_profile,
        },
    )
```

### 2.5 Profile Matching (`_match_profiles`)

```python
def _match_profiles(task_doc: "Agent Task") -> list[str]:
    """Return the names of Agent Profiles whose permitted_skills cover
    every skill in task_doc.required_skills.

    Phase 1 matching is exact: a profile must explicitly list the skill in
    its `permitted_skills` table (or inherit it from its Agent Role Profile).
    Phase 1.5 will add embedding-similarity fallback.
    """

    required_skill_names = {r.skill for r in task_doc.required_skills}
    if not required_skill_names:
        # No required skills → any Active profile can take it
        return [p.name for p in _active_profiles()]

    matched_profiles = []
    for profile in _active_profiles():
        permitted = _load_permitted_skills(profile.name)
        if required_skill_names.issubset(permitted):
            matched_profiles.append(profile.name)

    return matched_profiles


def _active_profiles() -> list:
    return frappe.get_all(
        "Agent Profile",
        filters={"status": "Active"},
        pluck="name",
    )


def _load_permitted_skills(profile_name: str) -> set[str]:
    """Return the set of skill names the profile can execute.
    Checks profile explicit whitelist then falls back to role profile."""
    profile = frappe.get_doc("Agent Profile", profile_name)

    skills = {row.skill for row in profile.permitted_skills if row.skill}

    if not skills and profile.agent_role_profile:
        role_profile = frappe.get_doc("Agent Role Profile", profile.agent_role_profile)
        skills = {row.skill for row in role_profile.get("assigned_roles", []) if row.skill}

    return skills
```

### 2.6 Task Runner (`friday/tasks/runner.py`)

Consumes the `agent_task.assigned` Redis pub/sub event. This is the async counterpart to the synchronous chat-driven dispatcher in `agent_runner/`:

```python
def on_agent_task_assigned(message: dict) -> None:
    """Called when a task is assigned to a profile.
    Executes the task inside Docker sandbox and transitions the state."""

    task_name = message["task_name"]
    profile_name = message["assigned_to_profile"]

    task = frappe.get_doc("Agent Task", task_name)

    # Transition to Executing
    task.transition("Executing")
    task.save(ignore_permissions=True)

    # Collect required skill + parameters from task
    # (task has required_skills table + description as parameters hint)
    skills = [row.skill for row in task.required_skills]

    # Execute each skill in sequence via the sandbox runner
    results = []
    for skill_name in skills:
        result = _execute_skill_in_sandbox(skill_name, task)
        results.append(result)

        if result.status != "success":
            task.transition("Blocked")
            task.result = frappe.as_json(results)
            task.save(ignore_permissions=True)
            return

    # All skills succeeded
    task.result = frappe.as_json(results)
    task.transition("Review")
    task.save(ignore_permissions=True)


def _execute_skill_in_sandbox(skill_name: str, task: "Agent Task") -> SandboxResult:
    """Execute one skill from the task's required_skills in a Docker sandbox.
    Uses the task-level API token scoped to this task + profile."""

    from friday.friday_core.sandbox.runner import execute as execute_sandbox

    parameters = _parse_task_parameters(task, skill_name)

    return execute_sandbox(
        skill_name=skill_name,
        parameters=parameters,
        agent_profile=task.assigned_to_profile,
        credentials={},        # resolved by sandbox/credentials.py
    )
```

### 2.7 Native Kanban View (no custom UI)

Frappe v16 ships a built-in Kanban board renderer for any DocType that has a `workflow_state` field (Data field type) and a configured Frappe Workflow. No custom frontend code is required.

**Configuration:**

1. **Workflow:** A Frappe Workflow document named `Agent Task Workflow` with the states and transitions defined in §2.1 above.
2. **Kanban board:** Created via Framework Console or `after_migrate` hook:
   ```
   doctype: Agent Task
   column_field: workflow_state
   board_name: "Agent Tasks"
   ```
3. **Field labels on the card:**
   - `title` (primary)
   - `priority` (badge, colour-coded)
   - `assigned_to_profile` (agent avatar)
   - `required_skills` (skill chips)

**Enabling the Kanban view** is a data-only operation (`frappe.get_doc` + `insert` + `add_comment` for board creation is unnecessary — Frappe renders the view dynamically from the workflow definition). The `workflow_state` field already exists on the DocType; no schema changes are required for the view.

### 2.8 CLI / Chat Flow vs. Console Task Flow

These are two distinct execution paths that share the dispatcher infrastructure but differ in entry point and lifecycle:

| | CLI / Chat Flow (Slices 1–7) | Console Task Flow (Slice 8) |
|---|---|---|
| Entry | `friday chat --profile <name>` → writes Chat Message row | `Agent Task` row created manually in Framework Console |
| Gateway | `Chat Message.after_insert` → session_manager → runner → LLM | None |
| Dispatcher | `agent_runner/dispatcher.dispatch()` — synchronous, called in-process | `tasks/dispatcher.tick()` — scheduled cron, atomic claim |
| Skill execution | Inside Docker sandbox (Slice 7) | Inside Docker sandbox (same) |
| Result delivery | Chat Message row (outbound) written by gateway | `Agent Task.result` JSON field written by task runner |
| State machine | None (stateless round-trip) | Full workflow state (Pending→Assigned→...) |
| Persistence | Ephemeral (lasts as long as session) | Persistent (survives restarts) |

Both paths share the same `SandboxResult` → `Execution Log` writing. The task runner writes to Execution Log exactly as the chat dispatcher does.

---

## 3. Files to Create or Modify

### New files

| File | Purpose |
|---|---|
| `friday/friday_core/tasks/__init__.py` | Package marker |
| `friday/friday_core/tasks/workflow.py` | `on_state_change` hook; `DISPATCHABLE_STATES` |
| `friday/friday_core/tasks/dispatcher.py` | `tick()`, `_fetch_dispatchable_tasks()`, `_claim_and_dispatch()`, `_match_profiles()` |
| `friday/friday_core/tasks/runner.py` | `on_agent_task_assigned()` event consumer; task execution loop |
| `friday/friday_core/doctype/agent_task_skill/agent_task_skill.json` | Already exists; verify fields |
| `friday/friday_core/tests/test_task_workflow.py` | Workflow state transitions; dispatchable derivation |
| `friday/friday_core/tests/test_task_dispatcher.py` | Atomic claim; concurrent dispatcher; profile matching |

### Modified files

| File | Change |
|---|---|
| `frappe/frappe/hooks.py` | Add `Agent Task.on_update → friday.tasks.workflow.on_state_change`; Wire `*/1 * * * *` cron to `friday.tasks.dispatcher.tick` |
| `frappe/friday/friday_core/doctype/agent_task/agent_task.json` | Add `workflow_state` field type override (ensure `Data` with workflow-state-like values; the actual states are driven by the Frappe Workflow document, not hardcoded in the DocType schema) |
| `frappe/friday/friday_core/doctype/agent_task/agent_task.json` | Add `dependencies` field (Table → Agent Task Dependency, Phase 1 can be a stub, needed for ordering) |
| `frappe/friday/friday_core/doctype/agent_task/agent_task.json` | Add `current_execution` Link → Execution Log (Point to active Execution Log row during execution) |
| `frappe/friday/friday_core/agent_runner/dispatcher.py` | Add comment clarifying that `dispatch()` handles chat-driven (tool-call) tasks; task-driven dispatch goes through `tasks/dispatcher.tick()` |
| `frappe/friday/friday_core/agent_runner/runner.py` | Subscribe to `agent_task.assigned` realtime event and hand off to task runner when task is claimed for the profile |
| `docs/contributing/proposals/slice-8-agent-task-kanban.md` | This file |

---

## 4. Module Structure (updated)

```
friday/friday_core/
├── agent_runner/          ← chat-drive tool-call dispatch (Slices 1–7)
│   ├── dispatcher.py     ← dispatch() — chat tool calls → skill execution
│   └── runner.py         ← run_turn() — LLM + tool call detection
├── tasks/                 ← task queue + async execution (Slice 8)
│   ├── workflow.py       ← on_state_change hook; dispatchable derivation
│   ├── dispatcher.py     ← tick(); atomic claim; profile matching
│   └── runner.py        ← on_agent_task_assigned() — async task execution
├── gateway/
├── skills/
├── sandbox/
└── permissions/
```

The dispatcher infrastructure is **task-profile agnostic**: the same permission check (`permissions.matrix.check`), sandbox runner (`sandbox.runner.execute`), and execution log writing are used by both the chat-driven path and the task-driven path.

---

## 5. Testing Plan

### Test Cases

| # | Scenario | Expected |
|---|---|---|
| T1 | Create `Agent Task` row in `Pending` state → `dispatchable=1` | Workflow hook sets `dispatchable=True` automatically |
| T2 | Transition task `Pending → Assigned` → `dispatchable=0`, `assigned_to_profile` set | Both conditions hold after transition |
| T3 | Two `dispatcher.tick()` calls concurrent → only one claims each task | `SELECT … FOR UPDATE SKIP LOCKED` prevents double-claim |
| T4 | Task `Pending` with no eligible profiles → left in `Pending`, no exception | Log warning emitted; task stays unclaimed |
| T5 | Task transitions to `Review` → `completed_at` reset | `completed_at` cleared on `Review` entry (task re-opened after block resolved) |
| T6 | Kanban view opens for `Agent Task` → all 6 columns visible | Kanban board renders states Pending/Assigned/Executing/Blocked/Review/Completed |
| T7 | Task in `Executing` transitions to `Blocked` → `result` preserves partial execution | `result` JSON shows execution history up to the failure |
| T8 | `Review → Completed` transition → `completed_at` set, `dispatchable=0` | Both fields correct after transition |
| T9 | Profile with no matching skills → `required_skills` unmet → task not assigned | `_match_profiles` returns empty; task stays Pending |
| T10 | Profile changes skill whitelist → already-claimed task is unaffected | In-progress task completes with original permissions |

### Coverage Targets

- `tasks/dispatcher.py`: ≥ 85% line coverage
- `tasks/workflow.py`: ≥ 80% line coverage
- `tasks/runner.py`: ≥ 80% line coverage
- Integration test: real concurrent `tick()` invocations against a seeded DB

### Slice 7 Regression

All Slice 7 sandbox tests and Slice 6 dispatcher tests must remain green. The only extension is a second dispatch path (task-driven); the chat-driven path is unchanged.

---

## 6. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Concurrent dispatcher instances double-claim the same task | 🔴 Blocker | `SELECT … FOR UPDATE SKIP LOCKED` is the canonical PostgreSQL solution; the query runs inside a Frappe transaction so row locks are held for the duration |
| No profile matches the task's `required_skills` → task is orphaned | 🟠 High | Log warning on every tick cycle; add `Agent Supervisor` dashboard filter for Pending tasks with no eligible profile; Phase 1.5 adds skill-similarity fallback |
| Kanban board state transitions are not role-gated | 🟠 High | Frappe Workflow enforces transitions server-side; the Kanban UI just renders the available actions per the workflow definition |
| Task runner pub/sub event fires but runner isn't subscribed | 🟡 Low | The runner registers the subscription in `gateway/service.py` on startup (Phase 1, Frappe site startup); if worker process dies, tasks in `Assigned` state will be detected as stale via a regular kicker |
| `workflow_state` is a plain `Data` field — no schema enforcement of valid states | 🟡 Low | The valid state list is enforced by the Frappe Workflow document; the Data field accepts any string. This is the same pattern Frappe uses for all workflow-state fields |
| Dispatcher runs before the Docker image is available | 🟡 Low | The `_execute_sandboxed` fallback to in-process execution (already implemented in Slice 7 dispatcher) applies here too — test/dev without Docker still work |

---

## 7. Exit Gate

### Slice 7 Regression

```
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_sandbox_runner
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_dispatcher
```
→ **All green**

### Task Workflow Tests

```
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_task_workflow
$ bench --site friday.localhost run-tests --module friday.friday_core.tests.test_task_dispatcher
```
→ **≥ 10/10 green**

### Manual Smoke Test

1. Open Frappe Framework Console on `friday.localhost`.
2. Create an `Agent Task` row: title="Test Kanban Task", priority="high", required_skills=`[create_note]`.
3. Verify `workflow_state` defaults to `Pending` and `dispatchable=1`.
4. Run: `bench --site friday.localhost execute friday.friday_core.tasks.dispatcher.tick`.
5. Observe: task moves to `Assigned` state → `Assigned to Profile` set → `dispatchable=0`.
6. Open the **Kanban view** for `Agent Task` in the Desk sidebar.
7. Observe: column "Pending" is empty; column "Assigned" shows the task card.
8. Watch a real-time update as the task runner executes and transitions the task to `Review` → `Completed`.

### Validation Checklist (from [`docs/design/11-agent-validation-checklist.md`](docs/design/11-agent-validation-checklist.md))

- [ ] `Agent Task` DocType has `workflow_state`, `dispatchable`, `assigned_to_profile`, `required_skills`, `result`, `started_at`, `completed_at`
- [ ] Frappe Workflow `Agent Task Workflow` has 6 states and transitions per §2.1
- [ ] `dispatchable` is `1` for `Pending` and `Assigned` tasks; `0` for all other states
- [ ] Two concurrent `tick()` calls do not double-claim any task
- [ ] Kanban board renders all 6 columns correctly
- [ ] Task transitions `Assigned → Executing` set `started_at`
- [ ] Task transitions to `Completed` or `Cancelled` set `completed_at`
- [ ] Execution Log is written for task-driven skills (same as chat-driven dispatch)
- [ ] Redis pub/sub message is emitted on `agent_task.assigned`

---

*Last updated: 2026-05-28*
