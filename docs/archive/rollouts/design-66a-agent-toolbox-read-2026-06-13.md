# Design 66a — The agent can finally read what it wrote (2026-06-13)

## The one-sentence version

When you ask a Friday agent "what brand directions do you have for
BB-0001?", it now **retrieves them** instead of fabricating three new
ones. And if it can't, it says so plainly — never invents.

## What you would have seen, before today

From the Legion validation transcript, line 5142:

> *"I'm having trouble retrieving the saved directions from the system.
> Let me create fresh ones for you now based on the Legion Coffee brief."*

The agent had **24 real brand directions saved** in the database
(BD-0002 through BD-0025) from a previous pipeline run. It had a
`create-brand-direction` tool and no reciprocal `get-brand-direction`
tool. So instead of saying "I don't have a way to read those," it
**made up three new ones** and presented them as if they were the
saved work. For a governance framework, that's the worst possible
failure mode — silent hallucination at the agent's mouth.

## What this PR ships — three things

**1. `read-record` and `list-records` — the Friday-beats-Hermes move**

Hermes builds a read tool by hand for every record type. Friday sits
on Frappe, a permissioned database, so **one generic governed read
tool covers every DocType the agent can already write to**. Save a
Brand Direction? You can read it back. Save a Task? You can read it
back. Save a Project? You can read it back. No per-type skill needed.

Both tools call `frappe.has_permission(...)` against the agent's User
on every call. Denials are structured (`not_found_or_unreadable`,
`denied`) — never an empty success. Password fields are stripped from
the response so credentials cannot leak through a read. Permission-
denied and not-found collapse to the same error so an agent cannot
probe forbidden existence.

**2. The fail-loud governance frame in every system prompt**

`prompt_builder._build_system_prompt` now ships one non-negotiable
GOVERNANCE paragraph in every agent's prompt:

> If you do not have a tool that can fetch the information someone is
> asking about, say so plainly. Never invent records, files, or data
> you did not retrieve through a tool call. Hallucination is a
> governance failure, not a creativity feature.

The operator's profile-specific `system_prompt` rides after this frame
verbatim, so per-profile voice and the governance contract compose
instead of conflict.

**3. A bootstrap script — provision once, idempotent**

```bash
bench --site friday.localhost execute \
  frappe.friday_core.skills.bootstrap_read.provision
```

Creates the Skill rows, wires them onto the Friday profile, grants
the Friday Reader role. Safe to re-run any time.

## Why we know it works — live proof on the bench

Provisioned today on `friday.localhost`, then verified four scenarios
the Legion incident would have failed on:

1. **`list-records`** for `Brand Direction` filtered by brief → returned
   the real BD-0006 row that was saved seconds before. **No fabrication.**
2. **`read-record`** for BD-0006 → returned the actual
   `direction_name` and `concept_story`. **Agent can retrieve its own work.**
3. **`read-record`** for a deliberately-missing `BD-NOPE-NOTREAL` →
   `{"error": "not_found_or_unreadable"}`. **Fail-loud, no fabrication.**
4. **`read-record`** for the `Minimax` LLM Provider (which has an
   encrypted `api_key`) → record returned, `api_key` correctly
   **absent**, `scrubbed_fields: ['api_key']`. **Credentials safe.**

## Tests

- **13 new** `test_read_skill.py` covering: parameter validation,
  permission-denied returns structured error (not a row), unknown
  doctype, not-found, success path, password-field scrubbing, list
  capping at 100, list denial returns empty, governance frame text
  presence.
- All adjacent suites still green: workflow (15), dispatcher (15),
  reconciler (12), brand skills (10).

## What's NOT in this PR

- **`attach-deliverable` + `list-project-files` + `get-project-file`**
  land in 66b. The Project becomes the home of the agent's finished
  files via Frappe's native File layer, not custom file infrastructure.
- **MCP** — the universal-tool protocol for outside-world tools (web,
  browser, GitHub) — is a separate, larger design.
- **Generic `write-record`** — too dangerous to expose generically in
  v0.1. Specific writes stay per-DocType skills with per-DocType
  validation.

## How an operator picks this up

After merging, on each existing bench, run:

```bash
bench --site <yoursite> execute \
  frappe.friday_core.skills.bootstrap_read.provision
```

The Friday profile gains two skills; the governance frame line lands
automatically in every agent's prompt on the very next turn.
