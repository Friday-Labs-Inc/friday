# Rollout — Design 78: role_gate enforcement (2026-06-17)

## Plain English

The architect-doc comparison surfaced a **silent security hole**: the `Skill.role_gate`
field exists on the doctype with a description that says "the role that may use
this skill" — but at runtime, the field was **never read**. The actual gate
that protected the `delegate-task` skill from non-Orchestrator profiles lived
in a hardcoded Python dict in `skills/loader.py`. Any operator who set
`role_gate` in Desk on a new high-risk skill would see a feature that did
absolutely nothing — and the agent could use it anyway.

This PR makes the field load-bearing. From now on:

- The loader reads `Skill.role_gate` from the database first. If the field is
  set, that's the gate.
- If the field is empty, the loader falls back to the hardcoded dict — so
  existing behavior is preserved zero-risk for any site that hasn't migrated.
- The permission matrix also re-checks the gate at call time (defense in
  depth), so a stale loader cache or a direct dispatcher call cannot bypass
  governance.

The migration step is automatic: `bootstrap_delegate.provision()` now sets
`Skill.role_gate = "Agent Delegator"` on the `delegate-task` Skill row. The
"Agent Delegator" Frappe Role was already created and assigned to the
Orchestrator profile by the same bootstrap (existing behavior), so existing
Orchestrators keep delegating without a single Desk touch.

## The four design decisions

This is the implementation of [`docs/design/78-role-gate-semantics.md`](../design/78-role-gate-semantics.md)
with **all recommended defaults**:

| Q | Decision | Why |
|---|---|---|
| Q1 | Frappe Role membership | The `Has Role` child table is canonical; gets role inheritance + Desk management for free. The `Agent Delegator` role already exists. |
| Q2 | Empty field falls back to the dict | Zero behavior change for sites that haven't migrated. |
| Q3 | Check at both menu-build AND call-time | Defense in depth — matches Friday's existing two-permission-gate pattern. |
| Q4 | Migrate only `delegate-task` | The only skill currently gated. Future Desk-managed skills get the new path automatically. |

## What changed (file-by-file)

### `skills/loader.py`

New helpers:

- `_resolve_role_gate(skill_doc)` — returns the role the calling profile must
  hold, or `None` if the skill is ungated. Reads `Skill.role_gate` first;
  falls back to `_ROLE_GATED_SKILLS`.
- `_profile_has_role(profile, required_role)` — handles two value spaces
  transparently: if `required_role` is one of the agent_role Select tier
  values (Orchestrator/Specialist/Worker), it checks `profile.agent_role`;
  otherwise it checks Frappe Role membership in `profile.assigned_roles`.

The gate filter inside `_load_uncached` was rewritten to use these helpers.
The old line was `agent_role != _ROLE_GATED_SKILLS.get(skill_name)`, which
mixed up the two value spaces and would have broken the moment anyone set
the field.

### `permissions/matrix.py`

- `PermissionMatrix` gains a new optional `agent_role: str | None` field
  (default `None`). Cached entries serialized before this field was added
  still deserialize cleanly thanks to `data.get()` in `from_dict`.
- `evaluate()` calls the same `_resolve_role_gate` / role-membership helpers
  at call-time so a stale loader cache, a direct dispatcher call, or any
  other bypass of menu-build filtering still hits the gate.

### `skills/bootstrap_delegate.py`

- `provision()` now sets `skill.role_gate = DELEGATOR_ROLE` (i.e.
  `"Agent Delegator"`) when re-saving the `delegate-task` Skill row.
- Idempotent — re-running provision on an already-migrated site is a no-op.

### `tests/test_skill_loader.py`

Three new tests lock the security behavior:

1. `test_role_gate_field_blocks_when_profile_lacks_role` — a skill with
   `role_gate` set to a Frappe Role is hidden from a profile whose
   `assigned_roles` do not include that role.
2. `test_role_gate_field_admits_when_profile_has_role` — same skill is
   visible to a profile that holds the role.
3. `test_role_gate_dict_fallback_for_unset_field` — when `role_gate` is
   blank, the hardcoded dict still gates (back-compat).

## What did NOT change

- The `_ROLE_GATED_SKILLS` dict still exists. It serves as the documented
  back-stop for skills whose `role_gate` field is blank. A future cleanup
  PR will remove it once every gated skill is migrated to the field.
- No schema migration is required. The `role_gate` field already existed
  on the Skill doctype as `Link → Role` (the architect-doc gap report
  confirmed this).
- Existing Orchestrator profiles continue to delegate without change. The
  "Agent Delegator" Frappe Role was already assigned to them by
  `bootstrap_delegate.provision()` long before this PR.

## How we proved it works

- `bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_skill_loader`
  → 11/11 green (8 existing + 3 new role-gate tests).
- `bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_delegate_skill`
  → 10/10 green (no regression in existing delegation flow).
- `bench --site friday.localhost migrate` → clean.
- `bench --site friday.localhost execute frappe.friday_core.skills.bootstrap_delegate.provision`
  → `Skill.role_gate = "Agent Delegator"` confirmed in the DB.

## What this unblocks

- Operators can now configure role gating on any new Skill row directly
  in Desk by setting `role_gate` to any Frappe Role they want — no code
  deploy needed for a new gate. The architect-doc Tool Registry pattern
  (per-skill role gating with audit trail) is now realised.

## Adversarial-review check from Design 77 v1 critique

The Design 77 v1 critic identified this exact issue with severity `CRITICAL`
and called out a value-space type-mismatch landmine that the naive fix
would trip. This PR avoids the landmine by **handling both value spaces
transparently** in `_profile_has_role` — operators can use either an
agent_role tier value (back-compat with the dict) or a Frappe Role
docname (the new path); both work side-by-side.
