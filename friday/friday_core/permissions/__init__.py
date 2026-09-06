# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday permission engine — gateway pre-check for skill invocations.

This package answers, in well under 10ms, the single question every
agent action depends on:

    "Is Agent X allowed to call Skill Y right now?"

Three modules, one responsibility each:

  - **matrix.py** — the decision logic. Loads an Agent Profile, looks
    up its roles and the DocType permissions those roles confer, builds
    a permission matrix, compares against what the Skill requires, and
    returns a `Decision(allowed, reason)`. The public function is
    `check(profile, skill)`. See its docstring for the full flow.

  - **cache.py** — the Redis cache that makes the check fast. Caches
    permission matrices for 60 seconds, invalidates on Agent Profile
    or Role updates (wired via `doc_events` in `frappe/hooks.py`).

  - **decisions.py** — the audit-log writer. Every check (allow OR
    deny) creates one immutable Permission Decision Log row, with a
    snapshot of the matrix used. This is what auditors read.

Tests live next to Slice 1's tests at
`friday/friday_core/tests/test_permissions.py`.

See also:
  - `docs/design/04-security-model.md` §Layer 2 — why this exists.
  - `docs/design/10-agent-execution-guide.md` §Slice 2 — what to build.
"""
