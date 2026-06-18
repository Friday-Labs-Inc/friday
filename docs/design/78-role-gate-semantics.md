# Design 78 — `Skill.role_gate` semantics (Q-by-Q lock)

**Status:** Awaiting user decision. Code does not land until questions Q1–Q4 are
answered. Triggered by the architect-doc comparison: the `role_gate` field on
the `Skill` doctype looks configured but is a silent permission hole — the
hardcoded `_ROLE_GATED_SKILLS` dict in `skills/loader.py` is the actual gate,
and the schema field is never read.

## The bug, in plain English

The `Skill` doctype has a field called `role_gate`. Its description says it
"replaces the hardcoded role gate dict in code." It does not. Today, only one
skill is gated: `delegate-task` — and that gate lives in a hardcoded Python
dict at `skills/loader.py:_ROLE_GATED_SKILLS`. Any other skill that has its
`role_gate` field set in Desk is **completely unenforced** at both the
menu-build layer (the loader) and the call-time layer (the permission matrix).
An operator who carefully restricts a high-risk skill to "Orchestrator only" in
Desk would be exposing it to every agent profile — and not see any warning.

This is a **security gap masquerading as a configured feature** — worse than
missing because it lulls the operator into thinking the gate exists. The
critic surfaced it from the architect-doc comparison: rated `CRITICAL` because
the field is described as load-bearing but does nothing.

## Why a Q-by-Q design lock instead of a one-line fix

The naive fix is one line in `loader.py`: replace the hardcoded dict lookup
with a query on `Skill.role_gate`. **But the field type and the comparison
target don't match.** `Skill.role_gate` is `fieldtype: Link, options: Role` —
it stores a Frappe `Role` docname (like `"System Manager"` or `"Agent
Supervisor"`). The hardcoded dict, by contrast, compares against
`profile.agent_role`, which is a `Select` field with three values:
`Orchestrator | Specialist | Worker`. These are different value spaces.

If the naive fix shipped, the code would APPEAR to work today (because no one
populates `role_gate`) but would silently break the moment any operator set it
— every gate check would fail for legitimate callers including the
`Orchestrator` who used to be allowed through the hardcoded dict.

So a decision is needed BEFORE any code. Four questions.

---

## Q1 — What does `role_gate` actually mean?

The field is currently described as "the role that may use this skill." But
that phrase hides which kind of role.

