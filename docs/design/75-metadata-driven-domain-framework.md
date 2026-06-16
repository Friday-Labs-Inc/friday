# Design 75 — Metadata-driven domain framework (Friday as a generic engine)

**Status:** Designed 2026-06-16 via an 8-agent design pass (audit + Frappe-Workflow study + prior art → synthesis → 3-domain stress-test → adversarial critic). Buildable, with the critic's 5 preconditions baked in below. **Supersedes the hardcoded approach of Design 74** — Design 74's brand team/pipeline becomes the *first domain bundle (data)*, not Python.

## The pivot (why this exists)

Design 74 hardcoded one domain into Python: `RANDOMPACK_PIPELINE` (a list), `TEAM_SKILLS` (a dict), skill-discriminated routing. That makes Friday "the RandomPack brand engine." Friday's real value is a **generic, governed agentic framework**: a domain — brand identity, data-center ops, a research project — is defined by **DATA** (a workflow + skills + agent profiles + roles), edited in Desk, with **zero Python**. Frappe is metadata-native and agents are first-class Users with roles; we lean into that as the first design inspiration.

> The engine becomes a **generic workflow interpreter**: read DocType records → advance state → dispatch the role-owner. No dispatcher/runner/reconciler code knows about branding, data centers, or any domain.

## 1. Data model (hybrid — Frappe Workflow + a transition-meta doctype)

Use **Frappe's native `Workflow`** as the state machine on the domain *work-item* DocType (states, role-gated transitions, audit, human gates — for free), plus a Friday-owned child that carries the agentic metadata Frappe Workflow lacks.

- **`Friday Workflow Transition Meta`** (standalone doctype, keyed by `workflow` + `from_state` + `action`): the agentic metadata for one Frappe Workflow transition — `phase_key` (Data, **unique per workflow**), `execution_mode` (agentic|milestone|mechanical), `agent_role` (Link→Role — the routing key), `required_skills` (Table — verification, not routing), `prompt_template` (Long Text, Jinja), `timeout_seconds`, `max_retries`, `wait_for_all_tasks` (Check — see §8). **Implementation correction (grounded in the Frappe contract):** this is NOT a child of `Workflow Transition` — that's a Frappe *istable* core doctype, so nested child tables aren't ORM-supported and patching it isn't upgrade-safe. A standalone doctype keyed to `(workflow, from_state, action)` is the clean, upgrade-safe binding. The engine resolves it by `(workflow, current_state, action)`; the `action` it carries is exactly what `apply_workflow` fires — no `next_on_complete` field needed (critic HIGH-3).
- **`Domain Bundle`** (top-level, the export/import unit): `bundle_name`, `domain_doctype` (the work-item DocType), `workflow_name` (Link→Workflow), `version`, `is_active`. Export = JSON of {workflow + phases + agent profiles + skills + roles + perms}; import is idempotent.
- **`Agent Profile`** + `discriminator_role` (Link→Role — the routing key) + `domain_bundle`. **Uniqueness enforced:** at most one Active profile per `discriminator_role` (validate at save — critic MEDIUM-7), so a misconfigured second profile fails loudly, not silently-dead.
- **`Task`** + `work_item_doctype` (Link→DocType) + `work_item_name` (Dynamic Link). `phase_key` carried so the engine can traverse to the transition.
- **`Skill`** + `role_gate` (Link→Role — replaces the hardcoded `_ROLE_GATED_SKILLS` dict).

## 2. Routing by metadata (kills the skill-discriminator hack)

The dispatcher stops iterating profiles + subset-matching skills. It reads the phase's `agent_profile_role` and resolves the owner by `discriminator_role` — O(1):

```python
frappe.db.get_value("Agent Profile", {"discriminator_role": role, "status": "Active"}, "name")
```

The skill-subset `_match_profiles` stays only as the fallback for *freeform* agentic tasks (no `phase_key`). `permitted_skills` + the permission matrix remain as defense-in-depth at execution time — not as routing.

