# Test Report — Design 69a Delegate-Skill Migration (2026-06-14)

## Scope

Migrate `test_delegate_skill.py` from the superseded **design 57** (synchronous,
inline `run_turn`) contract to the shipped **design 69a** (async, durable
Pending-Task) contract, and verify the broader design 67/68/69a test group still
passes. Also records the patch-ordering fix that unblocked `bench migrate`.

## Environment

- Runner: `env/bin/python -m unittest` (mock-based tests — no DB, no model).
- DB-backed tests (`test_skill_loader`) require `bench run-tests` with a bound
  site and are out of scope for this standalone run.

## Changes under test

| File | Change |
|------|--------|
| `frappe/patches.txt` | Moved `friday_core.patches.v1_0.backfill_agent_role` from `[pre_model_sync]` to `[post_model_sync]`. The patch queries the `agent_role` column, which does not exist until model sync applies it — running it pre-sync raised `psycopg2.errors.UndefinedColumn`. |
| `frappe/friday_core/tests/test_delegate_skill.py` | Rewrote the suite for the 69a contract (details below). Test-only; no production handler change. |

### Test-file migration detail

- Replaced the shared `_ctx_frappe` mock with `_wire`, which routes
  `get_cached_doc` across the three docs the 69a handler reads (parent profile,
  Agent Settings, target profile) and drives the depth/concurrency gates.
- Removed `TestProfileResolution` (auto-match / `_match_profiles` — a design-57
  feature 69a deleted) and the old `TestHappyPath` (inline `run_turn` sync
  contract 69a replaced).
- Added explicit coverage for the two headline 69a gates that the old suite
  never reached (role gate, concurrency gate) plus the async happy path.

## Results — `test_delegate_skill.py` (10/10 pass)

| # | Test | Contract pinned |
|---|------|-----------------|
| 1 | `test_child_session_cannot_delegate` | Depth gate — chain at `max_delegation_depth` (3) refuses (Q3) |
| 2 | `test_missing_required_params_raise` | Required params are `agent_profile` + `instruction`; `title` optional |
| 3 | `test_unknown_target_profile_raises` | Non-existent target → actionable error naming it |
| 4 | `test_inactive_target_profile_raises` | Non-Active target refused (status read off cached doc) |
| 5 | `test_non_orchestrator_cannot_delegate` | Role gate — only Orchestrators delegate (Q4) |
| 6 | `test_concurrency_limit_blocks_delegation` | Concurrency gate — ≥ `max_concurrent_delegations` refuses (Q10) |
| 7 | `test_creates_pending_child_and_returns_queued` | Async happy path — Pending child, `parent_task` set, project inherited, returns `queued` (Q1/Q2/Q8) |
| 8 | `test_top_level_delegation_has_no_parent_task` | Root delegation — `parent_task=None`, explicit project overrides |
| 9 | `test_registered_with_dispatcher` | Handler wired into dispatcher |
| 10 | `test_bootstrap_spec_is_valid` | Bootstrap skill schema consistent |

## Results — broader design 67/68/69a group (71/71 pass)

| Test file | Design | Tests |
|-----------|--------|-------|
| `test_delegate_skill` | 69a | 10 |
| `test_delegation` | 69a | 25 |
| `test_agent_role` | 68 | 19 |
| `test_mcp_sync` | 67 | 10 |
| `test_mcp_client` | 67 | 7 |
| **Total** | | **71** |

```
Ran 71 tests in 0.091s
OK
```

## DB-backed verification — `test_skill_loader` (8/8 pass)

Run under a bound site (role-gated skill visibility — the loader hides
`delegate-task` from non-Orchestrators, the layer in front of the handler's
role gate):

```
bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_skill_loader
Ran 8 tests in 0.984s
OK
```

## Not covered here

- End-to-end delegation through the live pipeline — see the Legion E2E v0.3
  addendum (`docs/testing/legion-e2e-v0.3-addendum-2026-06-14.md`), phases A0–A3.
</content>
</invoke>
