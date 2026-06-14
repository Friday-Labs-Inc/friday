# Friday hub workspace — 2026-06-14

## What shipped, in one sentence

A single **"Friday"** page now sits at the top of the Desk's left sidebar and
acts as the front door to everything Friday — so you stop hunting for screens
through global search.

## Why we did this

Up to now, Friday's screens were scattered. There was a **Projects** workspace
(a monitoring dashboard with the number tiles and charts), but everything else
— Agent Profiles, LLM Providers, Skills, MCP Servers, the audit logs, the setup
wizard, the live console — had no home. To open any of them you had to know its
exact name and type it into search. That's bad UX, and it was the first thing
that bit a real operator using the bench.

This change adds a **navigation hub**: one workspace whose only job is to lay
out links to all the Friday surfaces in a sensible, grouped way.

## What the page contains

**Shortcut tiles** (the big buttons across the top) for the things you touch
every day:

- **Project Console** — the live ops view
- **Projects** — the project list
- **Tasks** — the task list
- **Agents** — the Agent Profile list
- **Setup Friday** — the setup wizard

**Navigation cards** (grouped link lists) covering every Friday DocType:

| Card | What's in it |
|------|--------------|
| **Work** | Project, Task, Issue, Task Dependency |
| **Agents** | Agent Profile, Agent Settings, Agent Memory |
| **Models & Skills** | LLM Provider, LLM Usage Log, Skill, MCP Server |
| **Conversations & Surfaces** | Chat Message, Chat Platform, RandomPack Settings |
| **Governance & Logs** | Permission Decision Log, Execution Log, Workflow Request, Compaction Summary |

The existing **Projects** workspace is left exactly as it was — it stays the
monitoring dashboard. "Friday" is the new front door that sits above it.

## How it's built (and why it's safe)

It rides the **same provisioner** that already creates the Projects workspace,
its number cards, charts and Kanban:
`friday_core/console/provision_console.py`, which runs on every
`after_migrate`.

Three properties carried over from that provisioner, all of which matter:

1. **Idempotent** — it only creates the workspace if it doesn't already exist,
   so running migrate ten times changes nothing after the first.
2. **Failure-isolated** — if creating the hub ever errors, it's logged loudly
   and skipped; it can never abort the rest of the migration.
3. **DB record, not a file fixture** — the workspace is a plain public database
   row. We do *not* commit a `workspace/friday/friday.json` file (developer-mode
   writes one locally; it's intentionally not tracked), so Frappe never tries to
   reconcile an on-disk copy against the database.

One extra bit of resilience this hub adds: each navigation link is included
**only if its DocType actually exists on the site**. If a DocType is ever
renamed or removed in a future version, the hub silently drops that one link
instead of failing to build the whole page. (This was a real bug caught during
development — an early draft listed a DocType that didn't exist and the entire
hub refused to save.)

## Comparison with Hermes

Hermes has no equivalent. Hermes is a React app and hand-rolls every screen and
every bit of navigation in component code. Friday gets its whole Desk — sidebar,
workspaces, list views, the lot — from the Frappe platform it forked. This hub
is therefore not a port; it's a pure platform win. We only declare *what* to
link to; Frappe renders the page.

## Tests

`friday_core/tests/test_console_views.py` gained a `TestHubWorkspace` class:

- the hub is created, public, and sorts above the default workspaces;
- every declared shortcut and every navigation card/link is present;
- the page layout blob references only shortcuts and cards that actually exist.

The existing Projects-workspace tests continue to pass unchanged. Full module:
12 tests, green.

## How to see it

Open the Desk (`/app`) and look at the top of the left sidebar — **Friday** is
the first entry. On a fresh deploy it appears automatically after the first
`bench migrate`.
