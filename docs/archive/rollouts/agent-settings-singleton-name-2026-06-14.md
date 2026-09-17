# Agent Settings singleton naming fix — 2026-06-14

## The one-sentence version

The single "Agent Settings" row could never actually be created or read the way
most of the code expected, which broke the **Setup wizard** (and quietly
hobbled provider/compression resolution) on every fresh deploy — this fixes it
by giving the row one true name (`"__default"`) and using it everywhere.

## What went wrong

Friday keeps one row of global defaults in a DocType called **Agent Settings**
(default LLM provider, delegation limits, setup-complete flag, etc.). It's a
normal single-row DocType, not a Frappe "Single."

Two Frappe rules made the original approach impossible:

1. **You can't name a record the same as its DocType.** So the row literally
   cannot be named `"Agent Settings"`. The DocType auto-names off a hidden
   field and the row is actually named **`"__default"`**.
2. **`frappe.db.exists("Agent Settings", "Agent Settings")` lies.** Frappe has a
   shortcut: when you ask "does record X of doctype X exist?" it answers "yes"
   without checking the database (it assumes you mean a Single). So any code
   that guarded on that form got a **false "yes"** and skipped real work.

The result:

- The after-migrate helper that's supposed to create the row checked that
  false-positive, decided the row already existed, and **never created it** —
  and even if it had tried, it inserted under the forbidden name and would have
  failed. So on a fresh site, **there was no Agent Settings row at all**.
- The Setup wizard read the row as `get_cached_doc("Agent Settings", "Agent
  Settings")`, which can't resolve, so the page died with **"Agent Settings
  Agent Settings not found."**
- `compression.py`, `cli/setup.py`, and `provider.py` read it the same wrong
  way and silently got nothing (falling back to defaults instead of the
  configured values).

Only one place — the new delegation handler — already read it correctly as
`"__default"`. Everything else was inconsistent.

## Why the tests didn't catch it

Every existing test **mocked** Frappe, so none of them exercised the two real
rules above. The mocked suites stayed green while a real `bench migrate` + real
Setup page were broken. This is the exact reason we now require a clean local
`bench migrate` and real-endpoint checks before shipping — see the
"migrate gate" rule.

## The fix

- **One source of truth.** The Agent Settings controller now defines
  `SETTINGS_DOCTYPE = "Agent Settings"` and `SETTINGS_NAME = "__default"`, plus
  two helpers: `ensure_agent_settings()` (create the row correctly, idempotent)
  and `get_agent_settings()` (read it, creating it if missing).
- **Every reader uses the canonical name.** `setup/wizard.py`,
  `llm/compression.py`, `cli/setup.py`, `llm/provider.py`, and
  `skills/handlers_delegate.py` all now address the row as `"__default"`.
- **The guard no longer lies.** Existence checks use the dict form
  (`exists(doctype, {"name": SETTINGS_NAME})`), which actually hits the database.
- **Existing sites get healed.** A new patch
  (`v1_0/create_agent_settings_singleton`, post-model-sync) creates the row on
  any site missing it. The after-migrate hook does the same on every migrate.

## Proof it works (on the local bench, Postgres)

- New **real-DB** test `tests/test_agent_settings.py` (5 tests) pins: the row is
  named `"__default"`; `ensure` is idempotent; the accessor self-heals a missing
  row; reading it the right way works and reading it as `"Agent Settings"`
  raises (so the trap can't come back).
- Related suites green: `test_setup_wizard` (11), `test_cli_setup` (5),
  `test_llm_provider` (32), `test_delegation` (25).
- **Migrate gate:** deleted the row, ran `bench migrate` — clean (exit 0), the
  patch executed, and the row came back as `"__default"`.
- **Real endpoint:** `setup_status()` now returns its full payload instead of
  404-ing, so the Setup wizard page loads.

## Comparison with Hermes

Not applicable as a port — this is a Frappe-platform naming quirk specific to how
Friday models its global settings row. Hermes (a React app) has no equivalent
singleton-row-in-a-relational-DocType concept.