## 3. Gates and agentic steps are the same mechanism

Both are **Workflow Transitions**; they differ only by the `allowed` Role:
- **Gate** = transition owned by a *human* role (e.g. `Client Reviewer`); no `Friday Workflow Transition Meta` row (or `execution_mode = milestone`) → the engine no-ops; a human fires it (Desk button or webhook). Agents cannot fire it.
- **Agentic step** = transition owned by an *agent* role, with a phase row; the engine fires it on the agent's behalf.

### Governance: the `set_user` guard is load-bearing (critic CRITICAL-1)
Frappe's `validate_workflow` does **not** enforce the transition's `allowed` role in an RQ worker — the worker session is `Administrator`, which `has_approval_access` waves through, and `get_transitions` returns everything for Administrator. So role-gating only holds if the engine sets the acting user. **Mandatory pattern everywhere a transition is fired:**

```python
frappe.set_user(actor_user)        # agent's system user, or the gate gateway account
try:
    apply_workflow(doc, action)
    doc.save()
finally:
    frappe.set_user("Administrator")
```

- Each agent's system user holds **only** its agent role → it can fire only its own transitions. A unit test asserts `apply_workflow` with the *wrong* user **raises**.
- **Webhook gates** (`gate.decided`) must NOT do `task.workflow_state = "Completed"` directly (today's `randompack.py:308` bypass — critic MEDIUM-6). They fire `apply_workflow` as a dedicated **gateway service account** that holds the gate's human role and **no agent role**. This account ships in the Domain Bundle.

## 4. The generic engine

```
friday_core/engine/
  workflow_engine.py    # on_update interpreter: state → phase → dispatch
  phase_dispatcher.py   # render prompt_template, create Task, assign by discriminator_role
  advance.py            # on Task complete → fire the next transition (after commit)
```

- `workflow_engine.on_update` (initially `doc_events["Brand Brief"]`, generalized to `["*"]` only after validation — critic HIGH-5): on a work-item save, find the phase row for the new state; if agentic, `phase_dispatcher.dispatch`.
- `advance.advance_work_item(task)` runs when a Task completes — **via `frappe.enqueue(enqueue_after_commit=True)`, never synchronously** (critic CRITICAL-2: a synchronous `apply_workflow`→new-save→new-Task chain inside the completing Task's transaction can roll the Task back and cause double-runs). It resolves `Task.phase_key → Friday Workflow Transition Meta → .action` (the meta row carries the workflow + from_state + action of the Frappe transition), then fires that transition (with the §3 guard).

## 5. Two orthogonal lifecycles (the Design 74 conflation, fixed)

- **Domain workflow** = the Frappe Workflow on the *work-item* (Brand Brief / DC Incident / Research Project). This is **data**.
- **Task execution lifecycle** = Pending→Assigned→Executing→Completed on the *Task*. This is the **engine** (scheduler/runner/reconciler), unchanged.

**Standing rule: never attach a Frappe Workflow to the `Task` DocType** (the runner's raw-SQL claim would fight `validate_workflow` — critic Risk-1). They are different documents with different durability needs.

## 6. Code vs data

| Stays code (the floor) | Becomes data (Desk-editable) |
|---|---|
| the engine (interpreter, dispatcher, advance) | the workflow shape (Frappe Workflow + phase rows) |
| `runner.py` (LLM, streaming, tools, retry) | the team (Agent Profiles + `discriminator_role`) |
| skill **handlers** | routing (the role on each phase), gates (human-role transitions) |
| `reconciler` generic sweeps | prompts (`prompt_template` per phase) |
| permission matrix, agent-identity | skill role-gates (`Skill.role_gate`), domain sweeps (via `hooks.py`) |

Two brand-specific handlers (`get-brand-brief`, `create-brand-direction`) stay until replaced by generic `read-work-item` / `create-child-record` that read their target doctype+fields from the Skill's `parameters_schema` (medium-term, not a prerequisite). The reconciler's domain sweep moves to a `hooks.py` entry `friday_reconciler_sweeps` (critic MEDIUM-9) — no hardcoded names.

## 7. Migration (safe sequencing — critic HIGH-5)

1. **Additive schema only** (migrate clean, existing pipelines untouched): add `discriminator_role`+`domain_bundle` to Agent Profile; `work_item_doctype`+`work_item_name`+`phase_key` to Task; `role_gate` to Skill; create `Domain Bundle` + `Friday Workflow Transition Meta`.
2. **Fixtures, dicts retained:** `RANDOMPACK_PIPELINE` → a Frappe `Workflow` + phase rows; `TEAM_SKILLS` → Agent Profile rows with `discriminator_role`. The Python dicts become **fixture generators** (source of truth that emits the JSON), not runtime paths. Nothing deleted yet.
3. **Backfill** `discriminator_role` on each profile from `TEAM_SKILLS`.
4. **Scoped engine hook** (`doc_events["Brand Brief"]`, guarded by "is there a phase row?") so it no-ops for every other DocType.
5. **E2E-validate on Legion (Northwind)**, then generalize the hook and retire the dict paths. Never run two dispatch paths at once.

## 8. Scope boundary — Phase 1 does NOT do parallel fan-outs (critic HIGH-4)

Frappe Workflow stores one state per document; a true AND-join (e.g. naming + directions → gate1) needs a `phase_group` + `wait_for_all_tasks` mechanism in engine Python (count completed siblings before advancing). **Phase 1 ships sequential workflows only**; domains with parallel phases use the existing `Task.depends_on` workaround inside one "parallel" state (degraded operator visibility, acknowledged). The AND-join is **Phase 2**.

## 9. Back-edges (critic MEDIUM-8)

Workflows with two transitions into the same state (e.g. research "revise" loop) are disambiguated by **`phase_key` unique per workflow** (not per state-pair): the revision path gets its own `phase_key`. The engine keys on the transition (via `phase_key → parent`), never on the target state.

## 10. What becomes of Design 74

Not wasted — **converted to the first Domain Bundle**: `TEAM_SKILLS` → the `randompack-brand` bundle's Agent Profiles; `RANDOMPACK_PIPELINE` → its Workflow + phase rows; the discipline skills (`brand-strategy`, `brand-naming`) stay as Skill rows. `test_team_routing.py` is rewritten to test the generic `discriminator_role` lookup instead of importing `TEAM_SKILLS`. `bootstrap_team.py`/`bootstrap_brand.py` become fixture generators.

## Validated against 3 domains
The stress-test expressed **brand identity**, **data-center incident ops** (triage→diagnose→remediate→human-approve→verify→postmortem), and **research** (question→scan→synthesis→adversarial-review→report) purely as bundle data. The failures it surfaced (brand's fan-out, research's back-edge, DC's must-not-self-approve gate) are exactly the §3/§8/§9 design decisions above.

## The critic's non-negotiable preconditions (all folded in)
1. `set_user` + try/finally on every transition; test that the wrong user raises (§3).
2. `advance_work_item` via `enqueue_after_commit`, never synchronous (§4).
3. Engine infers the action via `phase_key → Friday Workflow Transition Meta.action`; no redundant `next_on_complete` (§4).
4. Parallel fan-out scoped to Phase 2; Phase 1 is sequential-only (§8).
5. Migration sequenced additive-first, hook scoped, no dual dispatch paths (§7).

Everything else (gateway account, `discriminator_role`/`phase_key` uniqueness, reconciler `hooks.py` sweep, Jinja template `validate` controller) are one-day fixes that don't touch the data model.

## Verdict
The goal is sound; only the happy-path's assumptions about Frappe's enforcement and the lifecycle boundary were over-optimistic — both corrected above without changing the data model. **This is the next real architecture; Design 74 is its first data bundle.**
