# The bootstrap drift audit — killing the "created once, never refreshed" class

## Why this exists

The same defect bit three times in one week:

1. **PR #179** — the file skills sat `status="Draft"` forever (the skill
   loader hard-excludes Draft), so the Creative Director agent's toolset
   never contained them. Found live in the Friday Labs E2E.
2. **Finding #18 / PR #190** — `remember` was allow-listed but the CD
   profile never got the role its permission check needs; the matrix
   silently dropped the tool. Found by the post-deploy verify.
3. **Finding #19 / PR #192** — `remember`'s schema gained a `scope`
   parameter in code that never appeared on prod, because the provisioner
   that refreshes it is CLI-only and nothing on the migrate path runs it.

One class: **a skill's definition (role, permissions, schema, status) is
written once at creation and then drifts from the code**, either because the
provisioner skips existing rows or because it only runs when an operator
remembers a bench command.

## The audit

Every `skills/bootstrap_*.py` plus the domain provisioners, classified:

| Bootstrap | Upsert? | On migrate? | Verdict |
|---|---|---|---|
| bootstrap_memory | full | ✅ (#192) | safe |
| bootstrap_cron | full | ✅ | safe |
| bootstrap_session_search | full | ✅ | safe |
| bootstrap_project | full | ✅ (gated) | safe |
| randompack_brand engine/visual/file-status | full | ✅ (domain) | safe |
| **bootstrap_files** | **partial — never set status** | ❌ CLI-only | **fixed** |
| **bootstrap_read** | **partial — never set status** | ❌ CLI-only | **fixed** |
| **bootstrap_brand** | full | ❌ CLI-only | **fixed** |
| **bootstrap_propose_skill** | full | ❌ CLI-only | **fixed** |
| **bootstrap_delegate** | full | ❌ CLI-only | **fixed** |
| **bootstrap_deliverables** | full | ❌ CLI-only | **fixed** |

Note: bootstrap_files' partial upsert is the literal #179 root — created
rows defaulted to Draft and existing rows were never touched on status. The
domain's `_ensure_file_skills` band-aid (flipping them Active) still runs
and is now redundant-but-harmless.

## The fix (the PR #192 pattern, applied everywhere)

1. Every drift-prone bootstrap gained **`ensure_definitions()`** — the
   role + permissions + Skill-row upsert, and nothing else. Profile wiring
   (who gets the skill) stays in `provision()`/domain provisioners:
   *granting is a decision; definitions are not.*
2. `bootstrap_files`/`bootstrap_read` upserts are now **complete** — they
   force `status="Active"`, risk level, and approval flag on both the
   create and update paths.
3. A new **`bootstrap_registry`** module runs all six from ONE
   after_migrate entry, failure-isolated per bootstrap (one broken ensure
   is logged; the rest still run; the migrate never aborts).
4. **The class-killer test**: a reflection test scans the skills package
   for `bootstrap_*.py` files and fails if any is on neither the registry
   nor an individual after_migrate entry — a future bootstrap cannot be
   forgotten without a red test saying so by name.

## Deploy notes

- `bench migrate` refreshes every skill definition from code — from now on,
  every deploy. Expect the first migrate to touch the six bootstraps' rows
  (timestamps update); behaviour changes only where code and site had
  already drifted.
- Also fixed in passing: the slice-95-4 rollout doc's Tavily
  `tool_include` example now uses the underscore names Tavily actually
  advertises (`tavily_search, tavily_extract`) — the hyphenated version
  matches nothing and mints 0 skills (proven on prod during registration).

## Tests

`tests/test_bootstrap_definitions.py` (6 DB-free): the coverage reflection
test, registry paths resolve, files/read existing rows get the FULL
definition (the #179 pin), registry isolation (one failure doesn't starve
the rest), and healthy-path ordering.
