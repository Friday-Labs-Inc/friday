# 53 — Project / Issue Tracker Port (design lock)

> **Status:** LOCKED. The contract the Project/Issue port implements against.
> **Scope:** Single-tenant Friday. ERPNext-free (the port copies ERPNext's *design*; it does **not** install or depend on ERPNext).
> **Audience:** Anyone — engineer, operator, or a high-schooler curious how Friday organises work.
> **Related:** [41 — porting strategy](41-porting-strategy-hermes-erpnext-raven.md) (Work Objects: Port, Not Depend) · [23 — secrets](23-secrets-credentials-management.md) (one-user-per-agent) · [52 — Hermes→Friday map](52-hermes-to-friday-map.md) · project memory `port-project-issue-tracker`, `erpnext-free-core`.

---

## 0. TL;DR

Friday gets a **generic project / issue / task tracker** in core — plain `Project`, `Task`, `Issue`, plus Frappe's native `ToDo`. It is the **operating model agents work inside** instead of improvising their own state. An **agent is just one kind of user** on a project, sitting next to human users.

We **port the design** of ERPNext's Project and Issue modules (mature, battle-tested) into `friday_core` as Friday's own DocTypes. We **do not** install ERPNext and we **drop** the ERP business cruft (billing, costing, timesheets-for-invoicing, support-contract SLAs).

---

## 1. Why — the operating model (plain English)

Today an agent that needs to do a multi-step job has nowhere to *put* the work. It improvises: holds the plan in its head, loses it across turns, can't hand off, can't show a human what's happening. That's fragile.

The fix is to give Friday a real **work tracker**, the same way a software team uses one:

- A **Project** is a container for related work ("Onboard the new vendor", "Close the books for March", "Ship the audit").
- A **Task** is one unit of work inside a project, assigned to *someone* to do.
- A **ToDo** is a lightweight action item / reminder handed to a specific person.
- An **Issue** is a problem or request — something went wrong, or someone needs something.

Agents operate **inside** that structure. They pick up their assigned Tasks, do them, and when something blocks them they raise an Issue — exactly like a human teammate would. Humans see the same board and can step in.

### Dual purpose (why the Issue tracker specifically)

The Issue tracker serves **two jobs at once**:

1. **Agent issue tracker (the system watching itself).** When an agent **fails** (error / out-of-memory / timeout / permission denied) or is **waiting on another agent** (a cross-agent dependency), the system raises an Issue automatically. This is how a human supervisor sees "agent X is stuck" without reading logs.
2. **General work tickets.** Ordinary problems and requests people (or agents) file by hand.

Both live in **one** `Issue` tracker, told apart by a `source` field.

---

## 2. The big decision: GENERIC, not agent-namespaced

**LOCKED.** The objects are **generic Friday-core objects**: `Project`, `Task`, `Issue` (+ Frappe `ToDo`). **Not** `Agent Project` / `Agent Task` / `Agent Issue`.

**An agent is one kind of *stakeholder user*, alongside humans.** This works cleanly because Frappe already gives us the seam: **each agent has its own Frappe `User` account** (the one-user-per-agent pattern, doc 23). So every assignee / stakeholder is just a **`User`** — some human, some agent — and one generic tracker serves both. When the assigned User happens to be an agent, Friday's execution machinery (sandbox, skills) runs; when it's a human, it's an ordinary task on their list.

> **Why we can use the plain names now.** Doc 14 originally prefixed them `Agent …` to avoid clashing with ERPNext's `Project`/`Task`/`Issue` if ERPNext were installed alongside. Under the **ERPNext-free** rule (memory `erpnext-free-core`), ERPNext is never installed, so there is no clash — and Frappe *core* has no `Project`/`Task`/`Issue` of its own. The `Agent`-prefixed names are dropped.

---

## 3. The objects (DocTypes)

Field lists below are the locked shape. "Ported" = the idea comes from the named ERPNext doctype; the Friday version is its own, trimmed.

### 3.1 `Project` (ported from ERPNext **Project**; renamed from `Agent Project`)
| Field | Type | Notes |
|---|---|---|
| `project_name` | Data, reqd | Title. |
| `description` | Text | |
| `status` | Select (workflow) | Open → In Progress → Completed · Cancelled · On Hold |
| `created_via` | Select | `Imported` / `Supervisor` / `Project Manager Agent` — how it came to exist |
| `project_manager` | Link → User | The PM (a human, or a PM-agent User) |
| `stakeholders` | Table → Project Stakeholder | The Users on this project (human + agent) |
| `priority` | Select | low / normal / high / urgent |

`Project Stakeholder` (child): `user` (Link → User), `role` (Select: Manager / Contributor / Watcher).

### 3.2 `Task` (ported from ERPNext **Task**; renamed from `Agent Task`)
| Field | Type | Notes |
|---|---|---|
| `subject` | Data, reqd | |
| `project` | Link → Project | |
| `assigned_to` | Link → **User** | Human or agent-User. (Replaces `assigned_to_profile`.) |
| `status` | Select | Open / In Progress / Completed / Cancelled |
| `workflow_state` | (Frappe Workflow) | Executing / Review / Blocked — kept from today |
| `priority` | Select | low / normal / high / urgent |
| `depends_on` | Table → Task Depends On | **Cross-task dependency** (ported from ERPNext `Task.depends_on`) |
| `required_skills` | Table → Task Skill | Only used when `assigned_to` is an agent-User |
| `description`, `result`, `started_at` | … | kept from today |

`Task Depends On` (child): `task` (Link → Task).
`Task Skill` (child, renamed from `Agent Task Skill`): `skill` (Link → Skill).

### 3.3 `Issue` (NEW — ported from ERPNext **Issue**)
| Field | Type | Notes |
|---|---|---|
| `subject` | Data, reqd | |
| `description` | Text | |
| `source` | Select | `Agent-raised` / `Human-raised` |
| `reason` | Select | `Failure` / `Dependency-Wait` / `Question` / `Bug` / `Other` |
| `status` | Select (workflow) | Open → In Progress → Resolved → Closed · Reopened |
| `priority` | Select | low / normal / high / urgent |
| `raised_by` | Link → User | Who/what raised it (agent-User or human) |
| `assigned_to` | Link → User | Who's handling it |
| `project` | Link → Project | Optional |
| `related_task` | Link → Task | The task this is about (failures / waits) |
| `waiting_on` | Link → Task | For `Dependency-Wait`: the unfinished blocker |
| `execution_log` | Link → Execution Log | For agent-raised: the audit row behind it |

### 3.4 `ToDo` — Frappe-native, **reused** (not re-implemented)
Frappe ships a `ToDo` doctype (allocated_to User, reference_type/name, description, priority, status, date). The **Orchestrator** creates ToDos that reference Tasks and are allocated to the assignee User. We do not build our own.

---

## 4. The flow (create → orchestrate → execute → issue)

```
1. A Project is created — Imported, by a Supervisor (human), or authored by a
   Project Manager Agent (fills in full details). It names its stakeholder Users.
        ↓
2. The Orchestrator decomposes the project into Tasks (+ ToDos) and assigns each
   to the right stakeholder User — human or agent.
        ↓
3. Each assignee works their items. When the assignee is an agent-User, Friday's
   sandbox/skill machinery runs the Task; a human just sees it on their list.
        ↓
4. Issues are captured when work hits trouble:
     - the actor FAILED (error / OOM / timeout / permission denied), or
     - the actor is WAITING on another actor (a Task whose `depends_on` isn't done).
   Agent-raised Issues link back to the Task and the Execution Log; the War Room
   posts reference them. Humans resolve or reassign from the same board.
```

---

## 5. Locked decisions (the Q-by-Q)

| # | Decision | LOCKED choice | Why |
|---|---|---|---|
| D1 | Naming | **Generic** `Project`/`Task`/`Issue` (+ Frappe `ToDo`); drop the `Agent` prefix | §2 — agent is one kind of User; ERPNext-free → no clash |
| D2 | Who is an assignee/stakeholder | A Frappe **`User`** (humans and agents alike; agents have their own User) | One model serves both; matches doc 23 |
| D3 | Orchestrator + PM Agent | **Behaviours, not new core machinery.** *Orchestrator* = the existing `tasks/dispatcher` job (it assigns Tasks/ToDos). *Project Manager Agent* = an ordinary Agent Profile with project-authoring skills | Don't grow the kernel for roles that are just agents doing work |
| D4 | ToDo | **Reuse Frappe's native `ToDo`** | It is built for exactly this; re-implementing is waste |
| D5 | Cross-agent dependency | Model as `Task.depends_on` (Task→Task). When a blocker is unfinished, **auto-raise a `Dependency-Wait` Issue and park the task** until it clears | First-class "waiting on another agent" visibility; ported straight from ERPNext `Task.depends_on` |
| D6 | Agent failure | A Blocked/errored/OOM/timeout Task **auto-raises a `Failure` Issue** linked to the Task + Execution Log; War Room post references it | This is purpose #1, wired into `tasks/runner.py` which already detects these |
| D7 | Workflow states | Native **Frappe Workflow** on each (Project, Task, Issue), same pattern as Task today | Reuse the framework; auditable transitions |
| D8 | Permissions | These are ordinary DocTypes — governed by Frappe roles + the Friday permission matrix like everything else | No special path; deny-by-default still applies |

---

## 6. What we port vs. chuck (ERPNext scope)

**Port the core** (from `frappe/erpnext` Projects + Support modules):
- Project (container) · Task (work unit, incl. `depends_on`) · Issue (ticket) · minimal Type / Priority / Status.

**Chuck the ERP business cruft** (do **not** port):
- Project costing / billing / profitability, Gross Margin.
- Timesheets-for-invoicing, billable hours, Activity Cost.
- Support **contract SLAs** (Service Level Agreement timers, response/resolution-by from a contract).
- Customer / Sales / Item links and any field that only makes sense inside an ERP.

A plain `priority` + optional `due date` covers urgency without dragging in SLA machinery.

---

## 7. Migration (rename/fold what exists)

`Agent Project`, `Agent Task`, `Agent Task Skill` already exist in `friday_core`. They become the generic objects:

| From | To |
|---|---|
| `Agent Project` | `Project` |
| `Agent Task` | `Task` |
| `Agent Task Skill` | `Task Skill` |
| `Agent Task.assigned_to_profile` (Link → Agent Profile) | `Task.assigned_to` (Link → **User**) |

- Use a Frappe `rename_doc` patch (preserves data) and update every code reference (`tasks/dispatcher.py`, `tasks/runner.py`, `tasks/workflow.py`, `warroom/publisher.py`, `gateway/service.py`, hooks).
- `assigned_to_profile → assigned_to`: each Agent Profile resolves to its linked Frappe User (doc 23). The execution path keys off "is this User an agent?".
- New build: the `Issue` DocType + the auto-raise wiring (D5, D6).

---

## 8. How it ties into what already exists

- **`tasks/dispatcher.py`** = the Orchestrator (assigns Tasks/ToDos). No new agent type.
- **`tasks/runner.py`** already catches Blocked / OOM / Timeout → that's where the `Failure` Issue auto-raise hooks in (D6).
- **`warroom/publisher.py`** already posts task state changes → posts now reference the Issue.
- **Execution Log** stays the immutable audit; an agent-raised Issue *links to* it (the Issue is the human-actionable record, the log is the proof).
- **Permission matrix** governs who (which role/User) can read/write Project/Task/Issue — unchanged path.

---

## 9. Out of scope / deferred

- ToDo *generation strategy* beyond "Orchestrator creates them" (smart decomposition is later).
- Gantt / timeline views (Frappe gives list + Kanban for free; fancier views later).
- Multi-site / cross-org projects (doc 37 territory — Phase 2).
- Auto-resolution of Issues by agents (v0.1: agents *raise*; humans or a follow-up slice *resolve*).

---

## 10. Build order (tests-first, per workflow)

1. **Tests first** — DocType existence + field contracts; dependency-wait auto-raise; failure auto-raise; assignment to a User (human and agent).
2. **Rename/fold** `Agent Project/Task/Task Skill` → `Project/Task/Task Skill` (+ patch + reference updates). Green migrate.
3. **`Issue` DocType** + workflow.
4. **Wiring:** `depends_on` park + `Dependency-Wait` auto-raise (D5); `Failure` auto-raise from `tasks/runner.py` (D6); War Room reference.
5. **Rollout doc** `docs/rollouts/…` (plain-English narrative) in the same PR.

---

## 11. References

- ERPNext source to port the *design* from: `frappe/erpnext` → Projects module (`Project`, `Task`) and Support module (`Issue`).
- [41 §"ERPNext Work Objects: Port, Not Depend"](41-porting-strategy-hermes-erpnext-raven.md)
- [23 §one-user-per-agent](23-secrets-credentials-management.md)
- Project memory: `port-project-issue-tracker`, `erpnext-free-core`.
