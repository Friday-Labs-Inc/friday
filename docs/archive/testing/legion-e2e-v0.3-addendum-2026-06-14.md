# Friday v0.3 — Legion E2E Addendum (Designs 67, 68, 69a)

**Audience:** the operator (you) **and** the Claude agent running on the Legion
machine — same format as the v0.2 runbook. Run this **after** the v0.2 runbook
passes (it depends on the pipeline, agents, and console being healthy).

**What this proves:** three v0.3 primitives that don't yet appear in the v0.2
runbook: MCP outside-world tools are synced and callable through the existing
skill pipeline (Design 67), the agent role contract shapes what each agent sees
and how it's prompted (Design 68), and an Orchestrator can delegate durable
child Tasks through the pipeline with depth/concurrency/role gates (Design 69a).

**What this does NOT cover** (manual-only or deferred):
- Design 63b-1/63b-2 (OAuth) — needs real Anthropic/OpenAI credentials and a
  browser; test manually via the Desk redirect flow.
- Design 64 (setup wizard) — one-time first-run; re-test by deleting the Agent
  Settings singleton and hitting `/app/friday-setup`.
- Design 69b (coordination: `wait_for_result`, `tail_child`, cancel cascade) —
  not yet shipped.
- Design 69c (console delegation tree) — not yet shipped.

---

## How to use this

Same conventions as the v0.2 runbook:

- Replace `$SITE` with the Legion site name.
- Every phase has a **VERIFY** block with the exact expected result.
- Do not proceed past a failed gate; report it.
- These phases are numbered **A1–A3** (Addendum 1–3) so they don't collide
  with v0.2's Phases 0–11.

---

## Phase A0 — Preconditions (v0.3 delta)

You already pulled code and ran `bench migrate` in v0.2 Phase 0. These steps
cover the new provisioning that v0.3 adds on top.

**A0.1 — Provision the delegate-task skill (Design 69a).**
```bash
bench --site $SITE execute \
  frappe.friday_core.skills.bootstrap_delegate.provision \
  --kwargs '{"profile_name": "Friday"}'
```
Idempotent. Creates the `Agent Delegator` role, the `delegate-task` Skill row
(risk: medium), and wires it into the Friday profile.

**A0.2 — Ensure the Friday profile is an Orchestrator.**

The role contract (Design 68) defaults new profiles to Specialist. Friday needs
Orchestrator to delegate.
```bash
bench --site $SITE console
```
```python
>>> p = frappe.get_doc("Agent Profile", "Friday")
>>> p.agent_role
# If blank or "Specialist", set it:
>>> if p.agent_role != "Orchestrator":
...     p.agent_role = "Orchestrator"
...     p.save(ignore_permissions=True)
...     frappe.db.commit()
```

**A0.3 — (Optional) Register an MCP server for Design 67 testing.**

If you have a remote MCP server to test against (e.g. a local
`npx @modelcontextprotocol/server-everything` on port 3001), create the
MCP Server row now:

```python
>>> if not frappe.db.exists("MCP Server", "test-mcp"):
...     s = frappe.get_doc({
...         "doctype": "MCP Server",
...         "server_name": "test-mcp",
...         "base_url": "http://localhost:3001/mcp",
...         "transport": "streamable_http",
...         "enabled": 1,
...     })
...     s.insert(ignore_permissions=True)
...     frappe.db.commit()
```

If you do NOT have a remote MCP server, skip to Phase A2 (Design 68) — Phase
A1 can be revisited later.

**VERIFY A0:**
```python
>>> frappe.db.exists("Skill", "delegate-task")                 # truthy
>>> frappe.db.get_value("Agent Profile", "Friday", "agent_role")  # 'Orchestrator'
>>> "delegate-task" in [r.skill for r in frappe.get_doc("Agent Profile", "Friday").permitted_skills]  # True
```
✅ Pass: delegate-task is provisioned, Friday is an Orchestrator.

---

## Phase A1 — MCP tool sync and invocation (Design 67)

**Skip this phase if you didn't register an MCP server in A0.3.**

