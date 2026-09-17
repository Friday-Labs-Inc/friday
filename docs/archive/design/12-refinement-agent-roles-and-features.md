# 12 — Agent Role Profiles, Hierarchies, Delegation, Escalation

> See `00-glossary.md` for term definitions.
> See `05-module-design.md` for the Agent Profile and Agent Role Profile DocType schemas (this doc covers the model and lifecycle around them).
> See `42-phase-one-authority-contract.md` §3 — Agent Role Profile is in v0.1 scope.

---

## 1. Why Agent Role Profiles

Manual role assignment per agent is error-prone, inconsistent across agents of the same type, and hard to update fleet-wide. Frappe solves this for humans with Role Profile. Friday adopts the same idea, specialised for agent governance.

A real deployment instantiates 50 task workers from one profile selection, not 50 manual role tables.

---

## 2. Agent Role Profile schema

Field reference for the DocType. Authoritative version lives in `05-module-design.md`.

| Field | Type | Notes |
|---|---|---|
| `profile_code` | Data (unique) | e.g. `task_worker`, `data_processor`, `supervisor` |
| `display_name` | Data | Human-readable name |
| `description` | Text | Purpose, capabilities, restrictions |
| `base_role_profile` | Link → Role Profile (Frappe native) | Optional inheritance from a Frappe Role Profile |
| `roles` | Table → Role | Roles granted to agents using this profile |
| `permitted_skills` | Table → Skill | Skill whitelist (overrides role-only matching) |
| `default_resource_quota` | Section | CPU, memory, requests/hr, max concurrent execs |
| `default_network_allowlist` | Table | Hosts the sandbox may reach by default |
| `requires_approval_above_risk` | Select | low / medium / high / always |
| `can_delegate_to` | Table → Agent Role Profile | Profiles this agent may delegate to |
| `can_escalate_to` | Table → Agent Role Profile | Profiles handling escalations from this profile |
| `status` | Select | Active / Deprecated |

Agent Profile carries `agent_role_profile` (Link → Agent Role Profile). `assigned_roles`, resource quota, network allowlist, and approval threshold are derived from the linked profile with per-agent override permitted within the profile's bounds.

**Why a new DocType vs. Frappe Role Profile:** Frappe Role Profile bundles only roles. Agent Role Profile must also bundle skills, resource quotas, network allowlist, approval thresholds, and delegation/escalation routing — a superset. Inheritance through `base_role_profile` reuses role bundles already defined for human users.

**Open question — Phase 1 slice 1 spike:** Frappe Role Profile's update-propagation semantics (cache invalidation, hook timing) need verification against agent contexts before relying on inheritance. If insufficient, Agent Role Profile carries its own role list and the inheritance link is informational only.

---

## 3. Standard profiles shipped with Friday

Default set; deployments extend, disable, or override.

| Profile | Purpose | Typical roles | Typical skills | Approval threshold |
|---|---|---|---|---|
| `task_worker` | Executes individual Agent Tasks | Friday Agent, Task Executor | Skills tagged `low-risk`, `task_execution` | `high` |
| `data_processor` | Reads, transforms, writes data documents | Friday Agent, Data Reader, Data Writer | Skills tagged `data_io` | `high` |
| `qa_agent` | Reviews completed work, flags issues | Friday Agent, QA Reviewer | Read-only skills + Comment write | `always` for any write |
| `supervisor_agent` | Oversees other agents, approves escalations | Friday Agent, Supervisor | Workflow Request decisions, agent delegation | `high` |
| `integration_agent` | Talks to external APIs and MCP servers | Friday Agent, Integration | External-call skills | `medium` |
| `dev_agent` | Authors / edits skills (drafts only) | Friday Agent, Skill Author | `skill_draft.create`, `skill.read` | `always` |
| `read_only_agent` | Observation / reporting only | Friday Agent, Read Only | All read skills, no write | n/a |

Starting points. Real deployments customise them.

---

## 4. Multi-agent hierarchy

Agents form a hierarchy through two explicit relationships. There is no implicit "everyone reports to admin". Every path is explicit, audited, and revocable by editing the role profile.

### 4.1 Delegation (peer or downward)

Agent of profile X may invoke an agent of profile Y if Y is in `X.role_profile.can_delegate_to`.

Example: `supervisor_agent.can_delegate_to = [task_worker, data_processor]`. `task_worker.can_delegate_to = []`.

### 4.2 Escalation (upward)

When an agent encounters a blocker, it escalates to a profile listed in its `can_escalate_to`.

Example: `task_worker.can_escalate_to = [supervisor_agent, human_supervisor]`.

---

## 5. Delegation chains

```
Agent A (profile X) wants to invoke a skill via Agent B (profile Y)
1. Gateway checks: Y ∈ X.role_profile.can_delegate_to.
2. Gateway checks: Y has permission for the requested skill.
3. Both pass → create a Delegation Request DocType.
4. Spawn or route to an instance of profile Y.
5. Y executes with its own permissions, not X's. Privilege does not escalate.
6. Result returns through the gateway; delegation chain logged.
```

