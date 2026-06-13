# Design 65a — The project data model + agent identity (2026-06-13)

## The one-sentence version

Beef up the `Project` and `Task` DocTypes with the fields a real project
console needs (dates, %-complete, cost, progress, color), and give **every
agent a real Frappe User** so it can be assigned, @-mentioned, and shown with
an avatar — no login, ever.

## Why this is PR #1 of four

Design 65 ("ERPNext-grade project module + live console") is the answer to the
user's loudest unsolved complaint after the Legion test: *"the project module
is completely useless… I have no clue what's happening in a project."* The full
design ships in four PRs:

- **65a (this PR)** — the data model + agent-as-User. Nothing visual yet; this
  is the foundation everything else stands on. Frappe's built-in Gantt needs
  date fields; the cost rollup needs cost fields; the "who's working" avatars
  need a User. So those land first.
- **65b** — native Frappe views (Gantt, Kanban, Dashboard, Workspace).
- **65c** — the bespoke live Project Console Desk Page (realtime push).
- **65d** — progress + cost rollup wiring.

See `docs/design/65-project-module-and-console.md` for the locked design.

## What this PR ships

### 1. New `Project` fields

`priority`, `project_lead_profile` (→ Agent Profile), a **Planning** section
(`expected_start_date`, `expected_end_date`, derived `actual_start_date` /
`actual_end_date`), and a **Progress & Cost** section (`percent_complete`,
`total_tasks`, `completed_tasks`, `estimated_cost_usd`, `actual_cost_usd`). The
derived ones are read-only and get *populated* by the rollup hook in 65d — this
PR just defines them.

### 2. New `Task` fields

A **Timeline & Display** section: `exp_start_date` / `exp_end_date` (the Gantt
needs a date range or it can't draw a bar), `progress`, `color`, `is_milestone`,
`duration_ms`, `cost_usd`. All display/rollup fields — the workflow state machine
is untouched.

### 3. Agent identity — `Agent Profile.frappe_user`

The headline. Each `Agent Profile` now links to a backing **system Frappe User**,
auto-provisioned by `identity/agent_identity.py`:

- email `agent+<slug>@friday.local`, `enabled=1`, `user_type="System User"`,
  roles mirrored from the profile.
- **Cannot log in**: no password is ever set, no API key issued,
  `send_welcome_email=0`, and `@friday.local` is non-routable. The only thing
  this identity can do is *be assigned to and mentioned* — it has no credential
  path. (Test `test_creates_user_with_expected_identity` asserts no
  `new_password` is ever passed.)
- The field name `frappe_user` is not new vocabulary — the 66a/66b skill
  bootstraps already call `profile.get("frappe_user")`. This PR finally creates
  the field they were written expecting.

This is the structural answer to *"only one agent posts in the War Room — what
about the others?"* Once every agent is a real Desk actor, assignment, avatars,
@-mentions, ToDo rows, and Gantt resource lanes all come for free from Frappe.

### Provisioning is idempotent + failure-isolated

- `provision_agent_user(profile)` — create-or-ensure one user; re-running never
  duplicates. Links the user back onto the profile via `db_set` (no `save()`, so
  it's safe to call from `after_insert`).
- `provision_all_agent_users()` — wired into `after_migrate`; backfills every
  existing profile. One bad profile is logged loudly and skipped, never aborting
  the rest (`test_one_failure_does_not_abort_the_rest`).
- `on_agent_profile_after_insert` — wired into `doc_events`; provisions newly
  created profiles and never raises.

## Compare with Hermes

Hermes renders "who's working" as a pixel-drawn badge in its React dashboard —
a string with a color. It has no assignment, no mentions, no ToDo, because a
Hermes session has no actor model. Per `feedback_hermes-floor-not-ceiling`, the
surpass axis here is **governed identity**: a Friday agent is a first-class,
permissioned Frappe principal, not a label. That's only possible because we
forked a full low-code platform underneath.

## Why we know it works

`bench migrate` applies the three DocType changes cleanly (all-optional fields,
existing rows migrate with NULLs). 10 unit tests cover the provisioner:
identity shape, the no-login invariant, idempotency, slug sanitization, role
mirroring, failure isolation, and both hooks. Full file:
`frappe/friday_core/tests/test_agent_identity.py`. Existing pipeline tests
(dispatcher/workflow/runner) are untouched and still green.

## What's NOT in this PR

- Any UI — no Gantt, no Kanban, no console page (65b/65c).
- The rollup logic that *fills* `percent_complete` / cost (65d). Those fields
  read blank until then; they are never shown a fabricated 0.
- Removing a User when a profile is deleted/retired — deferred; a retired agent
  keeps its (disabled-login) identity for historical assignment integrity.

## Operator note

After merging: `bench --site <site> migrate` once. It will create the backing
users for every existing Agent Profile automatically. No manual provisioning.