Design 67 turns any remote MCP server's tools into governed Skill rows. The
sync creates `mcp_<server>_<tool>` Skills; the operator then permits them on a
profile; the agent calls them through the same dispatch → matrix → approval →
execute pipeline as any first-party skill.

**A1.1 — Sync the server.**
```bash
bench --site $SITE execute frappe.friday_core.mcp.sync.sync_server \
  --kwargs '{"server_name": "test-mcp"}'
```

**VERIFY A1.1** (`bench console`):
```python
>>> mcp_skills = frappe.get_all("Skill",
...     filters={"mcp_server": "test-mcp"},
...     fields=["skill_name", "status", "mcp_tool_name"])
>>> mcp_skills                               # at least one skill row
>>> all(s.status == "Active" for s in mcp_skills)  # True
>>> frappe.db.get_value("MCP Server", "test-mcp",
...     ["last_synced", "last_sync_status"])  # last_sync_status starts with "ok:"
```
✅ Pass: MCP skills synced; each has `mcp_server` + `mcp_tool_name` populated.

**A1.2 — Wire an MCP skill onto a profile.**

Pick one of the synced skills (e.g. `mcp_test_mcp_echo`) and permit it on
the Friday profile:
```python
>>> skill_name = mcp_skills[0].skill_name
>>> p = frappe.get_doc("Agent Profile", "Friday")
>>> if skill_name not in [r.skill for r in p.permitted_skills]:
...     p.append("permitted_skills", {"skill": skill_name})
...     p.save(ignore_permissions=True)
...     frappe.db.commit()
```

**VERIFY A1.2** — the skill appears in the loaded tool list:
```python
>>> from frappe.friday_core.skills.loader import load_for_profile, invalidate_for_profile
>>> invalidate_for_profile("Friday")
>>> tools = load_for_profile("Friday")
>>> skill_name in [t.name for t in tools]    # True
```

**A1.3 — (Optional) Invoke the MCP skill through dispatch.**

If the MCP server has an `echo` or similar safe tool, fire it through the
dispatcher to confirm the full pipeline:
```python
>>> from frappe.friday_core.agent_runner.dispatcher import dispatch
>>> frappe.flags.friday_dispatch_context = {
...     "agent_profile": "Friday",
...     "session_id": "test::mcp-e2e",
... }
>>> result = dispatch(skill_name, {"message": "hello from Friday"})
>>> result  # should contain the echoed text, not an error
```
Check: an **Execution Log** row was created for this call, and a
**Permission Decision Log** row recorded the matrix check.

Desk check: open **Skill** list → the `mcp_test_mcp_*` rows have
`mcp_server = test-mcp`. Their `risk_level` and `requires_approval` are
editable by the operator (not locked by sync).

**A1.4 — Disabled server blocks invocation.**
```python
>>> frappe.db.set_value("MCP Server", "test-mcp", "enabled", 0)
>>> frappe.db.commit()
>>> try:
...     from frappe.friday_core.mcp.client import call_tool
...     # This should fail at the handler level (enabled check):
...     dispatch(skill_name, {"message": "should fail"})
...     print("BUG: should have raised")
... except Exception as e:
...     print(f"Correctly blocked: {e}")
... finally:
...     frappe.db.set_value("MCP Server", "test-mcp", "enabled", 1)
...     frappe.db.commit()
```
✅ Pass: disabled server = blocked invocation; re-enable restores it.

---

## Phase A2 — Agent role contract (Design 68)

Design 68 adds a `agent_role` Select (Orchestrator / Specialist / Worker) on
every Agent Profile. It drives: (1) the system prompt preamble the LLM sees,
(2) baseline skill seed on first insert, (3) default approval threshold. The
backfill patch ensures pre-existing profiles get `Specialist` instead of blank.

**A2.1 — Backfill patch ran.**
```python
>>> blanks = frappe.get_all("Agent Profile",
...     filters={"agent_role": ("is", "not set")}, pluck="name")
>>> blanks   # should be []
```
✅ Pass: no profile has a blank `agent_role` after migration.