### Delegation Request DocType

| Field | Type |
|---|---|
| `from_agent_profile` | Link |
| `to_agent_profile` | Link |
| `requested_skill` | Link → Skill |
| `parameters` | JSON |
| `parent_task` | Link → Agent Task |
| `parent_execution_log` | Link → Execution Log |
| `status` | Select (Pending / Running / Completed / Failed / Denied) |
| `result_execution_log` | Link → Execution Log |
| Submittable | Yes |

### Guards

- Delegation loop (A → B → A) is detected and rejected.
- Maximum chain depth configurable (default 5). Exceeding it returns an error and logs.
- Delegation never transfers credentials. Y uses Y's scoped token, never X's.

---

## 6. Escalation workflows

### Trigger

An agent escalates on:

- A required skill it has no permission for.
- Repeated failure (configurable; default 3 retries exhausted).
- An LLM-emitted explicit escalation tool call ("I need human or supervisor help").
- A wall-clock timeout exceeding the task's budget.

### Flow

```
1. Agent emits an Escalation Event (programmatic or LLM-decided).
2. Gateway creates an Escalation DocType row.
3. Looks up the agent's role_profile.can_escalate_to.
4. Routes in priority order:
   - First target: Workflow Request to the highest-priority profile.
   - No-response timeout: cascade to the next target.
   - Final fallback: War Room post with @here mention.
5. Resolver (agent or human) decides:
   - Approve + take over → resolver executes.
   - Approve + return → originating agent retries with new context.
   - Reject → task marked Blocked, awaiting human review.
6. Decision logged immutably.
```

### Escalation DocType

| Field | Type |
|---|---|
| `originating_agent_profile` | Link |
| `originating_task` | Link → Agent Task |
| `reason_code` | Select (permission_denied / repeated_failure / explicit / timeout) |
| `details` | Long Text |
| `attempted_targets` | Table |
| `resolved_by` | Link → User or Agent Profile |
| `resolution` | Select (taken_over / returned_to_agent / blocked / cancelled) |
| `resolved_at` | Datetime |
| Submittable | Yes |

### War Room integration

On cascade to War Room, Raven receives:

```
⚠️ Escalation from @agent-name on Task #1234
Reason: permission_denied (skill `transfer_funds`)
Suggested resolver: any @supervisor_agent
[Approve in Console →]  [Take Over →]  [Decline →]
```

Buttons are Raven Message Actions that trigger Workflow Request decisions.

---

## 7. Permission inheritance

```
effective_roles =
    (Agent Role Profile.base_role_profile.roles  if set else ∅)
  ∪ Agent Role Profile.roles
  ∪ Agent Profile.additional_roles               (per-agent override; optional)

effective_skills =
    (Agent Role Profile.permitted_skills)
  ∩ skills_permitted_by(effective_roles)
  ∪ Agent Profile.additional_skills              (per-agent override; ⊆ role-permitted)

effective_quota =
    Agent Profile.quota_override                 (if set)
  | Agent Role Profile.default_resource_quota
```

**Invariant:** An Agent Profile can never hold **more** permission than its Agent Role Profile permits. `additional_roles` must be a subset of role-profile-permitted; validated on save.

---

## 8. Lifecycle: creating an agent

1. Select an Agent Role Profile (standard or custom).
2. Create an Agent Profile with `agent_role_profile` set and a `linked_user` (Frappe User identity).
3. Optionally add `additional_skills` or `quota_override`.
4. Save. Friday derives `effective_roles`, `effective_skills`, `effective_quota` and caches them in Redis.

Onboarding 50 task workers is one profile selection per agent — or a bulk import.

---

## 9. Worked example — Customer Onboarding Sprint

**Setup**
- Agent Role Profiles: `task_worker`, `data_processor`, `supervisor_agent`.
- One project: "Customer Onboarding Sprint" (Agent Project).
- Tasks created with `required_skills` tagged.

**Agents**
- 5 × `task_worker` (each with a dedicated linked Frappe User).
- 2 × `data_processor`.
- 1 × `supervisor_agent`.

**Permission flow**
- Each `task_worker` inherits low-risk task-execution skills only.
- Each `data_processor` inherits Customer read/write + tagged data skills.
- The `supervisor_agent` holds delegation rights to both and is in both `can_escalate_to` lists.

**Runtime**
- Dispatcher claims 5 tasks → one per task_worker.
- task_worker #3 hits `permission_denied` on `update_customer_credit_score`.
- Auto-escalation → `supervisor_agent` (first in escalate_to).
- Supervisor sees the War Room post, delegates to a `data_processor`.
- `data_processor` executes successfully.
- task_worker #3 resumes with the updated data.
- Delegation and escalation chains all recorded immutably.