**Option A — Frappe Role membership.** `role_gate` stores a Frappe `Role`
docname (e.g. `"Agent Supervisor"`, or a custom role like `"Brand Specialist"`).
The loader checks if the role appears in the calling profile's `assigned_roles`
child table (Frappe's `Has Role`). Most flexible — any operator-defined Frappe
role can gate any skill. Matches the existing field type.

**Option B — Agent role tier.** `role_gate` stores `Orchestrator`, `Specialist`,
or `Worker` directly. The loader checks `profile.agent_role == role_gate`.
Simpler but less flexible. Requires changing the field type from `Link → Role`
to `Select` (with the three Design 68 values) or `Data`.

**Option C — Both, with explicit field name.** Rename: keep `role_gate` (Link to
Role, Option A semantics) AND add a separate `agent_role_gate` (Select, Option B
semantics). A skill can declare either or both; the loader requires both checks
to pass. Most expressive but doubles the configuration surface.

**Recommendation:** Option A. The `Has Role` child table is the canonical
Frappe role membership mechanism; we get role inheritance and Desk-managed
role assignment for free. The current `_ROLE_GATED_SKILLS` dict ("Orchestrator
only" for `delegate-task`) maps cleanly to Option A by creating an "Agent
Delegator" Frappe Role, assigning it to Orchestrator profiles' system users,
and setting `delegate-task.role_gate = "Agent Delegator"`.

---

## Q2 — What happens when the field is empty?

**Option A — Fall back to the hardcoded dict.** Keep `_ROLE_GATED_SKILLS` as a
fallback for any skill whose `role_gate` is blank. Backward-compatible: existing
behavior unchanged for `delegate-task`. The dict eventually shrinks to empty as
every gated skill gets its `role_gate` field populated, but the transition is
gradual and safe.

**Option B — Empty means no gate.** A blank `role_gate` field means the skill
is open to any profile that has it in their `permitted_skills`. Cleaner. But
requires populating `role_gate` on `delegate-task` as part of this fix or
existing Orchestrator-delegation governance breaks immediately.

**Option C — Empty raises at provision time.** Treat blank as a misconfiguration
on any skill that previously appeared in the hardcoded dict. Fails loudly
during `bench migrate` if the field is missing. Forces the operator to commit
to the new path.

**Recommendation:** Option A for the first release (zero behavior change for
existing sites), with a follow-up cleanup PR that populates `role_gate` on
`delegate-task` and removes the dict.

---

## Q3 — Where does the check live?

The architect doc calls for defense-in-depth: a fast filter at menu-build time
(so the LLM never sees the tool name it can't call) plus a re-check at
call-time (so a stale menu cache doesn't bypass governance).

**Option A — Menu-build only (`loader.py`).** Current behavior. The loader
filters the skill out of the per-profile list at menu-build time. Fast (single
join), cached. But if the cache is stale, a deleted profile could still call
a skill via direct dispatcher invocation.

**Option B — Call-time only (`permissions/matrix.py`).** Add the check to the
permission matrix. Slower per call but always authoritative. The dispatcher's
existing `Permission Decision Log` audit-trail captures every allow/deny.

**Option C — Both (defense-in-depth).** Loader filter for fast UX + matrix
re-check for authoritative governance. Matches Friday's existing pattern (the
two-permission-gate design the architect-doc comparison rated `exceeds`).

**Recommendation:** Option C. The codebase already has both layers; this fix
should follow the same pattern as `permitted_skills` instead of being a
loader-only outlier.

---

## Q4 — Migration: how do we populate `role_gate` on existing skills?

**Option A — Don't migrate. Leave it blank; the dict fallback (Q2-A) keeps
existing behavior.** Zero risk. The new code path stays dormant until an
operator sets `role_gate` on a Desk-managed skill.

**Option B — Migrate `delegate-task` only.** The only skill currently gated.
A one-line migration sets `role_gate = "Agent Delegator"` on the `delegate-task`
Skill row. Then the bootstrap creates the `Agent Delegator` Frappe Role and
assigns it to Orchestrator profiles' system users (`agent+orchestrator@friday.local`
gets the role). Removes the hardcoded dict entry.

**Option C — Audit + migrate everything.** Survey every skill across all
bundles, decide which need a gate, populate `role_gate` for each, and remove
the dict entirely. Most thorough. Most risk per change.

**Recommendation:** Option B. The migration scope matches the bug scope (one
gated skill today). Future skills configured in Desk get the new path
automatically.

---

## Summary of the four questions

| Q | Question | Default if you say "do what's safe" |
|---|---|---|
| Q1 | What does role_gate mean? | A: Frappe Role membership |
| Q2 | What happens when blank? | A: Fall back to hardcoded dict |
| Q3 | Where does the check live? | C: Both menu + call-time |
| Q4 | How do we migrate? | B: Migrate delegate-task only |

If you pick all the recommended defaults, the implementation is small (~50
lines in `loader.py` + `matrix.py`, plus a one-row data migration). If any
answer changes, the design changes — most importantly, picking Q1-B requires a
field-type change and a forward migration that rewrites existing field values.

## What this design does NOT decide

- Whether existing operator-set `role_gate` values on production Skill rows
  (if any) should be respected or zeroed out. There are none today (the field
  was never connected to the running gate), but a future operator-managed
  Desk site could have set it expecting it to work. The default assumption is
  "respect whatever is set"; if you want a clean slate, add a migration step.
- Whether the `_ROLE_GATED_SKILLS` dict should be deleted in the same PR as the
  loader change or as a follow-up. Deleting in the same PR is cleaner but
  requires Q4-B (so `delegate-task` has its gate elsewhere first). Deferring
  the dict deletion is safer for one-PR review.

## Recommended next step

Read this doc, answer Q1–Q4 (or say "all defaults"), then a one-day
implementation PR follows. No code is written until the four answers are
locked.