**A2.2 — Role preamble in the system prompt.**
```python
>>> from frappe.friday_core.llm.prompt_builder import _ROLE_PREAMBLES
>>> "ORCHESTRATOR ROLE" in _ROLE_PREAMBLES["Orchestrator"]   # True
>>> "delegate-task" in _ROLE_PREAMBLES["Orchestrator"]       # True
>>> "SPECIALIST ROLE" in _ROLE_PREAMBLES["Specialist"]       # True
>>> "WORKER ROLE" in _ROLE_PREAMBLES["Worker"]               # True
```

**A2.3 — New Orchestrator profile gets skill seed + approval default.**
```python
>>> test_orch = frappe.get_doc({
...     "doctype": "Agent Profile",
...     "profile_name": "E2E-Orch-Test",
...     "agent_role": "Orchestrator",
...     "status": "Active",
... })
>>> test_orch.insert(ignore_permissions=True)
>>> seeded = {r.skill for r in test_orch.permitted_skills}
>>> seeded   # {'read_record', 'list_records', 'list_project_files'}
>>> test_orch.requires_approval_above_risk   # 'high'
```

**A2.4 — New Worker profile: no seed, low approval threshold.**
```python
>>> test_worker = frappe.get_doc({
...     "doctype": "Agent Profile",
...     "profile_name": "E2E-Worker-Test",
...     "agent_role": "Worker",
...     "status": "Active",
... })
>>> test_worker.insert(ignore_permissions=True)
>>> len(test_worker.permitted_skills)          # 0
>>> test_worker.requires_approval_above_risk   # 'low'
```

**A2.5 — Existing profile update does NOT reseed** (seed is `before_insert`
only — prevents wipe-and-reseed loops).
```python
>>> test_orch.reload()
>>> test_orch.permitted_skills = []
>>> test_orch.save(ignore_permissions=True)
>>> test_orch.reload()
>>> len(test_orch.permitted_skills)   # 0 — no reseed on update
```

**A2.6 — Desk UI check.**

Open **Agent Profile → E2E-Orch-Test** in Desk:
- `agent_role` field shows "Orchestrator" in the top section.
- The three seeded skills appear in the Permitted Skills table.

**Cleanup:**
```python
>>> frappe.delete_doc("Agent Profile", "E2E-Orch-Test", force=1)
>>> frappe.delete_doc("Agent Profile", "E2E-Worker-Test", force=1)
>>> frappe.db.commit()
```

✅ Pass: roles backfilled, preambles correct, seed + approval defaults work per
role, no reseed on update.

---

## Phase A3 — Multi-agent delegation (Design 69a)

Design 69a is the durable async delegation primitive. An Orchestrator calls
`delegate-task` → a child Task is created as `Pending` → the existing pipeline
dispatches it independently. Three safety gates protect against runaway
delegation: role gate (Orchestrator-only), depth gate (chain length ≤ limit),
concurrency gate (active children ≤ profile's max).

**A3.1 — DocType fields exist after migrate.**
```python
>>> # parent_task on Task
>>> task_meta = frappe.get_meta("Task")
>>> pf = task_meta.get_field("parent_task")
>>> (pf.fieldtype, pf.options, pf.search_index)    # ('Link', 'Task', 1)

>>> # max_concurrent_delegations on Agent Profile
>>> ap_meta = frappe.get_meta("Agent Profile")
>>> mcf = ap_meta.get_field("max_concurrent_delegations")
>>> (mcf.fieldtype, mcf.default)                    # ('Int', '5')

>>> # delegation depth on Agent Settings
>>> as_meta = frappe.get_meta("Agent Settings")
>>> mdf = as_meta.get_field("max_delegation_depth")
>>> hcf = as_meta.get_field("delegation_depth_hard_ceiling")
>>> (mdf.default, hcf.default)                      # ('3', '8')
```

**A3.2 — Loader role gate: delegate-task hidden from non-Orchestrators.**

Create a Specialist profile with `delegate-task` permitted. The loader should
still strip it.
```python
>>> from frappe.friday_core.skills.loader import load_for_profile, invalidate_for_profile

>>> # Create a Specialist test profile with delegate-task permitted
>>> spec = frappe.get_doc({
...     "doctype": "Agent Profile",
...     "profile_name": "E2E-Spec-Delegate-Test",
...     "agent_role": "Specialist",
...     "status": "Active",
... })
>>> spec.insert(ignore_permissions=True)
>>> spec.append("permitted_skills", {"skill": "delegate-task"})
>>> spec.save(ignore_permissions=True)
>>> frappe.db.commit()

>>> invalidate_for_profile("E2E-Spec-Delegate-Test")
>>> tools = load_for_profile("E2E-Spec-Delegate-Test")
>>> "delegate-task" in [t.name for t in tools]   # False — stripped by role gate
```

**A3.3 — Loader role gate: delegate-task visible to Orchestrators.**
```python
>>> invalidate_for_profile("Friday")
>>> tools = load_for_profile("Friday")
>>> "delegate-task" in [t.name for t in tools]   # True
```

**A3.4 — Handler role gate (defense in depth).**

Even if the loader were bypassed, the handler itself refuses non-Orchestrators.
```python
>>> from frappe.friday_core.skills.handlers_delegate import delegate_task
>>> frappe.flags.friday_dispatch_context = {
...     "agent_profile": "E2E-Spec-Delegate-Test",
...     "session_id": "test::role-gate",
... }
>>> try:
...     delegate_task("delegate-task", {
...         "agent_profile": "Friday",
...         "instruction": "This should be blocked",
...     })
...     print("BUG: should have raised ValueError")
... except ValueError as e:
...     print(f"Correctly blocked: {e}")   # mentions "Orchestrator"
```
✅ Pass: two-layer defense — loader hides AND handler refuses.

**A3.5 — Successful delegation creates a child Task.**

This is the core test: the Orchestrator delegates, a durable child Task appears
with the right shape.
```python
>>> # Create a target Specialist profile
>>> target = frappe.get_doc({
...     "doctype": "Agent Profile",
...     "profile_name": "E2E-Target-Worker",
...     "agent_role": "Worker",
...     "status": "Active",
... })
>>> if not frappe.db.exists("Agent Profile", "E2E-Target-Worker"):
...     target.insert(ignore_permissions=True)

>>> # Create a parent Task (simulates an Orchestrator's current task)
>>> parent_task = frappe.get_doc({
...     "doctype": "Task",
...     "title": "E2E delegation parent",
...     "workflow_state": "Executing",
...     "execution_mode": "agentic",
...     "assigned_to_profile": "Friday",
... })
>>> parent_task.insert(ignore_permissions=True)
>>> frappe.db.commit()

>>> # Delegate from inside that task's context
>>> frappe.flags.friday_dispatch_context = {
...     "agent_profile": "Friday",
...     "session_id": f"task::{parent_task.name}",
... }
>>> result = delegate_task("delegate-task", {
...     "agent_profile": "E2E-Target-Worker",
...     "instruction": "Classify this brand brief into three categories.",
...     "title": "E2E classification subtask",
... })
>>> result["status"]                              # 'queued'
>>> child_name = result["child_task_name"]
>>> child_name                                     # truthy — a real Task name

>>> child = frappe.get_doc("Task", child_name)
>>> child.parent_task == parent_task.name           # True — graph edge
>>> child.workflow_state                            # 'Pending'
>>> child.execution_mode                            # 'agentic'
>>> child.assigned_to_profile                       # 'E2E-Target-Worker'
>>> child.originating_platform                      # 'delegation'
```
✅ Pass: child Task is durable, links back to parent, inherits project, starts
Pending.

**A3.6 — Depth gate blocks deep chains.**
```python
>>> from frappe.friday_core.skills.handlers_delegate import _delegation_depth

>>> # Our parent_task already exists; the child from A3.5 is depth 1.
>>> _delegation_depth(child_name)                   # 1

>>> # Set the site limit to depth 1 to test the gate:
>>> settings = frappe.get_doc("Agent Settings", "__default")
>>> old_depth = settings.max_delegation_depth
>>> settings.max_delegation_depth = 1
>>> settings.save(ignore_permissions=True)
>>> frappe.db.commit()
>>> frappe.clear_cache()

>>> # Now try to delegate FROM the child (depth would be 2, limit is 1):
>>> frappe.flags.friday_dispatch_context = {
...     "agent_profile": "Friday",
...     "session_id": f"task::{child_name}",
... }
>>> try:
...     delegate_task("delegate-task", {
...         "agent_profile": "E2E-Target-Worker",
...         "instruction": "This should be blocked by depth gate",
...     })
...     print("BUG: should have raised ValueError")
... except ValueError as e:
...     print(f"Correctly blocked: {e}")   # mentions "depth"

>>> # Restore the original depth limit
>>> settings.reload()
>>> settings.max_delegation_depth = old_depth
>>> settings.save(ignore_permissions=True)
>>> frappe.db.commit()
>>> frappe.clear_cache()
```
✅ Pass: depth gate enforces the limit.

**A3.7 — Concurrency gate blocks excess children.**
```python
>>> # Set concurrency limit to 1 on Friday's profile
>>> friday = frappe.get_doc("Agent Profile", "Friday")
>>> old_max = friday.max_concurrent_delegations
>>> friday.max_concurrent_delegations = 1
>>> friday.save(ignore_permissions=True)
>>> frappe.db.commit()

>>> # We already have one active child from A3.5 — next delegation should block:
>>> frappe.flags.friday_dispatch_context = {
...     "agent_profile": "Friday",
...     "session_id": f"task::{parent_task.name}",
... }
>>> try:
...     delegate_task("delegate-task", {
...         "agent_profile": "E2E-Target-Worker",
...         "instruction": "This should be blocked by concurrency gate",
...     })
...     print("BUG: should have raised ValueError")
... except ValueError as e:
...     print(f"Correctly blocked: {e}")   # mentions "concurrent"

>>> # Restore
>>> friday.reload()
>>> friday.max_concurrent_delegations = old_max
>>> friday.save(ignore_permissions=True)
>>> frappe.db.commit()
```
✅ Pass: concurrency gate enforces per-profile limits.

**A3.8 — Desk UI checks.**

- **Agent Settings** (`/app/agent-settings/__default`): `max_delegation_depth`
  (default 3) and `delegation_depth_hard_ceiling` (default 8, read-only)
  fields are visible.
- **Agent Profile → Friday**: `max_concurrent_delegations` field shows `5`.
- **Task list**: the child task from A3.5 shows `parent_task` populated.
  Filter by `parent_task = <parent_task.name>` — the child appears.

**Cleanup:**
```python
>>> # Delete test tasks and profiles (reverse order for FK safety)
>>> for t in frappe.get_all("Task", filters={"parent_task": parent_task.name}, pluck="name"):
...     frappe.delete_doc("Task", t, force=1)
>>> frappe.delete_doc("Task", parent_task.name, force=1)
>>> frappe.delete_doc("Agent Profile", "E2E-Spec-Delegate-Test", force=1)
>>> frappe.delete_doc("Agent Profile", "E2E-Target-Worker", force=1)
>>> frappe.db.commit()
```

✅ Phase A3 pass: all three gates work (role, depth, concurrency), child Task
shape is correct, loader and handler enforce defense in depth.

---

## Troubleshooting (v0.3 addendum)

| Symptom | Likely cause | Fix |
|---|---|---|
| `delegate-task` not in Friday's tool list | Friday profile is not Orchestrator | `frappe.set_value("Agent Profile","Friday","agent_role","Orchestrator")` + invalidate cache |
| `delegate-task` skill row missing | bootstrap not run | run A0.1 |
| `"only Orchestrator profiles can delegate"` on Friday | `agent_role` is blank or wrong | set it per A0.2 |
| `agent_role` blank on old profiles | backfill patch didn't run | `bench --site $SITE migrate` (runs `backfill_agent_role.py`) |
| MCP sync returns empty tools | server not running / wrong base_url | check `curl -X POST <base_url>` returns JSON-RPC |
| `McpError: Refusing non-http MCP URL` | base_url missing scheme | add `http://` or `https://` prefix |
| depth gate fires unexpectedly | `max_delegation_depth` set too low | check Agent Settings — default is 3 |
| concurrency gate fires unexpectedly | `max_concurrent_delegations` too low or stale Executing children | check profile value; look for zombie tasks in `Executing` state |
